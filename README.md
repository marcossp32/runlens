# runlens

**Find what fails in your real Claude Code runs, per skill and per version, and check whether your last edit helped.**

runlens archives every Claude Code session (and the subagents it spawned) into a local DuckDB database. It credits cost, time, tool errors, incidents and your interruptions to the skill that was active, keeps every version of each skill's text, and compares each version only with the same skill's previous version. Everything stays on your machine; the dashboard is one static HTML file.

<!-- TODO(images): the orchestrator wires the final screenshots. Intended files in docs/images/:
     overview-light.jpg, overview-dark.jpg (the skills overview), skill-page.jpg (one skill: versions and diff),
     compare.jpg (two versions: verdict, per-measure effects, confounders), diagnostics.jpg, data-health.jpg,
     how-it-works.jpg. All from demo data (scripts/make_demo.py). -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/overview-dark.jpg">
    <img alt="The runlens dashboard: every skill's current version against its previous one" src="docs/images/overview-light.jpg" width="900">
  </picture>
</p>
<p align="center"><sub>Every screenshot here comes from invented demo data (see <a href="#screenshots">Screenshots</a>).</sub></p>

**What it is good at, and what it is not.** runlens is the production side of improving a skill: it finds *where* a flow struggles in the runs you actually did, with the incidents and traces behind it, and tells you whether a new version's runs look better, worse or no different. It is observational, so it cannot prove that an edit *caused* a change; your tasks differ from run to run. For that, it exports the real failures as eval cases (`runlens export-eval`) that you re-run with a fixed benchmark: [`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals) or [skill-creator](https://code.claude.com/docs/en/skills).

