---
name: runlens-retro
description: "Runs a retrospective over recorded Claude Code runs with runlens: finds the skill versions that got worse and the skills with the weakest outcomes, traces them through incidents and failure labels to the skill instructions behind them, proposes evidence-backed edits, records each proposal and later checks whether it helped. Run it yourself as /runlens-retro after a batch of runs of a skill flow, or to check whether a skill change helped; Claude does not start it on its own because it writes proposals and can spend money."
argument-hint: "[skill] [--since YYYY-MM-DD]"
disable-model-invocation: true
---

Arguments: `$ARGUMENTS`. A skill name limits the retro to that skill; `--since` goes to `runlens refresh`.

Rules that hold throughout:
- Every claim cites **incident ids** you opened with `runlens show <id>`. A failure mode needs **two or more incidents**; one is an anecdote.
- Verdicts about versions come from runlens (`better`, `worse`, `no clear change`, `not enough runs`, `not scored`, `confounded`). Never compare raw averages or invent a threshold of your own, and never compare one skill with another: a version is judged against its own skill.
- You propose edits; you apply none unless asked. Each proposal is recorded so it can be verified later.

Copy this checklist and tick it as you go:

```
Retro progress:
- [ ] 1 Refresh and check the data
- [ ] 2 Pick where to look: versions and outcomes
- [ ] 3 Incidents and labels for the picked skills
- [ ] 4 Read the traces, group them into failure modes
- [ ] 5 Trace each mode to the skill text
- [ ] 6 Propose and record edits
- [ ] 7 Verify earlier proposals
- [ ] 8 Validate the report, then deliver it
```

## 1. Refresh and check

Run `runlens refresh` (add `--since` / `--skill` from the arguments), then `runlens check`.
- **A FAIL about counts or ingest** (`api_calls: raw N vs db M`, `tool_calls`, `agents`, `tool_results`, `ingest <stage> failed`, `evidence file(s) ... have no blob`): stop. Report the failing lines and that every number after them would be wrong. Do nothing else.
- **Any other FAIL** does not make the counts wrong: continue, put the line in the report as a warning and name the fix.
  - `no price for <model> (add it under [prices])`: costs of that model are missing or low, so say cost-based scores are understated and suggest `[prices]` in the config, then `runlens refresh`.
  - `ingested by parser v<N>, current is v<M>`: suggest `runlens refresh`; the numbers come from the old parser.
  - `cost: cost-state ... vs allocated ...` and `subagent(s) without a parent`: name the run and say its cost and subagent numbers are doubtful.
- `WARN` lines (archived but not ingested, queued, stale, never archived) are gaps: name them and suggest `runlens refresh`.
- Lines about open or stale runs are not failures: name them in the report and continue (runlens leaves open runs out of verdicts).

## 2. Pick where to look

