# Supabase Setup Guide for SOROT

This guide walks you through everything needed to connect SOROT's search
history to Supabase — both locally and when deployed to the cloud.

---

## Step 1 — Create a Supabase Account & Project

1. Go to [supabase.com](https://supabase.com) and click **Start your project**
2. Sign up with GitHub (recommended) or email
3. Click **New project**
4. Fill in the form:
   - **Name:** `sorot` (or anything you like)
   - **Database Password:** generate a strong password — **save this somewhere safe**
   - **Region:** choose the closest to your users (e.g. `Southeast Asia (Singapore)`)
5. Click **Create new project** and wait ~2 minutes for provisioning

---

## Step 2 — Create the `searches` Table

1. In your project dashboard, click **SQL Editor** in the left sidebar
2. Click **New query**
3. Paste the following SQL and click **Run** (▶):

```sql
-- Main history table
CREATE TABLE searches (
    id          BIGSERIAL    PRIMARY KEY,
    name        TEXT         NOT NULL,
    searched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    dimensions  JSONB        NOT NULL,
    profile     JSONB        NOT NULL
);

-- Index for fast newest-first queries
CREATE INDEX searches_searched_at_idx
    ON searches (searched_at DESC);
```

4. You should see **Success. No rows returned** — the table is ready.

> **Tip:** You can verify by clicking **Table Editor** in the sidebar — you
> should see a `searches` table with 0 rows.

---

## Step 3 — Get Your API Keys

1. In the left sidebar, go to **Project Settings** → **API**
2. Copy two values:

| Value | Where to find it | Which to use |
|---|---|---|
| **Project URL** | Under "Project URL" | `SUPABASE_URL` |
| **service_role key** | Under "Project API keys" → **service_role** | `SUPABASE_KEY` |

> ⚠️ **Use `service_role`, not `anon`.**
> The `anon` key is for client-side browser apps and requires Row Level Security
> (RLS) policies. For a server-side Streamlit app, `service_role` bypasses RLS
> and is the correct choice — but **never expose it in frontend code or public repos**.

---

## Step 4 — Configure Locally

Open your `.env` file (copy from `.env.example` if you haven't already):

```env
# Google AI Studio
GOOGLE_API_KEY=AIza...

# Supabase
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=eyJ...your-service-role-key...
```

Test that it works:

```bash
streamlit run app.py
```

Go to the **📋 Riwayat** tab — if it loads without errors, the connection is working.
Do a test search and check that the **📋 Riwayat** tab shows the result.

---

## Step 5 — Deploy to Streamlit Cloud

Streamlit Cloud uses **Secrets** instead of `.env` files.

1. Push your code to a GitHub repository
   > Make sure `.env` is in your `.gitignore` — **never commit API keys**

2. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**

3. Connect your GitHub repo, set:
   - **Branch:** `main`
   - **Main file path:** `app.py`

4. Before clicking Deploy, click **Advanced settings → Secrets**

5. Paste your secrets in TOML format:

```toml
GOOGLE_API_KEY = "AIza..."
SUPABASE_URL   = "https://your-project-id.supabase.co"
SUPABASE_KEY   = "eyJ...your-service-role-key..."
```

6. Click **Deploy**

Streamlit Cloud automatically loads these secrets as environment variables —
`python-dotenv` and `os.getenv()` both work transparently.

---

## Step 6 — Deploy to Other Cloud Platforms

### Railway / Render / Fly.io

Set environment variables in the platform dashboard:

| Variable | Value |
|---|---|
| `GOOGLE_API_KEY` | your Google AI Studio key |
| `SUPABASE_URL` | `https://your-project-id.supabase.co` |
| `SUPABASE_KEY` | your service_role key |

The `start` command for all platforms:
```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

### Docker

Add to your `Dockerfile`:
```dockerfile
ENV GOOGLE_API_KEY=""
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""
```

Then pass them at runtime:
```bash
docker run \
  -e GOOGLE_API_KEY="AIza..." \
  -e SUPABASE_URL="https://..." \
  -e SUPABASE_KEY="eyJ..." \
  -p 8501:8501 \
  sorot-app
```

---

## Verify Data in Supabase Dashboard

After running a search, go to **Table Editor → searches** in Supabase.
You should see a new row with:

| Column | Expected |
|---|---|
| `id` | auto-incremented integer |
| `name` | the name you searched |
| `searched_at` | timestamp with timezone |
| `dimensions` | JSON array of selected keys |
| `profile` | full PersonProfile JSON object |

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `EnvironmentError: SUPABASE_URL and SUPABASE_KEY must be set` | Keys not loaded | Check `.env` exists and has no typos; on cloud check Secrets |
| `relation "searches" does not exist` | Table not created yet | Re-run the SQL in Step 2 |
| `Invalid API key` | Wrong key used | Make sure you copied `service_role`, not `anon` |
| History loads but search doesn't save | `save_search` silently fails | Check Streamlit logs for the exact Supabase error |
| Slow history tab | No index on `searched_at` | Re-run the `CREATE INDEX` statement from Step 2 |

---

## Security Notes

- The `service_role` key bypasses all Row Level Security — treat it like a
  database root password
- Never commit it to a public GitHub repo
- Add `.env` to `.gitignore` before your first `git add`
- Rotate the key from **Project Settings → API → Reveal** if you accidentally expose it
