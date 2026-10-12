# runlens

A history of your Claude Code runs in DuckDB, to find where a skill flow struggles and to check whether a change to a skill helped.

A **run** is one Claude Code session plus every subagent it spawned. runlens knows nothing about any skill or flow: skills, agent types and roles are attributes read from the transcripts. Everything specific to a flow lives in `~/.runlens/config.toml`:
- which sessions count as runs;
- which output lines are signals;
- which files outside the transcript to keep.

## Requirements

| What | Why |
|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Installs runlens and the Python it runs on. You don't need Python installed yourself: uv fetches Python 3.11+ if it is missing |
| [Claude Code](https://code.claude.com/docs/en/setup) | runlens reads the transcripts Claude Code writes to `~/.claude/projects` |
| `claude` on the PATH | Only for `runlens classify`, which runs `claude -p` with your Claude Code login |
| git | Only if your config archives files with `{git_dir}` |

Works on Windows, macOS and Linux.

## Install

Do this on every machine where you run Claude Code.

**1. Install the tool.**

```bash
uv tool install git+https://github.com/marcossp32/runlens.git
```

This puts `runlens` in uv's tool directory, in its own environment. If `runlens` is not found afterwards, run `uv tool update-shell` and open a new terminal.

**2. Hook it into Claude Code.**

```bash
runlens install
```

This does three things, and is safe to run again:
- adds an async `SessionEnd` hook to `~/.claude/settings.json`, after backing the file up to `settings.json.runlens-backup-<time>`;
- copies the `/runlens-retro` skill into `~/.claude/skills`;
- writes `~/.runlens/config.toml` from [`config.example.toml`](runlens/config.example.toml) if there is none.

**3. Tell it which runs to record.**

Edit `[select]` in `~/.runlens/config.toml`. With the defaults, every session is recorded. For mstack's `/m-feature` flow, use the example config instead:

```bash
curl -o ~/.runlens/config.toml https://raw.githubusercontent.com/marcossp32/runlens/main/examples/m-feature.toml
```

**4. Load what you already have.**

```bash
runlens refresh
runlens check
```

From then on, the hook archives and ingests each run in the background when its session ends. Activity is logged to `~/.runlens/hooks.log`.

**5. Optional: keep Claude Code's own transcripts longer.**

Claude Code deletes transcripts after `cleanupPeriodDays`, 30 by default. The runlens archive keeps its own copy, so this only matters if you want older sessions in `/resume` or want `runlens refresh` to reach further back. Set it in `~/.claude/settings.json`:

```json
{ "cleanupPeriodDays": 90 }
```

### Good to know

- **Data stays on the machine.** The archive, the database and the report live in `~/.runlens/`, outside the repo. Each machine records only its own sessions. To bring another machine's history over, copy its `~/.runlens/archive/` and run `runlens ingest`.
- **The hook calls the tool's own Python** by absolute path. `uv tool upgrade` keeps that path. After `uv tool uninstall` followed by a fresh install, run `runlens install` again.
- **The dashboard contains transcript text.** It embeds the text of each skill version and the arguments of each run, so it is as private as the transcripts. Keep it on your machine, and check it before you share it.

### Update

```bash
uv tool upgrade runlens
runlens install     # refreshes the /runlens-retro skill
runlens refresh     # once: records the skill texts that versions are diffed against
```

### Uninstall

```bash
runlens uninstall                  # removes the hook from ~/.claude/settings.json
uv tool uninstall runlens
rm -rf ~/.claude/skills/runlens-retro
rm -rf ~/.runlens                  # only if you also want to delete the recorded history
```

## Use

```bash
runlens refresh      # archive + ingest the runs selected in config.toml
runlens check        # compare the database with the raw transcripts
runlens report       # write ~/.runlens/report.html
runlens dashboard    # write ~/.runlens/dashboard.html: scores, versions, profiles, comparisons
runlens show <id>    # the timeline around an incident or a tool call
```

| Command | What it does |
|---|---|
| `archive`, `ingest`, `refresh` | Copy runs out of `~/.claude/projects` and load them into DuckDB. Idempotent. Filters: `--since`, `--skill`, `--project`, `--session` |
| `check` | Compares counts with the raw transcripts, checks cost against Claude Code's `cost-state`, and finds subagents with no parent. The transcript format is internal to Claude Code and changes between versions; a `FAIL` means the parser fell behind |
| `summary` | One table per run and one per skill, in the terminal |
| `report` | A self-contained HTML report. `--session` limits it to some runs |
| `dashboard` | The benchmark dashboard, one static HTML file (see [Dashboard and benchmarks](#dashboard-and-benchmarks)). `--out` chooses the path. Rebuilt after each ingested run unless `[dashboard] auto = false` |
| `incidents` | List incidents (`--type`, `--skill`) |
| `show <id>` | What the agent was asked, said and did, in order, around an incident or a tool call |
| `classify` | Labels incidents with a failure taxonomy through `claude -p`. Uses your Claude Code login, no API key. About $0.02 per incident on Sonnet |
| `labels export/import <csv>` | Human review of the labels |
| `agreement` | LLM against human labels: Cohen's kappa, and TPR/TNR per category |
| `sql "<query>"` | Any query over the tables and views |

In Claude Code, `/runlens-retro` runs the whole retrospective:
1. refresh and check;
2. label;
3. read the traces behind the worst failure modes;
4. propose skill edits, each with its evidence and the metric that should move.

## What it records

| Table | One row per |
|---|---|
| `runs` | run: repo, branch, Claude Code version, cost, active time, human prompts |
| `agents` | agent (`main` and each subagent): type, role, spawn prompt, parent, final status, tokens, peak context, cost |
| `api_calls` | API call: model, effort, skill, tokens, cost |
| `tool_calls` | tool call: tool, skill, input, duration, error and its class, denial, idle wait, test file touched |
| `texts` | the agent's visible text between tool calls (the "why") |
| `events` | human prompts, interrupts, compactions, API errors, turn durations |
| `markers` | matches of the patterns in `config.toml` |
| `skill_loads` | each skill load, with a hash of the skill text (its version) and the invocation arguments |
| `skill_texts` | each skill version's text, once per skill and hash: what a diff between versions compares |
| `incidents` | moments worth reading, each with the timeline that led to it |
| `labels` | failure labels from the LLM and from humans; they survive re-ingest |

The `v_*` views in [`views.sql`](runlens/views.sql) group by run, skill, agent role, model, tool, error class, incident, label and skill version.

## How it works

- **Cost.** Each model's cost comes from Claude Code's `cost-state` and is split across that model's calls by their list-price cost. A run that is still open has no `cost-state` yet, so it is estimated at list price (`runs.cost_estimated`). Override prices under `[prices]`.
- **Skill attribution.** Each model turn and tool call is credited to a skill:
  - a skill load pushes it onto the stack of its agent;
  - an explicit `attributionSkill` wins;
  - a change to `None` pops back to the outer skill, because Claude Code records `None` when a nested skill ends; the outermost skill is never popped;
  - a subagent turn with no attribution inherits the skill active where the subagent was spawned.
  - **Known gap.** Claude Code also writes the spawning skill as `attributionSkill` on subagent turns. So a skill that a subagent loads for itself is credited to the skill that spawned it, and it gets no unit or versions of its own. Fixing this changes every per-skill total, so it is not done yet.
- **Forks.** A fork agent starts with a copy of its parent's history. Those records are skipped, so no work is counted twice.
- **Roles.** A role is the subagent's description with numbers folded, so `Repro F-013` becomes `Repro F-#`.
- **Skill versions.** A version is a hash of the skill text as Claude Code injected it, without the invocation arguments. Each version's text is kept once in `skill_texts`, so the dashboard can diff versions. `v_skill_version_stats` compares versions in SQL. A version whose text was never recorded is shown as unrecorded, and it is not counted as a version.
- **Incidents.** The generic ones are:
  - `error_streak`: consecutive failing tool calls;
  - `repeated_call`: identical calls;
  - `idle_loop`: calls that only wait or print, including `until …; do sleep` loops;
  - `test_edit_after_failure`: an edit to a test file right after a failure, a possible sign of test tampering;
  - `agent_failed`;
  - `permission_denied`;
  - `interrupt`;
  - `compaction`;
  - `api_error`;
  - `bad_marker`: a config marker whose value is declared bad.
- **Taxonomy.** Seeded from MAST and from coding-agent failure studies, plus operational categories. To adapt it, copy [`taxonomy.toml`](runlens/taxonomy.toml) to `~/.runlens/taxonomy.toml`.
- **LLM labels.** They are a first pass, not ground truth: unvalidated judges find few errors in traces. Review a sample with `labels export/import` and read `agreement` before trusting a category.

## Dashboard and benchmarks

`runlens dashboard` writes `~/.runlens/dashboard.html`: one static page with the data embedded. It opens offline from any folder, needs no server, and makes no network requests. The hook rebuilds it after each run is ingested.

Every skill that ran and every agent role gets its own score, with no labelling by hand. Each group you define in `config.toml` gets one too.

The dashboard has four pages:

- **Skills.** A summary row, then the charts: each skill's score range against the average, the version history of every skill, a bubble chart of score against cost per run, a treemap of where the spend goes, a heatmap of every skill against every measure, and runs per day. Below them, a table you can sort, and every recorded version in a collapsed list. Agent roles and groups are on the other two tabs. Roles seen only once are hidden until you tick the box.
- **A skill, role or group.** A gauge for the score, a radar profile against the average with each vertex labelled by its value, and KPI cards with sparklines. The radar overlays the current version on the one before it. Three tabs: **Versions** (when each version was in use, its score, what changed, with the diff), **What drives the score** (spend by version and the breakdown of every measure), and **Runs** (cost over time, cost against time, and each run).
- **Compare.** Pick any two skills, roles or groups, and any of their versions. The verdict uses their likely ranges, and the page shows a radar overlay and bars for each measure.
- **How it works.** The score in plain words, with the exact formula and settings in a collapsed section.

**The score.** 100 is the average run of the same kind (skill, agent role or group). Above 100 is better. It is a weighted geometric mean of eight metrics: cost per run (weight 3), time per run (2), tool error rate (2), incidents per run (2), human prompts per run (2), idle call rate (1), API error rate (1), bad markers per run (1). Each metric is compared with the average, pulled toward it when the sample is small, and clipped to a factor of two. Scores from fewer than five runs are flagged.

**The likely range.** The 5th to 95th percentile of the score over 200 resamples of the unit's runs. Two scores are only called different when their ranges do not overlap.

**Versions.** A version is one distinct skill text, recorded when Claude Code loads the skill. Versions are numbered by first use, and each is diffed against the one before it. Only versions whose text was recorded are counted.

**Groups.** Name a set of skills and agent types in `config.toml`:

```toml
[[group]]
name = "my-flow"
members = ["skill:my-plan", "skill:my-build", "agent:Explore"]
```

A group's runs are the union of its members' work, each piece counted once. Its version is the combination of its members' versions, so it changes when any member's text changes.

The score does not judge whether a run produced the right result. Read the traces with `runlens show` before acting on a drop.

## Using it with your flow

Only `config.toml` changes. See [`config.example.toml`](runlens/config.example.toml) for every option, and [`examples/m-feature.toml`](examples/m-feature.toml) for a real config for [mstack](https://github.com/marcossp32/mstack)'s `/m-feature` flow. You set three things:
- `[select]`: which sessions are runs;
- `[[evidence]]`: extra files to archive;
- `[[marker]]`: which output lines are signals, and which values are bad.

Optionally, `[[group]]` names a set of skills and agent types to score together (see [Dashboard and benchmarks](#dashboard-and-benchmarks)).

## Development

```bash
git clone git@github.com:marcossp32/runlens.git
cd runlens
uv sync                                         # .venv with the locked dependencies
uv run python -m unittest discover -s tests -v
uv tool install -e .                            # a `runlens` command that runs this checkout
```

Dependencies are locked in `uv.lock`. After changing them in `pyproject.toml`, run `uv lock`.

CI runs the tests on Windows and Linux with Python 3.11 and 3.14. They use a synthetic run that covers every tricky part of the transcript format:
- messages split across records;
- forks with copied history;
- skills with no attribution;
- cost allocation;
- markers and incidents;
- the hook, install, labels and dashboard.

`tests/test_bench.py` checks the score, the version, group and attribution rules on plain rows, without a database.

## References

- Cemri et al., [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657) (MAST), NeurIPS 2025: the failure taxonomy seed.
- [SWE-PRM](https://arxiv.org/abs/2509.02360) and [ImpossibleBench](https://arxiv.org/abs/2510.20270): coding-agent failure modes and test tampering.
- [TRAIL](https://arxiv.org/abs/2505.08638): why trace judges must be validated.
- Hamel Husain and Shreya Shankar, [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/): error analysis, binary judges, judge alignment.
- Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
- Claude Code [monitoring](https://code.claude.com/docs/en/monitoring-usage) and [hooks](https://code.claude.com/docs/en/hooks) docs.

## License

[MIT](LICENSE)
