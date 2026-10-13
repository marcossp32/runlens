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
{"kind": "skill", "units": [{"unit": "skill:m-build", "runs": 13, "invocations": 61}]}
```
