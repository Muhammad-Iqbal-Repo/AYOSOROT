# ui/graph_renderer.py
"""
Relationship graph renderer using pyvis.

Builds an interactive HTML network graph showing connections between the
profiled person and their family members, corporate affiliations, and
political parties.  The HTML is rendered inline via st.components.v1.html.

Node colours
────────────
  Orange  — the main subject
  Blue    — family members
  Green   — companies / corporate entities
  Purple  — political parties
  Grey    — party affiliations (political orgs)
"""
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from agent.schema import PersonProfile


# ── Constants ─────────────────────────────────────────────────────────────────

_NODE_COLORS = {
    "person":    "#e65100",   # orange  — subject
    "family":    "#1565c0",   # blue
    "company":   "#2e7d32",   # green
    "party":     "#6a1b9a",   # purple
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
        bgcolor="#0e1117",          # matches Streamlit dark background
        font_color="#fafafa",
        directed=False,
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
      "interaction": {"hover": true}
    }
    """)

    subject = profile.full_name

    # Central subject node
    net.add_node(
        subject,
        label=subject,
        color=_NODE_COLORS["person"],
        size=30,
        title=f"<b>{subject}</b>",
        font={"size": 16},
    )

    # Family members
    for member in profile.family_members:
        node_id = f"fam_{member.name}"
        label   = member.name
        title   = f"<b>{member.name}</b><br>{member.relation}"
        if member.role:
            title += f"<br>{member.role}"

        net.add_node(
            node_id,
            label=label,
            color=_NODE_COLORS["family"],
            size=20,
            title=title,
        )
        net.add_edge(
            subject,
            node_id,
            label=member.relation,
            color="#bbbbbb",
            width=1.5,
        )

    # Corporate affiliations
    for corp in profile.corporate_affiliations:
        node_id = f"corp_{corp.entity_name}"
        title   = f"<b>{corp.entity_name}</b>"
        if corp.role:
            title += f"<br>Jabatan: {corp.role}"
        if corp.group:
            title += f"<br>Grup: {corp.group}"

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
            color="#bbbbbb",
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
            title=f"<b>{party}</b>",
            shape="diamond",
        )
        net.add_edge(
            subject,
            node_id,
            label="Anggota / Afiliasi",
            color="#bbbbbb",
            width=1.5,
        )

    return net


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

    net  = _build_network(profile)

    # Write to a temp HTML file then read back for st.components
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as tmp:
        tmp_path = Path(tmp.name)
        net.save_graph(str(tmp_path))

    html_content = tmp_path.read_text(encoding="utf-8")
    tmp_path.unlink(missing_ok=True)

    # Legend
    legend_html = (
        '<div style="font-size:0.75em;margin-bottom:6px">'
        '<span style="background:#e65100;color:white;padding:1px 7px;border-radius:8px">● Tokoh</span>&nbsp;'
        '<span style="background:#1565c0;color:white;padding:1px 7px;border-radius:8px">● Keluarga</span>&nbsp;'
        '<span style="background:#2e7d32;color:white;padding:1px 7px;border-radius:8px">■ Perusahaan</span>&nbsp;'
        '<span style="background:#6a1b9a;color:white;padding:1px 7px;border-radius:8px">◆ Partai</span>'
        "</div>"
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    components.html(html_content, height=550, scrolling=False)
