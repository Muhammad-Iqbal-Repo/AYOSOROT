# utils/cache.py
"""
Lightweight in-session cache backed by Streamlit's session_state.

Results are keyed by lowercased name and live for the duration of the
browser session. This prevents burning API quota on repeat searches
within the same session.
"""
import hashlib
import json
from collections.abc import MutableMapping

import streamlit as st

from agent.schema import PersonProfile

_CACHE_KEY = "profile_cache"
_CACHE_CONTRACT_VERSION = "profile-v2"


def _normalise_component(value: str) -> str:
    return " ".join(value.casefold().split())


def build_profile_cache_key(
    query: str,
    dimensions: list[str],
    searcher_model: str,
    writer_model: str,
) -> str:
    """Builds a stable key for every input that can change a profile result."""
    payload = {
        "contract": _CACHE_CONTRACT_VERSION,
        "query": _normalise_component(query),
        "dimensions": sorted(dimensions),
        "searcher_model": searcher_model,
        "writer_model": writer_model,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def profile_revision(profile: PersonProfile) -> str:
    """Returns a short content fingerprint used to bind summaries and news."""
    payload = profile.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def profile_session_label(profile: PersonProfile) -> str:
    """Returns a readable, identity-aware label for session selectors."""
    context = (profile.identity_context or "").strip()
    return f"{profile.full_name} · {context}" if context else profile.full_name


def get_cached_profile(name: str) -> PersonProfile | None:
    """
    Return a cached PersonProfile for *name*, or None if not found.

    Args:
        name: The person's name (case-insensitive lookup).
    """
    cache: dict[str, PersonProfile] = st.session_state.get(_CACHE_KEY, {})
    return cache.get(name.lower())


def cache_profile(name: str, profile: PersonProfile) -> None:
    """
    Store *profile* in the session cache under *name*.

    Args:
        name:    The person's name used as the cache key.
        profile: A validated PersonProfile instance.
    """
    if _CACHE_KEY not in st.session_state:
        st.session_state[_CACHE_KEY] = {}
    st.session_state[_CACHE_KEY][name.lower()] = profile


def clear_cache() -> None:
    """Remove all cached profiles from the current session."""
    st.session_state.pop(_CACHE_KEY, None)


def clear_research_state(state: MutableMapping | None = None) -> None:
    """Clears research-derived state while preserving API/model configuration."""
    target = st.session_state if state is None else state
    exact_keys = {
        _CACHE_KEY,
        "searched_profiles",
        "last_profile",
        "identity_resolutions",
        "disambiguation",
        "company_news_selector",
        "news_profile_select",
        "graph_profile_select",
    }
    prefixes = (
        "summary_",
        "news_",
        "disambig_",
        "gen_summary_",
        "regen_",
        "refresh_",
        "fetch_",
        "filter_",
    )
    for key in list(target.keys()):
        if key in exact_keys or key.startswith(prefixes):
            target.pop(key, None)
