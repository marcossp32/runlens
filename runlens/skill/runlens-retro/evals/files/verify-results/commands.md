# Canned runlens output: verify with a confirmed and a refuted proposal

## runlens refresh
```
4 runs archived, 4 ingested
```

## runlens check
```
ok    c66287aa  agents=3 api=210 tools=150 cost=4.10 output tokens 98% of cost-state
all checks passed
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 17, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-review", "name": "m-review", "kind": "skill", "runs": 17, "invocations": 17, "versions": 3, "current": "v3",
            "verdict": "better", "direction": "better", "vs": "v2", "confounders": [], "outcome": null,
            "difference": {"score": 118.0, "ci95": [104.0, 133.0], "measures": {}}}]}
```

## runlens versions m-review --json
```json
{"skill": "m-review", "unit": "skill:m-review", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:m-review@a0a0a0a0", "label": "v2", "hash": "a0a0a0a0", "runs": 8, "invocations": 8, "score": 100.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:m-review@b1b1b1b1", "label": "v3", "hash": "b1b1b1b1", "runs": 9, "invocations": 9, "score": 118.0,
   "verdict": "better", "direction": "better", "vs": "v2", "confounders": [],
   "difference": {"score": 118.0, "ci95": [104.0, 133.0], "measures": {}}, "outcome": null}
]}
```

## runlens incidents --skill m-review
```
incident_id  run  type  n  skill  role  key  policy
-----------  ---  ----  -  -----  ----  ---  ------
(0 rows)
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "categories": []}
```

## runlens verify --json
```json
{"proposals": [
  {"id": "p-0004", "skill": "m-review", "base": "a0a0a0a0", "hypothesis": "Reading the tests before the diff cuts missed regressions",
   "measure": "incidents", "direction": "lower", "evidence": ["3a1f", "3b2e"], "after_versions": ["v3"], "runs_before": 8, "runs_after": 9,
   "verdict": "confirmed", "observed": "better", "confounders": [],
   "difference": {"measure": "incidents", "before": 0.6, "after": 0.2, "effect": 3.0, "ci95": [1.4, 6.5], "note": "effect > 1 means the after side is better on this measure"}},
  {"id": "p-0005", "skill": "m-review", "base": "a0a0a0a0", "hypothesis": "Capping the review at 5 comments cuts cost",
   "measure": "cost", "direction": "lower", "evidence": ["4c3d", "4d4e"], "after_versions": ["v3"], "runs_before": 8, "runs_after": 9,
   "verdict": "refuted", "observed": "worse", "confounders": [],
   "difference": {"measure": "cost", "before": 2.1, "after": 2.9, "effect": 0.72, "ci95": [0.6, 0.9], "note": "effect > 1 means the after side is better on this measure"}}
]}
```
