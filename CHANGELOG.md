# Changelog

## Unreleased

- `runlens dashboard` writes `~/.runlens/dashboard.html`, a static page built from the database with no server and no network:
  - every skill and agent role is scored on its own, and each group in `config.toml` is scored as one unit;
  - charts: score range, score by version (one line per skill), score against cost, spend, a heatmap of measures and runs per day; a gauge, a radar profile and sparklines for each unit; cost over time and cost against time per run;
  - a "Show in the charts" panel on the Skills page turns skills and their versions on and off; every chart and table there follows it;
  - each unit's versions are listed with their score, likely range and the diff against the version before;
  - two skills, roles or groups, and any of their versions, can be compared side by side;
  - a Diagnostics page covers the rest of the database: runs, incidents, tool errors, tools, models, agents, skill hand-offs and markers, as bars, columns, scatter plots, matrices, donuts and stacked bars;
  - a "How it works" page in five short tabs: the score, a worked example that follows one of your own skills from its measures to its score, the measures, the pages, and what to keep in mind.
- The score is computed, not labelled: a weighted geometric mean of eight metrics (cost, time, tool errors, incidents, human prompts, idle calls, API errors, bad markers), each compared with the average run of its kind. Each score has a 5th to 95th percentile interval from resampling the runs.
- Skill texts are stored once per version (`skill_texts`), so versions can be diffed. Run `runlens refresh` once to record them for runs already archived.
- Only versions whose skill text was recorded are counted. The rest are shown as unrecorded.
- The hook rebuilds the dashboard after each ingested run. Turn it off with `[dashboard] auto = false`.
- Known gap: a skill that a subagent loads for itself is credited to the skill that spawned it, so it gets no unit or versions of its own. Fixing it changes every per-skill total (see the README).

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
