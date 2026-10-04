# runlens

A history of your Claude Code runs in DuckDB, to find where a skill flow struggles and to check whether a change to a skill helped.

A **run** is one Claude Code session plus every subagent it spawned. runlens knows nothing about any skill or flow: skills, agent types and roles are attributes read from the transcripts. Everything specific to a flow lives in `~/.runlens/config.toml`:
- which sessions count as runs;
- which output lines are signals;
- which files outside the transcript to keep.

## Install

```bash
git clone git@github.com:marcossp32/runlens.git
cd runlens
pip install -e .
python -m runlens install
```

`install` does three things:
- adds an async `SessionEnd` hook to `~/.claude/settings.json`, after backing the file up;
- copies the `/runlens-retro` skill into `~/.claude/skills`;
- writes `~/.runlens/config.toml` from [`config.example.toml`](runlens/config.example.toml) if there is none.

It is idempotent. `python -m runlens uninstall` removes the hook.

With the hook, every session that ends and matches `[select]` is archived and ingested in the background. Activity is logged to `~/.runlens/hooks.log`.

Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default). The runlens archive is the copy that stays.

## Use

```bash
python -m runlens refresh      # archive + ingest the runs selected in config.toml
python -m runlens check        # compare the database with the raw transcripts
python -m runlens report       # write ~/.runlens/report.html
python -m runlens show <id>    # the timeline around an incident or a tool call
```

| Command | What it does |
|---|---|
| `archive`, `ingest`, `refresh` | Copy runs out of `~/.claude/projects` and load them into DuckDB. Idempotent. Filters: `--since`, `--skill`, `--project`, `--session` |
| `check` | Compares counts with the raw transcripts, checks cost against Claude Code's `cost-state`, and finds subagents with no parent. The transcript format is internal to Claude Code and changes between versions; a `FAIL` means the parser fell behind |
| `summary` | One table per run and one per skill, in the terminal |
| `report` | A self-contained HTML report. `--session` limits it to some runs |
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
| `incidents` | moments worth reading, each with the timeline that led to it |
| `labels` | failure labels from the LLM and from humans; they survive re-ingest |

The `v_*` views in [`views.sql`](runlens/views.sql) group by run, skill, agent role, model, tool, error class, incident, label and skill version.

## How it works

- **Cost.** Each model's cost comes from Claude Code's `cost-state` and is split across that model's calls by their list-price cost. A run that is still open has no `cost-state` yet, so it is estimated at list price (`runs.cost_estimated`). Override prices under `[prices]`.
- **Skill attribution.** Claude Code records `attributionSkill` on main-session turns but not inside subagents. When a nested skill ends, it records `None` instead of the outer skill. So:
  - a skill load pushes;
  - an explicit attribution wins;
  - a change to `None` pops back to the outer skill;
  - the outermost skill is never popped;
  - a subagent with no skill of its own inherits the skill active where it was spawned.
- **Forks.** A fork agent starts with a copy of its parent's history. Those records are skipped, so no work is counted twice.
- **Roles.** A role is the subagent's description with numbers folded, so `Repro F-013` becomes `Repro F-#`.
- **Skill versions.** A version is a hash of the skill text as Claude Code injected it, without the invocation arguments. `v_skill_version_stats` compares versions.
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

## Using it with your flow

Only `config.toml` changes. See [`config.example.toml`](runlens/config.example.toml) for every option, and [`examples/m-feature.toml`](examples/m-feature.toml) for a real config for [mstack](https://github.com/marcossp32/mstack)'s `/m-feature` flow. You set three things:
- `[select]`: which sessions are runs;
- `[[evidence]]`: extra files to archive;
- `[[marker]]`: which output lines are signals, and which values are bad.

## Requirements

- Python 3.11 or later.
- Claude Code.
- `claude` on the PATH, for `classify`.

CI runs the tests on Windows and Linux.

## Tests

```bash
python -m unittest discover -s tests -v
```

They run against a synthetic run that covers every tricky part of the transcript format:
- messages split across records;
- forks with copied history;
- skills with no attribution;
- cost allocation;
- markers and incidents;
- the hook, install and labels.

## References

- Cemri et al., [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657) (MAST), NeurIPS 2025: the failure taxonomy seed.
- [SWE-PRM](https://arxiv.org/abs/2509.02360) and [ImpossibleBench](https://arxiv.org/abs/2510.20270): coding-agent failure modes and test tampering.
- [TRAIL](https://arxiv.org/abs/2505.08638): why trace judges must be validated.
- Hamel Husain and Shreya Shankar, [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/): error analysis, binary judges, judge alignment.
- Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
- Claude Code [monitoring](https://code.claude.com/docs/en/monitoring-usage) and [hooks](https://code.claude.com/docs/en/hooks) docs.

## License

[MIT](LICENSE)
