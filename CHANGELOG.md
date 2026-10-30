# Changelog

## Unreleased

### Data
- The parser version is 4: every run is parsed again, once, on the next drain or `runlens refresh`. Labels made before this release match no incident and need redoing (`runlens check` lists them).
- A run's active time (`active_ms`) is now the union of the main session's turn intervals, so a turn that contains others is no longer counted twice (it exceeded wall clock in many runs).
- Skill attribution fixes (#2). A skill a subagent loads is no longer dropped by the `attributionSkill` the subagent inherited from its parent: the load wins, and the inherited value is only the spawn default. In the main session the fall-back to the outermost skill now ends at the next human prompt, unless the person started that skill with a slash command (`/ship-feature`): then it outlasts their answers until another skill command, and only the skills under it end; and `api_calls` and `tool_calls` get a `skill_inferred` flag for work whose skill was inferred rather than recorded.
- Plugin prefixes are dropped from skill names (`anthropic-skills:chrome-browser` is `chrome-browser`), so `skill_mentions.invoked` matches. Skills whose text follows the Skill call without a base directory (such as `artifact-design`) now produce a `skill_loads` row and so have versions.
- `agent_failed` incidents are credited to the skill the agent was running last, not the alphabetically first. `v_skill_version_stats` splits a run between the versions it used instead of giving all of it to the last. A session that used both versions of a skill is left out of both arms of that comparison.
- New-style forks (`fork-context-ref`) no longer double-count the parent's spawning call, lose its final token usage, or become their own parent.
- Harness output (`<local-command-stdout>`, `<bash-input>`, `<bash-stdout>`, compaction summaries) and housekeeping commands (`/clear`, `/compact`, `/model`...) no longer count as human prompts; a typed slash command such as `/ship-feature` still does; prompts with images do. A compaction summary that quotes "[Request interrupted" no longer creates an `interrupt` event.
- A run whose archive is older than its source stays `open` instead of becoming `complete` through idleness, until it is archived again.
- Sessions that share the first 8 characters of their id keep their full id in the explorer instead of merging.
- Incident detectors, fewer false positives (#7). `test_edit_after_failure` needs a failing test run before it and ignores a `Write` that creates a new file. `repeated_call` needs the same output each time and all calls within `repeat_window_s` (600). `idle_loop` counts consecutive idle calls only. `error_streak` no longer includes permission denials. Idle detection splits on pipes, and a poll loop is idle only when nothing but reads follows it. `FAIL` in test output matches upper case only ("failed to parse" is not a test failure). Roles ignore `:` `;` `,` `.` so "Scan A: versions" and "Scan A versions" are one role. Permission denials no longer count as tool errors in the views.
- Incident ids are built from the tool call that anchors the incident, so turning on `privacy.redact` or re-ingesting no longer orphans labels (labels made before this change match no incident and need redoing). `runlens check` warns about labels that match no incident.
- Cost split across skills and agents no longer shifts cost to the main session. The transcript holds most messages with the output count from the start of the stream, so the missing output was spread evenly. Each token category (input, cache read, cache write, output) now gets its own gap against cost-state, and the output gap goes only to calls with no `stop_reason`, in proportion to the text, thinking and tool input they carry (#3).
- A resumed session has one `cost-state` per process, each covering only its own process. They are added up, and calls from before the first one keep their list price. The run is marked `cost_estimated`, and `runlens check` notes how much was estimated (#3).
- Web searches count at $10 per 1,000 (`api_calls.web_searches`). The 1.1x US inference geo applies only to Claude 4.6 and later. Bedrock (`anthropic.claude-...-v1:0`) and Vertex (`claude-...@date`) model ids find their price. A change to the built-in price table re-ingests every run (#3).
- Token columns from the transcript (`v_skill`, `v_model`, `agents.*_tokens`, the report and dashboard) are labelled as undercounts of output.
- Work in the main session after a skill ends goes back to the skill the user invoked, not to an earlier sibling skill. In an `/ship-feature` run, plan, build, review and prove orchestration were credited to the grilling skill (#1). Skills the main session invokes now run one after another under the outermost one; subagents are unchanged.
- Groups found automatically are steadier (#10). A set needs two shared edits, not one. A set inside a configured `[[group]]`, or nearly the same as one, is left out instead of being scored twice. A group member a run did not use keeps its nearest used version, so it no longer splits the group into extra versions.

### Benchmark
- The cost measure leaves out runs without `cost-state` (list price on a partial transcript is about 30% too cheap, which made newer versions look cheaper) and invocations with a call that has no price (it counted as $0). Time keeps them. A comparison says how many runs were left out (#3).

### Method
- Confounders (#8): a change of model within a family (haiku-4-5 → haiku-5-5) and of Claude Code patch release (2.1.283 → 2.1.296) now confounds a verdict. Models are compared by full id, and `[method] cc_version` defaults to `"patch"` (set `"minor"` for the old behaviour).
- The confounder check no longer depends on `PYTHONHASHSEED`: sessions are sorted, ties are broken by name, and another skill's versions are compared as distributions, not by their most common value.
- The mix-shift threshold is 0.3 or 1.5 / √runs, whichever is higher, so two projects at 50/50 no longer trip it by chance with few runs.
- The model mix counts the main agent only; a skill that delegates to a cheaper model in subagents is no longer confounded by it.
- The dashboard no longer labels a pair better or worse when filtering produced a pair the model never checked for confounders.
- Proposals: `verify` now says `inconclusive` when the interval holds no change, and `refuted` only when the measure moved the other way beyond noise. "No clear change" is no longer reported as "no different" or as a refutation (#9).
- A version is a hash over a contiguous stretch of runs: reverting a skill (A, B, A) gives three versions and the current one is the newest (#9).
- New verdict `not scored` (enough runs, but every weight is 0) instead of `not enough runs` (#9).
- A NaN in a measure no longer counts as "2x better" in Python (JS and Python agree: the measure is skipped). In bootstrap draws a measure without data counts as no change instead of renormalising the weights (#9).
- 10,000 bootstrap resamples by default (was 4000), against Monte Carlo error at the ends of the interval (#9) The dashboard's own recompute stays at 4,000 at most, so changing a setting does not freeze the page.
- Each unit gets a Benjamini-Hochberg q over the units compared (`p_adjusted` in `score --json`); the dashboard flags a `better` or `worse` it does not support. Per-measure intervals are marked exploratory. "Above/below its typical run" is shown as a description, not a verdict (#9).
- README "The method" now states the limits: low power, peeking and multiplicity (#9).
- The database queries behind the model have an explicit `ORDER BY` (#9).

### Dashboard
- The bench time measure is named "Agent time per invocation" and its description says what it is: model-turn gaps summed over all agents (parallel agents add up, waits for subagents or the user are included, each gap capped), not wall-clock time.
- Clearer structure, nothing removed. Each page opens with its answer in plain words (for example "review-pr got better. 1 can't be judged because something else changed at the same time"), then at most four key numbers (the rest on one quiet line), then charts grouped under section headings, then the detail tables.
- Every chart card reads the same way: the question it answers, a one-line takeaway from the data, the chart, and a closed "How to read this" that holds the encodings, method notes and caveats that used to sit under every chart. Table, CSV, SVG and PNG moved into one "⋯" menu per card.
- The filter bar is one line until opened: a "Filters" button, a removable chip per active filter, and the count of runs left.
- Charts that were hard to read at first glance: the score range chart says "100 = usual level" and "◀ worse · better ▶" and names each symbol in words; version timelines show each skill's latest verdict next to its name and explain the line, band and dashed line; the forest plot reads "21% better" instead of "×1.21"; the run timeline names skills on their bars; heatmaps say which axis is "from" and which is "to"; the hand-off flow keeps its colour key under "How to read this", since every block is labelled.
- Glossary words (usual level, confounded, range, Pareto frontier, Wilson interval) explain themselves on hover, tap or keyboard focus. Versions made of several skill texts show each skill's name next to its hash.
- One skill's page shows all versions and the current one side by side in one profile table instead of ten cards; long lists of confounders fold away. Wide tables keep their rarer columns behind "More columns" (`cols=1` in the link).
- Dashboard wording no longer ranks skills or claims more than the data shows (#12). The cost chart is drawn once per outcome definition, with a takeaway that names no winner; the outcome and diagnostics takeaways drop their "most often" and "hits the most" lines; the measures heatmap is sorted by name. An outcome that is a PR opened is called the PR-opened rate, not the first-pass rate. Measure cells show the ratio to the reference (`×0.66`) instead of a signed percentage, a rate shows its value against the reference, and a ratio clipped at the cap is marked (`≥ ×2`). "Clearly above its usual level" is judged on the rounded range that is shown and never said of a confounded version.
- A clearer type scale (page 26, section 18, card 15, body 14, caption 12.5 px), an 8-point spacing scale, lighter card borders, and nested tabs drawn as pills so the two levels read apart.
- Data fixes (#11): a score against another version (`prev`, `first`, `ver:vN`) now counts both versions the same way, so a version against itself scores 100. The "Pull requests" count is the real number (a run lists at most five links). The Runs page cost, the calendar's spend and the spend-per-day charts follow the model, effort and date filters (a date range now cuts spend by the day of each call). "Cost by token type" includes runs with no `model_usage` and follows the effort filter. The two "problems per 100 tool calls" are named "Scored problems" and "All problems". The cost-of-each-run chart says "log scale" only when it is one, the heatmap's weight heads show the default weights, and a role's "few runs" mark counts sessions. Problem rates on the Diagnostics page are indexed once instead of re-filtered per cell.

### Privacy
- Redaction now runs before text is cut to its stored length, so a private key cut by the 2000- or 4000-character limit is no longer stored in clear; a private-key block with no `END` line is masked to the end of the text. `aws_secret_access_key = ...` is masked (keywords after `_` now match). Skill texts are redacted too.
- `export-eval` masks the task prompt and `--history` transcript when `redact = true`.
- The README lists which columns redaction covers (not the working directory, branch or PR links).
- The run page links a PR only when its URL starts with `https://`.

### Retro skill
- `/runlens-retro` is rewritten to shape the result rather than script the steps. It opens with what a retro is for, a Done when and acceptance criteria for the report, and the three lines it must not cross, each with its reason (wrong data stops it, it proposes but does not apply, labelling needs consent). The fixed step order, the checklist and the numeric quotas are gone. It knows how earlier proposals did before suggesting new edits, does not repeat an open proposal, says what it left out, and keeps a run with nothing new short. Consent to labelling can be given up front with the `label` argument.
- `runlens incidents` shows each incident's latest label (human before LLM), with the quoted instruction and skill hash in `--json`/`--csv`, and `runlens versions --json` gives `skill_dirs`, so the retro no longer writes SQL against internal tables to find them.
- `runlens check` warns when the installed `/runlens-retro` differs from the one this runlens ships (`runlens install` copies it once, so it fell behind silently).
- Five eval scenarios were added (a refuted edit behind new failures, an open proposal that must not be repeated, several skills at once, labelling with and without consent). Their assertions check what the report says, not which commands ran.
- `/runlens-retro` stops only on a FAIL about counts or ingest. An unpriced model, an old parser version, a cost-state mismatch or an orphan subagent now give a warning and the fix (`[prices]`, `runlens refresh`) and the retro goes on.
- `/runlens-retro` runs `runlens classify --dry-run` first and asks before it spends `claude -p` calls on the sample.
- Its description no longer says Claude uses it automatically: it is `disable-model-invocation`, so you run it yourself.
- The eval fixtures use the real `runlens check` line format, a skill that only loads in subagents now has its own score, and two cases were added (unpriced model, `verify` confirmed and refuted). `tests/test_retro_fixtures.py` checks every fixture against the CLI output on the demo history.

### export-eval
- A case with no grader that checks the failure is skipped and listed as skipped, instead of exported with only `skill-fired` (repeated calls and permission denials whose failing call is missing from the store). `tool_used` with `max` is never written without `input_match`, which would have meant "never use this tool". The skill-creator `evals.json` no longer carries the undocumented `name` field. The export README now says the one-arm default needs a path target and that `context.scaffold_script` runs only with `--scaffold` (#15).

### Fixed
- A drain now re-ingests runs last parsed by an older parser, so a parser bump no longer leaves the dashboard on old numbers until a manual `runlens ingest` (#5).
- `CLAUDE_CONFIG_DIR` is honoured for settings, skills and the transcripts folder, and the hook passes its `transcript_path` to the drain, so sessions outside `~/.claude/projects` are no longer dropped as "not selected" (#5).
- `runlens refresh` takes the drain lock while it archives and ingests; the drain looks at the queue once more after releasing the lock; the log no longer says "archived and ingested" for a run whose ingest failed (#5).
- The Skills page's outcome/cost scatter keeps a rate axis inside 0–100 % (a single point drew -400 % to 400 %), and a chart with one skill no longer draws or explains a Pareto frontier: it says where that skill sits instead. Its legend lists only the skills in that chart (#21).
- A `config.toml` that does not load no longer makes the SessionEnd hook lose the session: the hook queues it first and writes the config error to `hooks.log`, and the detached drain logs its config error there too instead of to nowhere. `runlens refresh` drains the queue once the config is fixed (#33).
- `ingest --skill` and `--project` (and the ingest step of `refresh`) are applied; they were accepted and ignored (#33).
- Pruned runs stay pruned. `prune` records what it deleted, so `refresh` no longer copies a run back from `~/.claude/projects`, `ingest` no longer reloads one pruned with `--keep-archive`, and `check` no longer asks for either. Naming a run with `--session` in `archive`, `ingest` or `refresh` brings it back (#33).
- `runlens check` warns about runs in the database whose archive is gone, and about a `--session` that matches no run (it said "all checks passed"). On an empty home it says there is nothing to check yet (#33).
- `runlens sql` can no longer write files: `COPY ... TO`, `ATTACH` and `INSTALL` are refused (external access is turned off and locked for the query). `sql ""` gives a one-line error instead of a traceback, and a SQL error no longer repeats its label ("Parser error: syntax error at ..."). The "database in use" message leaves out the Windows error text DuckDB mis-decodes (#33).
- Config typos that were accepted silently are refused: an `[outcome] marker` that names no `[[marker]]` (it was accepted when the config had no markers at all, and skills were scored without an outcome), and a `--config` file that does not exist (it fell back to the defaults). `[outcome]`, `[[group]]`, `[weights]` and `[method]` values are checked when the config loads, not first at `score` (#33).
- The drain's log says why a queued session was skipped: pruned, no transcript, or not selected by `[select]` (#33).
- `score` text: the outcome and cost/inv columns are the current version's own (they pooled every version, so a version with 1 run showed the skill's "88 % of 17"), a `current runs` column and a legend say which numbers are whose, a difference without an interval says so, a unit with one version says so instead of `-`, and an empty result says what to do. `score --json` adds `current_runs`, `current_outcome` and `current_typical`. `versions` prints "confounded by" only under a `confounded` verdict, as `score` does, and `versions <group name>` without `group:` suggests the unit id (#33).
- `verify` is harder to misread. Its table shows `predicted` (the hypothesis' direction) next to `moved` (which way the measure went, higher or lower), instead of `observed`, which is better or worse on the quality scale. `verify --json` keeps `observed` and adds `moved` and `difference.scale`, which says whether `ci95` is a score (100 = no change) or a clipped quality ratio (1 = no change). `proposals add` warns about `--evidence` ids that match no incident and a `--base-version` that matches no recorded version (#33).
- Messages that hid the cause (#33): `report --session <unknown>` says no run matches instead of "run refresh first"; `--since` and `--before` name the flag when the date is not ISO; `dashboard --out <folder>` and `report --out <folder>` say the path is a folder instead of a raw `WinError 5`; `show <bad id>` writes its error to stderr; `archive` labels a run it copies for the first time `new`, not `updated`; a second `install` on the same day says the backup is the one made earlier that day. A `settings.json` whose `SessionEnd` is not a list, or whose `hooks` is not an object, gives a one-line message in `install` and `uninstall` instead of a traceback. `summary` prints every row (DuckDB's printer showed 20 when piped), and `summary`, `dashboard` and `score` on an empty database say to run `runlens refresh`.

### Config, packaging and CI
- `config.toml` is checked for typos and wrong types: an unknown section or key (`[runs] idle_hourz`, `[selectt]`) and a value of the wrong type (`[method] min_runs = "x"`, `resamples = 4000.5`) stop the command with a one-line error that names the key (#17).
- `uv run pytest` works: pytest is a dev dependency group. pyproject lists the supported Python versions (3.11 to 3.14) and explains why `pytz` is a dependency although it is never imported (DuckDB needs it for TIMESTAMPTZ).
- CI runs `install` and `uninstall` end to end from the built wheel, against a temporary `RUNLENS_HOME`, `CLAUDE_SETTINGS` and home directory, and fails when the dashboard tests are skipped on any OS, not only Linux.
- CI tests Python 3.11 and 3.14 on Linux and 3.14 on Windows and macOS: four jobs instead of six, with one Windows job instead of two.

### Docs
- Fixed false or misleading claims in the README and changelog: skills loaded only in subagents, which `check` lines are `WARN`, what comes from `cost-state`, the measures sentence, the demo commands, the unverifiable token-coverage figure, the Evals link title, the CI browser platform and the pinned ruff version (#16).

## 0.2.0 - 2026-10-13

An audit of the whole tool found that the numbers it showed could not be trusted: missing tokens, double counts, runs frozen half-way, wrong prices, and verdicts that ranked task types rather than skill versions. This release fixes the data first, then the method, then the outputs.

**Upgrading.** Run `runlens install` (new hook and retro skill), then `runlens refresh`: every run is parsed again by the new parser, once. If you used `[[evidence]]` with 0.1, run `runlens migrate-evidence` (a dry run) and then with `--yes` to replace the per-run copies with deduplicated blobs; it handles paths over 260 characters on Windows. LLM labels on `error_streak`, `repeated_call` and `idle_loop` incidents are orphaned once, because those incident ids are now stable.

### Data you can trust
- Token usage per API message comes from its complete record, not the first streamed part, and each compaction is counted once (with its trigger and size).
- Token totals come from Claude Code's own cost-state (new `model_usage` table): in the runs we measured, transcripts held only about 10–24% of the output tokens (see `v_token_coverage`).
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
- A skill that a subagent loads for itself gets its own unit and versions; only the subagent's work before the load is credited to the skill that spawned it. The agent diagnostics list such skills under "Skills inside".
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
- `config.example.toml` documents every option with its default.

### Engineering
- CI runs on Linux, Windows and macOS with Python 3.11 and 3.14, lints with ruff, checks the dashboard script, renders every page in headless Chrome (Linux only), and smoke-tests the built wheel. Actions are pinned by commit SHA with read-only permissions.
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
