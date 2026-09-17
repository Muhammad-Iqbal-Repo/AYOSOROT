# ui/comparison_renderer.py
"""
Side-by-side comparison renderer for two or more PersonProfile objects.

The comparison is structured as a table where each row is an attribute
and each column is one person.  Boolean flags are shown as ✅/❌.
Lists are rendered as comma-separated values to fit in a cell.
"""
import pandas as pd
import streamlit as st

from agent.schema import PersonProfile
from ui.components import confidence_badge, source_quality_badge


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bool(value: bool | None) -> str:
    if value is True:  return "Ya"
    if value is False: return "Tidak"
    return "Tidak diketahui"


def _list(items: list) -> str:
    return ", ".join(str(i) for i in items) if items else "—"


def _alive(value: bool | None) -> str:
    if value is True:  return "Masih hidup"
    if value is False: return "Meninggal"
    return "Tidak diketahui"


# ── Section builders ──────────────────────────────────────────────────────────

def _build_overview(profiles: list[PersonProfile]) -> pd.DataFrame:
    rows = [
        ("Nama Lengkap",       [p.full_name                                  for p in profiles]),
        ("Alias",              [_list(p.also_known_as)                        for p in profiles]),
        ("Status Hidup",       [_alive(p.is_alive)                            for p in profiles]),
    ]
    return pd.DataFrame(
        {attr: values for attr, values in rows},
        index=[f"#{i+1} {p.full_name}" for i, p in enumerate(profiles)],
    ).T


def _build_gov_flags(profiles: list[PersonProfile]) -> pd.DataFrame:
    rows = [
        ("Menteri",               [_bool(p.is_minister)        for p in profiles]),
        ("Wakil Menteri",         [_bool(p.is_deputy_minister) for p in profiles]),
        ("Anggota DPR RI",        [_bool(p.is_dpr_member)      for p in profiles]),
        ("Anggota DPRD",          [_bool(p.is_dprd_member)     for p in profiles]),
        ("Staf Khusus",           [_bool(p.is_staf_khusus)     for p in profiles]),
        ("Pejabat Tinggi Negara", [_bool(p.is_high_official)   for p in profiles]),
    ]
    return pd.DataFrame(
        {attr: values for attr, values in rows},
        index=[p.full_name for p in profiles],
    ).T


def _build_roles(profiles: list[PersonProfile]) -> pd.DataFrame:
    rows = [
        ("Jabatan Saat Ini",  [_list(p.current_roles)      for p in profiles]),
        ("Jabatan Sebelumnya",[_list(p.past_roles)          for p in profiles]),
        ("Afiliasi Partai",   [_list(p.party_affiliations)  for p in profiles]),
    ]
    return pd.DataFrame(
        {attr: values for attr, values in rows},
        index=[p.full_name for p in profiles],
    ).T


def _build_tni(profiles: list[PersonProfile]) -> pd.DataFrame:
    rows = [
        ("TNI/Polri",         [_bool(p.tni_polri.is_tni_polri) for p in profiles]),
        ("Kesatuan",          [p.tni_polri.branch or "—"        for p in profiles]),
        ("Pangkat Terakhir",  [p.tni_polri.last_rank or "—"     for p in profiles]),
        ("Status",            [p.tni_polri.status or "—"        for p in profiles]),
    ]
    return pd.DataFrame(
        {attr: values for attr, values in rows},
        index=[p.full_name for p in profiles],
    ).T


def _build_confidence(profiles: list[PersonProfile]) -> pd.DataFrame:
    fc_attrs = [
        ("jabatan",           "Jabatan & Instansi"),
        ("partai",            "Partai Politik"),
        ("keluarga",          "Relasi Keluarga"),
        ("jabatan_khusus",    "Klasifikasi Pejabat"),
        ("tni_polri",         "TNI/POLRI"),
        ("usaha",             "Grup Usaha"),
        ("status_hidup",      "Status Hidup"),
        ("riwayat_pekerjaan", "Riwayat Pekerjaan"),
    ]
    rows = [
        (label, [getattr(p.field_confidence, key, "—") for p in profiles])
        for key, label in fc_attrs
    ]
    return pd.DataFrame(
        {attr: values for attr, values in rows},
        index=[p.full_name for p in profiles],
    ).T


# ── Main entry point ──────────────────────────────────────────────────────────

def render_comparison(profiles: list[PersonProfile]) -> None:
    """
    Renders a multi-section side-by-side comparison for 2–4 profiles.

    Args:
        profiles: List of PersonProfile objects to compare.
                  Pass 2–4 for a readable layout.
    """
    if len(profiles) < 2:
        st.info("Pilih minimal 2 profil untuk dibandingkan.")
        return

    _table_cfg = dict(use_container_width=True)

    # ── Overview ───────────────────────────────────────────────────────────────
    st.subheader("Ringkasan umum")
    st.dataframe(_build_overview(profiles), **_table_cfg)

    st.divider()

    # ── Government flags ───────────────────────────────────────────────────────
    st.subheader("Klasifikasi pejabat")
    st.dataframe(_build_gov_flags(profiles), **_table_cfg)

    st.divider()

    # ── Roles & party ──────────────────────────────────────────────────────────
    st.subheader("Jabatan dan partai")
    st.dataframe(_build_roles(profiles), **_table_cfg)

    st.divider()

    # ── TNI/Polri ──────────────────────────────────────────────────────────────
    st.subheader("TNI / POLRI")
    st.dataframe(_build_tni(profiles), **_table_cfg)

    st.divider()

    # ── Per-field confidence ───────────────────────────────────────────────────
    st.subheader("Tingkat kepercayaan per bidang")
    st.dataframe(_build_confidence(profiles), **_table_cfg)
