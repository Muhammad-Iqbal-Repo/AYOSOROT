# agent/orchestrator.py
"""
PersonIntelAgent — two-agent research pipeline.

Architecture
────────────
Every research task uses two agents in sequence:

  Searcher (user-selected model + Google Search)
    - Searches the web and returns raw findings as plain text
    - No JSON pressure — just find and dump facts

  Writer (user-selected model, no search tool)
    - Receives Searcher's raw findings as context
    - Formats into strict JSON / narrative text output

No default or fallback models are defined here. The user selects both models
explicitly in the sidebar. If a model returns an empty response, the Writer
automatically retries with progressively relaxed parameters before failing.

Constructor
───────────
  agent = PersonIntelAgent(
      api_key="AIza...",
      searcher_model="gemini-2.0-flash-lite",
      writer_model="gemini-2.0-flash",
  )

All parameters are required (no env-var fallback for models).
api_key still falls back to GOOGLE_API_KEY env var for local .env workflows.

Writer empty-response retry
───────────────────────────
Some models (e.g. gemini-2.5-pro) return empty text on the first call when
asked for large structured JSON. The Writer retries up to MAX_WRITER_RETRIES
times with slightly increased tokens and temperature on each attempt before
raising EmptyResponseError.
"""
import json
import os
import re
import time

from google import genai
from google.genai import types
from google.api_core.exceptions import (
    GoogleAPIError,
    InvalidArgument,
    ResourceExhausted,
    Unauthenticated,
)

from agent.exceptions import (
    ApiError,
    ConfigurationError,
    EmptyResponseError,
    ParseError,
    QuotaExceededError,
    SafetyBlockError,
)
from agent.prompts import (
    build_company_news_searcher_prompt,
    build_disambiguation_prompt,
    build_news_searcher_prompt,
    build_news_writer_prompt,
    build_searcher_prompt,
    build_summary_prompt,
    build_writer_prompt,
)
from agent.schema import DisambiguationCandidate, NewsArticle, PersonProfile
from utils.logger import get_logger

logger = get_logger(__name__)

# Token caps per call type
_SEARCHER_MAX_TOKENS  = 3000
_WRITER_MAX_TOKENS    = 2500   # structured JSON
_NEWS_SEARCHER_TOKENS = 4000
_NEWS_WRITER_TOKENS   = 3000
_DISAMBIG_TOKENS      = 400
_SUMMARY_MAX_TOKENS   = 1500

# Thinking model token cap — much higher because thinking tokens count
# against the budget before a single output token is produced.
_THINKING_MAX_TOKENS  = 8000

# Writer empty-response retry config
_MAX_WRITER_RETRIES  = 3
_TOKEN_INCREMENT     = 1000   # larger increment for thinking models
_TEMP_INCREMENT      = 0.1
_RETRY_DELAY_SEC     = 3.0    # thinking models are slower; wait longer

# Model name fragments that identify Gemini "thinking" models.
# These models require temperature=1.0 and a much higher token budget.
_THINKING_MODEL_PATTERNS = ("2.5", "thinking")


def _is_thinking_model(model_name: str) -> bool:
    """
    Returns True if *model_name* is a Gemini thinking model.

    Thinking models (e.g. gemini-2.5-pro, gemini-2.5-flash) have two key
    constraints that differ from standard models:
      - temperature MUST be 1.0 (the API rejects other values)
      - They consume thinking tokens before producing output, so
        max_output_tokens must be set much higher than the desired
        output length to avoid cutting off mid-generation.
    """
    name_lower = model_name.lower()
    return any(pat in name_lower for pat in _THINKING_MODEL_PATTERNS)


