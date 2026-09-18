# ui/news_renderer.py
"""
Renderer for news and article summaries.

Public API
──────────
  render_news(articles, context_label, filter_key_prefix)
      Renders a filterable list of NewsArticle cards.
      Reused for both person news and company news — the filter_key_prefix
      keeps Streamlit widget keys unique between the two sub-tabs.

Internal helpers
────────────────
  _render_card(article)      — one bordered card
  _filter_articles(...)      — applies quality + text filters
"""
from html import escape
from urllib.parse import urlparse

import streamlit as st

from agent.schema import NewsArticle, SourceQuality
from ui.components import empty_state, source_quality_badge


# ── Quality ordering for the filter selectbox ─────────────────────────────────
_QUALITY_ORDER = [
    SourceQuality.OFFICIAL,
    SourceQuality.NATIONAL,
    SourceQuality.LOCAL,
    SourceQuality.PROFESSIONAL,
    SourceQuality.OTHER,
]


# ── Single article card ───────────────────────────────────────────────────────

def _escape_markdown(text: str | None) -> str:
    """Escapes markdown control characters in model-derived text."""
    value = "" if text is None else str(text)
    for char in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!"):
        value = value.replace(char, f"\\{char}")
    return value


def _safe_http_url(url: str | None) -> str:
    """Returns *url* only when it is a valid http(s) URL."""
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def _render_card(article: NewsArticle) -> None:
    """Renders one article as a styled bordered card."""
    with st.container():
        # Title — linked when a URL is present
        title = _escape_markdown(article.title)
        safe_url = _safe_http_url(article.url)
        if safe_url:
            st.markdown(f"#### [{title}]({safe_url})")
        else:
            st.markdown(f"#### {title}")

        # Meta row: source name · quality badge · date
        meta_parts = [
            f"**{escape(str(article.source_name))}**",
            source_quality_badge(article.quality),
        ]
        if article.published_date:
            meta_parts.append(escape(str(article.published_date)))

        st.markdown(
            " &nbsp;·&nbsp; ".join(meta_parts),
            unsafe_allow_html=True,
        )

        # Summary body
        st.markdown(_escape_markdown(article.summary))
        st.divider()


# ── Filter helper ─────────────────────────────────────────────────────────────

def _filter_articles(
    articles: list[NewsArticle],
    selected_quality: str,
    search_query: str,
) -> list[NewsArticle]:
    """Returns the subset of *articles* matching quality and text filters."""
    filtered = articles

    if selected_quality != "Semua Sumber":
        filtered = [a for a in filtered if a.quality == selected_quality]

    if search_query:
        q = search_query.lower()
        filtered = [
            a for a in filtered
            if q in a.title.lower() or q in a.summary.lower()
        ]

    return filtered


# ── Main renderer ─────────────────────────────────────────────────────────────

def render_news(
    articles: list[NewsArticle],
    context_label: str = "berita",
    filter_key_prefix: str = "news",
) -> None:
    """
    Renders a filterable list of NewsArticle cards.

    Shared by both person-news and company-news sections — the
    *filter_key_prefix* makes each section's widget keys unique so Streamlit
    doesn't confuse the two filter inputs.

    Args:
        articles:          List of NewsArticle objects (newest-first).
        context_label:     Short label used in empty-state messages.
        filter_key_prefix: Prefix for all st widget keys in this call.
    """
    if not articles:
        empty_state(f"Tidak ada {context_label} yang ditemukan.")
        return

    st.caption(
        f"Menampilkan maksimal 10 {context_label} terbaru · "
        f"{len(articles)} artikel ditemukan"
    )

    # ── Filter controls ───────────────────────────────────────────────────────
    present_qualities = [
        q for q in _QUALITY_ORDER
        if any(a.quality == q for a in articles)
    ]

    col_quality, col_search = st.columns([1, 2])

    with col_quality:
        selected_quality = st.selectbox(
            label="Kualitas sumber",
            options=["Semua Sumber"] + present_qualities,
            key=f"{filter_key_prefix}_quality",
            label_visibility="collapsed",
        )

    with col_search:
        search_query = st.text_input(
            label="Cari artikel",
            placeholder="Cari dalam judul atau ringkasan",
            key=f"{filter_key_prefix}_search",
            label_visibility="collapsed",
        ).strip()

    # ── Apply & display ───────────────────────────────────────────────────────
    filtered = _filter_articles(articles, selected_quality, search_query)

    if not filtered:
        st.caption("Tidak ada artikel yang cocok dengan filter.")
        return

    st.caption(f"{len(filtered)} dari {len(articles)} artikel ditampilkan")
    st.divider()

    for article in filtered:
        _render_card(article)
