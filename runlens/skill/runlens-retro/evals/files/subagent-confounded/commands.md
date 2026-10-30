# Canned runlens output: a skill that only loads in subagents (it has its own unit), with a confounded version

## runlens refresh
```
0 new runs
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
  {"unit": "skill:ship-feature", "name": "ship-feature", "kind": "skill", "runs": 13, "invocations": 13, "versions": 1, "current": "v1",
   "verdict": null, "direction": null, "vs": null, "confounders": [], "outcome": null, "difference": null},
  {"unit": "skill:build-step", "name": "build-step", "kind": "skill", "runs": 13, "invocations": 61, "versions": 1, "current": "v1",
   "verdict": null, "direction": null, "vs": null, "confounders": [], "outcome": null, "difference": null},
  {"unit": "skill:scan-repo", "name": "scan-repo", "kind": "skill", "runs": 13, "invocations": 56, "versions": 2, "current": "v2",
   "verdict": "confounded", "direction": "better", "vs": "v1",
   "confounders": ["Claude Code 2.1 → 2.2", "model mix: claude-opus-5-5 90% → 20% of main-agent cost"],
   "outcome": null, "difference": {"score": 121.0, "ci95": [104.2, 139.8], "measures": {}}}
]}
```

## runlens sql "SELECT agent_id = 'main' AS in_main, count(*) FROM skill_loads WHERE skill = 'scan-repo' GROUP BY 1"
```
in_main  count
false    56
```

## runlens versions scan-repo --json
```json
{"skill": "scan-repo", "unit": "skill:scan-repo", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:scan-repo@9e8d7c6b", "label": "v1", "hash": "9e8d7c6b", "runs": 7, "invocations": 30, "score": 91.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:scan-repo@5a4b3c2d", "label": "v2", "hash": "5a4b3c2d", "runs": 6, "invocations": 26, "score": 110.0,
   "verdict": "confounded", "direction": "better", "vs": "v1",
   "confounders": ["Claude Code 2.1 → 2.2", "model mix: claude-opus-5-5 90% → 20% of main-agent cost"],
   "difference": {"score": 121.0, "ci95": [104.2, 139.8], "measures": {}}, "outcome": null}
]}
```

## runlens incidents --skill scan-repo --json
```json
[
  {"incident_id": "c1", "run": "c66287aa", "type": "error_streak", "n": 3, "skill": "scan-repo", "role": "Scan", "key": "Grep: other", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null},
  {"incident_id": "c2", "run": "d81f02bb", "type": "error_streak", "n": 2, "skill": "scan-repo", "role": "Scan", "key": "Bash: not_found", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null}
]
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "categories": []}
```

## runlens show c1
```
incident error_streak: Grep: other
    4 [Grep] pattern=useCart -> ERROR: path not found: src/
    5 [Grep] pattern=useCart path=app/ -> ERROR: path not found: app/
>>  6 [Grep] pattern=useCart path=lib/ -> ERROR: path not found: lib/
    7 [Glob] **/*.js -> ok: assets/cart.js ...
```

## runlens show c2
```
incident error_streak: Bash: not_found
    2 [Bash] rg useCart -> ERROR not_found: rg: command not found
>>  3 [Bash] rg -n useCart . -> ERROR not_found: rg: command not found
    4 [Grep] pattern=useCart -> ok
```

## runlens verify --json
```json
{"proposals": []}
```
