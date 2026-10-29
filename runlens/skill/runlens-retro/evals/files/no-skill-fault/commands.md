# Canned runlens output: no skill_instructions faults, no human labels

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
{"kind": "skill", "population": {"runs": 13, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:prove-change", "name": "prove-change", "kind": "skill", "runs": 13, "invocations": 46, "versions": 2, "current": "v2",
            "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [], "outcome": null,
            "difference": {"score": 97.2, "ci95": null, "measures": {}}}]}
```

## runlens versions prove-change --json
```json
{"skill": "prove-change", "unit": "skill:prove-change", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:prove-change@a1b2c3d4", "label": "v1", "hash": "a1b2c3d4", "runs": 9, "invocations": 31, "score": 101.3,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:prove-change@e5f6a7b8", "label": "v2", "hash": "e5f6a7b8", "runs": 4, "invocations": 15, "score": 97.0,
   "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [],
   "difference": {"score": 95.8, "ci95": null, "measures": {}}, "outcome": null}
], "skill_dirs": ["evals/files/no-skill-fault/prove-change"]}
```

## runlens incidents --skill prove-change --json
```json
[
  {"incident_id": "b1", "run": "c66287aa", "type": "idle_loop", "n": 9, "skill": "prove-change", "role": "Supervisor", "key": "9 idle calls, e.g. sleep 60", "policy": false, "label": "busy_waiting", "fault": "agent_judgment", "label_source": "llm", "instruction": null, "skill_hash": null},
  {"incident_id": "b2", "run": "d81f02bb", "type": "idle_loop", "n": 14, "skill": "prove-change", "role": "Supervisor", "key": "14 idle calls, e.g. Start-Sleep -Seconds 120", "policy": false, "label": "busy_waiting", "fault": "agent_judgment", "label_source": "llm", "instruction": null, "skill_hash": null},
  {"incident_id": "b3", "run": "e93a1c44", "type": "idle_loop", "n": 6, "skill": "prove-change", "role": "Supervisor", "key": "6 idle calls, e.g. sleep 90; echo waiting", "policy": false, "label": "busy_waiting", "fault": "agent_judgment", "label_source": "llm", "instruction": null, "skill_hash": null},
  {"incident_id": "b4", "run": "e93a1c44", "type": "permission_denied", "n": 1, "skill": "prove-change", "role": "Prover", "key": "Bash: rm -rf .git/scratch/prove", "policy": false, "label": "permission_blocked", "fault": "tooling_or_environment", "label_source": "llm", "instruction": null, "skill_hash": null}
]
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "agreement": null, "kappa": null, "kappa_ci95": null, "categories": []}
```

## runlens show b1
```
incident idle_loop: 9 idle calls, e.g. sleep 60
   12 [Agent] prover A (background) -> ok: launched
   13 [Agent] prover B (background) -> ok: launched
   14 [say] Waiting for both provers.
>> 15 [Bash] sleep 60 -> ok
   16 [Bash] sleep 60 -> ok
```

## runlens show b2
```
incident idle_loop: 14 idle calls
   20 [say] Both provers are running; I'll check back.
>> 21 [PowerShell] Start-Sleep -Seconds 120 -> ok
   22 [PowerShell] Start-Sleep -Seconds 120 -> ok
```

## runlens show b3
```
incident idle_loop: 6 idle calls
    8 [say] Waiting until they report.
>>  9 [Bash] sleep 90; echo waiting -> ok: waiting
```

## runlens show b4
```
incident permission_denied: Bash: rm -rf .git/scratch/prove
>> 30 [Bash] rm -rf .git/scratch/prove -> ERROR denied: blocked by a permission rule
```

## runlens proposals add (any arguments)
```
p-0011 recorded: prove-change a1b2c3d4
```

## runlens verify --json
```json
{"proposals": []}
```
