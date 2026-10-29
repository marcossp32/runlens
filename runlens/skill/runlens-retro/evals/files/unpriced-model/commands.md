# Canned runlens output: a model with no price (a FAIL that is not a data problem)

## runlens refresh
```
2 runs archived, 2 ingested
```

## runlens check
```
ok    c66287aa  agents=3 api=210 tools=150 cost=4.10 output tokens 98% of cost-state
FAIL  d81f02bb  3 api call(s) without a cost: no price for claude-nova-9 (add it under [prices]); agents=2 api=95 tools=61 cost=1.35
1 problem(s)
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 13, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-build", "name": "m-build", "kind": "skill", "runs": 13, "invocations": 61, "versions": 3, "current": "v3",
            "verdict": "no clear change", "direction": "no clear change", "vs": "v2", "confounders": [],
            "outcome": {"measure": "step_check first-pass rate", "value": 0.8, "n": 61},
            "difference": {"score": 99.0, "ci95": [86.0, 114.0], "measures": {}}}]}
```

## runlens versions m-build --json
```json
{"skill": "m-build", "unit": "skill:m-build", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:m-build@33e62960", "label": "v2", "hash": "33e62960", "runs": 6, "invocations": 30, "score": 100.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null, "outcome": null},
  {"id": "skill:m-build@f72bcc1f", "label": "v3", "hash": "f72bcc1f", "runs": 7, "invocations": 31, "score": 99.0,
   "verdict": "no clear change", "direction": "no clear change", "vs": "v2", "confounders": [],
   "difference": {"score": 99.0, "ci95": [86.0, 114.0], "measures": {}}, "outcome": null}
]}
```

## runlens incidents --skill m-build --json
```json
[
]
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "categories": []}
```

## runlens verify --json
```json
{"proposals": []}
```
