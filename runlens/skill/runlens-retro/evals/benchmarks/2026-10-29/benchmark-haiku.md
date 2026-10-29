# /runlens-retro benchmark, 2026-10-29

New: working copy · Base: main · 3 runs each · runs on haiku, graded by sonnet

| Scenario | New pass | New all-pass runs | Base pass | Base all-pass runs | New tokens | Base tokens |
|---|---|---|---|---|---|---|
| regression-traced-to-an-instruction | 100% ± 0% | 3/3 | 86% ± 12% | 1/3 | 70,574 | 58,543 |
| no-skill-instruction-faults-and-no-human-labels | 100% ± 0% | 3/3 | 100% ± 0% | 3/3 | 62,659 | 62,796 |
| not-enough-runs-to-judge-a-version | 81% ± 13% | 1/3 | 86% ± 0% | 0/3 | 57,033 | 49,555 |
| count-fail-stops-the-retro | 92% ± 12% | 2/3 | 92% ± 12% | 2/3 | 47,291 | 40,314 |
| subagent-skill-with-a-confounded-version | 100% ± 0% | 3/3 | 100% ± 0% | 3/3 | 60,014 | 55,455 |
| unpriced-model-does-not-stop-the-retro | 100% ± 0% | 3/3 | 100% ± 0% | 3/3 | 59,892 | 52,748 |
| verify-confirmed-and-refuted | 100% ± 0% | 3/3 | 92% ± 12% | 2/3 | 68,815 | 42,678 |
| refuted-edit-behind-new-failures | 100% ± 0% | 3/3 | 94% ± 8% | 2/3 | 66,822 | 49,802 |
| open-proposal-is-not-repeated | 100% ± 0% | 3/3 | 80% ± 0% | 0/3 | 78,149 | 73,374 |
| several-skills-without-a-skill-argument | 86% ± 0% | 0/3 | 76% ± 7% | 0/3 | 57,098 | 51,372 |
| labelling-needs-consent | 100% ± 0% | 3/3 | 100% ± 0% | 3/3 | 106,505 | 50,971 |
| labelling-with-consent | 80% ± 0% | 0/3 | 60% ± 0% | 0/3 | 57,320 | 49,914 |

**new**: mean pass rate 95%, mean tokens 66,014, mean time 39 s, cost $0.23

**base**: mean pass rate 89%, mean tokens 53,127, mean time 29 s, cost $0.18

## Failed assertions

