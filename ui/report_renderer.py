# ui/report_renderer.py
"""
Single-profile report renderer.

Every section function follows the same pattern:
  1. Check whether data exists — show empty_state() and return early if not
  2. Build a pandas DataFrame from the profile data
  3. Render filter controls then st.dataframe()

The section_header() helper accepts an optional confidence level which is
shown as a coloured badge next to the title, giving users instant visibility
into how reliable each section's data is.
"""
from html import escape
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from agent.schema import ClaimEntry, PersonProfile, SourceEntry
from ui.components import (
    Colors,
    badge,
    empty_state,
    flag_badge,
    metric_card,
    section_header,
    source_quality_badge,
)

_TABLE_CFG = dict(use_container_width=True, hide_index=True)


# ── Filter helpers ────────────────────────────────────────────────────────────

def _text_input(key: str, placeholder: str = "🔍 Filter...") -> str:
    """Renders a collapsed text input and returns the lowercased value."""
    return st.text_input(
        label="", placeholder=placeholder, key=key, label_visibility="collapsed"
    ).strip().lower()


def _safe_http_url(url: str | None) -> str:
    """Returns *url* only when it is a valid http(s) URL."""
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return ""


def _quality_text(source: SourceEntry) -> str:
    """Returns the human-readable quality value for a source."""
    return getattr(source.quality, "value", str(source.quality))


def _source_id(source: SourceEntry, index: int) -> str:
    """Returns an explicit source_id or a stable fallback like S1."""
    return source.source_id or f"S{index + 1}"


def _source_lookup(profile: PersonProfile) -> dict[str, SourceEntry]:
    """Builds a source lookup keyed by source_id and fallback row number."""
    lookup: dict[str, SourceEntry] = {}
    for index, source in enumerate(profile.sources):
        lookup[_source_id(source, index)] = source
    return lookup


def _normalise_claim_text(value: str) -> str:
    """Normalises claim values for forgiving exact-ish matching."""
    return " ".join(str(value).casefold().split())


def _claims_for(profile: PersonProfile, field: str, value: str | None = None) -> list[ClaimEntry]:
    """Returns claims matching a profile field and optional displayed value."""
    claims = [claim for claim in profile.claims if claim.field == field]
    if value is None:
        return claims

    target = _normalise_claim_text(value)
    matched: list[ClaimEntry] = []
    for claim in claims:
        claim_value = _normalise_claim_text(claim.value)
        if claim_value == target or claim_value in target or target in claim_value:
            matched.append(claim)
    return matched


def _source_chip(source_id: str, source: SourceEntry) -> str:
    """Returns one clickable evidence chip."""
    url = _safe_http_url(source.url)
    domain = urlparse(url).netloc.replace("www.", "") if url else ""
    label = source.title or domain or source_id
    if len(label) > 28:
        label = f"{label[:25]}..."

    tooltip_parts = [_quality_text(source)]
    if source.retrieved_at:
        tooltip_parts.append(f"retrieved {source.retrieved_at}")
    if source.snippet:
        tooltip_parts.append(source.snippet)
    tooltip = " | ".join(tooltip_parts)

    attrs = (
        'style="background:#E8F0FE;color:#1E3A5F;padding:2px 8px;'
        'border-radius:999px;font-size:0.72rem;font-weight:600;'
        'text-decoration:none;margin-left:4px;display:inline-block"'
    )
    title = escape(tooltip, quote=True)
    text = escape(label)
    if url:
        return f'<a href="{escape(url, quote=True)}" target="_blank" title="{title}" {attrs}>{text}</a>'
    return f'<span title="{title}" {attrs}>{text}</span>'


def _claim_sources_html(profile: PersonProfile, field: str, value: str | None = None) -> str:
    """Returns source chips for claims linked to a field/value pair."""
    claims = _claims_for(profile, field, value)
    if not claims:
        return ""

    lookup = _source_lookup(profile)
    seen: set[str] = set()
    chips: list[str] = []
    for claim in claims:
        for source_id in claim.evidence_ids:
            if source_id in seen or source_id not in lookup:
                continue
            seen.add(source_id)
            chips.append(_source_chip(source_id, lookup[source_id]))

    if chips:
        return " ".join(chips)
    return badge("Tanpa sumber eksplisit", "#E2E8F0", Colors.MUTED)


