# Changelog

## 0.2.0 - 2026-10-13

An audit of the whole tool found that the numbers it showed could not be trusted: missing tokens, double counts, runs frozen half-way, wrong prices, and verdicts that ranked task types rather than skill versions. This release fixes the data first, then the method, then the outputs.

**Upgrading.** Run `runlens install` (new hook and retro skill), then `runlens refresh`: every run is parsed again by the new parser, once. If you used `[[evidence]]` with 0.1, run `runlens migrate-evidence` (a dry run) and then with `--yes` to replace the per-run copies with deduplicated blobs; it handles paths over 260 characters on Windows. LLM labels on `error_streak`, `repeated_call` and `idle_loop` incidents are orphaned once, because those incident ids are now stable.

### Data you can trust
- Token usage per API message comes from its complete record, not the first streamed part, and each compaction is counted once (with its trigger and size).
- Token totals come from Claude Code's own cost-state (new `model_usage` table): transcripts hold only about 10–24% of the output tokens.
- Prices checked against the official table (Haiku 5.5, Opus 4.5 and Sonnet 4.5 added; cache-read prices corrected; fast mode and US-only inference). A model with no known price is flagged, never priced with a guess.
- API errors are split from quota and rate limits; limits are no longer incidents or errors.
- Runs are `complete` or `open`, and tiny `stub` runs are flagged (`[runs]` thresholds). Scores leave both out.
- New data: PR links, exit codes, timeouts, patch sizes, permission decisions, stopped subagents, skill mentions and whether they were then loaded, compactions, API error status.
- A run whose transcript kept growing after it was archived is archived and parsed again.

### Ingest and the hook
- The `SessionEnd` hook only queues the session and starts a detached worker, so a closing session can no longer kill the work. `runlens refresh` picks up anything still queued.
- Incremental ingest with bulk inserts: unchanged runs are skipped, and a full ingest takes seconds instead of minutes. `--force` parses everything again.
- One unreadable run no longer stops the rest: failures are recorded in `ingest_errors` and shown by `check`.
- Waiting and retrying on a busy database works on Windows too.
- `check` also compares the archive with `~/.claude/projects`, and lists runs never archived, runs still open, queued sessions, unpriced models and missing evidence.

### The method
- A version is compared only with its own skill's previous version; skills are never ranked against each other.
- Verdicts (`better`, `worse`, `no clear change`, `not enough runs`, `confounded`) come from a session-level bootstrap of the difference, with at least 5 runs a side.
- `confounded` names what else changed: another skill's text, the model or effort mix, the Claude Code version, the project mix. Skills used and edited together are also scored as one set, found in the runs (`[method] auto_groups`); a `[[group]]` defines one by hand.
- Cost and time are geometric means per invocation; rates are totals over totals; nothing is counted twice (permission denials, failed checks, idle loops and error streaks each count once).
- A configurable `[outcome]`: a marker's first-pass rate or a PR opened, plus cost per success.
- Weights per measure, globally or per skill or group (`[weights]`), and method settings (`[method]`).

### Closing the loop
- `runlens score` and `runlens versions <skill>`, with `--json` for agents.
- `runlens proposals add|list` records a hypothesis before an edit; `runlens verify` later marks it confirmed, refuted, not enough runs or confounded.
- `runlens export-eval` turns real incidents into eval cases for `claude plugin eval` and skill-creator, so an edit can be checked on a fixed benchmark.
- The judge (`classify`) now sees the active skill text and the steps after the incident, can answer `unknown`, and samples incidents stratified by type. `agreement` reports Cohen's kappa and per-category TPR/TNR.
- `/runlens-retro` is rewritten around version verdicts, proposals and verification, with its own eval cases.

