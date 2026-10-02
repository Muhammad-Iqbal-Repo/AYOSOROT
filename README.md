# SOROT

SOROT is a Streamlit workspace for researching public information about Indonesian figures. It builds an evidence-linked profile with Gemini, then supports comparison, current-news retrieval, and relationship exploration.

Profile research searches selected topics in up to three focused groups: public roles and affiliations, work and business, and family. The writer receives findings from each group, with a 24,000-token input cap checked using Gemini's token counter. If findings exceed the cap, complete lines are removed from each group while keeping each topic represented. A search group that reaches its output limit is retried as smaller topics; any topic still missing is shown as a warning. Selecting more groups can increase search requests, latency, and API usage.

Identity choices require URLs captured by Gemini's search grounding. Profile citations receive credit only when their URL was grounded and their excerpt matches the search findings; unmatched claims are shown as unverified. This is a consistency check on search output, not an independent verification of the linked page. News is deduplicated, ordered by recognized publication dates, and refreshed after six hours in the session cache.

## Requirements

- Python 3.11
- A Google AI Studio API key

`requirements.txt` contains the supported direct dependency ranges. `requirements.lock` records the direct versions used for the latest local verification. Use the lock file when you need to reproduce that environment.

## Local setup

Create a new environment as `.venv`. Do not rename an existing environment because its scripts can contain absolute paths.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
$env:GOOGLE_API_KEY = "your-key"
streamlit run app.py
```

The server-owned `GOOGLE_API_KEY` stays out of browser widget state. A key entered in the sidebar applies only to that Streamlit session and overrides the server key for its model listing and generation calls.

You can also set model defaults with `SEARCHER_MODEL` and `WRITER_MODEL`. The sidebar exposes available models after an API key is configured.

## Verification

Install the development dependencies and run the suite:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pip check
```

No live Gemini or Supabase calls are required by the automated tests.

## Data and credentials

Research profiles, summaries, news, and identity choices are session-scoped. Clearing research data preserves API/model configuration but removes derived research state. Do not commit `.streamlit/secrets.toml` or API keys.

## Optional history module

`utils/history.py` and `SUPABASE_SETUP.md` describe an inactive, optional Supabase history implementation. The current app does not import or call it, so Supabase is intentionally absent from active requirements. Do not expose that module in a shared deployment until user ownership, row-level access, scoped deletion, and pagination have been designed and tested.
