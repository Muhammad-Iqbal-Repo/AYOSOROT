# app.py
"""
SOROT — Sistem Observasi & Riset Online Tokoh

Tabs
────
  🔍 Cari Tokoh   — search with disambiguation + AI summary
  ⚖️  Bandingkan   — side-by-side multi-profile comparison
  📰 Berita Terkini — person and company news
  🕸️  Graf Relasi  — interactive relationship graph
"""
import os
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv

from config import APP_NAME, APP_SUBTITLE, AppConfig, RESEARCH_DIMENSIONS
from agent.exceptions import (
    ApiError, ConfigurationError, EmptyResponseError,
    ParseError, QuotaExceededError, SafetyBlockError,
)
from agent.orchestrator import PersonIntelAgent
from agent.schema import PersonProfile
from ui.comparison_renderer import render_comparison
from ui.components import Colors, inject_global_css
from ui.graph_renderer import render_graph
from ui.news_renderer import render_news
from ui.report_renderer import render_profile_details, render_profile_header, render_summary
from utils.cache import (
    build_profile_cache_key,
    cache_profile,
    clear_research_state,
    get_cached_profile,
    profile_revision,
    profile_session_label,
)

load_dotenv()

cfg = AppConfig()
st.set_page_config(
    page_title=cfg.page_title,
    page_icon=cfg.page_icon,
    layout=cfg.layout,
)


# ── Error messages ────────────────────────────────────────────────────────────

_ERROR_MESSAGES: dict[type, str] = {
    ConfigurationError: (
        "API key tidak ditemukan atau tidak valid. "
        "Masukkan API key yang valid di bagian **Konfigurasi API** pada sidebar.",
    ),
    SafetyBlockError: (
        "Permintaan diblokir oleh filter keamanan Gemini. "
        "Coba gunakan nama lengkap yang lebih spesifik.",
    ),
    QuotaExceededError: (
        "Kuota API Gemini telah habis. Tunggu beberapa menit lalu coba lagi.",
    ),
    EmptyResponseError: (
        "Model tidak mengembalikan data. "
        "Coba tambahkan konteks pada nama (kota / jabatan).",
    ),
    ParseError: (
        "Respons diterima tetapi tidak dapat diproses. Coba lagi.",
    ),
    ApiError: (
        "Kesalahan pada API Gemini. Periksa koneksi internet dan coba lagi.",
    ),
}

_AGENT_ERRORS = (
    ConfigurationError,
    SafetyBlockError,
    QuotaExceededError,
    EmptyResponseError,
    ParseError,
    ApiError,
)


# ── Session state helpers ─────────────────────────────────────────────────────

def _session_profiles() -> dict[str, PersonProfile]:
    """Returns the dict of profiles searched this session, keyed by full_name."""
    if "searched_profiles" not in st.session_state:
        st.session_state["searched_profiles"] = {}
    return st.session_state["searched_profiles"]


def _store_profile(profile: PersonProfile) -> None:
    """Saves profile to session state for compare / graph / news tabs."""
    _session_profiles()[profile_session_label(profile)] = profile
    st.session_state["last_profile"] = profile


def _current_api_key() -> str:
    """Returns the active API key from session state or the local environment."""
    return (st.session_state.get("api_key") or os.getenv("GOOGLE_API_KEY", "")).strip()


def _server_api_key() -> str:
    """Returns the server-owned key without exposing it through widget state."""
    return os.getenv("GOOGLE_API_KEY", "").strip()


def _get_api_config() -> tuple[str, str, str]:
    """
    Returns (api_key, searcher_model, writer_model) from session state.
    Falls back to empty strings — callers should validate before using.
    """
    return (
        _current_api_key(),
        st.session_state.get("searcher_model", ""),
        st.session_state.get("writer_model", ""),
    )


