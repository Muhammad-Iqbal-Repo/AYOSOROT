# utils/cache.py
"""
Lightweight in-session cache backed by Streamlit's session_state.

Results are keyed by lowercased name and live for the duration of the
browser session. This prevents burning API quota on repeat searches
within the same session.
"""
import streamlit as st

from agent.schema import PersonProfile

_CACHE_KEY = "profile_cache"


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
