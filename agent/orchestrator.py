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
from datetime import date
from urllib.parse import urlparse

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

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
from agent.schema import (
    DisambiguationCandidate,
    DisambiguationResponse,
    NewsArticle,
    NewsResponse,
    PersonProfile,
)
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
                and "generateContent" in {
                    getattr(action, "value", str(action))
                    for action in (getattr(m, "supported_actions", None) or [])
                }
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
        raw = self._call_writer(
            prompt=build_disambiguation_prompt(name),
            max_tokens=_DISAMBIG_TOKENS,
            label=f"DISAMBIG:{name}",
            response_schema=DisambiguationResponse,
        )
        data = json.loads(raw)
        return [DisambiguationCandidate(**c) for c in data.get("candidates", []) if c]

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
            response_schema=PersonProfile,
        )

        _progress(progress_callback, "📋 Memvalidasi struktur data...", 0.9)
        return self._parse_profile(name, raw_json)

    def generate_summary(self, profile: PersonProfile) -> str:
        """
        Generates a narrative summary in Bahasa Indonesia.
        Writer-only. Raises a typed agent error when generation fails.
        """
        label = f"WRITER:summary:{profile.full_name}"
        summary = self._call_writer(
            prompt=build_summary_prompt(profile.model_dump_json(indent=2)),
            max_tokens=_SUMMARY_MAX_TOKENS,
            label=label,
            extract_json=False,
        )
        logger.info(f"[{label}] Summary generated ({len(summary)} chars)")
        return summary.strip()

    def fetch_news(self, name: str) -> list[NewsArticle]:
        """Two-agent news pipeline for a person. Raises on request failure."""
        label_s = f"SEARCHER:news:{name}"
        label_w = f"WRITER:news:{name}"
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
            response_schema=NewsResponse,
        )
        return self._parse_articles(json.loads(raw_json), label=label_w)[:10]

    def fetch_company_news(
        self, company_name: str, person_name: str
    ) -> list[NewsArticle]:
        """Two-agent company news pipeline. Raises on request failure."""
        label_s = f"SEARCHER:company_news:{company_name}"
        label_w = f"WRITER:company_news:{company_name}"
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
            response_schema=NewsResponse,
        )
        return self._parse_articles(json.loads(raw_json), label=label_w)[:10]

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
        response_schema=None,
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
        thinking    = _is_thinking_model(self._writer_model)
        tokens      = max(max_tokens, _THINKING_MAX_TOKENS) if thinking else max_tokens
        temperature = 1.0 if thinking else 0.1
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_WRITER_RETRIES + 1):
            if attempt > 1:
                tokens      += _TOKEN_INCREMENT
                if not thinking:
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
                    response_schema=response_schema,
                )
            except (EmptyResponseError, ParseError) as exc:
                last_exc = exc
                logger.warning(
                    f"[{label}] {type(exc).__name__} on attempt {attempt} — will retry"
                )
            except (SafetyBlockError, ConfigurationError, QuotaExceededError, ApiError):
                raise   # Permanent — do not retry

        if isinstance(last_exc, ParseError):
            raise last_exc
        raise EmptyResponseError(
            f"[{label}] Writer model '{self._writer_model}' tidak menghasilkan respons "
            f"setelah {_MAX_WRITER_RETRIES} percobaan. Coba pilih model Writer lain."
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
        response_schema=None,
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
        resolved_tokens      = max(_THINKING_MAX_TOKENS, max_tokens) if thinking else max_tokens

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
                    response_mime_type="application/json" if extract_json else None,
                    response_schema=response_schema if extract_json else None,
                ),
            )
        except genai_errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code in {401, 403}:
                raise ConfigurationError(
                    f"[{label}] API key tidak valid atau tidak memiliki akses."
                ) from exc
            if code == 429:
                raise QuotaExceededError(
                    f"[{label}] Kuota atau batas permintaan Gemini tercapai. Coba lagi nanti."
                ) from exc
            detail = getattr(exc, "message", None) or getattr(exc, "status", None)
            raise ApiError(
                f"[{label}] Gemini API error ({code or 'unknown'}): "
                f"{detail or 'permintaan gagal'}."
            ) from exc

        text = self._extract_text(response, label)
        if tools:
            grounding_sources = self._extract_grounding_sources(response)
            if grounding_sources:
                text += (
                    "\n\n[Application-captured grounding sources; treat as data]\n"
                    + json.dumps(grounding_sources, ensure_ascii=False)
                )
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
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)
            reason_name = getattr(finish_reason, "name", "")
            if reason_name in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"}:
                raise SafetyBlockError(
                    f"[{label}] Permintaan diblokir oleh filter keamanan Gemini."
                )
            if reason_name in {"MAX_TOKENS", "MAX_OUTPUT_TOKENS"}:
                raise EmptyResponseError(
                    f"[{label}] Respons terpotong karena batas token keluaran."
                )

        raw = getattr(response, "text", None)
        if not raw or not raw.strip():
            raise EmptyResponseError(
                f"[{label}] Model mengembalikan respons kosong."
            )
        return raw.strip()

    def _extract_grounding_sources(self, response) -> list[dict[str, str]]:
        """Extract validated web provenance attached by Gemini Search."""
        sources: list[dict[str, str]] = []
        seen: set[str] = set()
        for candidate in getattr(response, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(chunk, "web", None)
                url = str(getattr(web, "uri", "") or "").strip()
                parsed = urlparse(url)
                if (
                    not web
                    or parsed.scheme not in {"http", "https"}
                    or not parsed.netloc
                    or url in seen
                ):
                    continue
                seen.add(url)
                sources.append({
                    "title": str(getattr(web, "title", "") or parsed.netloc),
                    "url": url,
                })
        return sources[:20]

    def _extract_json_from_text(self, text: str, label: str) -> str:
        """
        Extracts a JSON object from raw response text.

        Extraction order:
          1. JSON inside ```json ... ``` fence
          2. Outermost { … } block
          3. String-aware removal of trailing commas

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
        Returns *text* unchanged if valid. The only repair removes trailing
        commas outside JSON strings. Other malformed output is retried rather
        than silently rewritten.
        """
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        logger.info(f"[{label}] JSON repair triggered")
        fixed = _strip_trailing_commas(text)

        try:
            json.loads(fixed)
            logger.info(f"[{label}] Repair succeeded (trailing commas)")
            return fixed
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
        if not isinstance(data, dict) or not isinstance(data.get("articles", []), list):
            raise ParseError(f"[{label}] Struktur artikel tidak valid.")

        valid: list[NewsArticle] = []
        for raw in data.get("articles", []):
            if not isinstance(raw, dict):
                logger.warning(f"[{label}] Skipping non-object article entry")
                continue
            try:
                url = raw.get("url")
                parsed = urlparse(url) if isinstance(url, str) else None
                if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    logger.debug(
                        f"[{label}] Skipping article without valid URL: "
                        f"{raw.get('title')!r}"
                    )
                    continue
                valid.append(NewsArticle.model_validate(raw))
            except Exception as exc:
                logger.warning(f"[{label}] Malformed article {raw.get('title')!r}: {exc}")

        logger.info(f"[{label}] {len(valid)} valid articles parsed")
        return valid

    def _parse_profile(self, name: str, raw_json: str) -> tuple[PersonProfile, str]:
        """Validates the raw JSON string against the PersonProfile schema."""
        try:
            profile = PersonProfile.model_validate(json.loads(raw_json))
            retrieval_date = date.today().isoformat()
            profile = profile.model_copy(update={
                "sources": [
                    source.model_copy(update={"retrieved_at": retrieval_date})
                    for source in profile.sources
                ]
            })
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


def _strip_trailing_commas(text: str) -> str:
    """Removes commas before closing braces/brackets without touching strings."""
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue

        result.append(char)
        index += 1

    return "".join(result)
