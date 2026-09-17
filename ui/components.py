"""Shared visual primitives for the SOROT Streamlit interface."""
from html import escape

import streamlit as st

from agent.schema import ConfidenceLevel, SourceQuality


class Colors:
    PRIMARY = "#1E3A5F"
    PRIMARY_LIGHT = "#385777"
    ACCENT = "#F0A500"
    SUCCESS = "#1B7340"
    WARNING = "#B45309"
    DANGER = "#B91C1C"
    MUTED = "#526172"
    SURFACE = "#FFFFFF"
    PAPER = "#F6F4EE"
    INK = "#202C39"
    BORDER = "#D8DDE3"
    CONF_HIGH = SUCCESS
    CONF_MEDIUM = WARNING
    CONF_LOW = DANGER
    SRC_OFFICIAL = PRIMARY
    SRC_NATIONAL = SUCCESS
    SRC_LOCAL = "#5B21B6"
    SRC_PROFESSIONAL = "#0E7490"
    SRC_OTHER = MUTED


_CONFIDENCE_COLORS: dict[str, str] = {
    ConfidenceLevel.HIGH: Colors.CONF_HIGH,
    ConfidenceLevel.MEDIUM: Colors.CONF_MEDIUM,
    ConfidenceLevel.LOW: Colors.CONF_LOW,
}

_SOURCE_QUALITY_COLORS: dict[str, str] = {
    SourceQuality.OFFICIAL: Colors.SRC_OFFICIAL,
    SourceQuality.NATIONAL: Colors.SRC_NATIONAL,
    SourceQuality.LOCAL: Colors.SRC_LOCAL,
    SourceQuality.PROFESSIONAL: Colors.SRC_PROFESSIONAL,
    SourceQuality.OTHER: Colors.SRC_OTHER,
}


_CSS = f"""
<style>
:root {{
    --sorot-paper: {Colors.PAPER};
    --sorot-surface: {Colors.SURFACE};
    --sorot-ink: {Colors.INK};
    --sorot-muted: {Colors.MUTED};
    --sorot-navy: {Colors.PRIMARY};
    --sorot-gold: {Colors.ACCENT};
    --sorot-border: {Colors.BORDER};
}}
.stApp {{ background: var(--sorot-paper); color: var(--sorot-ink); }}
.block-container {{ max-width: 1120px !important; padding-top: 1.75rem !important; }}
h1, h2, h3, .sorot-masthead, .sorot-profile-name {{
    font-family: Georgia, "Times New Roman", serif !important;
    letter-spacing: -0.02em;
}}
[data-testid="stSidebar"] {{
    background: #EEF0F2;
    border-right: 1px solid var(--sorot-border);
}}
[data-testid="stSidebar"] hr {{ margin: 0.75rem 0 !important; }}
.sidebar-brand {{
    color: var(--sorot-navy);
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.25rem;
    font-weight: 700;
    margin: 0;
}}
.sidebar-section-label {{
    color: var(--sorot-muted);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    margin: 0 0 0.35rem;
    text-transform: uppercase;
}}
.sidebar-note {{ color: var(--sorot-muted); font-size: 0.78rem; margin: 0 0 0.5rem; }}
button, input, [data-baseweb="select"] > div {{ border-radius: 4px !important; }}
button:focus-visible, input:focus-visible, [tabindex]:focus-visible {{
    outline: 3px solid rgba(240, 165, 0, 0.55) !important;
    outline-offset: 2px !important;
}}
.stButton button, div[data-testid="stFormSubmitButton"] button {{ min-height: 44px; }}
div[data-testid="stFormSubmitButton"] button {{
    background: var(--sorot-gold) !important;
    border: 1px solid #D18F00 !important;
    color: var(--sorot-navy) !important;
    font-weight: 700 !important;
}}
div[data-testid="stFormSubmitButton"] button:hover {{ background: #DFA000 !important; }}
.sorot-masthead {{ color: var(--sorot-navy); font-size: 2rem; font-weight: 700; margin: 0; }}
.sorot-kicker {{ color: var(--sorot-muted); font-size: 0.9rem; margin: 0.2rem 0 1rem; }}
.sorot-search-card {{
    background: var(--sorot-surface);
    border: 1px solid var(--sorot-border);
    border-radius: 6px;
    margin-bottom: 1rem;
    padding: 1.25rem 1.5rem;
}}
.sorot-search-title {{ color: var(--sorot-navy); font-family: Georgia, serif; font-size: 1.3rem; font-weight: 700; margin: 0 0 0.25rem; }}
.sorot-search-subtitle {{ color: var(--sorot-muted); font-size: 0.88rem; margin: 0; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 1.25rem; }}
.stTabs [data-baseweb="tab"] {{ font-size: 0.9rem; padding: 0.65rem 0.15rem; }}
.stTabs [aria-selected="true"] {{ color: var(--sorot-navy) !important; border-bottom-color: var(--sorot-gold) !important; }}
.sorot-profile-name {{ color: var(--sorot-navy); font-size: 2rem; font-weight: 700; margin: 0; }}
.sorot-metric-row {{
    align-items: center;
    border-bottom: 1px solid var(--sorot-border);
    border-top: 1px solid var(--sorot-border);
    display: flex;
    flex-wrap: wrap;
    margin: 1rem 0;
    padding: 0.7rem 0;
}}
.sorot-metric {{ border-right: 1px solid var(--sorot-border); min-width: 120px; padding: 0.1rem 1rem; }}
.sorot-metric:first-child {{ padding-left: 0; }}
.sorot-metric:last-child {{ border-right: 0; }}
.sorot-metric-label {{ color: var(--sorot-muted); font-size: 0.7rem; letter-spacing: 0.05em; text-transform: uppercase; }}
.sorot-metric-value {{ color: var(--sorot-navy); font-size: 1rem; font-weight: 700; }}
.sorot-section-header {{ align-items: center; display: flex; gap: 0.5rem; margin: 0 0 0.75rem; }}
.sorot-section-title {{ color: var(--sorot-navy); font-family: Georgia, serif; font-size: 1.12rem; font-weight: 700; }}
.sorot-summary-card {{
    background: #FFFDF8;
    border: 1px solid var(--sorot-border);
    border-left: 3px solid var(--sorot-gold);
    color: var(--sorot-ink);
    line-height: 1.75;
    margin-bottom: 1rem;
    max-width: 76ch;
    padding: 1.2rem 1.4rem;
}}
.sorot-summary-card p {{ margin: 0 0 0.8rem; }}
.sorot-summary-card p:last-child {{ margin-bottom: 0; }}
.sorot-graph-legend {{ display: flex; flex-wrap: wrap; gap: 1rem; color: var(--sorot-muted); font-size: 0.78rem; margin: 0 0 0.5rem; }}
details summary {{ color: var(--sorot-navy); font-weight: 600; }}
@media (max-width: 720px) {{
    .block-container {{ padding-left: 1rem !important; padding-right: 1rem !important; }}
    .sorot-masthead, .sorot-profile-name {{ font-size: 1.65rem; }}
    .sorot-search-card {{ padding: 1rem; }}
    .sorot-metric {{ border-bottom: 1px solid var(--sorot-border); border-right: 0; flex: 1 1 45%; padding: 0.5rem 0; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 0.75rem; overflow-x: auto; }}
}}
</style>
"""


