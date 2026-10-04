# Changelog

## 0.1.1 - 2026-10-04

- Install and develop with uv:
  - `uv tool install` puts `runlens` on the PATH;
  - `uv.lock` pins the dependencies;
  - CI runs through `uv sync --locked`.
- Messages, the report and the `/runlens-retro` skill now say `runlens <command>` instead of `python -m runlens <command>`.
- The README covers everything a new machine needs: requirements, install, config, update, uninstall and development.
- CI moved to `actions/checkout@v7` and `astral-sh/setup-uv@v10`, which run on Node 24.

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