def _make_agent() -> PersonIntelAgent:
    """
    Creates a PersonIntelAgent from session state config.
    Raises ConfigurationError if API key or models are not set.
    """
    api_key, searcher_model, writer_model = _get_api_config()
    return PersonIntelAgent(
        api_key=api_key,
        searcher_model=searcher_model,
        writer_model=writer_model,
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────

# Model role descriptions shown below each selectbox
_SEARCHER_DESC = "Bertugas mencari informasi di web. Gunakan model ringan & cepat."
_WRITER_DESC   = "Bertugas menyusun & memformat hasil pencarian. Gunakan model terbaik."


def _sidebar() -> list[str]:
    """Render research scope first, with technical settings tucked away."""
    with st.sidebar:
        st.markdown(
            f"<p class='sidebar-brand'>{APP_NAME}</p>",
            unsafe_allow_html=True,
        )
        st.caption(APP_SUBTITLE)
        st.divider()

        st.markdown(
            "<p class='sidebar-section-label'>Dimensi riset</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p class='sidebar-note'>Pilih kategori informasi yang perlu ditelusuri.</p>",
            unsafe_allow_html=True,
        )
        selected: list[str] = []
        for key, (label, _) in RESEARCH_DIMENSIONS.items():
            if st.checkbox(label, value=True, key=f"dim_{key}"):
                selected.append(key)

        st.divider()
        with st.expander("API dan model"):
            user_api_key = st.text_input(
                "Google AI Studio API key",
                type="password",
                placeholder="Masukkan API key",
                key="api_key_input",
            )
            if user_api_key != st.session_state.get("api_key", ""):
                if user_api_key:
                    st.session_state["api_key"] = user_api_key
                else:
                    st.session_state.pop("api_key", None)
                st.session_state.pop("available_models", None)
                st.rerun()

            api_key = user_api_key or _server_api_key()
            if user_api_key:
                st.caption("Kunci pengguna aktif untuk sesi ini.")
            elif _server_api_key():
                st.caption("Konfigurasi API server aktif.")
            else:
                st.caption("API key diperlukan untuk melakukan riset.")

            if api_key:
                if "available_models" not in st.session_state:
                    with st.spinner("Mengambil daftar model..."):
                        try:
                            st.session_state["available_models"] = (
                                PersonIntelAgent.list_models(api_key)
                            )
                        except ConfigurationError as exc:
                            st.error(str(exc))
                            st.session_state.pop("api_key", None)

                models = st.session_state.get("available_models", [])
                if models:
                    st.selectbox("Model pencari", models, key="searcher_model")
                    st.caption(_SEARCHER_DESC)
                    st.selectbox("Model penulis", models, key="writer_model")
                    st.caption(_WRITER_DESC)
                else:
                    st.caption("Tidak ada model yang tersedia untuk kunci ini.")

        if st.button("Hapus data riset sesi", use_container_width=True):
            clear_research_state()
            st.success("Cache berhasil dihapus.")
        st.caption("Tri-Bal · 2026")

    return selected


# ── Error display ─────────────────────────────────────────────────────────────

def _show_error(exc: Exception) -> None:
    """Renders a typed, user-friendly error message with technical detail."""
    message = _ERROR_MESSAGES.get(
        type(exc), f"Terjadi kesalahan tak terduga: {exc}"
    )
    st.error(f"**{type(exc).__name__}**\n\n{message}")
    with st.expander("Detail teknis"):
        st.code(f"{type(exc).__name__}: {exc}")


# ── Search pipeline helpers ───────────────────────────────────────────────────

def _cache_key(query: str, selected_keys: list[str]) -> str:
    _, searcher_model, writer_model = _get_api_config()
    return build_profile_cache_key(
        query, selected_keys, searcher_model, writer_model
    )


def _identity_resolution(name: str) -> dict[str, str | None] | None:
    key = " ".join(name.casefold().split())
    return st.session_state.get("identity_resolutions", {}).get(key)


def _remember_identity_resolution(
    name: str, query: str, identity_context: str | None
) -> None:
    key = " ".join(name.casefold().split())
    if "identity_resolutions" not in st.session_state:
        st.session_state["identity_resolutions"] = {}
    st.session_state["identity_resolutions"][key] = {
        "query": query,
        "identity_context": identity_context,
    }


def _do_search(
    name:          str,
    selected_keys: list[str],
    agent:         PersonIntelAgent,
    progress_bar,
    status_text,
) -> PersonProfile | None:
    """Runs the agent pipeline. Returns profile on success, None on error."""
    def update(step: str, pct: float) -> None:
        progress_bar.progress(pct)
        status_text.markdown(
            f"<small style='color:{Colors.MUTED}'>{step}</small>",
            unsafe_allow_html=True,
        )

    try:
        profile, _ = agent.run(
            name, selected_keys=selected_keys, progress_callback=update
        )
        progress_bar.progress(1.0)
        status_text.empty()
        return profile

    except _AGENT_ERRORS as exc:
        progress_bar.empty()
        status_text.empty()
        _show_error(exc)
        return None

    except Exception as exc:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Kesalahan tidak terduga: {exc}")
        raise


# ── Tab 1 — Search ────────────────────────────────────────────────────────────

def _tab_search(selected_keys: list[str]) -> None:
    """
    Main search tab.

    Structure
    ─────────
    1. Search card (always shown)
    2. Disambiguation UI (shown if pending from previous rerun)
    3. Profile + Summary (always re-rendered from session_state on every rerun)

    The profile and summary sections are rendered from session_state on EVERY
    rerun — not only when the form is submitted. This is the key fix for the
    summary button: when the user clicks "Buat Ringkasan AI", Streamlit reruns,
    the form is not submitted, but the profile is still re-rendered from
    session_state and the summary logic runs correctly.

    Disambiguation state keys:
        disambig_pending  bool           — step is in progress
        disambig_name     str            — original name entered
        disambig_options  dict[str, str] — label → resolved name
        disambig_keys     list[str]      — selected_keys at submission time
    """
    api_key = _current_api_key()

    # ── Search card ────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='sorot-search-card'>"
        "<p class='sorot-search-title'>Telusuri tokoh publik Indonesia</p>"
        "<p class='sorot-search-subtitle'>"
        "Masukkan nama lengkap, lalu tambahkan jabatan atau wilayah bila namanya umum."
        "</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    if not api_key:
        st.warning(
            "Masukkan Google AI Studio API key pada bagian API dan model di sidebar."
        )
        # Still fall through to render any existing profile below
    else:
        with st.form("search_form"):
            name = st.text_input(
                "Nama tokoh",
                placeholder="Nama lengkap, jabatan, atau wilayah",
                help="Konteks seperti kota atau jabatan membantu membedakan tokoh dengan nama serupa.",
            )
            submitted = st.form_submit_button(
                "Telusuri tokoh",
                use_container_width=True,
            )

        # Disambiguation pending from previous rerun
        if st.session_state.get("disambig_pending") and not submitted:
            _resume_after_disambiguation(selected_keys)

        elif submitted and name.strip():
            if not selected_keys:
                st.warning("Pilih minimal satu dimensi riset di sidebar.")
            else:
                name = name.strip()
                resolution = _identity_resolution(name)
                if resolution:
                    _run_full_search(
                        str(resolution["query"]),
                        selected_keys,
                        identity_context=resolution.get("identity_context"),
                    )
                else:
                    cached = get_cached_profile(_cache_key(name, selected_keys))
                    if cached:
                        st.success("Hasil dari cache sesi ini")
                        _store_profile(cached)
                    else:
                        try:
                            agent = _make_agent()
                            with st.spinner("Memeriksa apakah nama ambigu..."):
                                candidates = agent.disambiguate(name)
                        except _AGENT_ERRORS as exc:
                            _show_error(exc)
                            candidates = None

                        if candidates:
                            options = {
                                f"{c.name}: {c.description}": {
                                    "query": f"{c.name}, {c.description}",
                                    "identity_context": c.description,
                                }
                                for c in candidates
                            }
                            options["Tetap cari dengan nama asli"] = {
                                "query": name,
                                "identity_context": None,
                            }
                            st.session_state.update({
                                "disambig_pending": True,
                                "disambig_name":    name,
                                "disambig_options": options,
                                "disambig_keys":    selected_keys,
                            })
                            st.rerun()
                        elif candidates == []:
                            _run_full_search(name, selected_keys, agent)

    # ── Always render profile + summary from session_state ─────────────────────
    # This block runs on EVERY rerun (including summary button clicks) so the
    # summary button is never swallowed by the form's early-return logic.
    last_profile: PersonProfile | None = st.session_state.get("last_profile")
    if last_profile:
        st.divider()
        _render_profile_section(last_profile)


def _resume_after_disambiguation(selected_keys: list[str]) -> None:
    """Renders the disambiguation UI and runs the search after confirmation."""
    name    = st.session_state["disambig_name"]
    options = st.session_state["disambig_options"]
    keys    = st.session_state.get("disambig_keys", selected_keys)

    st.warning(
        f'Nama **"{name}"** mungkin merujuk ke beberapa tokoh berbeda. '
        "Pilih tokoh yang dimaksud:"
    )
    chosen_label = st.radio("Pilih tokoh:", list(options.keys()), key="disambiguation")
    selection = options[chosen_label]

    if st.button("Lanjutkan pencarian", key="disambig_confirm", use_container_width=True):
        _remember_identity_resolution(
            name,
            selection["query"],
            selection.get("identity_context"),
        )
        for k in ("disambig_pending", "disambig_name", "disambig_options", "disambig_keys"):
            st.session_state.pop(k, None)
        _run_full_search(
            selection["query"],
            keys,
            identity_context=selection.get("identity_context"),
        )


def _run_full_search(
    query: str,
    selected_keys: list[str],
    agent: PersonIntelAgent | None = None,
    identity_context: str | None = None,
) -> None:
    """
    Cache-check → agent → store pipeline for a resolved, unambiguous name.

    This function only fetches and stores the profile.  Rendering is handled
    by _tab_search which always re-renders from session_state on every rerun —
    this separation ensures summary button clicks work correctly.
    """
    ck     = _cache_key(query, selected_keys)
    cached = get_cached_profile(ck)

    if cached:
        st.success("Hasil dari cache sesi ini")
        _store_profile(cached)
        return

    progress_bar = st.progress(0)
    status_text  = st.empty()

    try:
        active_agent = agent or _make_agent()
    except _AGENT_ERRORS as exc:
        progress_bar.empty()
        status_text.empty()
        _show_error(exc)
        return

    profile = _do_search(query, selected_keys, active_agent, progress_bar, status_text)
    if not profile:
        return

    profile = profile.model_copy(update={
        "identity_context": identity_context,
        "research_query": query,
        "researched_dimensions": list(selected_keys),
        "researched_at": datetime.now(timezone.utc).isoformat(),
    })
    cache_profile(ck, profile)
    _store_profile(profile)


def _render_profile_section(profile: PersonProfile) -> None:
    """
    Renders profile tables + AI summary section from session_state.

    Called on every rerun — not just on form submission — so summary button
    clicks correctly trigger generation without being swallowed.

    The agent is re-instantiated here only when a summary generation is
    actually needed, keeping the common path (just viewing) free of API calls.
    """
    render_profile_header(profile)

    # ── AI Summary ─────────────────────────────────────────────────────────────
    st.markdown(
        f"<h3 style='color:{Colors.PRIMARY}'>Ringkasan</h3>",
        unsafe_allow_html=True,
    )

    revision = profile_revision(profile)
    summary_key = f"summary_{revision}"

    if summary_key in st.session_state:
        summary = st.session_state[summary_key]
        if summary:
            render_summary(summary)
        else:
            st.caption("_Ringkasan tidak tersedia untuk tokoh ini._")
        if st.button("Buat ulang ringkasan", key=f"regen_{revision}"):
            del st.session_state[summary_key]
            st.rerun()
    else:
        st.caption(
            "Buat ringkasan naratif berbahasa Indonesia "
            "berdasarkan data profil yang telah dikumpulkan."
        )
        if st.button(
            "Buat ringkasan",
            key=f"gen_summary_{revision}",
            use_container_width=True,
        ):
            try:
                with st.spinner("Menyusun ringkasan..."):
                    agent = _make_agent()
                    summary = agent.generate_summary(profile)
                st.session_state[summary_key] = summary
                st.rerun()
            except _AGENT_ERRORS as exc:
                _show_error(exc)

    st.divider()
    render_profile_details(profile)


# ── Tab 2 — Compare ───────────────────────────────────────────────────────────

def _tab_compare() -> None:
    st.caption("Bandingkan profil tokoh yang telah dicari dalam sesi ini.")

    profiles = _session_profiles()
    if len(profiles) < 2:
        st.info(
            f"Butuh minimal 2 profil. "
            f"Cari {2 - len(profiles)} tokoh lagi di tab **Cari tokoh**."
        )
        return

    selected_names = st.multiselect(
        "Pilih tokoh (2–4):",
        options=list(profiles.keys()),
        max_selections=4,
    )
    if len(selected_names) < 2:
        st.info("Pilih minimal 2 tokoh.")
        return

    render_comparison([profiles[n] for n in selected_names])


# ── Tab 3 — News ──────────────────────────────────────────────────────────────

def _tab_news() -> None:
    """Person news and company news in two sub-tabs."""
    st.caption("Berita dan artikel terbaru tentang tokoh dan perusahaan terkait.")

    profile: PersonProfile | None = st.session_state.get("last_profile")
    if profile is None:
        st.info("Cari tokoh terlebih dahulu di tab **Cari tokoh**.")
        return

    profiles = _session_profiles()
    if len(profiles) > 1:
        current_label = profile_session_label(profile)
        chosen_name = st.selectbox(
            "Pilih tokoh:",
            options=list(profiles.keys()),
            index=list(profiles.keys()).index(current_label),
            key="news_profile_select",
        )
        profile = profiles[chosen_name]

    sub_person, sub_company = st.tabs(["Berita tokoh", "Berita perusahaan"])

    # ── Person news ────────────────────────────────────────────────────────────
    with sub_person:
        st.markdown(f"Berita terbaru untuk: **{profile.full_name}**")
        revision = profile_revision(profile)
        person_key = f"news_person_{revision}"

        if person_key in st.session_state:
            render_news(
                st.session_state[person_key],
                context_label="berita tokoh",
                filter_key_prefix=f"news_person_{revision}",
            )
            if st.button("Muat ulang", key="refresh_person_news"):
                del st.session_state[person_key]
                st.rerun()
        else:
            if st.button(
                f"Ambil berita terbaru: {profile.full_name}",
                use_container_width=True,
                key="fetch_person_news",
            ):
                try:
                    with st.spinner("Mencari berita tokoh..."):
                        articles = _make_agent().fetch_news(
                            profile.research_query or profile.full_name
                        )
                    st.session_state[person_key] = articles
                    st.rerun()
                except _AGENT_ERRORS as exc:
                    _show_error(exc)

    # ── Company news ───────────────────────────────────────────────────────────
    with sub_company:
        companies = [c.entity_name for c in profile.corporate_affiliations]

        if not companies:
            st.info(
                "Tidak ada data afiliasi perusahaan. "
                "Centang **Afiliasi grup usaha** di sidebar saat mencari."
            )
        else:
            selected_company = st.selectbox(
                "Pilih perusahaan / grup usaha:",
                options=companies,
                key="company_news_selector",
            )
            company_key = f"news_company_{revision}_{selected_company}"

            if company_key in st.session_state:
                render_news(
                    st.session_state[company_key],
                    context_label=f"berita {selected_company}",
                    filter_key_prefix=f"news_company_{revision}",
                )
                if st.button("Muat ulang", key="refresh_company_news"):
                    del st.session_state[company_key]
                    st.rerun()
            else:
                if st.button(
                    f"Ambil berita terbaru: {selected_company}",
                    use_container_width=True,
                    key="fetch_company_news",
                ):
                    try:
                        with st.spinner(f"Mencari berita untuk {selected_company}..."):
                            articles = _make_agent().fetch_company_news(
                                selected_company,
                                profile.research_query or profile.full_name,
                            )
                        st.session_state[company_key] = articles
                        st.rerun()
                    except _AGENT_ERRORS as exc:
                        _show_error(exc)


# ── Tab 4 — Graph ─────────────────────────────────────────────────────────────

def _tab_graph() -> None:
    st.caption("Graf interaktif relasi tokoh: keluarga, perusahaan, dan partai.")

    profile: PersonProfile | None = st.session_state.get("last_profile")
    if profile is None:
        st.info("Cari tokoh terlebih dahulu di tab **Cari tokoh**.")
        return

    profiles = _session_profiles()
    if len(profiles) > 1:
        current_label = profile_session_label(profile)
        chosen_name = st.selectbox(
            "Pilih tokoh:",
            options=list(profiles.keys()),
            index=list(profiles.keys()).index(current_label),
            key="graph_profile_select",
        )
        profile = profiles[chosen_name]

    st.markdown(f"Graf relasi untuk: **{profile.full_name}**")
    render_graph(profile)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    inject_global_css()

    selected_keys = _sidebar()

    st.markdown(
        f"<h1 class='sorot-masthead'>{APP_NAME}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p class='sorot-kicker'>"
        f"{APP_SUBTITLE}</p>",
        unsafe_allow_html=True,
    )

    tabs = st.tabs(
        ["Cari tokoh", "Bandingkan", "Berita terkini", "Graf relasi"],
        key="main_tabs",
        on_change="rerun",
    )
    renderers = (
        lambda: _tab_search(selected_keys),
        _tab_compare,
        _tab_news,
        _tab_graph,
    )
    for tab, render in zip(tabs, renderers):
        if tab.open:
            with tab:
                render()


if __name__ == "__main__":
    main()
