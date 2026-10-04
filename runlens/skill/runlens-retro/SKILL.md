---
name: runlens-retro
description: "Runs a retrospective over recorded Claude Code runs with runlens: refreshes the run history, labels incidents with a failure taxonomy, reads the traces behind the worst failure modes, and proposes evidence-backed edits to the skills that caused them. Use after a batch of runs of any skill flow, or to check whether a skill change helped."
disable-model-invocation: true
---

Every claim cites **incident ids** you read with `runlens show`. A failure mode needs **two or more incidents**; one is an anecdote. You propose skill edits; you apply none unless asked. All commands are `python -m runlens <command>`; `--help` lists them.

# Refresh

1. `refresh` archives and ingests the runs selected in `~/.runlens/config.toml`. To scope: `--since <date>`, `--skill <name>`, `--session <id>`.
2. `check`. Any `FAIL` means the transcript format changed under the parser: stop and report the failing lines, since every number after it is wrong.
3. `report` writes `~/.runlens/report.html`. Give the human its path.

# Label

4. `classify --limit 40` labels the incidents that have none yet, highest-signal types first (bad markers, failed agents, error streaks, test edits after a failure). Tell the human the cost line it prints.
5. LLM labels are a first pass, not ground truth. When `agreement` reports fewer than 30 paired labels, say so and offer `labels export <file.csv>`: the human fills `human_category`, then `labels import <file.csv>`. A category whose TPR or TNR is below 80% is reported as unverified.

# Find the failure modes

6. Rank with `sql`, worst first. Example queries:
   - `SELECT * FROM v_label_summary WHERE source = 'llm' AND category <> 'expected_behavior' ORDER BY incidents DESC`
   - `SELECT * FROM v_skill ORDER BY cost_usd DESC`
   - `SELECT * FROM v_role ORDER BY error_rate DESC`
   - `SELECT * FROM v_incident_summary ORDER BY incidents DESC`
7. For each of the top categories, `show <incident_id>` on 3 to 5 of its incidents. Write one line per incident: what happened, and the step where it went wrong (open coding).
8. Group those lines into failure modes (axial coding). The taxonomy is a seed; a mode it lacks gets its own name.

# Trace each mode to a skill

9. For a mode whose label says `fault = skill_instructions`, find the skill: `SELECT DISTINCT skill, skill_dir FROM skill_loads WHERE skill = '<skill>'`. Read its `SKILL.md` and references.
10. Quote the line that caused it, or name the instruction that is missing. No line to quote: say the cause is agent judgment or the environment, not the skill.
11. Propose the smallest edit that removes the cause. Keep the skill's own style. A rule that only restates the instructions already there is not an edit.

# Check a change afterwards

12. Skill versions are hashes of the skill text as each run loaded it. `SELECT * FROM v_skill_version_stats WHERE skill = '<skill>'` compares cost per run, error rate, incidents and bad markers across versions. Fewer than 3 runs on a version: say the comparison is not yet meaningful.

# Report

```
Scope     · <runs, dates, total cost>   check: ok | FAIL
Mode <n>  · <name> · <incidents> incidents in <runs> runs · <cost or time it took>
  Evidence · <incident ids>
  Cause    · <skill>/<file>:<line> "<quote>" | missing: <instruction> | agent judgment | environment
  Edit     · <proposed diff>
  Measure  · <view and column that should move, e.g. v_skill_version_stats.error_rate for m-build>
Labels    · <paired labels, agreement, unverified categories>
Report    · <path to report.html>
```
