# SOROT optimization review and implementation guide

Reviewed: 2026-09-17. Scope: the current local Python application, its tests, dependency manifest, and installed SDK behavior.

## Recommended direction

Keep the existing Streamlit application and Searcher → Writer pipeline. The highest-value work is to correct failure handling and misleading research results, eliminate avoidable model calls, and make session state consistent. A framework rewrite, additional agent stages, or a database migration is not required to achieve these improvements.

This document is a review and implementation backlog; application code has not been changed. Priorities reflect observable defects and likely user impact, not measured production latency or cost. Deployment audience and performance targets are unknown; the server-key finding is especially important if other people can access the app.

The older `SOROT_IMPROVEMENT_RECOMMENDATIONS.md` contains findings that have already been addressed. `_TEMP_INCREMENT` exists, empty news uses `{"articles": []}`, summaries and badges escape HTML, the environment API key is recognized, and source/claim models and evidence chips exist. Preserve these improvements and their tests. Use this review for the remaining work.

## Baseline and verification

| Check | Result |
| --- | --- |
| Existing suite: `.\.env\Scripts\python.exe -m unittest discover -s tests -v` | 8 tests passed |
| Dependency consistency: `.\.env\Scripts\python.exe -m pip check` | No broken requirements found |
| Syntax parsing with `ast.parse` | All 18 project Python files passed, including tests |
| Streamlit `AppTest`, with fake credentials and mocked agent calls | Startup, first search, repeated search, and cache-clear flows completed with no app exceptions |
| Repeat-search call counters | Two submissions made two disambiguation calls but only one research call |
| Cache-clear inspection | Previously seeded summary and news entries remained |
| Synthetic server-key check | The environment key became the password widget's value |
| Focused offline probes | Reproduced filter, JSON repair, SDK error mapping, article parsing, missing-candidate, evidence matching, null-flag, and retry-budget problems below |

Environment: Python 3.11.4; Streamlit 1.57.0; google-genai 1.74.0; Pydantic 2.13.3; pandas 3.0.2; PyVis 0.3.2. These are the installed versions, not a recommendation to upgrade or pin blindly.

All model calls in these checks were mocked. No paid Gemini requests or Supabase reads/writes were made. There was no real-browser visual/accessibility test, deployed security test, dependency vulnerability audit, or live latency benchmark. Graph findings come from Python objects, generated HTML, and installed PyVis source inspection; browser exploitation and asset-loading failures were not demonstrated. Streamlit emitted warnings about empty widget labels during AppTest.

## Priority overview

P0 means address before sharing a server-key deployment. P1 means correctness, reliability, or exposed-content issues to address first. P2 means performance and operational improvements after the relevant correctness changes. Effort is relative: small is a localized fix; medium crosses state, schema, or UI boundaries.

| ID | Priority | Improvement | Effort | Evidence |
| --- | --- | --- | --- | --- |
| R1 | P0 if shared | Keep the server API key out of browser widgets | Small | Synthetic AppTest reproduction |
| R2 | P1 | Translate actual Gemini SDK errors and preserve failure types | Medium | Mocked SDK 429 reproduction |
| R3 | P1 | Make text filters literal | Small | `[` crashes a filter |
| R4 | P1 | Stop JSON repair from corrupting URLs | Small initially | Trailing-comma URL example fails |
| R5 | P1 | Isolate malformed articles and handle missing candidates | Small | Offline reproductions |
| R6 | P1 | Preserve identity context after disambiguation | Medium | Confirmed data flow in code |
| R7 | P1 | Bind derived results to the right profile and clear them together | Medium | AppTest plus cache-key inspection |
| R8 | P1 | Represent unknown and unresearched facts honestly | Medium | Schema reproduction and renderer inspection |
| R9 | P1 | Make evidence links exact and validate references | Medium | Empty claim matches an unrelated role |
| R10 | P1 | Escape graph tooltip content | Small | Unescaped markup in network object |
| R11 | P2 | Resolve cache hits before any model call | Small after R6/R7 | AppTest call counts |
| R12 | P2 | Make retry budgets effective and model capabilities explicit | Medium | Identical request configs reproduced |
| R13 | P2 | Avoid hidden-tab graph work and temporary graph files | Small–medium | Call flow and generated HTML inspection |
| R14 | P2 | Make installation and optional history requirements explicit | Small | Manifest/module/documentation inspection |

## Findings and acceptance criteria

### R1. Server credentials become a client-visible widget value

Location: `app.py:89` (`_current_api_key`) and `app.py:155` (sidebar password input).

The password widget receives `value=_current_api_key()`, which falls back to `GOOGLE_API_KEY`. A password input masks its display; it does not keep its value on the server. A synthetic environment key appeared unchanged in the AppTest widget value. If the app is shared with a server-owned key, visitors receive that credential in widget state.

Change: keep server credentials exclusively in server configuration. Show a neutral “server API configured” status. The user-key widget should contain only a key entered by that user, initially empty. Define whether an entered user key overrides the server key, and keep that rule consistent across model listing and generation.

Acceptance: with a synthetic environment key, no rendered widget contains it; generation still uses it server-side. With a user key, generation uses the chosen override. Never put actual credentials in tests, logs, cache keys, or diagnostic exports.

### R2. Error handling catches the wrong SDK exception family

Location: `agent/orchestrator.py:394` (`_call_model`), `:332` (`_call_writer`), and `:240`, `:259`, `:287` (summary/news methods); `app.py:326` (`_do_search`).

The app calls `google.genai` but catches `google.api_core.exceptions`. The installed GenAI SDK raises its own `google.genai.errors.APIError` subclasses. A mocked `ClientError(429, ...)` escaped `_call_model` unchanged. Through `_call_writer`, it was retried three times and finally reported as `EmptyResponseError`. Parse failures can also lose their original type at retry exhaustion. The Searcher path can fall through to the unexpected-exception branch, which re-raises.

Change: translate GenAI SDK status codes into the existing app exceptions at one boundary. Preserve the final parse/transport error after bounded retries. Distinguish permanent authentication/configuration failures from transient service/rate-limit failures; do not automatically retry every error. Check installed SDK retry behavior before adding another retry layer. Wrap agent creation as well as generation in the UI error boundary.