### Dashboard
- New: `runlens dashboard` writes `~/.runlens/dashboard.html`, one static page with no server and no network requests: an overview of every skill, role and group, a page per unit with its versions and their diffs, a comparison of two versions, diagnostics, and how the method works. The hook rebuilds it unless `[dashboard] auto = false`.
- Skill texts are stored once per version (`skill_texts`), so versions can be diffed. Only versions whose text was recorded are counted.
- A skill that a subagent loads for itself is credited to the skill that spawned it; the agent diagnostics list such skills under "Skills inside".
- Built from modules into one page: charts drawn at their real width, one colour per skill everywhere, validated light and dark palettes, better/worse not shown by red and green alone, keyboard tooltips, view state in the URL, CSV/SVG/PNG export.
- Pages follow the new method: within-skill verdicts, per-measure effects with intervals, confounders and data health. The gauge, radar, treemap and two-slice donuts are gone.
- A filter bar on every page (dates, repo, branch, model, effort, skills, Claude Code version) and a Score menu (baseline, weights, confidence). With custom settings the page re-runs the method on the runs kept and marks the result "custom".
- New pages: Runs (calendar and cost scatter) and one run on one time axis with every subagent, its spend so far and its problems; Data health, with a badge in the header.
- New charts: score waterfalls, forest plots of version differences, Pareto frontiers of outcome against cost, cost by token type, calendar heatmaps, weekly rates with Wilson intervals, skill hand-off flows, event lanes.
- Saved views in the browser, and shared ones from `[[dashboard.view]]` in config.toml.

### Privacy and storage
- Evidence is stored once per content, limited to files modified during the run, capped by `max_mb`, and never includes browser profiles, databases, `node_modules` or `.git` objects. The old example copied 1.5 GB per run.
- `[privacy] redact = true` masks secrets, tokens and e-mails before text is stored.
- `runlens prune` deletes old runs from the database and the archive.
- Every archive operation handles Windows paths over 260 characters.

### CLI and config
- `sql` and `incidents` print `--json` or `--csv`; `incidents` hides permission-rule denials unless `--all`.
- Config errors, bad SQL and a busy database print one line instead of a traceback.
- `install` and `uninstall` touch only runlens's own hook and write `settings.json` atomically.
- `config.example.toml` documents every option with its default; `examples/m-feature.toml` adds outcomes, per-skill weights and an `m-stack` group, and scopes evidence to the run.

### Engineering
- CI runs on Linux, Windows and macOS with Python 3.11 and 3.14, lints with ruff, checks the dashboard script, renders every page in headless Chrome, and smoke-tests the built wheel. Actions are pinned by commit SHA with read-only permissions.
- Tests for ingest edge cases, the judge, proposals, the dashboard page and the shipped configs, plus null simulations that keep the method's false-change rate near nominal.

## 0.1.1 - 2026-10-04

- Install and develop with uv:
  - `uv tool install` puts `runlens` on the PATH;
  - `uv.lock` pins the dependencies;
  - CI runs through `uv sync --locked`.
- Messages, the report and the `/runlens-retro` skill now say `runlens <command>` instead of `python -m runlens <command>`.
- The README covers everything a new machine needs: requirements, install, config, update, uninstall and development.
- CI moved to `actions/checkout@v7` and `astral-sh/setup-uv@v10.2.0`, which run on Node 24.

## 0.1.0 - 2026-10-04

First release.

- Archive Claude Code runs (session plus subagents) out of `~/.claude/projects` and load them into DuckDB.
- Tables:
  - `runs`, `agents`, `api_calls`, `tool_calls`;
  - `texts`, `events`, `markers`, `skill_loads`;
  - `incidents`, `labels`.
- Analysis views in `views.sql`.
- Cost from Claude Code's `cost-state`, split across calls by list price. Runs still open get a list-price estimate.
- Skill attribution that covers subagents and nested skills. Fork history is deduplicated.
- Generic incidents, each with the timeline that led to it:
  - error streaks and repeated calls;
  - idle waits and test edits after a failure;
  - failed agents, permission denials and interrupts;
  - compactions and API errors;
  - bad config markers.
- `classify`: an LLM judge (`claude -p`) labels incidents with a MAST-seeded failure taxonomy. Human review goes through `labels export/import`, and `agreement` measures how the two compare.
- `check`: verifies the database against the raw transcripts, to catch changes in the transcript format.
- `report`: a self-contained HTML report.
- A `SessionEnd` hook archives and ingests each run when it ends. Set it up with `install` and remove it with `uninstall`.
- `/runlens-retro`: a skill that runs a retrospective and proposes skill edits backed by evidence.