**Contents:** [Quick start](#quick-start) · [Install](#install) · [Improve a skill](#improve-a-skill-step-by-step) · [The method](#the-method) · [Dashboard](#the-dashboard) · [CLI](#cli-reference) · [Config](#config-reference) · [Data](#data-reference) · [Privacy](#privacy-and-retention) · [Troubleshooting](#troubleshooting) · [Uninstall](#uninstall) · [Development](#development)

## Quick start

```bash
uv tool install git+https://github.com/marcossp32/runlens.git
runlens install      # the SessionEnd hook, the /runlens-retro skill and a starter config
runlens refresh      # archive and load the runs you already have
runlens check        # the data is complete and the parser kept up
runlens score        # each skill's current version against its previous one
runlens dashboard    # prints the path of dashboard.html: open it in a browser
```

A **run** is one Claude Code session plus every subagent it spawned. runlens knows nothing about any particular flow: skills, agent types and roles are read from the transcripts, and everything flow-specific (which sessions count, which output lines are signals, what a success looks like) lives in `~/.runlens/config.toml`.

## Install

| Requirement | Why |
|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Installs runlens and fetches Python 3.11+ if you don't have it |
| [Claude Code](https://code.claude.com/docs/en/setup) | runlens reads the transcripts it writes to `~/.claude/projects` |
| `claude` on the PATH | Only for `runlens classify` (it runs `claude -p` with your login, no API key) |
| git | Only if an `[[evidence]]` rule uses `{git_dir}` |

Works on Windows, macOS and Linux. Do this on every machine where you run Claude Code.

1. **Install the tool:** `uv tool install git+https://github.com/marcossp32/runlens.git`. If `runlens` is not found afterwards, run `uv tool update-shell` and open a new terminal.
2. **Hook it into Claude Code:** `runlens install`. Safe to run again. It:
   - adds a `SessionEnd` hook to `~/.claude/settings.json` (backed up first to `settings.json.runlens-backup-<date>`);
   - copies the `/runlens-retro` skill into `~/.claude/skills`;
   - writes `~/.runlens/config.toml` from [`config.example.toml`](runlens/config.example.toml) if there is none.
3. **Say which runs to record** under `[select]` in `~/.runlens/config.toml` (default: every session). For mstack's `/m-feature` flow, start from [`examples/m-feature.toml`](examples/m-feature.toml).
4. **Load what you already have:** `runlens refresh`, then `runlens check`.

**How the hook works.** When a session ends, the hook only writes `~/.runlens/pending/<session_id>`, logs one line to `~/.runlens/hooks.log`, starts a detached `runlens drain` and returns, well under a second. It is synchronous with a 10 s timeout, because Claude Code can kill an async hook before it has done anything when a `claude -p` session tears down. The detached drain archives and ingests the queued runs and rebuilds the dashboard. If a drain never ran (the machine slept, the process was killed), `runlens refresh` processes the queue first.

**Keep Claude Code's transcripts longer (optional).** Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default). The runlens archive keeps its own copy, so this only matters for `/resume` or for `runlens refresh` to reach further back: set `{ "cleanupPeriodDays": 90 }` in `~/.claude/settings.json`.

**Good to know.**
- Each machine records only its own sessions. To bring another machine's history over, copy its `~/.runlens/archive/` and run `runlens ingest`.
- The hook calls the tool's own Python by absolute path. `uv tool upgrade` keeps that path; after `uv tool uninstall` and a fresh install, run `runlens install` again.

**Update.**

```bash
uv tool upgrade runlens
runlens install           # refreshes the /runlens-retro skill
runlens refresh           # runs parsed by an older parser are parsed again automatically
runlens migrate-evidence  # once, if you used [[evidence]] with runlens 0.1 (dry run; add --yes)
```

## Improve a skill, step by step

The loop is *find a weak spot → trace it to the skill text → edit → verify*. `/runlens-retro` in Claude Code runs steps 1 to 4 for you and records its proposals; the commands below are what it runs.

1. **Refresh and check.** `runlens refresh`, then `runlens check`. A `FAIL` line means the numbers are wrong (stop and fix it first); `WARN` lines name gaps such as runs still open.
2. **Find where to look.** `runlens score` lists every skill's current version against its previous one. `runlens versions <skill>` shows all versions of one skill: runs, invocations, outcome, the verdict against the version before, its confounders, and the diff. Look first at versions whose verdict is `worse`, then at skills with a low or falling outcome, then at the ones with the most incidents.
3. **Read the evidence.** `runlens incidents --skill <skill>` lists what went wrong; `runlens show <id>` prints the timeline around one incident. `runlens classify --skill <skill>` labels incidents with a failure taxonomy (the judge sees the skill text that was active, so it can quote the instruction at fault). A failure mode needs two or more incidents; one is an anecdote.
4. **Record a proposal before editing.** `runlens proposals add --skill <skill> --hypothesis "..." --measure error_rate --direction lower --evidence <ids>` stores the hypothesis against the version you are about to edit.
5. **Edit the skill.** The next run that loads it records a new version (a hash of its text).
6. **Verify.** Two ways, best used together:
   - **Fast and causal:** `runlens export-eval --incident <id> ...` writes the real failures as eval cases. Run them with `claude plugin eval` (the export's README has the exact command) or merge them into the skill's skill-creator evals, once with the old text and once with the new. Same tasks, repeated runs: this is what can show the edit itself helped.
   - **Slow and in production:** after the new version has at least 5 finished runs, `runlens verify` compares them with the base version's runs and marks the proposal `confirmed`, `refuted`, `not enough runs` or `confounded`.

**How many runs you need.** A verdict needs at least `[method] min_runs` (default 5) finished, non-stub runs on *each* side. Runs are resampled by session, so five sessions are five data points however many times the skill was invoked in them. With five runs a side, only large changes clear the interval; a 10–20% change usually needs many more runs than you will have. That is why the eval benchmark is the faster check and the production verdict is the confirmation.

**Editing several skills at once makes verdicts "confounded".** If you edit `plan` and `build` together, every run of the new `build` also has the new `plan`, so `build`'s verdict cannot be put down to its own text: runlens says `confounded` and names `plan also changed (a1b2 → c3d4)`. Either edit one skill at a time, or define a `[[group]]` with the skills you edit together. A group's version changes when any member's text changes, and its verdict is not confounded by its own members, so the group is the level at which a batch edit can be judged.

## The method

The question runlens answers is *did a change to this skill make its runs better or worse?* So every comparison stays inside one skill (or one group).

- **Population.** Only finished runs count (`status = 'complete'`: the session ended, or no new records for `[runs] idle_hours`), and stub runs (fewer than 3 model turns or under $0.02) are left out.
- **Measures.** Each is a ratio of sums over runs, so a big run weighs as much as its size. Cost and time are geometric means per invocation (a skill load, a subagent spawn or a group run), because a tenth of the runs carry most of the spend. Rates are events over opportunities.

  | Measure | Weight | What it is |
  |---|---|---|
  | `outcome` | 3 | The result the flow is meant to reach, from `[outcome]`: a check's first-pass rate, or a PR opened. Only with an outcome configured |
  | `cost` | 2 | Model spend per invocation |
  | `seconds` | 1 | Working time per invocation (each model turn to the same agent's next, capped at 10 minutes) |
  | `error_rate` | 2 | Failing tool calls over tool calls. Calls a permission rule denied are not errors |
  | `incidents` | 2 | Problems per 100 tool calls. Not counted: policy denials, failed checks, idle loops and error streaks (other measures count them) and incidents labelled expected behaviour |
  | `interventions` | 1 | Human prompts per invocation (skills and groups only). Set it to 0 for skills meant to ask |
  | `idle_rate` | 1 | Tool calls that only wait or print |
  | `api_error_rate` | 1 | Model turns with an API error. Quota and rate limits are not errors |
  | `bad_markers` | 1 | Config markers with a bad value, per invocation (a marker used as the outcome counts there instead) |

  Change weights under `[weights]`, globally or per skill or group.
- **Score.** 100 is the skill's own typical run. For each measure, ℓ = ln(reference / value), clipped to a factor of 2 either way; the score is 100 × exp(Σ w·ℓ / Σ w). A version's value is pulled slightly toward its own skill's value (2 pseudo-runs), never toward other skills. Scores of different skills are shown side by side but never ranked: research is cheaper than building, and that says nothing about either skill.
- **Verdict.** Version B against version A comes from a bootstrap of the *difference*: each side's runs are resampled by session (4000 times), the weighted difference is recomputed each time, and its central 95% interval (expanded percentile, for small samples) decides: entirely above zero is `better`, entirely below is `worse`, otherwise `no clear change`. Fewer than 5 runs on a side is `not enough runs`, with no interval.
- **Confounders.** When something else changed between the two sides, the verdict is `confounded` and names it: another skill's text changed in the same runs, the model or effort mix shifted, the Claude Code version changed, or the project mix changed. The raw direction is kept, but the change cannot be put down to the skill text.
- **Outcome.** Without an `[outcome]`, the score measures cost and friction only, and a cheaper skill that does less would look better. Configure one: a marker's first-pass rate (a chain of checks counts as one attempt, a success at the first check is a first-pass success) or `pr = "opened"`. The dashboard also shows cost per success.

**What the score does not tell you.**
- Whether the work was right, beyond the outcome you configured. Read the traces before acting on a drop.
- Anything about one skill compared with another.
- That an edit *caused* a change: tasks differ between runs. Use the eval export for that.
- Anything about a skill that only runs inside subagents: Claude Code credits a subagent's turns to the skill that spawned it, so such a skill has no unit or versions of its own (it is listed under the dashboard's agent diagnostics, "Skills inside").

## The dashboard

`runlens dashboard` writes `~/.runlens/dashboard.html` (`--out` to choose the path): one static page with the data embedded. It opens offline from any folder, needs no server and makes no network requests. The hook rebuilds it after it ingests runs unless `[dashboard] auto = false`; after a manual `runlens refresh`, run `runlens dashboard`.

<!-- TODO(web): page names may still change; descriptions are kept generic until the dashboard settles.
     Confirm the data-health page, the filter bar and the run explorer once the dashboard work lands. -->

| Page | It answers |
|---|---|
| **Overview** of skills, agent roles and groups | How is each skill doing now, and did its latest version change anything? Each skill's current version against its previous one, with the verdict and run counts, side by side and not ranked |
| **One skill, role or group** | Why? Its versions over time with their diffs, each measure against the skill's typical run, and its runs one by one |
| **Compare** | Is version B really different from A? The verdict, each measure's effect with its interval, the outcome change and the confounders |
| **Diagnostics** | What else happened? Runs, problems and tool errors, tools, models and effort, token and cache cost, subagents, skill hand-offs, markers and labels |
| **Data health** | Can you trust the numbers? Open and stub runs, failed ingests, unpriced models, token coverage, parser version and last refresh |
| **How it works** | The method, with a worked example on one of your own skills |

<p align="center"><img alt="One skill: its versions with the score of each and the diff from the one before" src="docs/images/skill-page.jpg" width="760"></p>
<p align="center"><img alt="Comparing two versions: verdict, per-measure effects and confounders" src="docs/images/compare.jpg" width="760"></p>

The page state is in the URL, so a link reproduces a view; `[[dashboard.view]]` in the config adds named views to the page. **The dashboard contains transcript text** (each skill version's text, run arguments and task titles): keep it on your machine and check it before you share it.

## CLI reference

Every command accepts `--config <file>` before the command name (default `~/.runlens/config.toml`). Errors a user can fix (bad config, bad SQL, database busy) print one line and exit 1.

**Data**

| Command | What it does | Flags |
|---|---|---|
| `archive` | Copy selected runs from `~/.claude/projects` into the archive. A run whose source changed is copied again | `--since DATE`, `--skill NAME`, `--project TEXT`, `--session ID` (the last three repeatable), `--quiet` |
| `ingest` | Load the archive into DuckDB. Incremental: unchanged runs are skipped (see [Data](#data-reference)) | as `archive`, plus `--force` (parse every run again) |
| `refresh` | Drain the hook's queue, then `archive` + `ingest` | as `ingest` |
| `check` | Compare the database with the archive and the archive with `~/.claude/projects`; exits 1 on any `FAIL` or `WARN` | `--session ID` (repeatable), `--no-sources` (skip the comparison with `~/.claude/projects`) |
| `prune` | Delete runs from the database and the archive. Lists them unless `--yes` | `--before DATE`, `--session ID` (or 8-char prefix, repeatable), `--keep-archive` (database rows only), `--yes` |
| `migrate-evidence` | Convert evidence archived by runlens 0.1 into deduplicated blobs and delete the old folders. Dry run unless `--yes` | `--yes`, `--keep-excluded` (also keep browser profiles, databases, node_modules) |
| `sql "<query>"` | Any read-only query over the tables and views | `--json`, `--csv` |

**Method**

| Command | What it does | Flags |
|---|---|---|
| `score` | Each unit's current version against its previous one: runs, invocations, verdict, difference, outcome, typical cost | `--kind skill\|agent\|group` (default `skill`), `--json` |
| `versions <skill>` | Every version of a skill (or a unit id such as `group:my-flow`): runs, invocations, score, verdict, confounders, outcome, cost per success | `--json` |
| `proposals add` | Record a proposed edit; prints its id (`p-0001`, ...) | `--skill` (required), `--hypothesis` (required), `--measure` (required: `score` or a measure key), `--direction lower\|higher` (required), `--evidence ID ...`, `--base-version HASH` (default: the current version) |
| `proposals list` | List recorded proposals | `--json` |
| `verify [<id>]` | Check one or every proposal against the runs since: `confirmed`, `refuted`, `not enough runs`, `confounded` | `--json` |

**Diagnosis**

| Command | What it does | Flags |
|---|---|---|
| `incidents` | List incidents. Permission denials caused by your permission rules are hidden unless `--all` | `--type`, `--skill`, `--limit N` (50), `--all`, `--json`, `--csv` |
| `show <id>` | The timeline around an incident or tool call: what the agent was asked, said and did | `--steps N` (12 before), `--after N` (4) |
| `classify` | Label incidents with the failure taxonomy through `claude -p`. Prints its cost | `--type` (repeatable), `--skill` (repeatable), `--limit N` (20), `--model ALIAS`, `--workers N` (4), `--relabel`, `--sample stratified\|priority`, `--seed N`, `--dry-run` (print one prompt, no model call) |
| `labels export\|import <csv>` | Human review of the labels | export: `--limit N` (stratified sample), `--seed N`, `--blind` (leave the LLM labels out) |
| `agreement` | LLM labels against human ones: Cohen's kappa, TPR/TNR per category, which categories are verified | `--json` |
| `export-eval` | Turn real incidents into eval cases for `claude plugin eval` and skill-creator, with a README saying what is and is not reconstructed | `--incident`, `--skill`, `--label`, `--type` (all repeatable), `--format plugin-eval\|skill-creator\|both`, `--out DIR`, `--limit N` (10), `--history` (resume the main transcript just before the failing step) |
| `summary` | One table per run and one per skill, in the terminal | |
| `report` | A self-contained HTML diagnosis report | `--out FILE`, `--session ID` (repeatable) |
| `dashboard` | The benchmark dashboard | `--out FILE` |

**Setup:** `install [--no-skill]`, `uninstall` (removes only the runlens hook), `hook` (the hook's entry point, reads the hook JSON on stdin).

**Environment:** `RUNLENS_HOME` (default `~/.runlens`), `CLAUDE_PROJECTS` (default `~/.claude/projects`), `CLAUDE_SETTINGS` (default `~/.claude/settings.json`).

## Config reference

Every section is optional. [`config.example.toml`](runlens/config.example.toml) documents every key with its default; [`examples/m-feature.toml`](examples/m-feature.toml) is a real config for [mstack](https://github.com/marcossp32/mstack)'s `/m-feature` flow. A value runlens cannot use stops the command with a one-line error naming the key.

| Section | Keys (default) | What it sets |
|---|---|---|
| `[select]` | `since` (""), `skills` ([]), `projects` ([]) | Which sessions are runs. CLI filters override it |
| `[runs]` | `idle_hours` (12), `stub_api_calls` (3), `stub_cost_usd` (0.02) | When a run without a closing record counts as finished, and when a run is too small to benchmark |
| `[privacy]` | `redact` (false), `patterns` ([]) | Mask secrets, tokens and e-mails before text reaches DuckDB; extra regexes |
| `[analysis]` | `repeat_min` (3), `idle_min` (3), `error_streak_min` (2), `context_steps` (8), `test_path`, `idle_parts` | Thresholds and patterns of the generic incident detectors |
| `[classify]` | `model` ("sonnet"), `before` (12), `after` (4), `skill_chars` (14000), `timeline_chars` (9000) | The judge's model and how much timeline and skill text it sees |
| `[[evidence]]` | `name`, `glob`, `scope` ("run"), `slack_minutes` (10), `max_mb` (200), `exclude` ([]) | Extra files to keep with each run. Placeholders `{cwd}`, `{git_dir}`, `{session_id}` |
| `[[marker]]` | `name`, `pattern`, `source` ("any"), `bad` ([]) | Output lines that are signals; a bad value becomes an incident |
| `[outcome]` / `[[outcome]]` | `marker` + `success` + `failure` (the marker's bad values), or `pr = "opened"`; `skills` ([] = all); `name` | What a successful run looks like |
| `[weights]`, `[weights.<skill or group>]` | measure = weight (see [the method](#the-method)) | Weight of each measure; 0 = shown, not scored |
| `[method]` | `min_runs` (5), `resamples` (4000), `confidence` (0.95), `cc_version` ("minor") | How verdicts are made |
| `[[group]]` | `name`, `members` (`"skill:<name>"` or `"agent:<type>"`) | Skills and agent types scored as one unit |
| `[prices]` | `"<model>" = [input, output, cache_read]` (USD per million tokens) | Prices for models missing from the built-in table |
| `[dashboard]`, `[[dashboard.view]]` | `auto` (true); a view's `name` and `hash` | Rebuild the dashboard after the hook ingests runs; named links into the page, offered as starting points |

To adapt the failure taxonomy, copy [`taxonomy.toml`](runlens/taxonomy.toml) to `~/.runlens/taxonomy.toml`.

## Data reference

Everything is in `~/.runlens/runlens.duckdb`; query it with `runlens sql`. The schema migrates itself when runlens is upgraded. `ingest` parses a run again when its archived transcript, the parser, or the config sections that shape its rows (`[[marker]]`, `[analysis]`, `[prices]`, `[runs]`, `[privacy]`) changed; anything else is skipped.

| Table | One row per |
|---|---|
| `runs` | run: repo, branch, Claude Code version, cost, active time, `status` (complete/open), `is_stub`, `pr_urls`, `unpriced_models` |
| `agents` | agent (`main` and each subagent): type, role, spawn prompt, parent, final status, tokens, peak context, effort, `stopped_by_user` |
| `api_calls` | API call: model, effort, skill, tokens, cost, API errors (`api_limit` marks quota and rate limits, which are not errors) |
| `tool_calls` | tool call: tool, skill, input, duration, error and class, exit code, denial and permission decision, patch size, idle wait |
| `texts` | the agent's visible text between tool calls |
| `events` | human prompts, interrupts, compactions, API errors and limits, re-injected skills |
| `markers` | matches of the `[[marker]]` patterns |
| `skill_loads` | each skill load, with the hash of its text (its version) and the arguments |
| `skill_texts` | each skill version's text, once: what version diffs compare |
| `skill_mentions` | a skill offered to an agent, and whether it was then loaded |
| `compactions` | each real compaction: trigger, tokens before and after |
| `model_usage` | Claude Code's own per-model token and cost totals for the run (from its cost-state) |
| `incidents` | moments worth reading, each with the timeline that led to it |
| `labels` | failure labels from the LLM and from humans; they survive re-ingest |
| `proposals` | proposed skill edits and their verification; they survive re-ingest |
| `ingest_state`, `ingest_errors`, `meta` | what was ingested by which parser, what failed, schema and parser version |

Views (in [`views.sql`](runlens/views.sql)): `v_runs`, `v_skill`, `v_role`, `v_model`, `v_tools`, `v_tool_errors`, `v_idle`, `v_markers`, `v_skill_flow`, `v_skill_versions`, `v_skill_version_stats`, `v_incident_summary`, `v_labels`, `v_label_summary`, `v_token_coverage`, `v_api_errors`, `v_skill_mentions`, `v_compactions`, `v_data_health`.

**How some numbers are read.**
- **Cost** comes from Claude Code's cost-state per model, split across that model's calls by list price. A run with no cost-state yet is estimated at list price (`cost_estimated`). A model with no known price gets no cost and is named by `runlens check`; add it under `[prices]`.
- **Tokens.** Transcripts hold only about 10–24% of the output tokens Claude Code counts, and most calls have no final usage record, so token totals come from `model_usage` (cost-state). Per-call output and thinking tokens are lower bounds.
- **Skill attribution.** A skill load pushes the skill onto its agent's stack, an explicit attribution wins, and the end of a nested skill pops back to the outer one. Fork agents' copied history is skipped, so nothing is counted twice.
- **Versions.** A version is a hash of the skill text as Claude Code injected it, without the arguments. Files a skill reads later (references, scripts) are not part of it.

## Privacy and retention

- **Everything is local.** The archive, database, dashboard and report live in `~/.runlens/`. Nothing is sent anywhere, except incident timelines and skill text to `claude -p` when you run `classify`.
- **Redaction.** `[privacy] redact = true` masks API keys and tokens (Anthropic, OpenAI, GitHub, GitLab, Slack, AWS, Google, Stripe, npm), private keys, JWTs, bearer tokens, passwords in URLs and assignments, and e-mail addresses in every stored text column; add your own regexes in `patterns`. Hashes are taken before masking, so counts do not change. The archived transcripts stay verbatim, because they are what runlens re-ingests from.
- **Retention.** `runlens prune --before 2026-01-01` (or `--session <id>`) lists the runs it would delete; add `--yes` to delete their database rows and archived files. `--keep-archive` deletes only the rows.
- **Evidence.** `[[evidence]]` files are stored once by content hash under `archive/_blobs`. By default only files modified during the run are kept, at most `max_mb` per run and rule, and browser profiles (cookies, saved passwords, local storage), databases, `node_modules`, `.git` objects and virtualenvs are never kept. Add your own `exclude` globs.

## Troubleshooting

| You see | Why, and what to do |
|---|---|
| `runlens check` prints `FAIL` | The parser fell behind the transcript format, an ingest failed, or evidence blobs are missing. Don't trust the numbers until it passes |
| `WARN ... open` or `queued by the hook` | A session is still running, or its drain has not run. `runlens refresh`; open runs are left out of verdicts until they finish (or go `idle_hours` without new records) |
| `WARN ... source changed since it was archived` | A session kept going after it was archived. `runlens refresh` copies and parses it again |
| `the database is in use by another runlens process` | DuckDB allows one writer at a time; a drain or another command holds it. Commands wait 30 s; try again a moment later |
| `no price for <model>` | Add the model under `[prices]`; its calls have no list-price cost until then |
| Token totals don't match the transcript | Expected: see **Tokens** in the [data reference](#data-reference). Use `model_usage` or `v_token_coverage` |
| A skill is missing from `score` | It may not match `[select]`, have no finished non-stub runs, or only run inside subagents |
| A verdict says `not enough runs` or `confounded` | See [how many runs you need](#improve-a-skill-step-by-step) and why batch edits are confounded |
| The dashboard is out of date | `runlens dashboard` rebuilds it. Hook and drain errors are in `~/.runlens/hooks.log` |
| Deleting `~/.runlens` fails on Windows | Archived paths can exceed 260 characters. Use the long-path form (see [Uninstall](#uninstall)) |

## Uninstall

```bash
runlens uninstall                    # removes only the runlens hook from ~/.claude/settings.json
uv tool uninstall runlens
rm -rf ~/.claude/skills/runlens-retro
rm -rf ~/.runlens                    # only if you also want to delete the recorded history
```

On Windows, archived paths can be longer than 260 characters, and a plain delete fails with "path too long" or "directory not empty". Use the long-path prefix:

```bat
rd /s /q "\\?\%USERPROFILE%\.runlens"
```

## Development

```bash
git clone https://github.com/marcossp32/runlens.git
cd runlens
uv sync                                       # .venv with the locked dependencies
uv run python -m unittest discover -s tests   # the test suite
uvx ruff check                                # lint
uv tool install -e .                          # a `runlens` command that runs this checkout
```

Dependencies are locked in `uv.lock`; after changing `pyproject.toml`, run `uv lock`. CI runs the suite on Linux, Windows and macOS with Python 3.11 and 3.14, lints with ruff, checks the dashboard script with `node --check`, renders every dashboard page in headless Chrome on Linux, and smoke-tests the built wheel. The browser tests look for Chrome, Chromium or Edge and are skipped without one; `RUNLENS_BROWSER` points them at a specific binary.

### Screenshots

The images in this README come from `scripts/make_demo.py`, which builds an invented history in a throwaway folder. It never reads your transcripts. To see the same data:

```bash
python scripts/make_demo.py demo-home
RUNLENS_HOME=demo-home runlens dashboard --out demo.html
```

## References

- Cemri et al., [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657) (MAST), NeurIPS 2025: the failure taxonomy seed.
- [SWE-PRM](https://arxiv.org/abs/2509.02360) and [ImpossibleBench](https://arxiv.org/abs/2510.20270): coding-agent failure modes and test tampering.
- [TRAIL](https://arxiv.org/abs/2505.08638): why trace judges must be validated.
- Hesterberg, [What Teachers Should Know About the Bootstrap](https://arxiv.org/abs/1411.5279): the expanded percentile interval for small samples.
- Hamel Husain and Shreya Shankar, [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/): error analysis, binary judges, judge alignment.
- Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
- Claude Code docs: [hooks](https://code.claude.com/docs/en/hooks), [plugin evals](https://code.claude.com/docs/en/plugin-evals), [skills](https://code.claude.com/docs/en/skills).

## License

[MIT](LICENSE)
