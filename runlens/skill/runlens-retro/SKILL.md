---
name: runlens-retro
description: "Runs a retrospective over recorded Claude Code runs with runlens: reports whether earlier skill edits helped, finds where skills fail now and traces each failure to the skill text behind it, and records evidence-backed edit proposals that runlens verifies on later runs. Run it yourself as /runlens-retro after a batch of runs, or to check whether a skill change helped; Claude does not start it on its own because it records proposals and can spend money."
argument-hint: "[skill] [--since YYYY-MM-DD] [label]"
disable-model-invocation: true
---

Arguments: `$ARGUMENTS`. A skill name narrows the retro to that skill, `--since` goes to `runlens refresh`, and `label` is the person's consent to paid labelling for this retro.

A retro leaves the person knowing three things: whether their earlier skill edits helped, where their skills fail now and why, and which edit is worth trying next. Every conclusion carries evidence they can open themselves, and every proposed edit is recorded so runlens can judge it on the runs that follow. How you investigate is yours to decide. What follows is what makes a retro trustworthy, and what runlens gives you to work with.

# Done when

The person has a report that answers those three questions as far as the data allows and says plainly where it does not, and every edit it proposes is recorded in runlens under the id `proposals add` returned.

# Acceptance criteria

- [ ] Each earlier proposal in scope is reported with the verdict `runlens verify` gave it, and the report knows those verdicts before it suggests anything new for the same skill; a refuted one comes with a view on keeping or reverting that edit, while one still waiting for runs is left to run.
- [ ] Each failure mode rests on two or more incidents you read with `runlens show`, cited by id. One incident is an anecdote.
- [ ] Each cause cites the skill text (`file:line` and its words, found in that file) or names where the cause lies instead (agent judgment, environment), and then proposes no skill edit.
- [ ] Each claim about a version is a runlens verdict with its run counts; a confounded one names what else changed.
- [ ] Label categories count as findings only where `runlens agreement` marks them verified; otherwise they are hypotheses and the report says so.
- [ ] Each new proposal names the measure it should move and the direction, and none repeats an open proposal for the same problem; the report points to that one instead.
- [ ] The report says what it examined and what it left out, and when nothing has changed since the last retro, it is short and says so.
- [ ] No skill file was edited, and no paid labelling ran without the person's consent.

# Lines not to cross

- **Wrong data stops the retro.** A `runlens check` FAIL about counts or ingest (`api_calls: raw N vs db M`, `tool_calls`, `agents`, `tool_results`, `ingest <stage> failed`, `evidence file(s) ... have no blob`) means every number after it is wrong, and quoting any of them, even with a caveat, invites the person to act on it. Report those lines and the fix, and stop.
- **Propose, don't apply.** Editing a skill creates the next version under evaluation; that choice belongs to the person, so apply an edit only when they ask.
- **Labelling spends their money.** Each `runlens classify` label is a `claude -p` call on their account. Run it only with consent: the `label` argument, or a yes after you told them how many incidents `--dry-run` lists. Without it, work from incident types and your own reading of the traces, and say in the report what labelling would add and what it would cost.

# What the evidence means

- **Verdicts** (`better`, `worse`, `no clear change`, `not enough runs`, `not scored`, `confounded`) judge a version against earlier versions of the same skill, on resampled runs. Skills are never compared with each other, and raw averages or thresholds of your own would replace that method with guesswork.
- **A version's own numbers** (`outcome`, `measures`, `score`) describe it; only the verdict compares it. Quote them as description, never as better or worse.
- **Few runs make verdicts cautious.** runlens gives a verdict from `[method] min_runs` runs a side (5 by default), and with that few only large changes clear the interval, so `no clear change` and `inconclusive` are the usual results and are not evidence that nothing changed. A proposal aimed at one measure (`error_rate`, `incidents`, `cost`, `outcome`, ...) is judged on that measure alone and reaches a verdict far sooner than one on `score`.
- **A failure that appears with a new version** most often comes from the lines that version added or removed (`diff` in `versions`). An edit made for an earlier proposal is the first suspect: say so when the cause is that edit, since the fix is then to revert or rework it rather than add a rule on top.
- **`confounded`** means something else changed between the two sides (another skill, the model mix, the Claude Code version, the project); the change cannot be put down to the skill text.
- **Labels** come from an LLM judge until people label a sample. A label with `fault = skill_instructions` carries the quoted `instruction` and the `skill_hash` the judge saw; a quote marked `[quote not found in the skill text]` is unconfirmed. Incidents labelled `expected_behavior` are the system working. Unverified labels weaken the categories, not the traces: a mode you read yourself in two or more traces still earns a recorded proposal, since recording it is how the person will learn whether the edit helped.
- **Other check lines** do not make the counts wrong, so they belong in the report as warnings with their fix: an unpriced model understates cost (add it under `[prices]`, then `runlens refresh`); an old parser version or `WARN` gaps ask for `runlens refresh`; a cost-state mismatch or orphan subagents make that run's cost doubtful; an out-of-date installed skill asks for `runlens install`. Open runs are simply left out of verdicts.

# What runlens gives you

| Command | What you get |
|---|---|
| `runlens refresh`, `runlens check` | fresh data, and whether it can be trusted |
| `runlens score --kind skill --json` | each skill's current version against its previous one, with run counts, outcome and confounders |
| `runlens versions <skill> --json` | every version: verdict, `vs`, runs, `difference` with its interval, `confounders`, `diff` of the text against the previous version, and `skill_dirs` where its files live |
| `runlens incidents --skill <skill> --json` | its incidents, each with its latest label (human before LLM): `label`, `fault`, `instruction`, `skill_hash` |
| `runlens show <id>` | the steps that led to one incident, with the active skill |
| `runlens agreement --json` | which label categories human review has verified |
| `runlens classify --skill <skill> --limit 40 [--dry-run]` | LLM labels for unlabelled incidents (a stratified sample); paid without `--dry-run` |
| `runlens labels export <file> --limit 50 --blind` | a sample for the person to label, so categories can become verified |
| `runlens proposals list --json`, `runlens proposals add ...` | proposals already recorded, and recording a new one (`--help` lists the fields) |
| `runlens verify --json` | each proposal's verdict on the runs since: confirmed, refuted, inconclusive, not enough runs, confounded |
| `runlens export-eval --incident <id> ...` | eval cases from real failures, for controlled re-runs instead of waiting for new runs |
| `runlens sql "<query>"` | anything else, read-only |

# The report

Write it for someone deciding what to do next. This shape works well; change it when the findings call for something else.

```
Scope      · <skills, runs, dates, cost> · data: ok | <warnings>
Earlier    · <proposal id> <skill>: <verify verdict> (<runs before> vs <runs after>) · <keep | revert | wait, and why>
Versions   · <skill> <version> vs <previous>: <verdict> (n=<runs> vs <runs>) | confounded by <...>
Mode <n>   · <name> · <incidents> incidents in <runs> runs · <skill and version>
  Evidence · <incident ids>
  Cause    · <skill>/<file>:<line> "<quote>" | missing: <instruction> | agent judgment | environment
  Edit     · <smallest edit that removes the cause, in the skill's own style>
  Measure  · <measure> <direction> · proposal <id> | builds on <open proposal id>
Anecdotes  · <single incidents worth knowing about, not modes>
Labels     · <verified categories> | hypotheses: <why>
Not looked · <what was left out, and why>
Next       · <what would make the next retro sharper: runs needed, labelling, an eval to export>
```