class PersonIntelAgent:

    def __init__(
        self,
        api_key:        str | None = None,
        searcher_model: str        = "",
        writer_model:   str        = "",
    ) -> None:
        """
        Args:
            api_key:        Google AI Studio API key.
                            Falls back to GOOGLE_API_KEY env var for local dev.
            searcher_model: Model name for the Searcher agent. Required.
            writer_model:   Model name for the Writer agent. Required.

        Raises:
            ConfigurationError: if no API key is available.
            ConfigurationError: if searcher_model or writer_model is empty.
        """
        resolved_key = (api_key or os.getenv("GOOGLE_API_KEY", "")).strip()
        if not resolved_key:
            raise ConfigurationError(
                "API key tidak ditemukan. "
                "Masukkan API key di sidebar atau isi GOOGLE_API_KEY di file .env."
            )
        if not searcher_model:
            raise ConfigurationError("Model Pencari (Searcher) belum dipilih.")
        if not writer_model:
            raise ConfigurationError("Model Penulis (Writer) belum dipilih.")

        self._client         = genai.Client(api_key=resolved_key)
        self._search_tool    = types.Tool(google_search=types.GoogleSearch())
        self._searcher_model = searcher_model
        self._writer_model   = writer_model

        logger.info(
            f"PersonIntelAgent ready | "
            f"searcher={searcher_model!r} | writer={writer_model!r}"
        )

    # ── Class-level utilities ─────────────────────────────────────────────────

    @classmethod
    def list_models(cls, api_key: str) -> list[str]:
        """
        Returns all Gemini generative model names available for *api_key*.

        Filters to models whose name starts with "gemini-" to exclude
        embedding, vision-only, and other non-generative model families.
        Results are sorted alphabetically.

        Raises:
            ConfigurationError: if the key is invalid or the listing call fails.
        """
        if not api_key or not api_key.strip():
            raise ConfigurationError("API key tidak boleh kosong.")

        try:
            client = genai.Client(api_key=api_key.strip())
            models = [
                m.name.split("/")[-1]
                for m in client.models.list()
                if m.name.split("/")[-1].startswith("gemini-")
            ]
            return sorted(set(models))
        except Exception as exc:
            raise ConfigurationError(
                f"Gagal mengambil daftar model: {exc}. "
                "Pastikan API key valid dan memiliki akses ke Gemini API."
            ) from exc

    # ── Public API ────────────────────────────────────────────────────────────

    def disambiguate(self, name: str) -> list[DisambiguationCandidate]:
        """
        Checks whether *name* refers to multiple public figures.
        Writer-only (no search). Fails silently — never blocks search.
        """
        try:
            raw  = self._call_writer(
                prompt=build_disambiguation_prompt(name),
                max_tokens=_DISAMBIG_TOKENS,
                label=f"DISAMBIG:{name}",
            )
            data = json.loads(raw)
            return [DisambiguationCandidate(**c) for c in data.get("candidates", []) if c]
        except Exception as exc:
            logger.warning(f"[DISAMBIG:{name}] Skipped — {exc}")
            return []

    def run(
        self,
        name:              str,
        selected_keys:     list[str] | None = None,
        progress_callback                   = None,
    ) -> tuple[PersonProfile, str]:
        """
        Full two-agent profile research pipeline.

        Step 1 — Searcher: finds raw facts (search tool enabled)
        Step 2 — Writer:   formats findings into JSON (no search)

        Raises:
            ConfigurationError, QuotaExceededError, SafetyBlockError,
            EmptyResponseError, ParseError, ApiError
        """
        _progress(progress_callback, "🔍 [Agen Pencari] Menelusuri sumber publik...", 0.15)

        raw_findings = self._call_searcher(
            prompt=build_searcher_prompt(name, selected_keys),
            max_tokens=_SEARCHER_MAX_TOKENS,
            label=f"SEARCHER:profile:{name}",
            progress_callback=progress_callback,
        )
        logger.info(f"[SEARCHER:profile:{name}] {len(raw_findings)} chars returned")

        _progress(progress_callback, "✍️ [Agen Penulis] Menyusun profil terstruktur...", 0.6)

        raw_json = self._call_writer(
            prompt=build_writer_prompt(name, raw_findings, selected_keys),
            max_tokens=_WRITER_MAX_TOKENS,
            label=f"WRITER:profile:{name}",
        )

        _progress(progress_callback, "📋 Memvalidasi struktur data...", 0.9)
        return self._parse_profile(name, raw_json)

    def generate_summary(self, profile: PersonProfile) -> str:
        """
        Generates a narrative summary in Bahasa Indonesia.
        Writer-only. Returns empty string on any error.
        """
        label = f"WRITER:summary:{profile.full_name}"
        try:
            summary = self._call_writer(
                prompt=build_summary_prompt(profile.model_dump_json(indent=2)),
                max_tokens=_SUMMARY_MAX_TOKENS,
                label=label,
                extract_json=False,
            )
            logger.info(f"[{label}] Summary generated ({len(summary)} chars)")
            return summary.strip()
        except Exception as exc:
            logger.warning(f"[{label}] Failed — {exc}")
            return ""

    def fetch_news(self, name: str) -> list[NewsArticle]:
        """Two-agent news pipeline for a person. Returns [] on error."""
        label_s = f"SEARCHER:news:{name}"
        label_w = f"WRITER:news:{name}"
        try:
            raw_findings = self._call_searcher(
                prompt=build_news_searcher_prompt(name),
                max_tokens=_NEWS_SEARCHER_TOKENS,
                label=label_s,
            )
            logger.info(f"[{label_s}] {len(raw_findings)} chars returned")

            raw_json = self._call_writer(
                prompt=build_news_writer_prompt(name, raw_findings),
                max_tokens=_NEWS_WRITER_TOKENS,
                label=label_w,
            )
            articles = self._parse_articles(json.loads(raw_json), label=label_w)
            if not articles:
                logger.warning(
                    f"[{label_w}] Writer returned 0 articles. "
                    f"Searcher findings (first 400 chars):\n{raw_findings[:400]}"
                )
            return articles
        except Exception as exc:
            logger.warning(f"[{label_w}] News fetch failed — {type(exc).__name__}: {exc}")
            return []

    def fetch_company_news(
        self, company_name: str, person_name: str
    ) -> list[NewsArticle]:
        """Two-agent company news pipeline. Returns [] on error."""
        label_s = f"SEARCHER:company_news:{company_name}"
        label_w = f"WRITER:company_news:{company_name}"
        try:
            raw_findings = self._call_searcher(
                prompt=build_company_news_searcher_prompt(company_name, person_name),
                max_tokens=_NEWS_SEARCHER_TOKENS,
                label=label_s,
            )
            logger.info(f"[{label_s}] {len(raw_findings)} chars returned")

            raw_json = self._call_writer(
                prompt=build_news_writer_prompt(company_name, raw_findings),
                max_tokens=_NEWS_WRITER_TOKENS,
                label=label_w,
            )
            return self._parse_articles(json.loads(raw_json), label=label_w)
        except Exception as exc:
            logger.warning(f"[{label_w}] Company news failed — {type(exc).__name__}: {exc}")
            return []

    # ── Agent call wrappers ───────────────────────────────────────────────────

    def _call_searcher(
        self,
        prompt:            str,
        max_tokens:        int,
        label:             str,
        progress_callback  = None,
    ) -> str:
        """Calls the Searcher model with search tool. Returns raw text."""
        return self._call_model(
            model=self._searcher_model,
            prompt=prompt,
            tools=[self._search_tool],
            max_tokens=max_tokens,
            temperature=0.1,
            label=label,
            extract_json=False,
            progress_callback=progress_callback,
        )

    def _call_writer(
        self,
        prompt:       str,
        max_tokens:   int,
        label:        str,
        extract_json: bool = True,
    ) -> str:
        """
        Calls the Writer model without search tool.

        Retries up to _MAX_WRITER_RETRIES times when the model returns an
        empty response — incrementing tokens and temperature slightly on each
        attempt to nudge the model into producing output.

        Args:
            extract_json: True → extract JSON block from response.
                          False → return raw text (for narrative summaries).
        """
        tokens      = max_tokens
        temperature = 0.1
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_WRITER_RETRIES + 1):
            if attempt > 1:
                tokens      += _TOKEN_INCREMENT
                temperature += _TEMP_INCREMENT
                delay        = _RETRY_DELAY_SEC * (attempt - 1)
                logger.warning(
                    f"[{label}] Writer retry {attempt}/{_MAX_WRITER_RETRIES} — "
                    f"tokens={tokens} temperature={temperature:.2f} delay={delay}s"
                )
                time.sleep(delay)

            try:
                return self._call_model(
                    model=self._writer_model,
                    prompt=prompt,
                    tools=[],
                    max_tokens=tokens,
                    temperature=temperature,
                    label=label,
                    extract_json=extract_json,
                    progress_callback=None,
                )
            except EmptyResponseError as exc:
                # Empty response — retry with relaxed parameters
                last_exc = exc
                logger.warning(f"[{label}] Empty response on attempt {attempt} — will retry")
            except (SafetyBlockError, ConfigurationError, QuotaExceededError, ApiError):
                raise   # Permanent — do not retry
            except Exception as exc:
                last_exc = exc
                logger.warning(f"[{label}] Writer attempt {attempt} failed — {exc}")

        raise EmptyResponseError(
            f"[{label}] Writer model '{self._writer_model}' mengembalikan respons kosong "
            f"setelah {_MAX_WRITER_RETRIES} percobaan. "
            "Coba pilih model Writer yang berbeda (misalnya gemini-2.0-flash)."
        ) from last_exc

    # ── Core model caller ─────────────────────────────────────────────────────

    def _call_model(
        self,
        model:             str,
        prompt:            str,
        tools:             list,
        max_tokens:        int,
        temperature:       float,
        label:             str,
        extract_json:      bool,
        progress_callback,
    ) -> str:
        """
        Makes a single generate_content call to *model*.

        Automatically adjusts parameters for thinking models:
          - Forces temperature=1.0  (API requirement for thinking models)
          - Uses _THINKING_MAX_TOKENS instead of max_tokens  (thinking tokens
            consume budget before output starts, so a small cap causes empty
            responses even when the model has something to say)

        Raises typed exceptions for every failure mode — never returns None.

        Permanent errors (raised immediately, no retry by caller):
            ConfigurationError, QuotaExceededError, SafetyBlockError, ApiError

        Transient errors (caller may retry):
            EmptyResponseError, ParseError
        """
        thinking = _is_thinking_model(model)
        resolved_temperature = 1.0 if thinking else temperature
        resolved_tokens      = _THINKING_MAX_TOKENS if thinking else max_tokens

        if thinking:
            logger.info(
                f"[{label}] Thinking model detected ('{model}') — "
                f"using temperature=1.0 and max_output_tokens={resolved_tokens}"
            )

        try:
            response = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=tools,
                    temperature=resolved_temperature,
                    max_output_tokens=resolved_tokens,
                ),
            )
        except Unauthenticated as exc:
            raise ConfigurationError(
                f"[{label}] API key tidak valid. Periksa kembali kunci API Anda."
            ) from exc
        except InvalidArgument as exc:
            raise ApiError(
                f"[{label}] Permintaan tidak valid: {exc}. "
                "Jika menggunakan model thinking (gemini-2.5-x), pastikan "
                "tidak ada parameter yang tidak didukung."
            ) from exc
        except ResourceExhausted as exc:
            raise QuotaExceededError(
                f"[{label}] Kuota API Gemini habis. Coba lagi nanti."
            ) from exc
        except GoogleAPIError as exc:
            raise ApiError(f"[{label}] Google API error: {exc}") from exc

        text   = self._extract_text(response, label)
        result = self._extract_json_from_text(text, label) if extract_json else text
        return result

    # ── Response helpers ──────────────────────────────────────────────────────

    def _extract_text(self, response, label: str) -> str:
        """
        Returns the raw text from a response object.

        Raises:
            SafetyBlockError   — finish_reason is SAFETY
            EmptyResponseError — response text is blank or missing
        """
        try:
            finish_reason = response.candidates[0].finish_reason
            if finish_reason and finish_reason.name == "SAFETY":
                raise SafetyBlockError(
                    f"[{label}] Permintaan diblokir oleh filter keamanan Gemini."
                )
        except (IndexError, AttributeError):
            pass

        raw = getattr(response, "text", None)
        if not raw or not raw.strip():
            raise EmptyResponseError(
                f"[{label}] Model mengembalikan respons kosong."
            )
        return raw.strip()

    def _extract_json_from_text(self, text: str, label: str) -> str:
        """
        Extracts a JSON object from raw response text.

        Extraction order:
          1. JSON inside ```json ... ``` fence
          2. Outermost { … } block
          3. Repair: remove JS comments, strip trailing commas
          4. Last resort: truncate at final }

        Raises:
            ParseError — no valid JSON could be extracted or repaired.
        """
        # 1 — Markdown fence
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            return self._repair_json(fence.group(1).strip(), label)

        # 2 — Outermost brace
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            return self._repair_json(brace.group(0).strip(), label)

        raise ParseError(
            f"[{label}] Tidak ada blok JSON ditemukan dalam respons Writer."
        )

    def _repair_json(self, text: str, label: str) -> str:
        """
        Returns *text* unchanged if valid. Applies three repairs in sequence.

        Repairs:
          1. Remove // JS-style comments
          2. Strip trailing commas before } or ]
          3. Truncate at the last }
        """
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        logger.info(f"[{label}] JSON repair triggered")
        fixed = re.sub(r"//[^\n]*", "", text)
        fixed = re.sub(r",\s*([\}\]])", r"\1", fixed)

        try:
            json.loads(fixed)
            logger.info(f"[{label}] Repair succeeded (trailing commas)")
            return fixed
        except json.JSONDecodeError:
            pass

        last = fixed.rfind("}")
        if last != -1:
            truncated = fixed[: last + 1]
            try:
                json.loads(truncated)
                logger.info(f"[{label}] Repair succeeded (truncation)")
                return truncated
            except json.JSONDecodeError:
                pass

        raise ParseError(
            f"[{label}] JSON tidak dapat diparsing atau diperbaiki. Coba lagi."
        )

    # ── Domain object parsers ─────────────────────────────────────────────────

    def _parse_articles(self, data: dict, label: str) -> list[NewsArticle]:
        """
        Parses the 'articles' list from a Writer response dict.
        Each article is validated individually — one bad entry does not
        discard the rest.
        """
        valid: list[NewsArticle] = []
        for raw in data.get("articles", []):
            if not raw.get("url", "").startswith("http"):
                logger.debug(f"[{label}] Skipping article without URL: {raw.get('title')!r}")
                continue
            try:
                valid.append(NewsArticle.model_validate(raw))
            except Exception as exc:
                logger.warning(f"[{label}] Malformed article {raw.get('title')!r}: {exc}")

        logger.info(f"[{label}] {len(valid)} valid articles parsed")
        return valid

    def _parse_profile(self, name: str, raw_json: str) -> tuple[PersonProfile, str]:
        """Validates the raw JSON string against the PersonProfile schema."""
        try:
            profile = PersonProfile.model_validate(json.loads(raw_json))
            logger.info(f"[WRITER:profile:{name}] Profile validated successfully")
            return profile, raw_json
        except json.JSONDecodeError as exc:
            raise ParseError(
                f"[WRITER:profile:{name}] JSON tidak valid: "
                f"baris {exc.lineno}, kolom {exc.colno}."
            ) from exc
        except ValueError as exc:
            raise ParseError(
                f"[WRITER:profile:{name}] Struktur data tidak sesuai skema: {exc}"
            ) from exc


# ── Module helpers ────────────────────────────────────────────────────────────

def _progress(callback, step: str, pct: float) -> None:
    """Calls *callback* only when it is not None."""
    if callback:
        callback(step, pct)
