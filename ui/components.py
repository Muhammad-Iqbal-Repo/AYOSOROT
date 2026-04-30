# ui/components.py
"""
Design system for SOROT.

Contains:
  - Color palette constants
  - CSS injection (call inject_global_css() once in main())
  - Badge and label primitives
  - Layout helpers used across all renderers
"""
import streamlit as st

from agent.schema import ConfidenceLevel, SourceQuality


# ── Palette ───────────────────────────────────────────────────────────────────
# Single source of truth for all colours used in the app.

class Colors:
    # Brand
    PRIMARY       = "#1E3A5F"   # deep navy
    PRIMARY_LIGHT = "#2E5299"   # mid blue
    ACCENT        = "#F0A500"   # gold

    # Semantic
    SUCCESS  = "#1B7340"
    WARNING  = "#B45309"
    DANGER   = "#B91C1C"
    MUTED    = "#6B7280"
    SURFACE  = "#F8FAFC"

    # Confidence levels
    CONF_HIGH   = "#1B7340"   # green
    CONF_MEDIUM = "#B45309"   # amber
    CONF_LOW    = "#B91C1C"   # red

    # Source quality
    SRC_OFFICIAL     = "#1E3A5F"   # navy
    SRC_NATIONAL     = "#1B7340"   # green
    SRC_LOCAL        = "#5B21B6"   # violet
    SRC_PROFESSIONAL = "#0E7490"   # teal
    SRC_OTHER        = "#6B7280"   # grey


_CONFIDENCE_COLORS: dict[str, str] = {
    ConfidenceLevel.HIGH:   Colors.CONF_HIGH,
    ConfidenceLevel.MEDIUM: Colors.CONF_MEDIUM,
    ConfidenceLevel.LOW:    Colors.CONF_LOW,
}

_SOURCE_QUALITY_COLORS: dict[str, str] = {
    SourceQuality.OFFICIAL:      Colors.SRC_OFFICIAL,
    SourceQuality.NATIONAL:      Colors.SRC_NATIONAL,
    SourceQuality.LOCAL:         Colors.SRC_LOCAL,
    SourceQuality.PROFESSIONAL:  Colors.SRC_PROFESSIONAL,
    SourceQuality.OTHER:         Colors.SRC_OTHER,
}


# ── Global CSS ────────────────────────────────────────────────────────────────

_CSS = f"""
<style>
/* ── Sidebar background ──────────────────── */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {Colors.PRIMARY} 0%, {Colors.PRIMARY_LIGHT} 100%);
}}

/* ── Sidebar text — nuclear selector to override all Streamlit inline styles ── */
[data-testid="stSidebar"] * {{
    color: #F1F5F9 !important;
}}

/* ── Sidebar checkboxes ──────────────────── */
[data-testid="stSidebar"] .stCheckbox * {{
    color: #FFFFFF !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    line-height: 1.5 !important;
}}
/* Checkbox tick border */
[data-testid="stSidebar"] [data-testid="stCheckbox"] > label > div:first-child {{
    border-color: rgba(255,255,255,0.7) !important;
    background: rgba(255,255,255,0.05) !important;
}}
[data-testid="stSidebar"] hr {{
    border-color: rgba(255,255,255,0.2) !important;
    margin: 8px 0 !important;
}}

/* ── Sidebar inputs — white background for readability ── */
[data-testid="stSidebar"] input[type="password"],
[data-testid="stSidebar"] input[type="text"] {{
    background: #FFFFFF !important;
    color: #1E3A5F !important;
    border: 2px solid rgba(255,255,255,0.5) !important;
    border-radius: 6px !important;
    font-size: 0.85rem !important;
}}
[data-testid="stSidebar"] input[type="password"]::placeholder,
[data-testid="stSidebar"] input[type="text"]::placeholder {{
    color: #94A3B8 !important;
}}

/* ── Sidebar selectbox ───────────────────── */
[data-testid="stSidebar"] [data-baseweb="select"] > div {{
    background: #FFFFFF !important;
    border: 2px solid rgba(255,255,255,0.5) !important;
    border-radius: 6px !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div {{
    color: #1E3A5F !important;
    font-size: 0.85rem !important;
}}

/* ── Sidebar buttons ─────────────────────── */
[data-testid="stSidebar"] .stButton button {{
    background: rgba(255,255,255,0.15) !important;
    color: #F1F5F9 !important;
    border: 1px solid rgba(255,255,255,0.3) !important;
    border-radius: 6px !important;
    font-size: 0.82rem !important;
    transition: background 0.2s;
}}
[data-testid="stSidebar"] .stButton button:hover {{
    background: rgba(255,255,255,0.28) !important;
}}

/* ── Sidebar section labels ──────────────── */
.sidebar-section-label {{
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.55) !important;
    margin: 0 0 4px 0;
    padding: 0;
}}

/* ── Main content ────────────────────────── */
.block-container {{
    padding-top: 1.5rem !important;
    max-width: 1100px !important;
}}

/* ── Metric cards ────────────────────────── */
.sorot-metric-row {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin: 12px 0;
}}
.sorot-metric {{
    background: {Colors.SURFACE};
    border: 1px solid #E2E8F0;
    border-left: 4px solid {Colors.PRIMARY};
    border-radius: 8px;
    padding: 10px 16px;
    min-width: 140px;
    flex: 1;
}}
.sorot-metric-label {{
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: {Colors.MUTED};
    margin-bottom: 2px;
}}
.sorot-metric-value {{
    font-size: 1rem;
    font-weight: 600;
    color: {Colors.PRIMARY};
}}

/* ── Summary card ────────────────────────── */
.sorot-summary-card {{
    background: linear-gradient(135deg, {Colors.PRIMARY} 0%, {Colors.PRIMARY_LIGHT} 100%);
    color: white;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
    line-height: 1.7;
}}
.sorot-summary-card p {{
    margin: 0 0 10px 0;
    font-size: 0.95rem;
}}
.sorot-summary-card p:last-child {{
    margin-bottom: 0;
}}

/* ── Section headers ─────────────────────── */
.sorot-section-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 2px solid {Colors.PRIMARY};
    margin-bottom: 10px;
}}
.sorot-section-title {{
    font-size: 1rem;
    font-weight: 600;
    color: {Colors.PRIMARY};
    margin: 0;
}}

/* ── Search card ────────────────────────── */
.sorot-search-card {{
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-top: 4px solid #1E3A5F;
    border-radius: 12px;
    padding: 24px 28px 20px 28px;
    margin-bottom: 8px;
    box-shadow: 0 2px 8px rgba(30,58,95,0.07);
}}
.sorot-search-title {{
    font-size: 1.05rem;
    font-weight: 700;
    color: #1E3A5F;
    margin: 0 0 4px 0;
}}
.sorot-search-subtitle {{
    font-size: 0.82rem;
    color: #6B7280;
    margin: 0 0 16px 0;
}}

/* ── Search button ───────────────────────── */
div[data-testid="stFormSubmitButton"] button {{
    background: linear-gradient(135deg, {Colors.PRIMARY} 0%, {Colors.PRIMARY_LIGHT} 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em !important;
    padding: 0.6rem 1.5rem !important;
    transition: opacity 0.2s !important;
}}
div[data-testid="stFormSubmitButton"] button:hover {{
    opacity: 0.9 !important;
}}

/* ── Tabs ────────────────────────────────── */
.stTabs [data-baseweb="tab"] {{
    font-size: 0.85rem;
    padding: 8px 16px;
}}
.stTabs [aria-selected="true"] {{
    color: {Colors.PRIMARY} !important;
    border-bottom-color: {Colors.PRIMARY} !important;
}}

/* ── Expander ────────────────────────────── */
details summary {{
    font-weight: 600;
    color: {Colors.PRIMARY};
}}
</style>
"""


