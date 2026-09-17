# ui/graph_renderer.py
"""
Relationship graph renderer using pyvis.

Builds an interactive HTML network graph showing connections between the
profiled person and their family members, corporate affiliations, and
political parties.  The HTML is rendered inline via st.components.v1.html.

Colour, shape, and text labels distinguish each relationship category. A
tabular fallback exposes the same information without relying on the graphic.
"""
from html import escape

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from agent.schema import PersonProfile


# ── Constants ─────────────────────────────────────────────────────────────────

_NODE_COLORS = {
    "person":  "#F0A500",
    "family":  "#2F6B8A",
    "company": "#357A55",
    "party":   "#76528B",
}

_GRAPH_HEIGHT = "520px"


# ── Graph builder ─────────────────────────────────────────────────────────────

def _build_network(profile: PersonProfile) -> Network:
    """
    Constructs a pyvis Network from a PersonProfile.

    Returns the Network object (not yet rendered to HTML).
    """
    net = Network(
        height=_GRAPH_HEIGHT,
        width="100%",
        bgcolor="#FFFFFF",
        font_color="#202C39",
        directed=False,
        cdn_resources="in_line",
    )
    net.set_options("""
    {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.01,
          "springLength": 120
        },
        "minVelocity": 0.75,
        "solver": "forceAtlas2Based"
      },
      "interaction": {"hover": true, "keyboard": {"enabled": true}},
      "nodes": {"borderWidth": 1, "font": {"face": "Arial", "color": "#202C39"}},
      "edges": {"color": "#9AA4B2", "font": {"face": "Arial", "color": "#526172"}}
    }
    """)

    subject = profile.full_name

    # Central subject node
    net.add_node(
        subject,
        label=subject,
        color=_NODE_COLORS["person"],
        size=30,
        title=f"<b>Tokoh: {escape(subject)}</b>",
        font={"size": 16},
        shape="dot",
    )

    # Family members
    for member in profile.family_members:
        node_id = f"fam_{member.name}"
        label   = member.name
        title   = f"<b>{escape(member.name)}</b><br>{escape(member.relation)}"
        if member.role:
            title += f"<br>{escape(member.role)}"

        net.add_node(
            node_id,
            label=label,
            color=_NODE_COLORS["family"],
            size=20,
            title=title,
            shape="ellipse",
        )
        net.add_edge(
            subject,
            node_id,
            label=member.relation,
            color="#9AA4B2",
            width=1.5,
        )

    # Corporate affiliations
    for corp in profile.corporate_affiliations:
        node_id = f"corp_{corp.entity_name}"
        title   = f"<b>{escape(corp.entity_name)}</b>"
        if corp.role:
            title += f"<br>Jabatan: {escape(corp.role)}"
        if corp.group:
            title += f"<br>Grup: {escape(corp.group)}"

        net.add_node(
            node_id,
            label=corp.entity_name,
            color=_NODE_COLORS["company"],
            size=18,
            title=title,
            shape="box",
        )
        net.add_edge(
            subject,
            node_id,
            label=corp.role or "Afiliasi",
            color="#9AA4B2",
            width=1.5,
        )

    # Political party affiliations
    for party in profile.party_affiliations:
        node_id = f"party_{party}"
        net.add_node(
            node_id,
            label=party,
            color=_NODE_COLORS["party"],
            size=18,
            title=f"<b>{escape(party)}</b>",
            shape="diamond",
        )
        net.add_edge(
            subject,
            node_id,
            label="Anggota / Afiliasi",
            color="#9AA4B2",
            width=1.5,
        )

    return net


def _relationship_rows(profile: PersonProfile) -> list[dict[str, str]]:
    """Returns every graph edge in a screen-reader-friendly table shape."""
    rows: list[dict[str, str]] = []
    rows.extend(
        {
            "Kategori": "Keluarga",
            "Nama": member.name,
            "Hubungan": member.relation,
            "Detail": member.role or "Tidak ada detail tambahan",
        }
        for member in profile.family_members
    )
    rows.extend(
        {
            "Kategori": "Perusahaan",
            "Nama": affiliation.entity_name,
            "Hubungan": affiliation.role or "Afiliasi",
            "Detail": affiliation.group or "Tidak ada detail tambahan",
        }
        for affiliation in profile.corporate_affiliations
    )
    rows.extend(
        {
            "Kategori": "Partai",
            "Nama": party,
            "Hubungan": "Anggota atau afiliasi",
            "Detail": "Tidak ada detail tambahan",
        }
        for party in profile.party_affiliations
    )
    return rows


def render_graph(profile: PersonProfile) -> None:
    """
    Renders an interactive relationship graph for *profile* inside Streamlit.

    Shows a brief legend and an info message if the profile has no connections
    to visualise.
    """
    has_data = any([
        profile.family_members,
        profile.corporate_affiliations,
        profile.party_affiliations,
    ])

    if not has_data:
        st.caption(
            "Tidak ada data relasi (keluarga, perusahaan, atau partai) "
            "yang cukup untuk membuat grafik."
        )
        return

    net = _build_network(profile)
    html_content = net.generate_html(notebook=False)

    # Legend
    legend_html = (
        '<div class="sorot-graph-legend">'
        '<span><b>● Tokoh</b></span>'
        '<span><b>○ Keluarga</b></span>'
        '<span><b>■ Perusahaan</b></span>'
        '<span><b>◆ Partai</b></span>'
        "</div>"
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    components.html(html_content, height=550, scrolling=False)

    with st.expander("Lihat relasi sebagai tabel"):
        st.dataframe(
            _relationship_rows(profile),
            use_container_width=True,
            hide_index=True,
        )
