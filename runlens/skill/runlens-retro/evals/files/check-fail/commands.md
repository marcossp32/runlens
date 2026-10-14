# Canned runlens output: check FAIL

## runlens refresh
```
2 runs archived, 2 ingested
```

## runlens check
```
ok    c66287aa  agents=3 api=210 tools=150 cost=4.10 output tokens 98% of cost-state
FAIL  27efa8c1  api_calls: raw 3911 vs db 812; tool_calls: raw 3052 vs db 640; agents=4 api=812 tools=640 cost=41.20
ok    d81f02bb  agents=2 api=95 tools=61 cost=1.35 output tokens 97% of cost-state
1 problem(s)
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 13, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-build", "name": "m-build", "kind": "skill", "runs": 13, "invocations": 61, "versions": 2, "current": "v2",
            "verdict": "no clear change", "direction": "no clear change", "vs": "v1", "confounders": [], "outcome": null,
            "difference": {"score": 104.0, "ci95": [88.1, 121.9], "measures": {}}}]}
```
