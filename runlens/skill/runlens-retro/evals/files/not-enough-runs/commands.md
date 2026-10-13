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
{"kind": "skill", "population": {"runs": 5, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-plan", "name": "m-plan", "kind": "skill", "runs": 5, "invocations": 5, "versions": 2, "current": "v2",
            "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [], "outcome": null,
            "difference": {"score": 61.0, "ci95": null, "measures": {}}}]}
```

## runlens versions m-plan --json
```json
{"skill": "m-plan", "unit": "skill:m-plan", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:m-plan@0c1d2e3f", "label": "v1", "hash": "0c1d2e3f", "runs": 3, "invocations": 3, "score": 118.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null, "measures": {"cost": 1.9}},
  {"id": "skill:m-plan@4a5b6c7d", "label": "v2", "hash": "4a5b6c7d", "runs": 2, "invocations": 2, "score": 79.0,
   "verdict": "not enough runs", "direction": null, "vs": "v1", "confounders": [],
   "difference": {"score": 61.0, "ci95": null, "measures": {"cost": {"a": 1.9, "b": 6.4, "effect": 0.5, "ci95": null}}},
   "outcome": null, "measures": {"cost": 6.4}}
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
{"proposals": [{"id": "p-0003", "skill": "m-plan", "base": "0c1d2e3f", "hypothesis": "Asking for the plan outline first cuts rework",
  "measure": "cost", "direction": "lower", "evidence": ["5e6f", "6f70"], "after_versions": ["v2"], "runs_before": 3, "runs_after": 2,
  "verdict": "not enough runs", "observed": null, "difference": null, "confounders": []}]}
```
