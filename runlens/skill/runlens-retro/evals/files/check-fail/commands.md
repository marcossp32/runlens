# Canned runlens output: check FAIL

## runlens refresh
```
2 runs archived, 2 ingested
```

## runlens check
```
FAIL 27efa8c1  api_calls: database 812, transcripts 3911
FAIL 27efa8c1  tool_calls: database 640, transcripts 3052
ok   12 other runs match the transcripts
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 13, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-build", "name": "m-build", "kind": "skill", "runs": 13, "invocations": 61, "versions": 2, "current": "v2",
            "verdict": "no clear change", "direction": "no clear change", "vs": "v1", "confounders": [], "outcome": null,
            "difference": {"score": 104.0, "ci95": [88.1, 121.9], "measures": {}}}]}
```