def inject_global_css() -> None:
    """Inject the global SOROT stylesheet once from the app entry point."""
    st.markdown(_CSS, unsafe_allow_html=True)


def badge(text: str, color: str, text_color: str = "white") -> str:
    """Return a compact inline HTML badge."""
    return (
        '<span style="'
        f"background:{escape(str(color), quote=True)};"
        f"color:{escape(str(text_color), quote=True)};"
        'padding:2px 8px;border-radius:4px;font-size:0.75em;'
        'font-weight:600;margin:2px;display:inline-block">'
        f"{escape(str(text))}</span>"
    )


def confidence_badge(level: str) -> str:
    color = _CONFIDENCE_COLORS.get(level, Colors.MUTED)
    return badge(level.upper() if level else "BELUM DINILAI", color)


def source_quality_badge(quality: str) -> str:
    return badge(quality, _SOURCE_QUALITY_COLORS.get(quality, Colors.MUTED))


def flag_badge(label: str, active: bool | None) -> str:
    if active:
        return badge(f"Ya: {label}", Colors.PRIMARY)
    if active is None:
        return badge(f"{label}: Tidak diketahui", "#E2E8F0", Colors.MUTED)
    return badge(f"Tidak: {label}", "#E2E8F0", Colors.MUTED)


def section_header(icon: str, title: str, confidence: str | None = None) -> None:
    """Render an editorial section heading with optional confidence."""
    icon_html = f'<span aria-hidden="true">{escape(str(icon))}</span>' if icon else ""
    confidence_html = f" {confidence_badge(confidence)}" if confidence else ""
    st.markdown(
        '<div class="sorot-section-header">'
        f"{icon_html}<span class=\"sorot-section-title\">{escape(str(title))}</span>"
        f"{confidence_html}</div>",
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str) -> str:
    return (
        '<div class="sorot-metric">'
        f'<div class="sorot-metric-label">{escape(str(label))}</div>'
        f'<div class="sorot-metric-value">{escape(str(value))}</div>'
        "</div>"
    )


def empty_state(message: str = "Tidak ditemukan") -> None:
    st.markdown(
        f'<p style="color:{Colors.MUTED};font-style:italic;font-size:0.85rem">'
        f"{escape(str(message))}</p>",
        unsafe_allow_html=True,
    )


def confidence_color(level: str) -> str:
    return _CONFIDENCE_COLORS.get(level, Colors.MUTED)
