# utils/history.py
"""
Persistent search history backed by Supabase (PostgreSQL).

Public API — identical to the previous SQLite implementation so app.py
requires zero changes:

    init_db()                              → validates connection on startup
    save_search(name, profile, dimensions) → INSERT a new row
    get_all()                              → SELECT all rows, newest first
    get_by_id(search_id)                   → SELECT one row by id
    delete_by_id(search_id)               → DELETE one row
    clear_all()                            → DELETE all rows

Supabase table schema (run this once in the SQL Editor):

    CREATE TABLE searches (
        id          BIGSERIAL PRIMARY KEY,
        name        TEXT        NOT NULL,
        searched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        dimensions  JSONB       NOT NULL,
        profile     JSONB       NOT NULL
    );

    -- Optional: speed up ORDER BY searched_at DESC
    CREATE INDEX searches_searched_at_idx ON searches (searched_at DESC);

    -- Optional: Row Level Security (enable if using anon key)
    -- ALTER TABLE searches ENABLE ROW LEVEL SECURITY;

Environment variables required:
    SUPABASE_URL  — your project URL  (e.g. https://abc.supabase.co)
    SUPABASE_KEY  — service_role key  (from Project Settings → API)
"""
import json
import os
from datetime import datetime, timezone
from functools import lru_cache

from supabase import Client, create_client

from agent.schema import PersonProfile
from utils.logger import get_logger

logger = get_logger(__name__)

_TABLE = "searches"


# ── Client singleton ──────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _client() -> Client:
    """
    Returns a cached Supabase client.

    Uses @lru_cache so the client is created once per process — not once per
    Streamlit rerun.  Raises EnvironmentError if keys are missing so the caller
    gets a clear message instead of a cryptic SDK error.
    """
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()

    if not url or not key:
        raise EnvironmentError(
            "SUPABASE_URL and SUPABASE_KEY must be set in your .env file "
            "(or in Streamlit secrets for cloud deployments)."
        )

    return create_client(url, key)


# ── Initialisation ────────────────────────────────────────────────────────────

def init_db() -> None:
    """
    Validates the Supabase connection on startup.

    Does NOT create the table — that must be done once via the SQL Editor
    in the Supabase dashboard (see the docstring at the top of this file).

    Logs a warning (does not raise) so a missing table surfaces in the History
    tab rather than crashing the whole app on startup.
    """
    try:
        # A lightweight read — will throw if credentials are wrong
        _client().table(_TABLE).select("id").limit(1).execute()
        logger.info("Supabase connection OK")
    except EnvironmentError:
        raise   # Missing keys — propagate immediately
    except Exception as exc:
        # Table might not exist yet — warn but let the app start
        logger.warning(f"Supabase init check failed: {exc}")


# ── Write operations ──────────────────────────────────────────────────────────

def save_search(
    name: str,
    profile: PersonProfile,
    dimensions: list[str],
) -> int:
    """
    Inserts a completed search into Supabase.

    Args:
        name:       The searched name as entered by the user.
        profile:    The validated PersonProfile.
        dimensions: The dimension keys that were selected.

    Returns:
        The auto-assigned row id from Supabase.

    Raises:
        Exception: Propagates Supabase SDK errors to the caller.
    """
    payload = {
        "name":        name,
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "dimensions":  dimensions,                  # list → stored as JSONB
        "profile":     json.loads(profile.model_dump_json()),  # dict → JSONB
    }

    response = _client().table(_TABLE).insert(payload).execute()
    row_id = response.data[0]["id"]
    logger.info(f"Saved search id={row_id} for {name!r}")
    return row_id


# ── Read operations ───────────────────────────────────────────────────────────

def get_all() -> list[dict]:
    """
    Returns all searches ordered newest-first.

    Each dict contains:
        id          int
        name        str
        searched_at str  (ISO-8601)
        dimensions  list[str]
        profile     PersonProfile
    """
    response = (
        _client()
        .table(_TABLE)
        .select("*")
        .order("searched_at", desc=True)
        .execute()
    )

    results = []
    for row in response.data:
        try:
            results.append(_deserialise(row))
        except Exception as exc:
            logger.warning(f"Skipping corrupt row id={row.get('id')}: {exc}")
    return results


def get_by_id(search_id: int) -> dict | None:
    """Returns a single search record by id, or None if not found."""
    response = (
        _client()
        .table(_TABLE)
        .select("*")
        .eq("id", search_id)
        .maybe_single()
        .execute()
    )

    if not response.data:
        return None
    try:
        return _deserialise(response.data)
    except Exception as exc:
        logger.warning(f"Corrupt row id={search_id}: {exc}")
        return None


# ── Delete operations ─────────────────────────────────────────────────────────

def delete_by_id(search_id: int) -> None:
    """Deletes a single search record."""
    _client().table(_TABLE).delete().eq("id", search_id).execute()
    logger.info(f"Deleted history id={search_id}")


def clear_all() -> None:
    """Deletes all search records."""
    # neq("id", 0) is a safe way to match all rows without a bare DELETE
    _client().table(_TABLE).delete().neq("id", 0).execute()
    logger.info("History cleared")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _deserialise(row: dict) -> dict:
    """
    Converts a raw Supabase row dict into a typed dict with a PersonProfile.

    Supabase returns JSONB columns as already-parsed Python dicts/lists, so
    we don't need json.loads() — just pass the dict directly to Pydantic.
    """
    return {
        "id":          row["id"],
        "name":        row["name"],
        "searched_at": row["searched_at"],
        "dimensions":  row["dimensions"],   # already a list (from JSONB)
        "profile":     PersonProfile.model_validate(row["profile"]),
    }
