# Canned runlens output: not enough runs

## runlens refresh
```
1 run archived, 1 ingested
```

## runlens check
```
ok   5 runs match the transcripts
```

## runlens score --kind skill --json
```json
{"kind": "skill", "units": [{"unit": "skill:m-plan", "runs": 5, "invocations": 5, "outcome": null}]}
```

## runlens versions m-plan --json
```json
{"skill": "m-plan", "versions": [
  {"label": "v1", "hash": "0c1d2e3f", "runs": 3, "invocations": 3, "verdict": null, "cost_per_run_usd": 1.9},
  {"label": "v2", "hash": "4a5b6c7d", "runs": 2, "invocations": 2, "vs": "v1", "verdict": "not enough runs",
   "cost_per_run_usd": 6.4, "confounders": []}
]}
```

## runlens incidents --skill m-plan
```
(no incidents)
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "categories": []}
```

## runlens verify --json
```json
{"proposals": [{"id": "p-0003", "skill": "m-plan", "base": "0c1d2e3f", "measure": "cost per run", "direction": "lower",
  "verdict": "not enough runs", "runs_after": 2}]}
```