Run `runlens score --kind skill --json`, then `runlens versions <skill> --json` for each skill in scope. For each version read `verdict` against the version named in `vs`, its `runs` and `invocations`, `difference` (score with the earlier version = 100, its `ci95`, and the outcome change if one is configured), `confounders`, and `outcome` (for example a marker's first-pass rate) with its `n`.

Pick, in this order: versions whose verdict is `worse`; then skills whose outcome measure is falling or low within their own history; then the skills with the most incidents. Branches:
- **`not enough runs`**: report the run counts and say the comparison is not meaningful yet. You may still read incidents in step 3, but make no claim that the version is better or worse.
- **`confounded`**: report it as confounded and name what else changed (other skills, model mix, Claude Code version, project). Do not attribute the change to the skill text.
- **A skill loaded only inside subagents** has its own unit and shows in `score` and `versions` like any other (check with `runlens sql "SELECT agent_id = 'main' AS in_main, count(*) FROM skill_loads WHERE skill = '<skill>' GROUP BY 1"`). Read its verdict as for any skill. If it is missing from `score` anyway, it has no complete runs or no loads: say so, and still read its incidents in step 3.

## 3. Incidents and labels

For each picked skill: `runlens incidents --skill <skill>`. Unlabelled ones: each label is a `claude -p` call on the human's account, so first run `runlens classify --skill <skill> --limit 40 --dry-run` (no model call: it lists the incidents it would label and one judge prompt). Tell the human how many incidents that is, ask whether to go ahead, and only on a yes run it without `--dry-run` (a stratified random sample) and report the cost line it prints. On a no, work from the incident types and your own reading of the traces.

Then `runlens agreement --json`. A category counts as a finding only when it is `verified` there.
- **Too few human labels** (`enough` is false): say the label counts are hypotheses, work from the incident types and your own reading of the traces, and offer `runlens labels export sample.csv --limit 50 --blind`: the human fills `human_category` and `human_fault`, then `runlens labels import sample.csv`.
- Incidents labelled `expected_behavior` are the system working; leave them out.

## 4. Read the traces

For each incident type or category with two or more incidents in a picked skill, `runlens show <id>` on 3 to 5 of them. Write one line per incident: what happened and the step where it went wrong. Group the lines into failure modes; the taxonomy is a seed, and a mode it lacks gets its own name.

## 5. Trace each mode to the skill text

Find the skill's files: `runlens sql "SELECT DISTINCT skill_dir FROM skill_loads WHERE skill = '<skill>'"`. Read its `SKILL.md` and the references the mode touches.
- **Labels with `fault = skill_instructions`** carry the quoted `instruction` and the `skill_hash` the judge saw. Find the quote in the file and cite `file:line`. A quote marked `[quote not found in the skill text]` is unconfirmed: check it yourself.
- **No `skill_instructions` labels** (common): decide yourself, from the SKILL.md you just read, whether a line caused the mode or a missing instruction would have prevented it. Neither: say the cause is agent judgment or the environment, and propose no skill edit.
- **For a `worse` version**, diff it against the previous one: `runlens sql "SELECT content_hash, text FROM skill_texts WHERE skill = '<skill>'"` and tie the mode to added or removed lines.

## 6. Propose and record

Propose the smallest edit that removes the cause, in the skill's own style, and say why it should work. A rule that restates what the skill already says is not an edit.

Record each proposal with `runlens proposals add` (`--help` lists the fields): the skill, the version hash it edits, the hypothesis, the measure that should move (`score`, `outcome`, `cost`, `error_rate`, `incidents`, ...) and in which direction, and the evidence incident ids. To check it on controlled re-runs instead of waiting for new runs, `runlens export-eval --incident <id> ...` writes eval cases for `claude plugin eval` and skill-creator; give the human the command from its README.

## 7. Verify earlier proposals

`runlens verify --json` checks recorded proposals against the runs since. Report each as confirmed, refuted, inconclusive (no clear change: not evidence the edit did nothing), not enough runs or confounded (with its `confounders`), using its verdict as given. An edit "helped" only on a `verify` or eval result, never on impressions.

## 8. Validate, then deliver

Check the draft report against this list. Fix every miss by going back to its step, then check again; deliver only when all hold.
- Every mode cites two or more incident ids you opened with `show`.
- Every quoted cause gives `file:line`, and the quote is in that file.
- Every version claim is a runlens verdict with its run counts; confounded ones list their confounders.
- Label counts are used only for verified categories; otherwise they are called hypotheses.
- Every proposal has the id `proposals add` returned and names its measure.

```
Scope      · <runs, dates, total cost>   check: ok | <open runs>
Versions   · <skill> <version> vs <previous>: <verdict> (n=<runs> vs <runs>) | confounded by <...>
Mode <n>   · <name> · <incidents> incidents in <runs> runs · <skill and version>
  Evidence · <incident ids>
  Cause    · <skill>/<file>:<line> "<quote>" | missing: <instruction> | agent judgment | environment
  Edit     · <proposed diff>
  Measure  · <measure and direction> · proposal <id> · eval: <export-eval folder, if made>
Verified   · <proposal id>: confirmed | refuted | inconclusive | not enough runs | confounded by <...>
Labels     · <paired labels, kappa, verified and unverified categories>
```
