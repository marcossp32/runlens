# Canned runlens output: a skill that only runs in subagents, with a confounded version

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
{"kind": "skill", "units": [{"unit": "skill:m-feature", "runs": 13, "invocations": 13}, {"unit": "skill:m-build", "runs": 13, "invocations": 61}]}
```

## runlens sql "SELECT agent_id = 'main' AS in_main, count(*) FROM skill_loads WHERE skill = 'm-scan' GROUP BY 1"
```
in_main  count
false    56
```

## runlens versions m-scan --json
```json
{"skill": "m-scan", "unit": "invocation", "versions": [
  {"label": "v1", "hash": "9e8d7c6b", "runs": 7, "invocations": 30, "verdict": null},
  {"label": "v2", "hash": "5a4b3c2d", "runs": 6, "invocations": 26, "vs": "v1", "verdict": "confounded",
   "confounders": ["Claude Code 2.1.283 -> 2.1.293", "model mix: opus share 0.9 -> 0.2"]}
]}
```

## runlens incidents --skill m-scan
```
incident_id  run       type          n  skill   role  key
c1           c66287aa  error_streak  3  m-scan  Scan  Grep: other
c2           d81f02bb  error_streak  2  m-scan  Scan  Bash: not_found
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
