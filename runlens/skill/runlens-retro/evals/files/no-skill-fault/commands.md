# Canned runlens output: no skill_instructions faults, no human labels

## runlens refresh
```
0 new runs
```

## runlens check
```
ok   13 runs match the transcripts
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 13, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-prove", "name": "m-prove", "kind": "skill", "runs": 13, "invocations": 46, "versions": 2, "current": "v2",
            "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [], "outcome": null,
            "difference": {"score": 97.2, "ci95": null, "measures": {}}}]}
```

## runlens versions m-prove --json
```json
{"skill": "m-prove", "unit": "skill:m-prove", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:m-prove@a1b2c3d4", "label": "v1", "hash": "a1b2c3d4", "runs": 9, "invocations": 31, "score": 101.3,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:m-prove@e5f6a7b8", "label": "v2", "hash": "e5f6a7b8", "runs": 4, "invocations": 15, "score": 97.0,
   "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [],
   "difference": {"score": 95.8, "ci95": null, "measures": {}}, "outcome": null}
]}
```

## runlens incidents --skill m-prove
```
incident_id  run       type               n   skill    role        key
b1           c66287aa  idle_loop          9   m-prove  Supervisor  9 idle calls, e.g. sleep 60
b2           d81f02bb  idle_loop          14  m-prove  Supervisor  14 idle calls, e.g. Start-Sleep -Seconds 120
b3           e93a1c44  idle_loop          6   m-prove  Supervisor  6 idle calls, e.g. sleep 90; echo waiting
b4           e93a1c44  permission_denied  1   m-prove  Prover      Bash: rm -rf .git/mstack/prove
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "agreement": null, "kappa": null, "kappa_ci95": null, "categories": []}
```

## Labels of these incidents (any `runlens sql` over `labels`)
```
incident_id  category            fault                   instruction
b1           busy_waiting        agent_judgment
b2           busy_waiting        agent_judgment
b3           busy_waiting        agent_judgment
b4           permission_blocked  tooling_or_environment
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
incident permission_denied: Bash: rm -rf .git/mstack/prove
>> 30 [Bash] rm -rf .git/mstack/prove -> ERROR denied: blocked by a permission rule
```

## runlens sql "SELECT DISTINCT skill_dir FROM skill_loads WHERE skill = 'm-prove'"
```
evals/files/no-skill-fault/m-prove
```

## runlens proposals add (any arguments)
```
p-0011 recorded: m-prove a1b2c3d4
```

## runlens verify --json
```json
{"proposals": []}
```
