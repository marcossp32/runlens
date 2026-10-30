---
name: runlens-retro
description: "Runs a retrospective over recorded Claude Code runs with runlens: reports whether earlier skill edits helped, finds where skills fail now and traces each failure to the skill text behind it, and records evidence-backed edit proposals that runlens verifies on later runs. Run it yourself as /runlens-retro after a batch of runs, or to check whether a skill change helped."
argument-hint: "[skill] [--since YYYY-MM-DD] [label]"
disable-model-invocation: true
---

Arguments: `$ARGUMENTS`. A skill name narrows the retro to that skill, `--since` goes to `runlens refresh`, which then fetches only runs started from that date while verdicts still use every run already stored, and `label` is the person's consent to paid labelling for this retro.

A retro leaves the person knowing three things: whether their earlier skill edits helped, where their skills fail now and why, and which edit is worth trying next. Every conclusion carries evidence they can open themselves, and every proposed edit is recorded so runlens can judge it on the runs that follow. How you investigate is yours to decide.

# Done when

The person has a report that answers those three questions as far as the data allows and says plainly where it does not, its data line is what `runlens check` printed after this retro's `runlens refresh`, and every edit it proposes is recorded in runlens under the id `proposals add` returned.

# Acceptance criteria

- [ ] Each earlier proposal in scope is reported with the verdict `runlens verify` gives it on this retro's data (the one `proposals list` carries is from its last check) and what that means for its edit: keep it, revert or rework it, apply it where no newer version has run since (its `note` says so), or wait for more runs.
- [ ] Each failure mode rests on two or more incidents you read with `runlens show`, cited by id. One incident is an anecdote.
- [ ] Each cause is either in the skill text the incidents ran under, quoted with its `file:line` where today's file still holds it, or the instruction that text lacks; or named as lying outside the text (agent judgment, environment), and then no skill edit is proposed for it.
- [ ] Each claim about a version is a runlens verdict with its run counts; a confounded one names what else changed.
- [ ] Label categories count as findings only where `runlens agreement` marks them verified; otherwise they are hypotheses and the report says so.
- [ ] Each new proposal names the measure it should move and the direction. None repeats an edit `verify` refuted, or an open proposal for the same problem; the report points to that one instead. A proposal is open while `verify` says `not enough runs`: any other verdict was reached on enough runs a side, so a problem still present then is one its edit did not fix.
- [ ] The report says what it examined and what it left out, and when nothing has changed since the last retro, it is short and says so.

# Lines not to cross

- **Wrong data stops the retro.** A `runlens check` FAIL of the form `raw N vs db M` says a run's rows disagree with its transcript. Every verdict over that run's skills is built on them, so quoting any number, even with a caveat, invites the person to act on it. After a refresh it means the parser has fallen behind the transcript format: report those lines as that, for the person to report, and stop. Every other check line leaves the stored rows right and goes into Scope as a warning with its fix: a run missing or behind (a failed ingest, never archived, changed since archiving) shrinks what verdicts see; an unpriced model understates cost until its price is under `[prices]` and the runs are refreshed; a cost-state mismatch or a subagent without a parent makes that run's cost doubtful; a missing evidence blob changes no number.
- **Propose, don't apply.** Editing a skill creates the next version under evaluation; that choice belongs to the person, so apply an edit only when they ask.
- **Labelling spends their money.** Each `runlens classify` label is a `claude -p` call on their account. Run it only with consent: the `label` argument, or a yes after you told them how many incidents `--dry-run` lists. Without it, work from incident types and your own reading of the traces, and say in the report what labelling would add and how many incidents it would label.

# What the evidence means

- **Verdicts** judge a version against earlier versions of the same skill, on resampled runs, and are the only comparison the report makes. A version's own numbers (`outcome`, `measures`, `score`) describe it; skills are never compared with each other; raw averages or thresholds of your own would replace that method with guesswork.
- **Few runs make verdicts cautious.** runlens gives a verdict from `[method] min_runs` runs a side (5 by default), and with that few only large changes clear the interval, so `no clear change` and `inconclusive` are the usual results and are not evidence that nothing changed. A proposal aimed at one measure is judged on that measure's own interval, where the noise of the other measures in `score` does not dilute it.
- **A failure that appears with a new version** most often comes from the lines that version added or removed (`diff` in `versions`). An edit made for an earlier proposal is the first suspect: say so when the cause is that edit, since the fix is then to revert or rework it rather than add a rule on top.
- **`confounded`** means something besides the skill text changed between the two sides (`confounders` names it), so the change cannot be put down to the text. Where that is another skill edited at the same time, a group holding both (`runlens score --kind group`) is where the batch edit can be judged.
- **`notes`** say what differed between the two sides without confounding the verdict, such as Claude Code patch releases (by default only a minor release confounds). Mention one when it bears on a claim, as something that also differed, never as the cause of the change.
- **Labels** come from an LLM judge until people label a sample. A label with `fault = skill_instructions` carries the quoted `instruction` and the `skill_hash` the judge saw; a quote marked `[quote not found in the skill text]` is unconfirmed. Incidents labelled `expected_behavior` are the system working. Unverified labels weaken the categories, not the traces: a mode you read yourself in the traces still earns a recorded proposal, since recording it is how the person will learn whether the edit helped.

# What runlens gives you

| Command | What you get |
|---|---|
| `runlens refresh`, `runlens check` | fresh data, and whether it can be trusted |
| `runlens score --kind skill --json` | each skill's current version against its previous one, with run counts, outcome and confounders |
| `runlens versions <skill> --json` | every version: verdict, `vs`, runs, `difference` with its interval, `confounders`, `diff` of the text against the previous version, and `skill_dirs` where its files live |
| `runlens incidents --skill <skill> --json` | its incidents, each with its latest label (human before LLM): `label`, `fault`, `instruction`, `skill_hash`; oldest first, cut at `--limit` (50), with no time or version, so a busy skill's current incidents come from `incidents` joined to `skill_loads` in `runlens sql` |
| `runlens show <id>` | the steps that led to one incident, with the active skill |
| `runlens agreement --json` | which label categories human review has verified |
| `runlens classify --skill <skill> [--dry-run]` | LLM labels for unlabelled incidents; paid without `--dry-run` |
| `runlens labels export <file> --limit <n> --blind` | a sample for the person to label, so categories can become verified; `runlens agreement` says how many human labels that still needs |
| `runlens proposals list --json`, `runlens proposals add ...` | proposals already recorded, and recording a new one (`--help` lists the fields) |
| `runlens verify --json` | each proposal's verdict on the runs since |
| `runlens export-eval --incident <id> ...` | eval cases from real failures, for controlled re-runs instead of waiting for new runs |
| `runlens sql "<query>"` | anything else, read-only; `skill_texts` holds each version's text as loaded (its `content_hash` starts with the version `hash`), without frontmatter, so its line numbers are not the file's |

# The report

Write it for someone deciding what to do next. This shape works well; change it when the findings call for something else.

```
Scope      · <skills, runs, dates, cost> · data: ok | <warnings>
Earlier    · <proposal id> <skill>: <verify verdict> (<runs before> vs <runs after>) · <keep | revert or rework | apply | wait, and why>
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
