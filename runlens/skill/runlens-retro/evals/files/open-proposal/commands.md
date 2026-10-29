# Canned runlens output: a regression that an open proposal already covers

## runlens refresh
```
3 runs archived, 3 ingested
```

## runlens check
```
ok    c66287aa  agents=3 api=150 tools=90 cost=2.00 output tokens 98% of cost-state
ok    d81f02bb  agents=3 api=163 tools=97 cost=2.35 output tokens 98% of cost-state
ok    e93a1c44  agents=3 api=176 tools=104 cost=2.70 output tokens 98% of cost-state
ok    27efa8c1  agents=3 api=189 tools=111 cost=3.05 output tokens 98% of cost-state
ok    31aa90bd  agents=3 api=202 tools=118 cost=3.40 output tokens 98% of cost-state
ok    42bb81ce  agents=3 api=215 tools=125 cost=3.75 output tokens 98% of cost-state
ok    53cc72df  agents=3 api=228 tools=132 cost=4.10 output tokens 98% of cost-state
ok    64dd63e0  agents=3 api=241 tools=139 cost=4.45 output tokens 98% of cost-state
ok    75ee54f1  agents=3 api=254 tools=146 cost=4.80 output tokens 98% of cost-state
ok    86ff45a2  agents=3 api=267 tools=153 cost=5.15 output tokens 98% of cost-state
ok    97a036b3  agents=3 api=280 tools=160 cost=5.50 output tokens 98% of cost-state
ok    a8b127c4  agents=3 api=293 tools=167 cost=5.85 output tokens 98% of cost-state
ok    b9c218d5  agents=3 api=306 tools=174 cost=6.20 output tokens 98% of cost-state
all checks passed
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 13, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation", "units": [
  {"unit": "skill:m-build", "name": "m-build", "kind": "skill", "runs": 13, "invocations": 61, "versions": 3, "current": "v3",
   "verdict": "worse", "direction": "worse", "vs": "v2", "confounders": [],
   "outcome": {"measure": "step_check first-pass rate", "value": 0.71, "n": 61},
   "difference": {"score": 71.4, "ci95": [58.2, 88.9], "measures": {},
                  "outcome": {"a": 0.87, "b": 0.55, "value": -0.32, "ci95": [-0.51, -0.12]}}},
  {"unit": "skill:m-feature", "name": "m-feature", "kind": "skill", "runs": 13, "invocations": 13, "versions": 1, "current": "v1",
   "verdict": null, "direction": null, "vs": null, "confounders": [], "outcome": null, "difference": null}
]}
```

## runlens versions m-build --json
```json
{"skill": "m-build", "unit": "skill:m-build", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:m-build@33e62960", "label": "v2", "hash": "33e62960", "runs": 6, "invocations": 30, "score": 112.4,
   "verdict": null, "vs": null, "confounders": [], "difference": null,
   "outcome": {"measure": "step_check first-pass rate", "value": 0.87, "n": 30}},
  {"id": "skill:m-build@f72bcc1f", "label": "v3", "hash": "f72bcc1f", "runs": 7, "invocations": 31, "score": 80.3,
   "verdict": "worse", "direction": "worse", "vs": "v2", "confounders": [],
   "difference": {"score": 71.4, "ci95": [58.2, 88.9],
                  "measures": {"outcome": {"a": 0.87, "b": 0.55, "effect": 0.36, "ci95": [0.21, 0.71]}},
                  "outcome": {"a": 0.87, "b": 0.55, "value": -0.32, "ci95": [-0.51, -0.12]}},
   "outcome": {"measure": "step_check first-pass rate", "value": 0.55, "n": 31},
   "diff": "@@ -8 +8,2 @@\n Read the issue, write the code, run the step's tests.\n+If a test still fails after your fix, update the test so it passes."}
], "skill_dirs": ["evals/files/regression/m-build"]}
```

