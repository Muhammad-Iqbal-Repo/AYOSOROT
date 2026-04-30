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
import streamlit as st
from dotenv import load_dotenv

from config import APP_ICON, APP_NAME, APP_SUBTITLE, AppConfig, RESEARCH_DIMENSIONS
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
from ui.report_renderer import render_profile, render_summary
from utils.cache import cache_profile, clear_cache, get_cached_profile

load_dotenv()

cfg = AppConfig()
st.set_page_config(
    page_title=cfg.page_title,
    page_icon=cfg.page_icon,
    layout=cfg.layout,
)


# ── Error messages ────────────────────────────────────────────────────────────

_ERROR_MESSAGES: dict[type, tuple[str, str]] = {
    ConfigurationError: (
        "🔑",
        "API key tidak ditemukan atau tidak valid. "
        "Masukkan API key yang valid di bagian **Konfigurasi API** pada sidebar.",
    ),
    SafetyBlockError: (
        "🛡️",
        "Permintaan diblokir oleh filter keamanan Gemini. "
        "Coba gunakan nama lengkap yang lebih spesifik.",
    ),
    QuotaExceededError: (
        "⏳",
        "Kuota API Gemini telah habis. Tunggu beberapa menit lalu coba lagi.",
    ),
    EmptyResponseError: (
        "📭",
        "Model tidak mengembalikan data. "
        "Coba tambahkan konteks pada nama (kota / jabatan).",
    ),
    ParseError: (
        "⚠️",
        "Respons diterima tetapi tidak dapat diproses. Coba lagi.",
    ),
    ApiError: (
        "🌐",
        "Kesalahan pada API Gemini. Periksa koneksi internet dan coba lagi.",
    ),
}


# ── Session state helpers ─────────────────────────────────────────────────────

def _session_profiles() -> dict[str, PersonProfile]:
    """Returns the dict of profiles searched this session, keyed by full_name."""
    if "searched_profiles" not in st.session_state:
        st.session_state["searched_profiles"] = {}
    return st.session_state["searched_profiles"]


def _store_profile(profile: PersonProfile) -> None:
    """Saves profile to session state for compare / graph / news tabs."""
    _session_profiles()[profile.full_name] = profile
    st.session_state["last_profile"] = profile