def inject_global_css() -> None:
    """Injects the global SOROT stylesheet. Call once in main()."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ── Badge primitives ──────────────────────────────────────────────────────────

def badge(text: str, color: str, text_color: str = "white") -> str:
    """Returns an inline HTML pill badge."""
    return (
        f'<span style="'
        f"background:{color};color:{text_color};"
        f"padding:2px 10px;border-radius:20px;"
        f'font-size:0.75em;font-weight:600;margin:2px;display:inline-block">'
        f"{text}</span>"
    )


def confidence_badge(level: str) -> str:
    """Returns a badge styled for a ConfidenceLevel value."""
    color = _CONFIDENCE_COLORS.get(level, Colors.MUTED)
    return badge(level.upper() if level else "UNKNOWN", color)


def source_quality_badge(quality: str) -> str:
    """Returns a badge styled for a SourceQuality value."""
    color = _SOURCE_QUALITY_COLORS.get(quality, Colors.MUTED)
    return badge(quality, color)


def flag_badge(label: str, active: bool) -> str:
    """Returns a classification flag badge — filled when active, grey outline when not."""
    if active:
        return badge(f"✓ {label}", Colors.PRIMARY)
    return badge(label, "#E2E8F0", Colors.MUTED)


# ── Layout helpers ────────────────────────────────────────────────────────────

def section_header(icon: str, title: str, confidence: str | None = None) -> None:
    """
    Renders a styled section header with an optional confidence badge.

    Args:
        icon:       Emoji prefix.
        title:      Section title text.
        confidence: Optional ConfidenceLevel string shown as a badge.
    """
    conf_html = f"&nbsp;{confidence_badge(confidence)}" if confidence else ""
    st.markdown(
        f'<div class="sorot-section-header">'
        f'<span style="font-size:1.1em">{icon}</span>'
        f'<span class="sorot-section-title">{title}</span>'
        f"{conf_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str) -> str:
    """Returns an HTML metric card string."""
    return (
        f'<div class="sorot-metric">'
        f'<div class="sorot-metric-label">{label}</div>'
        f'<div class="sorot-metric-value">{value}</div>'
        f"</div>"
    )


def empty_state(message: str = "Tidak ditemukan") -> None:
    """Renders a muted caption for empty data sections."""
    st.markdown(
        f'<p style="color:{Colors.MUTED};font-style:italic;font-size:0.85rem">'
        f"{message}</p>",
        unsafe_allow_html=True,
    )


def confidence_color(level: str) -> str:
    """Maps a ConfidenceLevel string to a CSS colour."""
    return _CONFIDENCE_COLORS.get(level, Colors.MUTED)