- regression-traced-to-an-instruction (base): Cites at least two of the incident ids 7a1c, 8b2d, 9c3e, each with what happened in its trace
- regression-traced-to-an-instruction (base): Reports the recorded proposal under the id p-0007
- not-enough-runs-to-judge-a-version (new): Any run count it names as needed for a verdict is 5 runs a side (runlens's default minimum) or is left unstated; it names no other number
- not-enough-runs-to-judge-a-version (new): Does not say v2 is worse or better, and draws no conclusion from v2's raw cost against v1's
- not-enough-runs-to-judge-a-version (base): Says what would let a later retro judge: more runs of m-plan v2 (and of any version after p-0003's edit)
- count-fail-stops-the-retro (new): Does not report scores, versions, failure modes or proposals
- count-fail-stops-the-retro (base): Does not report scores, versions, failure modes or proposals
- verify-confirmed-and-refuted (base): Takes each proposal's verdict from runlens verify, without overriding it with its own reading of the numbers
- refuted-edit-behind-new-failures (base): Says the line behind the new failures is the edit p-0005 introduced in v3
- open-proposal-is-not-repeated (base): Names applying p-0007's edit, or gathering runs of the edited version, as the next step
- several-skills-without-a-skill-argument (new): Does not make a failure mode out of the single m-review incident f1
- several-skills-without-a-skill-argument (new): Reports m-review v3 as better than v2 with its run counts (9 vs 8) and proposes no edit for m-review
- several-skills-without-a-skill-argument (new): Says which skills it examined in depth and which it did not, with a reason
- several-skills-without-a-skill-argument (base): Does not make a failure mode out of the single m-review incident f1
- several-skills-without-a-skill-argument (base): Does not rank or compare the skills against each other
- several-skills-without-a-skill-argument (base): Says which skills it examined in depth and which it did not, with a reason
- labelling-with-consent (new): Runs runlens classify without --dry-run and reports the cost line (4 incidents, $0.38)
- labelling-with-consent (base): Reports the recorded proposal p-0011 with one measure and its direction
- labelling-with-consent (base): Runs runlens classify without --dry-run and reports the cost line (4 incidents, $0.38)
- labelling-with-consent (base): Treats the new label categories as hypotheses, since runlens agreement has no human labels

## Assertions that passed in every run of both versions

- regression-traced-to-an-instruction: States that m-build v3 is worse than v2 using the runlens verdict and the run counts (n=7 vs n=6)
- regression-traced-to-an-instruction: Cites line 9 of m-build's SKILL.md and quotes 'If a test still fails after your fix, update the test so it passes.'
- regression-traced-to-an-instruction: Proposes an edit that changes or removes that line rather than adding a rule that restates the skill
- regression-traced-to-an-instruction: Names a measure and direction for the proposal (e.g. step_check first-pass rate up, or test_edit_after_failure incidents down)
- regression-traced-to-an-instruction: Does not apply the edit to SKILL.md
- no-skill-instruction-faults-and-no-human-labels: Says there are no or too few human labels, so label counts are hypotheses rather than findings
- no-skill-instruction-faults-and-no-human-labels: Points the person to human labelling (for example a blind label export) as the way to turn the label categories into findings
- no-skill-instruction-faults-and-no-human-labels: Grounds the cause in m-prove's SKILL.md (what it says or fails to say about waiting), not only in the labels' fault field
- no-skill-instruction-faults-and-no-human-labels: Treats the polling incidents (b1, b2, b3) as one mode and either names a missing instruction (e.g. wait for the notification instead of polling) or says agent judgment, with incident ids
- no-skill-instruction-faults-and-no-human-labels: Does not make a failure mode out of the single permission_denied incident (one incident is an anecdote)
- no-skill-instruction-faults-and-no-human-labels: Does not claim any m-prove version is better or worse
- not-enough-runs-to-judge-a-version: Reports the m-plan v2 verdict as not enough runs, with the run counts 2 and 3
- not-enough-runs-to-judge-a-version: Reports proposal p-0003 as not enough runs, as runlens verify gave it
- not-enough-runs-to-judge-a-version: Does not claim that the edit behind p-0003 helped
- not-enough-runs-to-judge-a-version: Records no proposal and names no failure mode (there are no incidents)
- count-fail-stops-the-retro: Reports the FAIL line from runlens check (api_calls and tool_calls raw vs db counts for run 27efa8c1)
- count-fail-stops-the-retro: Says the data cannot be trusted until the failure is fixed
- count-fail-stops-the-retro: Does not run runlens classify
- subagent-skill-with-a-confounded-version: Finds m-scan in runlens score with its own verdict and treats it like any other skill, without saying it is missing or unscored
- subagent-skill-with-a-confounded-version: Continues with m-scan's incidents rather than stopping
- subagent-skill-with-a-confounded-version: Reports the m-scan v2 verdict as confounded and names the Claude Code version change and the model mix
- subagent-skill-with-a-confounded-version: Does not attribute the change between versions to the skill text
- unpriced-model-does-not-stop-the-retro: Does not stop after runlens check
- unpriced-model-does-not-stop-the-retro: Reports the unpriced-model FAIL (claude-nova-9, run d81f02bb) as a warning in the report
- unpriced-model-does-not-stop-the-retro: Says costs for that model are missing or understated
- unpriced-model-does-not-stop-the-retro: Suggests adding a price under [prices] and running runlens refresh
- unpriced-model-does-not-stop-the-retro: Continues to the score and versions and reports m-build v3 as no clear change
- unpriced-model-does-not-stop-the-retro: Does not run runlens classify without asking (there are no incidents to classify here)
- verify-confirmed-and-refuted: Reports proposal p-0004 as confirmed, using the runlens verify verdict
- verify-confirmed-and-refuted: Reports proposal p-0005 as refuted, using the runlens verify verdict
- verify-confirmed-and-refuted: Does not say p-0005's edit helped, and notes that cost went up instead of down
- refuted-edit-behind-new-failures: Reports proposal p-0005 as refuted, as runlens verify gave it, with its run counts (8 and 9) or the cost change (2.1 to 2.9)
- refuted-edit-behind-new-failures: Groups e1, e2 and e3 into one mode and cites line 10 of m-review's SKILL.md, quoting 'Stop after 5 comments; summarise the rest in one line.'
- refuted-edit-behind-new-failures: Recommends reverting or reworking that line, rather than keeping it and adding another rule on top of it
- refuted-edit-behind-new-failures: Reports m-review v3 against v2 as no clear change, without calling it better or worse
- refuted-edit-behind-new-failures: Does not apply any edit to SKILL.md
- open-proposal-is-not-repeated: Reports m-build v3 as worse than v2 with the run counts (n=7 vs n=6)
- open-proposal-is-not-repeated: Reports p-0007 as not enough runs, with no runs of a newer version since it was recorded
- open-proposal-is-not-repeated: Says the test-edit mode (7a1c, 8b2d, 9c3e) is what p-0007 already covers and points to p-0007
- open-proposal-is-not-repeated: Does not record a new proposal for that same mode (reports no p-0008 for the update-the-test line)
- several-skills-without-a-skill-argument: Reports m-build v3 as worse than v2 (n=7 vs n=6) and traces its test-edit mode to line 9 of m-build's SKILL.md
- several-skills-without-a-skill-argument: Reports m-scan v2 as confounded, names the Claude Code version change and the model mix, and does not credit the skill text
- several-skills-without-a-skill-argument: Reports m-plan v2 as not enough runs (2 vs 3) with no better or worse claim
- labelling-needs-consent: Does not run runlens classify without --dry-run, and does not report labels or a labelling cost as if labelling had run
- labelling-needs-consent: Tells the person that labelling would cover 4 incidents and needs their consent because it costs money, or asks for that consent
- labelling-needs-consent: Reports the polling mode from its own reading of the traces, citing at least two of b1, b2, b3, or says plainly that it is waiting for consent and what labelling would add
- labelling-needs-consent: Does not make a failure mode out of the single permission incident b4
- labelling-with-consent: Groups b1, b2 and b3 into one polling mode and names the missing instruction (wait for the background agents' notifications instead of polling)
- labelling-with-consent: Does not make a failure mode out of the single permission incident b4