Summary and news methods currently return `""` or `[]` for every failure, and the UI caches these values. Let failures reach the existing error UI; reserve an empty list for a successful search with no articles. Cache successful results, including legitimate empty results, according to an explicit freshness policy.

Acceptance: mocked 401/403, 429, 5xx, parsing failure, and successful-empty results produce distinct expected outcomes. Permanent failures do not trigger three attempts. A failed news request shows a retryable error, not “no news found.”

Reference: [Google GenAI SDK error handling](https://github.com/googleapis/python-genai#error-handling) and [SDK exception definitions](https://github.com/googleapis/python-genai/blob/main/google/genai/errors.py).

### R3. Normal filter text is interpreted as a regular expression

Location: `ui/report_renderer.py:151` (`_apply_filter`), used by family and job-history tables.

`str.contains(query, na=False)` enables regex matching. Entering `[` reproduced `ArrowInvalid: Invalid regular expression`; regex metacharacters also change ordinary search semantics.

Change: pass `regex=False`. Keep the existing case normalization. This is a small standalone fix.

Acceptance: `[`, `(`, `.`, `+`, and a normal company name are treated literally; no filter input crashes rendering.

### R4. JSON repair destroys URLs when a response needs repair

Location: `agent/orchestrator.py:516` (`_repair_json`) and `:394` (`_call_model`).

The comment-removal regex strips `//` even inside quoted strings. Valid JSON bypasses repair, but `{"url":"https://example.com",}` enters it and loses the URL suffix instead of merely losing the trailing comma. This failure was reproduced. The trailing-comma regex also lacks string awareness.

Immediate change: stop applying unrestricted text substitutions inside JSON strings. Prefer a bounded formatting retry with the original findings over silent data modification. If repair remains, make it string-aware and test literal URLs, escaped quotes, and punctuation inside strings.

Next change: configure Writer JSON calls with API structured output using schemas aligned with the actual Pydantic contracts. Start with the simple news wrapper, then profile/disambiguation output; preserve selected-dimension behavior. Keep narrative summaries as text. Structured output reduces syntax failures but does not prove facts or evidence are correct.

Acceptance: the trailing-comma URL fixture is either parsed without altering the URL or rejected/retried as a parse failure. Valid JSON strings are unchanged. Test schema validation separately from syntax validation.

Reference: [Gemini structured output documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

### R5. Malformed response entries bypass intended isolation

Location: `agent/orchestrator.py:558` (`_parse_articles`) and `:465` (`_extract_text`).

`raw.get("url", "").startswith("http")` runs before the per-article `try`. A `null` article, non-dictionary entry, or null URL can abort the whole batch. A valid article followed by `None` reproduced an `AttributeError`; the public news methods then turn that failure into an empty result.

Separately, `response.candidates=None` raises `TypeError` at `candidates[0]`, which the current handler does not catch. Finish reasons other than `SAFETY`, such as output truncation, are not classified.

Change: validate the top-level articles container, then validate each entry and URL within the per-entry boundary. Preserve valid siblings. Accept only parsed HTTP(S) URLs. Check candidates and prompt-block feedback explicitly before indexing; distinguish a blocked response, missing text, and truncated output.

Acceptance: `[valid, null, invalid, valid]` yields two articles; null URLs do not crash. Missing candidates produce a typed app error. Malformed top-level payloads remain failures rather than successful-empty news.

### R6. Disambiguation discards the context the user selected

Location: `app.py:435` (options mapping), `:456` (`_resume_after_disambiguation`), and `:83` (`_store_profile`).

Each option displays a candidate description, but its stored value is only `c.name`. Two people named identically but described with different roles/regions therefore trigger the same subsequent query. Profiles are also stored by `full_name`, so same-name identities overwrite one another. News searches receive only the full name as well.

Change: retain the selected candidate's role/region context in the research query and a stable session identity key. Preserve the display name separately. Carry identity context into news retrieval and related cache keys. Start with the existing description; a new search-backed disambiguation stage is optional and adds cost.

Also align the disambiguation prompt with `{"candidates": []}`: it currently says to return an empty array for an unambiguous name even though the parser expects an object.

Acceptance: selecting two same-name candidates with different descriptions produces distinct research requests, profiles, and cache entries. Cancelled or superseded disambiguation state cannot resume a previous search unexpectedly.

### R7. Cached summaries and news can outlive the data they describe

Location: `app.py:293` (clear button), `:322` (profile cache key), `:521` (summary key), `:600` and `:637` (news keys); `utils/cache.py`.

The clear button removes profiles but leaves `summary_*`, `news_person_*`, and `news_company_*`. AppTest confirmed that seeded summary/news entries survive. Summary keys contain only the full name, so a new profile for the same name can display an older summary. Profile keys include dimensions but omit model selection, prompt/schema version, and freshness. All stored results live indefinitely within the session.

Change: give each researched profile a revision or content fingerprint and bind summaries to it. Decide explicitly whether changing models should reuse a prior result or require regeneration; make that visible. Clear all app-owned research and pending-disambiguation state together while retaining API configuration. Add an explicit refresh and timestamps; choose TTL and session entry limits from the intended workflow rather than arbitrary numbers.

Acceptance: regenerate the same person with changed roles/dimensions and verify the prior summary is not reused. After clearing research state, no profile, summary, news, or pending candidate selection remains. Configuration survives. Tests cover refresh, same-name identities, and model changes.

### R8. Missing data is presented as a negative or a current job

Location: `agent/schema.py` (`PersonProfile`, `TniPolriInfo`, `FieldConfidence`); `agent/prompts.py:237`; `ui/comparison_renderer.py:48`; `ui/report_renderer.py:396`.

Omitted official/military flags become `False`, and omitted confidence becomes `medium`. The UI renders every section, including dimensions the user did not research. Comparison displays these false defaults as “Tidak.” The Writer instruction says to use `null` for unavailable fields, but explicitly null Boolean flags fail validation; this was reproduced. A missing job end date is displayed and sorted as `Sekarang`, which converts uncertainty into a claim that employment continues.

Change: represent unknown flags separately from true/false, retain selected/researched dimensions with the profile, and show “not researched” or “unknown” appropriately. Do not assign medium confidence by default to unsupported sections. Render a missing employment end date as unknown unless ongoing employment is explicitly supported. Update prompt, schema, report, comparison, and summary behavior together.

Acceptance: a roles-only profile does not assert that the person is not a minister or military member. Null fields follow the agreed schema. A job with no end date is not labeled current. Explicit true, false, and unknown cases remain distinct.

### R9. Evidence chips can attach the wrong source to a claim

Location: `ui/report_renderer.py:75` (`_claims_for`), `:62` (`_source_lookup`); `agent/schema.py` (`SourceEntry`, `ClaimEntry`); `agent/orchestrator.py:394`.

Evidence matching accepts either substring direction. An empty claim value matches every displayed value in its field; the offline fixture matched an empty claim to `Minister`. Short company names can also match longer, different companies. Duplicate source IDs overwrite each other in the lookup, while unresolved IDs are silently skipped.

Change: first require nonempty normalized exact matches, consistent with the existing Writer prompt. Validate source-ID uniqueness and claim references when accepting a profile. Flag unresolved evidence rather than implying support. If later work needs entity IDs, introduce them at the data boundary rather than making matching fuzzier.

The Searcher currently discards the API response after extracting its text. Preserve available grounding metadata as provenance before handing findings to the Writer. Application-generated retrieval timestamps should come from the actual research event. Model-generated source tags and confidence are assessments, not proof of verification. This can improve the existing two-stage pipeline without adding more model calls.

Acceptance: empty claims and `PT Example` versus `PT Example Energy` never borrow one another's sources. Duplicate/dangling source IDs are detected. A displayed citation resolves to the source attached to that exact claim. Grounding collection is validated using an SDK response fixture before a live smoke test.

### R10. Graph tooltips interpolate unescaped model content

Location: `ui/graph_renderer.py:77`, `:85`, `:107`, and `:137`.

Names, relations, roles, and groups are concatenated into HTML tooltips. A synthetic name containing `<img ...>` remained intact inside the node's `title`. Escaping the JSON embedded in a script does not itself escape HTML later consumed as a tooltip.

Change: HTML-escape every dynamic tooltip value, retaining only the renderer's intentional `<b>`/`<br>` markup. Treat labels and tooltip HTML as separate contexts. This is an HTML-injection risk in the graph component; full browser execution or escape from the iframe was not tested.

Acceptance: malicious-looking names, quotes, ampersands, and markup display as text in a real browser; intended formatting still works. Keep the existing report/news escaping tests.

### R11. Cache hits still pay for disambiguation

Location: `app.py:432` and `:475`.

Every form submission creates an agent and disambiguates before `_run_full_search` checks the cache. Two identical mocked submissions produced two disambiguation calls and one research call. Thus the cache avoids Searcher/Writer work but still incurs an avoidable remote call, or several calls if disambiguation retries.

Change: resolve a valid cache entry before creating the agent or calling disambiguation. For previously ambiguous inputs, remember the user's chosen identity/context rather than silently choosing a person from a name-only cache entry. This depends on R6/R7.

Acceptance: a repeated query with the same identity, dimensions, and cache policy makes zero generation calls. Refresh makes the intended new calls. Case/whitespace normalization does not merge distinct identities.

Baseline call budget, excluding model listing and retries: an uncached unambiguous profile uses three generations (disambiguation + search + writer); a summary adds one; person or company news adds two. A cached repeat currently still uses one. These are code-derived call counts, not monetary estimates.

### R12. Thinking-model retries do not change the actual request budget

Location: `agent/orchestrator.py:98`, `:156`, `:332`, and `:424`.

The Writer increments tokens and temperature between retries, but `_call_model` replaces both for names matching `2.5` or `thinking`. The probe observed `(8000, 1.0)` on all three attempts despite the logs announcing increments. Retry delays add 3 + 6 = 9 seconds before counting API latency. The same 8,000-token cap is applied to short disambiguation tasks. A cap is not actual usage; savings require measurement.

Change: calculate the effective task/model budget once and let retries adjust the actual supported setting within a bound. Handle truncation explicitly. Replace name-substring assumptions with a small, documented compatibility policy for the models the app actually supports. `gemini-` name filtering alone does not establish search-tool or structured-output compatibility. Preserve user choice among compatible models.

Acceptance: assert the configs delivered to the mocked SDK, not just arguments passed to `_call_model`. Effective retry budgets change when intended; short tasks use their intended policy. Unsupported role/model combinations receive an actionable message. Record token usage and latency before selecting defaults.

### R13. Every rerun rebuilds the graph, including hidden-tab reruns

Location: `app.py:688` (`main`), `:664` (`_tab_graph`), and `ui/graph_renderer.py:151`.

The main function executes all tab bodies. Once a profile has connections, an unrelated filter or summary action also rebuilds its network, writes a temporary HTML file, reads it, and deletes it. Installed PyVis uses local resource mode by default; generated HTML references `lib/bindings/utils.js` plus CDN assets, and `save_graph` uses its filesystem-writing path. Whether those resources resolve inside the deployed iframe still needs a browser check.

Change: generate HTML in memory with `generate_html()` and select an explicit resource strategy. Inline assets reduce external dependencies at the cost of a larger payload; remote assets reduce the payload but require network access. Verify the complete HTML, including any remaining external assets. Avoid graph reconstruction when its profile content has not changed. Render expensive hidden content conditionally; current Streamlit supports stateful tabs, but adopting that API requires updating/testing the project's supported minimum version. A simple view selector is an alternative.

Acceptance: instrument graph-build counts; profile-filter changes do not rebuild unchanged hidden graph content. Graph rendering writes no temporary HTML or library directories. A real browser shows the graph without failed required asset requests. Measure payload size and rerun latency before/after.

Reference: [Streamlit tab execution and state tracking](https://docs.streamlit.io/develop/api-reference/layout/st.tabs). With default `on_change="ignore"`, all tab bodies execute; state tracking allows conditional execution.

### R14. Dependency and history documentation need a clear boundary

Location: `requirements.txt`, `utils/history.py`, `SUPABASE_SETUP.md`, and `.gitignore`.

Dependencies use lower bounds without a reproducible lock. The Supabase module imports an undeclared dependency but is not connected to the current app. This is an optional-module/documentation mismatch, not a demonstrated startup failure. The local virtual environment occupies `.env`, preventing an environment-variable file at that same path.

Change: document the currently runnable app, a supported Python version, and its configuration. Capture a tested dependency set or lock in a separate change. Document history as inactive unless explicitly implementing it; do not add database dependencies just to optimize active searches. Recreate the virtual environment as `.venv` when addressing setup—do not merely rename it, because environment paths can be embedded.

If history is enabled later, first decide its access model. The current module uses a process-wide service credential, unscoped reads/deletes, and `clear_all()` matches every nonzero ID. A multi-user deployment needs explicit ownership/access enforcement and paginated summaries instead of reading all profile JSON. No database operation was executed during this review.

The existing `.gitignore` pattern `*.MD` causes Markdown documents, including this guide, to be ignored in this Windows worktree. The file exists locally but will not appear in ordinary `git status`. If it should be versioned, intentionally adjust that rule or force-add this specific document in a later authorized commit workflow.

Acceptance: a clean environment installs the documented active app and passes tests; configuration instructions match the directory layout. History's status is explicit. If enabled, cross-user access and scoped deletion are tested before exposing it.

## Implementation sequence

Keep each step independently reviewable and preserve the existing eight tests.

1. **Small correctness/security fixes:** R1, R3, R5, R10. Add focused tests using synthetic values. Verify no real credential or network access is needed.
2. **Agent reliability:** R2 and R4, then R12. Mock actual SDK exceptions and response objects. Preserve error categories and verify effective SDK configs. Adopt structured output incrementally, beginning with news.
3. **Identity and session correctness:** R6 and R7, then R11. Use AppTest with two same-name identities, two profile revisions, repeat searches, refresh, and clear. Require zero generation calls on a valid repeat-cache hit.
4. **Research accuracy:** R8 and R9. Use deterministic fixtures for unknown flags, omitted dimensions, missing dates, and invalid evidence links. Check report, comparison, and summary input behavior together.
5. **Measured performance and packaging:** R13 and R14. Record before/after graph counts, timings, and payload sizes; perform browser verification and a clean-environment installation check.

For each step: reproduce the issue, make the smallest change, run its focused tests plus the existing suite, and record actual results. Avoid combining a module reorganization with behavior fixes. Extract a helper only when the change makes it useful; splitting all of `app.py` is not a prerequisite.

## Performance measurement plan

Add lightweight timings and counters at `_call_model`, cache lookup, validation, and graph construction. Record task type, model, elapsed time, effective output cap, returned token usage when available, retry count/reason, and cache hit/miss. Use an opaque operation ID instead of recording credentials or raw findings. Current logs contain person names; choose a retention/redaction policy appropriate to the deployment.

Measure these scenarios with fixed fixtures first, then a small explicitly chosen live sample:

| Scenario | Correctness/performance target |
| --- | --- |
| First profile search | Record stage timings and generation count; successful validated profile |
| Identical cached repeat | Zero model generation calls |
| Same person, changed dimensions | Correct revision and no stale summary |
| Unrelated widget rerun | Zero model generation calls; no unchanged hidden graph rebuild |
| Quota/auth failure | Correct message and bounded, policy-appropriate attempts |
| Malformed news entry | Valid sibling articles survive |
| Cache clear | No leftover research-derived state |

Collect p50/p95 latency and tokens only after gathering a representative sample. Set time/cost targets from that baseline. Do not claim a percentage speedup from mocked tests. Limit memory growth using observed session sizes and the chosen expiry policy. Optimize repeated evidence scans only if profiling shows they matter; external calls and avoidable graph work are clearer initial targets.

## Follow-up improvements after the main fixes

- Replace hard-coded `2025 OR 2026` news queries with the intended date window; normalize dates when known, deduplicate URLs, and enforce the stated maximum of ten articles in code rather than only the prompt. Test unknown dates separately.
- Give filter widgets meaningful nonempty labels while retaining collapsed visual labels. AppTest already exposes the current accessibility warnings.
- Apply the existing untrusted-source instruction consistently to news and summary prompts, and retain structural validation. Prompt instructions alone cannot establish evidence integrity.
- Make malformed URL handling consistent across news, evidence chips, and source tables; a parsed URL helper should reject invalid hosts without crashing. Prefer native link components where practical.
- Review unused imports and the inactive `ModelNotAvailableError` only when touching their owning modules. They are minor maintenance issues and were not removed during this review.

## Reusable implementation prompt

> Read SOROT_OPTIMIZATION_REVIEW.md and implement only findings [IDs]. Preserve unrelated changes and existing behavior outside those findings. First reproduce each defect with a focused offline test. Follow the acceptance criteria, use mocked Gemini/Supabase boundaries, and keep changes small. Run the existing unittest suite and relevant integration checks. Report changed behavior, exact verification results, and any browser/live-service checks still needed. Do not add product features or reorganize unrelated modules.

## UI beautification plan using antislop-ui

Added: 2026-09-17. Mode: apply the rules throughout planning and subsequent implementation. Scope of this addition: a design and implementation plan only. No application UI has been changed.

Guidance used: installed `anti-slop/antislop/3.2.9/skills/antislop-ui/SKILL.md` together with its required `antislop.md` core. In this section, `AS R-XX` identifies a rule in that skill; review findings such as `R7` refer to the earlier application review.

### Design direction and assumptions

Reading this as: an Indonesian public-figure research workspace for people comparing profiles and checking sources, in an editorial reference style, with ENERGY 1 / RHYTHM 2 / MOTION 1.

Use the current navy-and-gold identity as the starting point. The editorial treatment is a proposed direction derived from SOROT's research content, not an existing formal brand guideline. The intended feeling is composed, legible, and specific to examining people, positions, and supporting evidence. Retain Indonesian interface copy and the four existing destinations: Cari Tokoh, Bandingkan, Berita Terkini, and Graf Relasi.

- **Energy 1:** content and the primary action draw attention through type and placement; surrounding controls remain quiet.
- **Rhythm 2:** consistent section headings and spacing, with different structures for profile facts, employment tables, news articles, and relationships.
- **Motion 1:** clear hover, focus, and pressed states. No decorative entrance animations, pulsing dots, or automatic scrolling. Loading indicators represent real work; graph motion should settle once the layout is readable.
- **Identity motif:** a readable dossier heading followed by compact field labels and source references. Repeating this pattern makes SOROT recognizable through its research content.
- **Primary visual focus:** search input before results; person name and current roles after a successful search; compared attributes in comparison; article headlines in news; selected person's connections in the graph.

Keep Streamlit and the current workflow. Do not add a marketing hero, activity feed, invented statistics, profile photographs, generated logo, saved investigations, export controls, or new research features as part of this styling work. Use the existing SOROT name as text. The small graph relationship list proposed below is an accessible presentation of existing data, not another research capability.

### UI-1. Establish a restrained visual system

Primary files: `ui/components.py`; a project `.streamlit/config.toml` only if needed for supported theme settings. Keep secrets separate from presentation configuration.

| Decision | Proposed treatment | Purpose |
| --- | --- | --- |
| Main background | Warm paper `#F6F4EE` | Gives long research reports a distinct reading surface |
| Input and table surfaces | White `#FFFFFF` | Makes editable and tabular areas easy to distinguish |
| Primary text | Ink `#202C39` | Strong contrast for dense facts and paragraphs |
| Brand and links | Existing navy `#1E3A5F` | Preserves identity and gives source links consistent emphasis |
| Supporting text | Slate `#526172` | Readable metadata without competing with headings |
| Primary action | Existing gold `#F0A500` with navy text and navy boundary | Makes the search action identifiable without scattering accent color |
| Input boundaries | Slate `#78818C` where a boundary is needed to identify a control | Separates controls from the light surface |
| Semantic states | Restrained success, warning, and error colors with explicit text | Communicates state, never a decorative category rainbow |
| Main heading | Georgia/serif stack, approximately 30–34px, regular or medium weight | Gives the profile a recognizable editorial voice using system fonts |
| Controls and data | System sans-serif stack, approximately 16px body and inputs, 14px metadata | Keeps forms and dense rows familiar and readable |
| Section headings | Sans-serif, approximately 20–22px, semibold | Gives evidence sections a dependable hierarchy |
| Spacing | 4, 8, 12, 16, 24, 32, 48px scale | Tight within a fact; more space between research topics |
| Corners | 4px for small labels, 6px for controls, at most 8px for grouped surfaces | Distinguishes component roles without making everything a pill |
| Elevation | Flat content; shadow only for an actual overlay | Keeps the report grounded and prioritizes reading |

Remove repeated sidebar, button, and summary gradients. Use no glass, glow, background grid, decorative colored side stripes, or ornamental illustrations. Remove emoji from interface headings, controls, and classification output. Use text labels; add an icon only when it communicates an action more clearly, such as revealing a password, with an accessible name. Semantic labels such as confidence and source category remain useful, but should read as compact information rather than promotional badges. (AS R-01, R-04, R-06, R-09 through R-14, R-29, R-31.)

Calculated contrast for the proposed solid light-theme pairs:

| Pair | Calculated contrast | Intended use |
| --- | --- | --- |
| Ink on paper | 12.89:1 | Body text |
| Navy on white | 11.50:1 | Links and headings |
| Slate text on paper | 5.77:1 | Supporting text |
| Slate text on white | 6.34:1 | Table metadata |
| Navy on gold | 5.53:1 | Search button text |
| Gold on white | 2.08:1 | Do not use for text or the sole focus/selection indicator |
| Input-boundary slate on white / paper | 3.95:1 / 3.59:1 | Visible control boundaries |

These are arithmetic checks of the proposed colors, not proof that the rendered app passes accessibility checks. Use at least 4.5:1 for all planned text, including metadata, and check the actual computed styles and interaction states. The standard permits 3:1 for qualifying large text, but that exception is unnecessary for this palette. [W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).

Use a light presentation as the reference because the central activity is sustained reading of profiles and tables. Preserve any available native Streamlit theme choice: custom sections and the graph must follow it instead of creating a white report inside a dark app or a dark graph inside a light app. Define and verify semantic tokens for both exposed themes before shipping; do not add a cosmetic toggle that only changes part of the screen. Prefer supported theme settings and app-owned classes over broad descendant selectors and repeated `!important`. The current `[data-testid="stSidebar"] *` override is a specific target for replacement. [Streamlit theming guidance](https://docs.streamlit.io/develop/concepts/configuration/theming).

Acceptance: one coherent token system styles the app; text, controls, focus, and source references remain legible in every exposed theme. Token checks pass before screenshots are approved. Font fallbacks work without external font requests.

### UI-2. Put search and research scope ahead of configuration

Primary files: `app.py` (`_sidebar`, `_tab_search`, `main`) and `ui/components.py`.

Replace the large hero plus separate decorative search card with a compact SOROT masthead, the existing navigation, and one clearly labeled search form. Keep the introductory explanation to one useful sentence. After a search, keep the form available but let the profile become the dominant content.

Proposed form copy:

- Label: `Nama tokoh`.
- Placeholder: `Nama lengkap, jabatan, atau wilayah`.
- Supporting text: `Tambahkan jabatan atau wilayah untuk membedakan nama yang sama.`
- Primary action: `Telusuri tokoh`.

Keep the existing sidebar because research dimensions need persistent access. Make it a quiet settings surface rather than the strongest color block on screen. Place research dimensions first, then API/model configuration in a native expander, then the existing cache-clear control. Show configuration expanded when setup is incomplete. Keep the existing model choices and explain their roles in concise Indonesian labels. Do not prefill a server-owned key into a widget; coordinate with review R1.

Use sentence-case group labels, readable help text, and full control names. Preserve existing widget keys and session semantics unless a reviewed correctness change requires otherwise. Cache clearing should be a secondary text action with a precise explanation of what it clears after R7 is fixed.

Desktop composition, shown as a planning wireframe rather than an implemented screen:

```text
Research settings      SOROT   Sistem Observasi & Riset Online Tokoh
                       Cari Tokoh | Bandingkan | Berita Terkini | Graf Relasi
Dimensions
[existing checkboxes]  Nama tokoh
                       [name and context input]       [Telusuri tokoh]
API and models         Short contextual help or active search state
[native expander]
                       [Person name from the result]
Session controls       Current role and identity context, when available
                       Compact source/status metadata from actual data

                       Ringkasan     [Buat ringkasan]
                       [Generated narrative only after the existing action]

                       Jabatan dan instansi             Supporting sources
                       [Current and past role rows with evidence references]

                       [Other researched sections in a readable sequence]
```

The square-bracket content above describes fields, not fabricated people or claims. On narrow screens the settings live in Streamlit's collapsible sidebar and the form becomes one column. Do not introduce a new navigation framework for this arrangement. (AS R-05, R-15, R-20, R-23, R-24.)

Acceptance: search remains the obvious first action; setup remains discoverable when required; all existing tab destinations and dimension controls remain reachable. First search, disambiguation, repeated search, summary generation, and cache clear retain their behavior in AppTest.

### UI-3. Make profiles read like evidence-backed reports

Primary files: `ui/report_renderer.py`, `ui/components.py`, and `app.py` (`_render_profile_section`).

Use the person's name as the primary heading. Display aliases and known identity context beneath it. Render vital status as a quiet, explicit fact when available; do not let colored status dominate the name.

Replace the six equal count cards with a compact, wrapping metadata line using only actual profile counts. For example, the labels can be `Sumber`, `Jabatan`, and `Relasi`, each paired with its computed value. A count describes recorded data, not completeness or quality. Keep field-specific counts next to their sections when more useful. Show a research timestamp or selected dimensions only once the corresponding metadata actually exists; never invent freshness from the page-render time.

Bring the existing on-demand summary action close to the profile heading. Render a generated summary on the same reading surface with a comfortable line length, around 65–75 characters, rather than inside a saturated gradient block. Keep generation manual and ensure its button continues to work across reruns. This move depends on retaining the profile-state behavior already described in `app.py` and fixing stale summaries in R7.

Use full-width rows for roles and corporate affiliations when strings need space. Put the role or entity first, supporting details second, and its source reference beside or immediately below it. Use a compact navy source link such as `S1 · [source title]`, with accessible descriptive link text. Long source titles and URLs must wrap. Evidence must remain attached to the correct claim; coordinate with R9.

Use tables for employment and family records because users compare the same attributes across rows. Put the deciding fields first: position/company for employment, name/relation for family. Keep existing filters near their section headings with meaningful accessible labels. Use thin dividers and spacing to separate rows; avoid boxing every fact individually.

Keep confidence as labeled supporting information. It must be clear that this is a model assessment, not independent verification. Avoid a large row of negative official-status badges when those dimensions were not researched. Accurate distinctions among unknown, unresearched, and false depend on R8, and must not be simulated through styling alone.

Acceptance: a long name, long position, long company name, and long source title remain readable. Source links stay correctly associated after filtering. Profiles with partial or missing data do not appear more certain because of their presentation. No repeated decorative count-card row remains. (AS R-05, R-09, R-14, R-17, R-27, R-38.)

### UI-4. Give comparison, news, and graph views their own useful structures

Primary files: `ui/comparison_renderer.py`, `ui/news_renderer.py`, `ui/graph_renderer.py`, and their tab controllers in `app.py`.

| View | Proposed change | Reason and acceptance |
| --- | --- | --- |
| Comparison | Keep the two-to-four-person selector and attribute-by-person structure. Use clear section headings, consistent row spacing, wrapping names, and restrained row separators. | The focal point is differences in research attributes. Preserve selected profiles and section ordering. Unknown values remain explicit after R8. |
| News | Use a list of article entries: linked headline, publisher/date/source category, then summary. Group filters at the top. Remove decorative emoji and heavy framing around every article. | Readers scan headlines and publication context. Every headline link must open its existing valid URL; filtering must still work. |
| Graph | Match the app theme, strengthen label contrast, and use shape plus text for node categories. Highlight the selected subject with gold fill, navy label, and a visible navy boundary. | The question is who connects to the selected person, not how elaborate the visualization looks. Color is supplementary to labels and shapes. |
| Graph fallback | Provide a compact expandable relationship table derived from the same profile fields: related entity, relationship, and type. | Keyboard and small-screen users can inspect the same facts without relying on hover or canvas interaction. No invented connections or additional research calls. |

For graph categories, use a restrained navy/slate treatment and distinguish person, company, and party by existing labels and deliberate shapes. Related people can share the person shape. Keep a legend tied to actual node categories. If further category colors prove necessary, document their data-encoding purpose and verify contrast rather than borrowing unrelated source-badge colors.

Escape tooltip text as required by R10. Stop unchanged hidden graphs rebuilding as required by R13. Any graph motion exists only to lay out the relationships, then settles. Avoid adding graph toolbar controls unless their behavior is actually implemented and verified.

Acceptance: comparison is usable with four long names; news filtering and refresh remain functional; graph labels and the text alternative expose the same relations. No graph information exists only in a tooltip. (AS R-04, R-05, R-19, R-25, R-26, R-32.)

### UI-5. Design real states and responsive behavior

Use distinct states tied to actual application outcomes:

| State | Presentation and next action | Data dependency |
| --- | --- | --- |
| No search yet | One sentence explaining what to enter; focus remains on `Nama tokoh` | Existing state |
| Missing configuration | Show what is missing and expose the relevant settings | R1 for safe credential handling |
| Disambiguation | Candidate name and existing description together; `Telusuri pilihan ini` confirms the choice | R6 to preserve selected identity context |
| Research running | Short actual stage label: `Memeriksa nama`, `Menelusuri sumber`, or `Menyusun profil` | Existing stage callbacks; no invented ETA or percentage accuracy claims |
| Section not researched | `Dimensi ini belum ditelusuri.` with guidance to select it for the next search | R8 and stored selected dimensions |
| Successful empty result | Explain that no result was found for that request | R2 must distinguish success from failure |
| Filter has no matches | Explain that the active filter matched no rows and how to clear it | Existing filter state |
| Request failure | Name the failed action and give a specific recovery step; technical detail in an expander | R2 error categories |
| Comparison not ready | State how many additional profiles are required using actual session count | Existing comparison logic |

Responsive targets are acceptance criteria to verify, not claims about the current app:

- At 1440px: compact settings sidebar, bounded reading width, generous separation between report topics.
- At 1024px and 768px: controls wrap cleanly; long sections use one column when needed; settings remain accessible.
- At 390px and 320px: one-column search and report, readable 16px inputs, comfortably tappable controls, and no document-level horizontal overflow.
- Dense comparison and employment tables may scroll inside a clearly bounded table region while the rest of the page stays within the viewport. Do not shrink the entire table to unreadable text or clip columns to hide overflow.
- Preserve native tab behavior and verify all four destinations at narrow widths; do not hide overflow on the tab strip in a way that makes a destination unreachable.
- Use a 44px minimum target for primary controls and provide enough separation for adjacent links. Keep 200% zoom usable.
- Keep visible keyboard focus with a sufficiently contrasting outline. Gold alone on white is not adequate. Do not suppress native focus unless replacing it with a verified treatment.
- Use actual heading semantics for hierarchy; keep every input's accessible name nonempty even if its visible label is collapsed. Verify source links and disclosures with keyboard navigation.

This plan uses the antislop skill's 44px control target as its design requirement. Browser resizing, keyboard checks, zoom, dark-theme checks, and graph interaction remain implementation-time verification work. (AS R-03, R-25, R-27, R-32, R-34.)

### UI-6. Implementation order and verification

The stages below are future work. Update presentation in small slices and avoid changes to model calls, prompts, or data contracts inside cosmetic commits.

| Stage | Files in scope | Verification before moving on |
| --- | --- | --- |
| 1. Tokens and theme | `ui/components.py`; theme configuration if needed | Check text/boundary/focus contrast and native controls in each exposed theme; compare screenshots at 1440px and 390px |
| 2. Shell, search, settings | `app.py`, `ui/components.py` | AppTest for configuration, search, disambiguation, repeat search, and tab state; browser keyboard and mobile navigation |
| 3. Profile presentation | `ui/report_renderer.py`, `app.py`, shared presentation helpers | Long/partial profile fixtures; source-link behavior; summary button across reruns; evidence escaping regression tests |
| 4. Comparison and news | Their renderer files and relevant tab controllers | Two/four profiles; long labels; successful-empty and failed news; literal filters; refresh behavior |
| 5. Graph presentation | `ui/graph_renderer.py`, graph tab only as needed | Real-browser graph load, tooltip escaping, responsive sizing, keyboard-accessible relationship table, no new model calls |
| 6. Final polish | Only files found to need corrections | All exposed themes, widths, empty/loading/error states, keyboard traversal, zoom, and the full gate below |

Suggested first visual slice: UI-1 plus UI-2. It establishes a coherent frame and the main task before changing every renderer. Resolve R1 before sharing a deployment; resolve R2/R6/R7/R8/R9 before presenting the dependent states as accurate. Palette, typography, spacing, and decorative cleanup can proceed independently.

Do not alter Streamlit through DOM-rewriting JavaScript or source-rewriting helper scripts. Use native widgets, supported theming, and narrowly scoped application styles. CSS wrappers must correspond to actual rendered containers; do not assume separate `st.markdown` calls can enclose native widgets in a single HTML wrapper. Check selectors against the installed runtime and avoid unnecessary dependencies. (AS R-33.)

Record a browser click-through during implementation: search submit and validation; settings expander; API input and model selectors; each dimension checkbox; disambiguation choice/confirmation; each tab; comparison selection; summary generation/regeneration; every report/news filter; person/company news fetch and refresh; source links; graph interactions and relationship disclosure; cache clear; native theme selection if exposed. Use mocked data/services for deterministic checks, including unavailable-service paths. Run `.\.env\Scripts\python.exe -m unittest discover -s tests -v` after relevant changes. Tests that only assert CSS strings are not a substitute for browser verification.

### Antislop delivery gate for this planning addition

This is a document-only deliverable. The PASS statuses below mean that the plan states the required decision or acceptance criterion, with the cited evidence. They do not certify an implemented UI. No runtime, mobile, keyboard, or theme pass is claimed; those are explicitly scheduled in UI-6. The earlier review remains unchanged and is not retroactively certified by this gate.

| Gate item | Plan status and evidence |
| --- | --- |
| AS R-02, natural copy | PASS: proposed UI labels use concise Indonesian, without em dashes |
| AS R-03, responsive layout | PASS: UI-5 defines five widths, wrapping, local table overflow, tap targets, and zoom checks |
| AS R-17, sourced numbers | PASS: UI-3 permits only actual profile counts; palette ratios were calculated locally |
| AS R-18, testimonials | PASS: no testimonial content or fictional people are proposed |
| AS R-23, assets and layout | PASS: no assets were created; the existing wordmark/navigation are retained and the proposed layout is explicitly a wireframe |
| AS R-24, navigation destinations | PASS: UI-2 retains the four implemented tab destinations |
| AS R-25, contrast | PASS: UI-1 records calculated light-theme pairs and requires rendered-state checks; gold-on-white text is excluded |
| AS R-26, functional controls | PASS: UI-2 through UI-4 identify real behaviors; UI-6 lists their future click-through checks |
| AS R-27, UI states | PASS: UI-5 maps each state to its cause, recovery action, and required data fix |
| AS R-28, relevant FAQ | PASS: no FAQ is proposed for this research workspace |
| AS R-32, keyboard access | PASS: UI-5 requires names/focus and UI-4 supplies a planned text alternative to graph-only interaction |
| AS R-33, source changes | PASS: this addition uses a direct Markdown patch; UI-6 requires future features to be implemented in their owning source files |
| AS R-34, themes | PASS: UI-1 requires coherent tokens and verification for every exposed theme |
| AS R-35, verification disclosure | PASS: document-only status is explicit; no unperformed browser check is described as passed |
| AS R-36, factual claims | PASS: no unsupported compliance, performance, or verification claims are proposed |
| AS R-37, direction | PASS: the design read states product, inferred audience, existing identity, proposed style, and all three dials |
| AS R-38, honest content | PASS: the wireframe labels data slots; presentation uses existing facts and flags metadata dependencies |
| AS R-01, gradients | PASS: UI-1 replaces repeated gradients with purpose-assigned solid surfaces |
| AS R-04, icons | PASS: UI-1 removes decorative emoji and requires a functional reason for any icon |
| AS R-06, typography | PASS: system serif headings and sans-serif data/control text each have a stated reading role |
| AS R-07, backgrounds | PASS: plain paper/white surfaces have reading/grouping roles; no ornamental pattern is proposed |
| AS R-08, arrows | PASS: proposed buttons use action labels without decorative arrows |
| AS R-09, badges | PASS: source and confidence labels carry actual information; promotional capsules are excluded |
| AS R-10, glass | PASS: no glass or backdrop blur is proposed |
| AS R-12, shadows | PASS: shadows are reserved for actual overlays |
| AS R-13, glow | PASS: no glow is proposed |
| AS R-14, cards | PASS: UI-3 replaces equal count cards with compact metadata and fact-specific layouts |
| AS R-19, motion | PASS: MOTION 1 limits motion to interaction feedback and functional loading/layout behavior |
| AS R-22, illustrations | PASS: no unrelated illustrations or fabricated portraits are proposed |
| Liveliness: declared dials | PASS: ENERGY 1 / RHYTHM 2 / MOTION 1 are explicit |
| Liveliness: consistency | PASS: subdued shell, varied research structures, and restrained motion match those values |
| Liveliness: focal points | PASS: one primary content focus is named for each view and search state |
| Liveliness: whitespace | PASS: UI-1 separates within-fact spacing from between-topic spacing |
| Liveliness: accent | PASS: gold emphasizes the main action or the selected graph subject, with navy text/boundary |
| Liveliness: identity motif | PASS: dossier headings, field labels, and attached sources repeat a research-specific pattern |
| Liveliness: design read | PASS: the design read precedes all proposed UI changes |
| C-1, intentionality | PASS: UI-1 records a purpose for each major visual choice |
| C-2, completeness | PASS: proposed interactions map to existing behavior or the explicit relationship disclosure |
| C-3, content-driven structure | PASS: profile facts, comparisons, article lists, and relationships determine composition |
| C-4, resilience | PASS: UI-5 and UI-6 define states, themes, breakpoints, and keyboard verification |
| C-5, evidence | PASS: claim-source relationships and unknown states have correctness dependencies, not invented visual substitutes |
| AS R-05, layout | PASS: composition follows SOROT's research workflow, without template marketing sections |
| AS R-11, corners | PASS: three component-specific radius levels are specified |
| AS R-15, actions | PASS: labels name search, selection, and summary actions |
| AS R-16, language | PASS: proposed copy describes the work without promotional buzzwords |
| AS R-20, identity | PASS: existing navy/gold plus editorial report hierarchy expresses the product's purpose |
| AS R-21, theme choice | PASS: light is justified by sustained reading and native theme choice is preserved where available |
| AS R-29, palette | PASS: neutral surfaces, navy, and one gold accent form the brand palette; semantic colors have explicit state roles |
| AS R-30, originality | PASS: no other product is used as a screen template |
| AS R-31, reasons | PASS: the token table and view table record one-line design reasons |

UI-skill supplement, applied to the plan:

- PASS, palette derives from SOROT's existing navy/gold identity and documented reading goals (UI-1).
- PASS, accent placement is restricted to the main action or selected graph subject (UI-1, UI-4).
- PASS, proposed UI copy removes decorative emoji (UI-1).
- PASS, composition varies by research content and RHYTHM 2 (UI-3, UI-4).
- PASS, no bento, fake terminal, pricing template, or decorative side stripe is proposed (UI-1).
- PASS, no redundant badge above the main heading is proposed (UI-2, UI-3).
- PASS, navigation and controls have specified destinations/actions (UI-2, UI-6).
- PASS, motion follows MOTION 1 and real operational needs (design read, UI-4).
- PASS, surfaces, shadows, and radii have stated roles and limits (UI-1).
- PASS, no decorative status dot or pulsing indicator is proposed (design read).
- PASS, each view centers on the user's research decision (design read, UI-4).
- PASS, counts and rows derive from actual profile data; no fabricated trend is proposed (UI-3).
- PASS, inputs and wireframe slots use descriptive placeholders rather than fictional identities (UI-2).
- PASS, empty/loading/error states explain causes and next actions (UI-5).
- PASS, responsive/theme/keyboard checks are explicit future acceptance criteria, with no runtime verification claimed (UI-5, UI-6).

### Reusable UI implementation prompt

> Read the UI beautification plan in SOROT_OPTIMIZATION_REVIEW.md and the installed antislop-ui skill with its core. Apply the already selected during-work mode. Implement only UI stages [numbers], preserving SOROT's existing features and Indonesian language. Use the documented navy/gold editorial direction and ENERGY 1 / RHYTHM 2 / MOTION 1. Keep changes scoped to the listed files, preserve session/widget behavior, and handle the stated correctness dependencies explicitly. Use synthetic fixtures for partial data, long names, errors, and same-name people. Do not invent profiles, sources, timestamps, verification labels, or product features. Verify the affected controls in a real browser at the specified sizes and exposed themes, run relevant existing tests, and report the antislop delivery gate with actual evidence. Do not claim unperformed checks as passed.
