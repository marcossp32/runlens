# Canned runlens output: several skills, no skill named: one worse, one confounded, one better, one too new to judge

## runlens refresh
```
6 runs archived, 6 ingested
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
{"kind": "skill", "population": {"runs": 30, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation", "units": [
  {"unit": "skill:build-step", "name": "build-step", "kind": "skill", "runs": 13, "invocations": 61, "versions": 3, "current": "v3",
   "verdict": "worse", "direction": "worse", "vs": "v2", "confounders": [],
   "outcome": {"measure": "step_check first-pass rate", "value": 0.71, "n": 61},
   "difference": {"score": 71.4, "ci95": [58.2, 88.9], "measures": {},
                  "outcome": {"a": 0.87, "b": 0.55, "value": -0.32, "ci95": [-0.51, -0.12]}}},
  {"unit": "skill:scan-repo", "name": "scan-repo", "kind": "skill", "runs": 13, "invocations": 56, "versions": 2, "current": "v2",
   "verdict": "confounded", "direction": "better", "vs": "v1",
   "confounders": ["Claude Code 2.1.283 → 2.1.293", "model mix (share of cost): opus 90% → 20%"],
   "outcome": null, "difference": {"score": 121.0, "ci95": [104.2, 139.8], "measures": {}}},
  {"unit": "skill:review-pr", "name": "review-pr", "kind": "skill", "runs": 17, "invocations": 17, "versions": 3, "current": "v3",
   "verdict": "better", "direction": "better", "vs": "v2", "confounders": [], "outcome": null,
   "difference": {"score": 118.0, "ci95": [104.0, 133.0], "measures": {}}},
  {"unit": "skill:plan-feature", "name": "plan-feature", "kind": "skill", "runs": 5, "invocations": 5, "versions": 2, "current": "v2",
   "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [], "outcome": null,
   "difference": {"score": 61.0, "ci95": null, "measures": {}}}
]}
```

## runlens versions build-step --json
```json
{"skill": "build-step", "unit": "skill:build-step", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:build-step@33e62960", "label": "v2", "hash": "33e62960", "runs": 6, "invocations": 30, "score": 112.4,
   "verdict": null, "vs": null, "confounders": [], "difference": null,
   "outcome": {"measure": "step_check first-pass rate", "value": 0.87, "n": 30}},
  {"id": "skill:build-step@f72bcc1f", "label": "v3", "hash": "f72bcc1f", "runs": 7, "invocations": 31, "score": 80.3,
   "verdict": "worse", "direction": "worse", "vs": "v2", "confounders": [],
   "difference": {"score": 71.4, "ci95": [58.2, 88.9],
                  "measures": {"outcome": {"a": 0.87, "b": 0.55, "effect": 0.36, "ci95": [0.21, 0.71]}},
                  "outcome": {"a": 0.87, "b": 0.55, "value": -0.32, "ci95": [-0.51, -0.12]}},
   "outcome": {"measure": "step_check first-pass rate", "value": 0.55, "n": 31},
   "diff": "@@ -8 +8,2 @@\n Read the issue, write the code, run the step's tests.\n+If a test still fails after your fix, update the test so it passes."}
], "skill_dirs": ["evals/files/regression/build-step"]}
```

## runlens versions scan-repo --json
```json
{"skill": "scan-repo", "unit": "skill:scan-repo", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:scan-repo@9e8d7c6b", "label": "v1", "hash": "9e8d7c6b", "runs": 7, "invocations": 30, "score": 91.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:scan-repo@5a4b3c2d", "label": "v2", "hash": "5a4b3c2d", "runs": 6, "invocations": 26, "score": 110.0,
   "verdict": "confounded", "direction": "better", "vs": "v1",
   "confounders": ["Claude Code 2.1.283 → 2.1.293", "model mix (share of cost): opus 90% → 20%"],
   "difference": {"score": 121.0, "ci95": [104.2, 139.8], "measures": {}}, "outcome": null}
]}
```

## runlens versions review-pr --json
```json
{"skill": "review-pr", "unit": "skill:review-pr", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:review-pr@a0a0a0a0", "label": "v2", "hash": "a0a0a0a0", "runs": 8, "invocations": 8, "score": 100.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:review-pr@b1b1b1b1", "label": "v3", "hash": "b1b1b1b1", "runs": 9, "invocations": 9, "score": 118.0,
   "verdict": "better", "direction": "better", "vs": "v2", "confounders": [],
   "difference": {"score": 118.0, "ci95": [104.0, 133.0], "measures": {}}, "outcome": null}
]}
```

## runlens versions plan-feature --json
```json
{"skill": "plan-feature", "unit": "skill:plan-feature", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:plan-feature@0c1d2e3f", "label": "v1", "hash": "0c1d2e3f", "runs": 3, "invocations": 3, "score": 118.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null, "measures": {"cost": 1.9}},
  {"id": "skill:plan-feature@4a5b6c7d", "label": "v2", "hash": "4a5b6c7d", "runs": 2, "invocations": 2, "score": 79.0,
   "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [],
   "difference": {"score": 61.0, "ci95": null, "measures": {"cost": {"a": 1.9, "b": 6.4, "effect": 0.5, "ci95": null}}},
   "outcome": null, "measures": {"cost": 6.4}}
]}
```

## runlens incidents --skill build-step --json
```json
[
  {"incident_id": "7a1c", "run": "c66287aa", "type": "test_edit_after_failure", "n": 1, "skill": "build-step", "role": "Build step #", "key": "Edit: tests/cart.test.mjs", "policy": false, "label": "test_tampering", "fault": "skill_instructions", "label_source": "llm", "instruction": "If a test still fails after your fix, update the test so it passes.", "skill_hash": "f72bcc1f"},
  {"incident_id": "8b2d", "run": "d81f02bb", "type": "test_edit_after_failure", "n": 1, "skill": "build-step", "role": "Build step #", "key": "Edit: tests/search.test.mjs", "policy": false, "label": "test_tampering", "fault": "skill_instructions", "label_source": "llm", "instruction": "If a test still fails after your fix, update the test so it passes.", "skill_hash": "f72bcc1f"},
  {"incident_id": "9c3e", "run": "e93a1c44", "type": "test_edit_after_failure", "n": 1, "skill": "build-step", "role": "Build step #", "key": "Write: tests/menu.test.mjs", "policy": false, "label": "test_tampering", "fault": "agent_judgment", "label_source": "llm", "instruction": null, "skill_hash": "f72bcc1f"},
  {"incident_id": "4d4f", "run": "e93a1c44", "type": "permission_denied", "n": 1, "skill": "build-step", "role": "Build step #", "key": "Bash: rm -rf .git/scratch", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null}
]
```

## runlens incidents --skill review-pr --json
```json
[
  {"incident_id": "f1", "run": "c66287aa", "type": "error_streak", "n": 3, "skill": "review-pr", "role": "main", "key": "Bash", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null}
]
```

## runlens incidents --skill scan-repo --json
```json
[
]
```

## runlens incidents --skill plan-feature --json
```json
[
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

## runlens show f1
```
incident error_streak: 3 errors in a row, Bash
   11 [Bash] npm test -> ERROR: ECONNRESET registry.npmjs.org
   12 [Bash] npm test -> ERROR: ECONNRESET registry.npmjs.org
>> 13 [Bash] npm test -> ERROR: ECONNRESET registry.npmjs.org
   14 [Bash] npm test -> ok: 31 passed
```

## runlens proposals list --json
```json
{"proposals": []}
```

## runlens verify --json
```json
{"proposals": []}
```

## runlens proposals add (any arguments)
```
p-0007 recorded: build-step f72bcc1f
```