def _render_evidence_row(label: str, value: str, chips_html: str = "") -> None:
    """Renders one compact claim row with optional evidence chips."""
    st.markdown(
        "<div style='padding:6px 0;border-bottom:1px solid #E5E7EB'>"
        f"<span style='color:{Colors.MUTED};font-size:0.78rem;font-weight:600'>"
        f"{escape(label)}</span>"
        f"<span style='margin-left:8px'>{escape(value)}</span>"
        f"{chips_html}"
        "</div>",
        unsafe_allow_html=True,
    )


def _apply_filter(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Returns rows where ANY column contains *query* (case-insensitive)."""
    if not query:
        return df
    mask = df.apply(
        lambda col: col.astype(str).str.lower().str.contains(query, na=False)
    ).any(axis=1)
    return df[mask]


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_header(profile: PersonProfile) -> None:
    """Name, aliases, vital status, and quick-glance metric cards."""
    col_name, col_status = st.columns([3, 1])

    with col_name:
        safe_name = escape(profile.full_name)
        st.markdown(
            f"<h2 style='margin:0;color:{Colors.PRIMARY}'>"
            f"👤 {safe_name}</h2>",
            unsafe_allow_html=True,
        )
        if profile.also_known_as:
            st.caption(f"Alias: {', '.join(profile.also_known_as)}")

    with col_status:
        if profile.is_alive is True:
            st.markdown(badge("✅ Masih Hidup", Colors.SUCCESS), unsafe_allow_html=True)
        elif profile.is_alive is False:
            st.markdown(badge("❌ Meninggal", Colors.DANGER), unsafe_allow_html=True)
            if profile.death_info:
                st.caption(profile.death_info)
        else:
            st.markdown(badge("❓ Tidak Diketahui", Colors.MUTED), unsafe_allow_html=True)

    # Quick-glance metric row
    cards_html = '<div class="sorot-metric-row">'
    cards_html += metric_card("Jabatan Aktif",   str(len(profile.current_roles)) or "—")
    cards_html += metric_card("Jabatan Lampau",  str(len(profile.past_roles)) or "—")
    cards_html += metric_card("Afiliasi Partai", str(len(profile.party_affiliations)) or "—")
    cards_html += metric_card("Keluarga",        str(len(profile.family_members)) or "—")
    cards_html += metric_card("Grup Usaha",      str(len(profile.corporate_affiliations)) or "—")
    cards_html += metric_card("Riwayat Kerja",   str(len(profile.job_history)) or "—")
    cards_html += "</div>"
    st.markdown(cards_html, unsafe_allow_html=True)


def _render_classification_flags(profile: PersonProfile) -> None:
    section_header(
        "🏛️", "Klasifikasi Pejabat",
        confidence=profile.field_confidence.jabatan_khusus,
    )
    flags = {
        "Menteri":             profile.is_minister,
        "Wakil Menteri":       profile.is_deputy_minister,
        "Anggota DPR RI":      profile.is_dpr_member,
        "Anggota DPRD":        profile.is_dprd_member,
        "Staf Khusus":         profile.is_staf_khusus,
        "Pejabat Tinggi Neg.": profile.is_high_official,
    }
    html = "".join(
        flag_badge(label, active)
        for label, active in flags.items()
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_roles(profile: PersonProfile) -> None:
    section_header("🏛️", "Jabatan & Instansi", confidence=profile.field_confidence.jabatan)

    rows = (
        [
            {"status": "Saat Ini", "role": r, "field": "current_roles"}
            for r in profile.current_roles
        ]
        + [
            {"status": "Sebelumnya", "role": r, "field": "past_roles"}
            for r in profile.past_roles
        ]
    )
    if not rows:
        empty_state()
        return

    query = _text_input("filter_jabatan", "🔍 Filter jabatan atau instansi...")
    filtered = [
        row for row in rows
        if not query or query in row["role"].lower() or query in row["status"].lower()
    ]
    if not filtered:
        st.caption("⚠️ Tidak ada hasil yang cocok dengan filter.")
        return

    for row in filtered:
        _render_evidence_row(
            row["status"],
            row["role"],
            _claim_sources_html(profile, row["field"], row["role"]),
        )
    st.caption(f"{len(filtered)} dari {len(rows)} baris ditampilkan")


def _render_party(profile: PersonProfile) -> None:
    section_header("🎯", "Afiliasi Partai Politik", confidence=profile.field_confidence.partai)

    if not profile.party_affiliations:
        empty_state()
        return

    query = _text_input("filter_partai", "🔍 Filter partai...")
    filtered = [
        party for party in profile.party_affiliations
        if not query or query in party.lower()
    ]
    if not filtered:
        st.caption("⚠️ Tidak ada hasil yang cocok dengan filter.")
        return

    for party in filtered:
        _render_evidence_row(
            "Partai / Organisasi Politik",
            party,
            _claim_sources_html(profile, "party_affiliations", party),
        )
    st.caption(f"{len(filtered)} dari {len(profile.party_affiliations)} baris ditampilkan")

    if profile.political_notes:
        st.caption(f"📝 {profile.political_notes}")


def _render_tni(profile: PersonProfile) -> None:
    section_header("🎖️", "Status TNI / POLRI", confidence=profile.field_confidence.tni_polri)

    t = profile.tni_polri
    if not t.is_tni_polri:
        empty_state("Bukan TNI/Polri atau tidak ditemukan")
        return

    status_color = "#1b5e20" if t.status == "Aktif" else "#e65100"
    df = pd.DataFrame([{
        "Kesatuan": t.branch or "—",
        "Pangkat Terakhir": t.last_rank or "—",
        "Status": t.status or "—",
    }])
    st.dataframe(
        df.style.apply(
            lambda _: ["", "", f"background-color:{status_color};color:white"],
            axis=1,
        ),
        **_TABLE_CFG,
    )
    chips = _claim_sources_html(profile, "tni_polri")
    if chips:
        st.markdown(f"<p style='margin-top:6px'>Sumber: {chips}</p>", unsafe_allow_html=True)


def _render_corporate(profile: PersonProfile) -> None:
    section_header("🏢", "Afiliasi Grup Usaha", confidence=profile.field_confidence.usaha)

    if not profile.corporate_affiliations:
        empty_state()
        return

    query = _text_input("filter_usaha", "🔍 Filter entitas, jabatan, atau grup...")
    rows = [
        {
            "entity": c.entity_name,
            "details": f"{c.role or '—'} | {c.group or '—'}",
        }
        for c in profile.corporate_affiliations
    ]
    filtered = [
        row for row in rows
        if not query
        or query in row["entity"].lower()
        or query in row["details"].lower()
    ]
    if not filtered:
        st.caption("⚠️ Tidak ada hasil yang cocok dengan filter.")
        return

    for row in filtered:
        _render_evidence_row(
            row["details"],
            row["entity"],
            _claim_sources_html(profile, "corporate_affiliations", row["entity"]),
        )
    st.caption(f"{len(filtered)} dari {len(rows)} baris ditampilkan")


def _render_family(profile: PersonProfile) -> None:
    section_header("👨‍👩‍👧", "Relasi Keluarga", confidence=profile.field_confidence.keluarga)

    if not profile.family_members:
        empty_state()
        return

    df = pd.DataFrame([
        {
            "Nama":         m.name,
            "Hubungan":     m.relation,
            "Peran Publik": m.role or "—",
            "Catatan":      m.notes or "—",
        }
        for m in profile.family_members
    ])

    all_relations = sorted(df["Hubungan"].unique().tolist())
    col_rel, col_search = st.columns([1, 2])

    with col_rel:
        selected_rel = st.selectbox(
            label="", options=["Semua"] + all_relations,
            key="filter_keluarga_rel", label_visibility="collapsed",
        )
    with col_search:
        query = _text_input("filter_keluarga_nama", "🔍 Filter nama atau peran...")

    filtered = df if selected_rel == "Semua" else df[df["Hubungan"] == selected_rel]
    filtered = _apply_filter(filtered, query)

    if filtered.empty:
        st.caption("⚠️ Tidak ada hasil.")
    else:
        st.dataframe(filtered, **_TABLE_CFG)
    st.caption(f"{len(filtered)} dari {len(df)} baris ditampilkan")


def _render_job_history(profile: PersonProfile) -> None:
    section_header(
        "💼", "Riwayat Pekerjaan",
        confidence=profile.field_confidence.riwayat_pekerjaan,
    )

    if not profile.job_history:
        empty_state()
        return

    rows = [
        {
            "Jabatan":    j.title,
            "Perusahaan": j.company,
            "Industri":   j.industry or "—",
            "Mulai":      j.start_year or "—",
            "Selesai":    j.end_year or "Sekarang",
            "Lokasi":     j.location or "—",
            "Sumber":     j.source or "—",
        }
        for j in profile.job_history
    ]
    df = (
        pd.DataFrame(rows)
        .assign(_sort=lambda d: d["Selesai"].map(
            lambda v: "9999" if v == "Sekarang" else v
        ))
        .sort_values("_sort", ascending=False)
        .drop(columns=["_sort"])
        .reset_index(drop=True)
    )

    all_industries = sorted(i for i in df["Industri"].unique() if i != "—")
    col_ind, col_search = st.columns([1, 2])

    with col_ind:
        selected_ind = st.selectbox(
            label="", options=["Semua Industri"] + all_industries,
            key="filter_job_industry", label_visibility="collapsed",
        )
    with col_search:
        query = _text_input("filter_job_search", "🔍 Filter jabatan, perusahaan, atau lokasi...")

    filtered = df if selected_ind == "Semua Industri" else df[df["Industri"] == selected_ind]
    filtered = _apply_filter(filtered, query)

    if filtered.empty:
        st.caption("⚠️ Tidak ada hasil.")
    else:
        st.dataframe(filtered, **_TABLE_CFG)
    st.caption(f"{len(filtered)} dari {len(df)} entri ditampilkan")


def _render_sources(profile: PersonProfile) -> None:
    """Sources table with quality badges and analyst notes."""
    if profile.analyst_notes:
        st.info(f"📝 **Catatan Analis:** {profile.analyst_notes}")

    with st.expander("📎 Sumber Data"):
        if not profile.sources:
            empty_state("Tidak ada sumber yang dicatat")
            return

        # Quality filter
        all_qualities = sorted({s.quality for s in profile.sources})
        selected_q = st.selectbox(
            label="Filter kualitas sumber:",
            options=["Semua"] + all_qualities,
            key="filter_source_quality",
        )

        sources_to_show = (
            profile.sources if selected_q == "Semua"
            else [s for s in profile.sources if s.quality == selected_q]
        )

        df_sources = pd.DataFrame([
            {
                "ID":       _source_id(s, i),
                "Kualitas": s.quality,
                "Judul":    s.title or "—",
                "Diambil":  s.retrieved_at or "—",
                "Cuplikan": s.snippet or "—",
                "URL":      s.url,
            }
            for i, s in enumerate(profile.sources)
            if selected_q == "Semua" or s.quality == selected_q
        ])
        st.dataframe(
            df_sources,
            column_config={"URL": st.column_config.LinkColumn("URL")},
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"{len(sources_to_show)} dari {len(profile.sources)} sumber ditampilkan")

        # Quality legend
        legend = " ".join(
            source_quality_badge(q) for q in [
                "Resmi", "Media Nasional", "Media Lokal", "Profesional", "Lainnya"
            ]
        )
        st.markdown(legend, unsafe_allow_html=True)


# ── Summary renderer ─────────────────────────────────────────────────────────

def render_summary(summary_text: str) -> None:
    """
    Renders the AI-generated narrative summary inside a styled card.

    Args:
        summary_text: Plain text narrative from generate_summary().
                      May contain newline-separated paragraphs.
    """
    paragraphs = [p.strip() for p in summary_text.split("\n") if p.strip()]
    paras_html = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    st.markdown(
        f'<div class="sorot-summary-card">{paras_html}</div>',
        unsafe_allow_html=True,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def render_profile(profile: PersonProfile) -> None:
    """
    Renders a complete PersonProfile as a structured Streamlit report.

    Sections (in order):
      1. Header             — name, alias, vital status, metric cards
      2. Klasifikasi Pejabat — flag badges with confidence indicator
      3. Jabatan / Partai   — filterable tables (2-col)
      4. TNI/Polri / Usaha  — filterable tables (2-col)
      5. Relasi Keluarga    — filterable table with relation selectbox
      6. Riwayat Pekerjaan  — filterable table with industry selectbox
      7. Sumber Data        — quality-filtered sources table with legend
    """
    _render_header(profile)
    st.divider()
    _render_classification_flags(profile)
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        _render_roles(profile)
    with col2:
        _render_party(profile)

    st.divider()

    col3, col4 = st.columns(2)
    with col3:
        _render_tni(profile)
    with col4:
        _render_corporate(profile)

    st.divider()
    _render_family(profile)
    st.divider()
    _render_job_history(profile)
    st.divider()
    _render_sources(profile)