def _get_api_config() -> tuple[str, str, str]:
    """
    Returns (api_key, searcher_model, writer_model) from session state.
    Falls back to empty strings — callers should validate before using.
    """
    return (
        st.session_state.get("api_key", ""),
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
    """
    Renders the full sidebar and returns the selected dimension keys.

    Sections:
      1. Brand header
      2. API key input
      3. Model selection (Searcher + Writer)
      4. Research dimensions (checkboxes)
      5. Session controls + copyright
    """
    with st.sidebar:
        # ── Brand ─────────────────────────────────────────────────────────────
        st.markdown(
            f"<h2 style='margin:0;letter-spacing:0.05em'>{APP_ICON} {APP_NAME}</h2>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<p style='color:rgba(255,255,255,0.65);font-size:0.8rem;margin:2px 0 0 0'>"
            f"{APP_SUBTITLE}</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        # ── API Key ────────────────────────────────────────────────────────────
        st.markdown(
            "<p class='sidebar-section-label'>🔑 API KEY</p>",
            unsafe_allow_html=True,
        )
        api_key = st.text_input(
            label="api_key_label",
            value=st.session_state.get("api_key", ""),
            type="password",
            placeholder="Masukkan Google AI Studio API Key...",
            key="api_key_input",
            label_visibility="collapsed",
        )

        if api_key and api_key != st.session_state.get("api_key", ""):
            st.session_state["api_key"] = api_key
            st.session_state.pop("available_models", None)
            st.rerun()

        if not api_key:
            st.markdown(
                "<p style='color:rgba(255,255,255,0.5);font-size:0.72rem;margin:4px 0'>"
                "🔒 Tersimpan hanya selama sesi ini.</p>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<p style='color:rgba(255,255,255,0.5);font-size:0.72rem;margin:4px 0'>"
                "✅ API Key aktif</p>",
                unsafe_allow_html=True,
            )

        st.divider()

        # ── Model Selection ────────────────────────────────────────────────────
        st.markdown(
            "<p class='sidebar-section-label'>⚙️ PILIH MODEL</p>",
            unsafe_allow_html=True,
        )

        if not api_key:
            st.markdown(
                "<p style='color:rgba(255,255,255,0.5);font-size:0.8rem'>"
                "Masukkan API key untuk melihat model tersedia.</p>",
                unsafe_allow_html=True,
            )
        else:
            # Fetch model list once per session per API key
            if "available_models" not in st.session_state:
                with st.spinner("Mengambil daftar model..."):
                    try:
                        models = PersonIntelAgent.list_models(api_key)
                        st.session_state["available_models"] = models
                    except ConfigurationError as exc:
                        st.error(f"🔑 {exc}")
                        st.session_state.pop("api_key", None)

            models = st.session_state.get("available_models", [])

            if models:
                # ── Searcher selectbox ─────────────────────────────────────────
                st.markdown(
                    "<p style='color:rgba(255,255,255,0.75);font-size:0.8rem;"
                    "margin:0 0 2px 0'>🔍 Model Pencari</p>",
                    unsafe_allow_html=True,
                )
                searcher_model = st.selectbox(
                    label="searcher_label",
                    options=models,
                    key="searcher_model",
                    label_visibility="collapsed",
                )
                st.markdown(
                    f"<p style='color:rgba(255,255,255,0.45);font-size:0.72rem;"
                    f"margin:2px 0 10px 0'>{_SEARCHER_DESC}</p>",
                    unsafe_allow_html=True,
                )

                # ── Writer selectbox ───────────────────────────────────────────
                st.markdown(
                    "<p style='color:rgba(255,255,255,0.75);font-size:0.8rem;"
                    "margin:0 0 2px 0'>✍️ Model Penulis</p>",
                    unsafe_allow_html=True,
                )
                writer_model = st.selectbox(
                    label="writer_label",
                    options=models,
                    key="writer_model",
                    label_visibility="collapsed",
                )
                st.markdown(
                    f"<p style='color:rgba(255,255,255,0.45);font-size:0.72rem;"
                    f"margin:2px 0 0 0'>{_WRITER_DESC}</p>",
                    unsafe_allow_html=True,
                )

                # ── Active model summary card ──────────────────────────────────
                s = st.session_state.get("searcher_model", "—")
                w = st.session_state.get("writer_model", "—")
                st.markdown(
                    f"<div style='background:rgba(255,255,255,0.1);border-radius:8px;"
                    f"padding:8px 12px;margin-top:10px;border:1px solid rgba(255,255,255,0.15)'>"
                    f"<p style='color:rgba(255,255,255,0.5);font-size:0.65rem;"
                    f"text-transform:uppercase;letter-spacing:0.08em;margin:0 0 4px 0'>"
                    f"Model Aktif</p>"
                    f"<p style='color:#F1F5F9;font-size:0.78rem;margin:0 0 2px 0'>"
                    f"🔍 <b>Pencari:</b> {s}</p>"
                    f"<p style='color:#F1F5F9;font-size:0.78rem;margin:0'>"
                    f"✍️ <b>Penulis:</b> {w}</p>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<p style='color:rgba(255,255,255,0.5);font-size:0.8rem'>"
                    "Tidak ada model yang tersedia untuk key ini.</p>",
                    unsafe_allow_html=True,
                )

        st.divider()

        # ── Research Dimensions ────────────────────────────────────────────────
        st.markdown(
            "<p class='sidebar-section-label'>🗂️ DIMENSI RISET</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='color:rgba(255,255,255,0.55);font-size:0.75rem;margin:0 0 6px 0'>"
            "Pilih kategori informasi yang ingin dicari.</p>",
            unsafe_allow_html=True,
        )

        selected: list[str] = []
        for key, (label, _) in RESEARCH_DIMENSIONS.items():
            if st.checkbox(label, value=True, key=f"dim_{key}"):
                selected.append(key)

        st.divider()

        # ── Session Controls ───────────────────────────────────────────────────
        if st.button("🗑️ Hapus Cache Sesi", use_container_width=True):
            clear_cache()
            for k in ("searched_profiles", "last_profile"):
                st.session_state.pop(k, None)
            st.success("Cache berhasil dihapus.")

        st.markdown(
            "<p style='color:rgba(255,255,255,0.35);font-size:0.72rem;"
            "text-align:center;margin-top:12px'>© Muhammad Iqbal 2026</p>",
            unsafe_allow_html=True,
        )

    return selected


# ── Error display ─────────────────────────────────────────────────────────────

def _show_error(exc: Exception) -> None:
    """Renders a typed, user-friendly error message with technical detail."""
    icon, message = _ERROR_MESSAGES.get(
        type(exc), ("❌", f"Terjadi kesalahan tak terduga: {exc}")
    )
    st.error(f"{icon} **{type(exc).__name__}**\n\n{message}")
    with st.expander("🔧 Detail teknis"):
        st.code(f"{type(exc).__name__}: {exc}")


# ── Search pipeline helpers ───────────────────────────────────────────────────

def _cache_key(name: str, selected_keys: list[str]) -> str:
    return f"{name}|{'_'.join(sorted(selected_keys))}"


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

    except (
        ConfigurationError, SafetyBlockError, QuotaExceededError,
        EmptyResponseError, ParseError, ApiError,
    ) as exc:
        progress_bar.empty()
        status_text.empty()
        _show_error(exc)
        return None

    except Exception as exc:
        progress_bar.empty()
        status_text.empty()
        st.error(f"❌ Kesalahan tidak terduga: {exc}")
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
    api_key = st.session_state.get("api_key", "")

    # ── Search card ────────────────────────────────────────────────────────────
    st.markdown(
        "<div class='sorot-search-card'>"
        "<p class='sorot-search-title'>🔍 Telusuri Tokoh Publik Indonesia</p>"
        "<p class='sorot-search-subtitle'>"
        "Masukkan nama lengkap untuk mendapatkan profil publik, berita terkini, "
        "dan peta relasi tokoh secara otomatis."
        "</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    if not api_key:
        st.warning(
            "⚠️ Masukkan **Google AI Studio API Key** di sidebar untuk memulai pencarian."
        )
        # Still fall through to render any existing profile below
    else:
        with st.form("search_form"):
            name = st.text_input(
                "Nama lengkap tokoh:",
                placeholder="Contoh: Prabowo Subianto, Bahlil Lahadalia...",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button(
                f"{APP_ICON} Sorot Tokoh Ini",
                use_container_width=True,
            )

        # Disambiguation pending from previous rerun
        if st.session_state.get("disambig_pending") and not submitted:
            _resume_after_disambiguation(selected_keys)

        elif submitted and name.strip():
            if not selected_keys:
                st.warning("⚠️ Pilih minimal satu dimensi riset di sidebar.")
            else:
                name = name.strip()
                agent = _make_agent()

                with st.spinner("🔎 Memeriksa apakah nama ambigu..."):
                    candidates = agent.disambiguate(name)

                if candidates:
                    options = {f"{c.name} — {c.description}": c.name for c in candidates}
                    options["🔍 Tetap cari dengan nama asli"] = name
                    st.session_state.update({
                        "disambig_pending": True,
                        "disambig_name":    name,
                        "disambig_options": options,
                        "disambig_keys":    selected_keys,
                    })
                    st.rerun()
                else:
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
        f'⚠️ Nama **"{name}"** mungkin merujuk ke beberapa tokoh berbeda. '
        "Pilih tokoh yang dimaksud:"
    )
    chosen_label = st.radio("Pilih tokoh:", list(options.keys()), key="disambiguation")
    chosen_name  = options[chosen_label]

    if st.button("✅ Lanjutkan Pencarian", key="disambig_confirm", use_container_width=True):
        for k in ("disambig_pending", "disambig_name", "disambig_options", "disambig_keys"):
            st.session_state.pop(k, None)
        _run_full_search(chosen_name, keys, _make_agent())


def _run_full_search(name: str, selected_keys: list[str], agent: PersonIntelAgent) -> None:
    """
    Cache-check → agent → store pipeline for a resolved, unambiguous name.

    This function only fetches and stores the profile.  Rendering is handled
    by _tab_search which always re-renders from session_state on every rerun —
    this separation ensures summary button clicks work correctly.
    """
    ck     = _cache_key(name, selected_keys)
    cached = get_cached_profile(ck)

    if cached:
        st.success("✅ Hasil dari cache sesi ini")
        _store_profile(cached)
        return

    progress_bar = st.progress(0)
    status_text  = st.empty()

    profile = _do_search(name, selected_keys, agent, progress_bar, status_text)
    if not profile:
        return

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
    render_profile(profile)
    st.divider()

    # ── AI Summary ─────────────────────────────────────────────────────────────
    st.markdown(
        f"<h3 style='color:{Colors.PRIMARY}'>🤖 Ringkasan AI</h3>",
        unsafe_allow_html=True,
    )

    summary_key = f"summary_{profile.full_name}"

    if summary_key in st.session_state:
        summary = st.session_state[summary_key]
        if summary:
            render_summary(summary)
        else:
            st.caption("_Ringkasan tidak tersedia untuk tokoh ini._")
        if st.button("🔄 Regenerasi Ringkasan", key=f"regen_{profile.full_name}"):
            del st.session_state[summary_key]
            st.rerun()
    else:
        st.caption(
            "Buat ringkasan naratif berbahasa Indonesia "
            "berdasarkan data profil yang telah dikumpulkan."
        )
        if st.button(
            "✨ Buat Ringkasan AI",
            key=f"gen_summary_{profile.full_name}",
            use_container_width=True,
        ):
            with st.spinner("✍️ Menyusun ringkasan..."):
                agent = _make_agent()
                summary = agent.generate_summary(profile)
            st.session_state[summary_key] = summary
            st.rerun()


# ── Tab 2 — Compare ───────────────────────────────────────────────────────────

def _tab_compare() -> None:
    st.caption("Bandingkan profil tokoh yang telah dicari dalam sesi ini.")

    profiles = _session_profiles()
    if len(profiles) < 2:
        st.info(
            f"Butuh minimal 2 profil. "
            f"Cari {2 - len(profiles)} tokoh lagi di tab **🔍 Cari Tokoh**."
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
        st.info("Cari tokoh terlebih dahulu di tab **🔍 Cari Tokoh**.")
        return

    profiles = _session_profiles()
    if len(profiles) > 1:
        chosen_name = st.selectbox(
            "Pilih tokoh:",
            options=list(profiles.keys()),
            index=list(profiles.keys()).index(profile.full_name),
            key="news_profile_select",
        )
        profile = profiles[chosen_name]

    sub_person, sub_company = st.tabs(["📰 Berita Tokoh", "🏢 Berita Perusahaan"])

    # ── Person news ────────────────────────────────────────────────────────────
    with sub_person:
        st.markdown(f"Berita terbaru untuk: **{profile.full_name}**")
        person_key = f"news_person_{profile.full_name}"

        if person_key in st.session_state:
            render_news(
                st.session_state[person_key],
                context_label="berita tokoh",
                filter_key_prefix="news_person",
            )
            if st.button("🔄 Refresh", key="refresh_person_news"):
                del st.session_state[person_key]
                st.rerun()
        else:
            if st.button(
                f"📰 Ambil Berita Terbaru — {profile.full_name}",
                use_container_width=True,
                key="fetch_person_news",
            ):
                with st.spinner("🔍 Mencari berita tokoh..."):
                    articles = _make_agent().fetch_news(profile.full_name)
                st.session_state[person_key] = articles
                st.rerun()

    # ── Company news ───────────────────────────────────────────────────────────
    with sub_company:
        companies = [c.entity_name for c in profile.corporate_affiliations]

        if not companies:
            st.info(
                "Tidak ada data afiliasi perusahaan. "
                "Centang **🏢 Afiliasi Grup Usaha** di sidebar saat mencari."
            )
        else:
            selected_company = st.selectbox(
                "Pilih perusahaan / grup usaha:",
                options=companies,
                key="company_news_selector",
            )
            company_key = f"news_company_{profile.full_name}_{selected_company}"

            if company_key in st.session_state:
                render_news(
                    st.session_state[company_key],
                    context_label=f"berita {selected_company}",
                    filter_key_prefix="news_company",
                )
                if st.button("🔄 Refresh", key="refresh_company_news"):
                    del st.session_state[company_key]
                    st.rerun()
            else:
                if st.button(
                    f"🏢 Ambil Berita Terbaru — {selected_company}",
                    use_container_width=True,
                    key="fetch_company_news",
                ):
                    with st.spinner(f"🔍 Mencari berita untuk {selected_company}..."):
                        articles = _make_agent().fetch_company_news(
                            selected_company, profile.full_name
                        )
                    st.session_state[company_key] = articles
                    st.rerun()


# ── Tab 4 — Graph ─────────────────────────────────────────────────────────────

def _tab_graph() -> None:
    st.caption("Graf interaktif relasi tokoh — keluarga, perusahaan, dan partai.")

    profile: PersonProfile | None = st.session_state.get("last_profile")
    if profile is None:
        st.info("Cari tokoh terlebih dahulu di tab **🔍 Cari Tokoh**.")
        return

    profiles = _session_profiles()
    if len(profiles) > 1:
        chosen_name = st.selectbox(
            "Pilih tokoh:",
            options=list(profiles.keys()),
            index=list(profiles.keys()).index(profile.full_name),
            key="graph_profile_select",
        )
        profile = profiles[chosen_name]

    st.markdown(f"Graf relasi untuk: **{profile.full_name}**")
    render_graph(profile)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    inject_global_css()

    selected_keys = _sidebar()

    # Hero header
    st.markdown(
        f"<h1 style='font-size:2.6rem;font-weight:800;margin:0;color:{Colors.PRIMARY}'>"
        f"{APP_ICON} {APP_NAME}</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='color:{Colors.MUTED};margin:4px 0 0 0;font-size:0.95rem'>"
        f"{APP_SUBTITLE}</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    tab_search, tab_compare, tab_news, tab_graph = st.tabs([
        "🔍 Cari Tokoh",
        "⚖️ Bandingkan",
        "📰 Berita Terkini",
        "🕸️ Graf Relasi",
    ])

    with tab_search:
        _tab_search(selected_keys)
    with tab_compare:
        _tab_compare()
    with tab_news:
        _tab_news()
    with tab_graph:
        _tab_graph()


if __name__ == "__main__":
    main()