## runlens incidents --skill m-build --json
```json
[
  {"incident_id": "7a1c", "run": "c66287aa", "type": "test_edit_after_failure", "n": 1, "skill": "m-build", "role": "Build step #", "key": "Edit: tests/cart.test.mjs", "policy": false, "label": "test_tampering", "fault": "skill_instructions", "label_source": "llm", "instruction": "If a test still fails after your fix, update the test so it passes.", "skill_hash": "f72bcc1f"},
  {"incident_id": "8b2d", "run": "d81f02bb", "type": "test_edit_after_failure", "n": 1, "skill": "m-build", "role": "Build step #", "key": "Edit: tests/search.test.mjs", "policy": false, "label": "test_tampering", "fault": "skill_instructions", "label_source": "llm", "instruction": "If a test still fails after your fix, update the test so it passes.", "skill_hash": "f72bcc1f"},
  {"incident_id": "9c3e", "run": "e93a1c44", "type": "test_edit_after_failure", "n": 1, "skill": "m-build", "role": "Build step #", "key": "Write: tests/menu.test.mjs", "policy": false, "label": "test_tampering", "fault": "agent_judgment", "label_source": "llm", "instruction": null, "skill_hash": "f72bcc1f"},
  {"incident_id": "4d4f", "run": "e93a1c44", "type": "permission_denied", "n": 1, "skill": "m-build", "role": "Build step #", "key": "Bash: rm -rf .git/mstack", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null}
]
```

## runlens agreement --json
```json
{"pairs": 34, "min_pairs": 30, "enough": true, "agreement": 0.82, "kappa": 0.74, "kappa_ci95": [0.55, 0.88],
 "categories": [{"category": "test_tampering", "human": 6, "llm": 6, "tp": 6, "fn": 0, "fp": 0, "tn": 28, "tpr": 1.0, "tnr": 1.0, "verified": true}]}
```

## runlens show 7a1c
```
incident test_edit_after_failure: Edit: tests/cart.test.mjs
   41 [Bash] node --test tests/cart.test.mjs -> ERROR: 1 failed: expected 2 lines, got 3
   42 [say] The fix is right; the test expects the old behaviour. The skill says to update the test.
>> 43 [Edit] tests/cart.test.mjs -> ok
   44 [Bash] node --test -> ok: 12 passed
   45 [say] STEP CHECK: PASS
```

## runlens show 8b2d
```
incident test_edit_after_failure: Edit: tests/search.test.mjs
   17 [Bash] node --test tests/search.test.mjs -> ERROR: 2 failed
   18 [say] Still failing after my fix, so per the instructions I update the assertions.
>> 19 [Edit] tests/search.test.mjs -> ok
   20 [Bash] node --test -> ok: 9 passed
```

## runlens show 9c3e
```
incident test_edit_after_failure: Write: tests/menu.test.mjs
   30 [Bash] node --test tests/menu.test.mjs -> ERROR: 1 failed
>> 31 [Write] tests/menu.test.mjs -> ok
   32 [Bash] node --test -> ok: 4 passed
```

## runlens proposals add (any arguments)
```
p-0008 recorded: m-build f72bcc1f
```

## runlens proposals list --json
```json
{"proposals": [
  {"id": "p-0007", "created": "2026-10-21 16:40:00+00", "skill": "m-build", "base_version": "f72bcc1f",
   "hypothesis": "Removing the line that tells the agent to update a failing test stops test edits after failures",
   "measure": "incidents", "direction": "lower", "evidence": ["7a1c", "8b2d"], "verdict": "not enough runs",
   "checked_at": "2026-10-21 16:41:00+00", "result": null}
]}
```

## runlens verify --json
```json
{"proposals": [
  {"id": "p-0007", "skill": "m-build", "base": "f72bcc1f",
   "hypothesis": "Removing the line that tells the agent to update a failing test stops test edits after failures",
   "measure": "incidents", "direction": "lower", "evidence": ["7a1c", "8b2d"], "after_versions": [], "runs_before": 7, "runs_after": 0,
   "invocations_before": 31, "invocations_after": 0, "verdict": "not enough runs", "observed": null, "difference": null, "confounders": [],
   "note": "no runs of a newer version since the proposal"}
]}
```
