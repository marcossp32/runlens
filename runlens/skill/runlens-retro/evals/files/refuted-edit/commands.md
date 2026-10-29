# Canned runlens output: an earlier edit was refuted, and the new failures trace back to that same edit

## runlens refresh
```
5 runs archived, 5 ingested
```

## runlens check
```
ok    c66287aa  agents=3 api=210 tools=150 cost=4.10 output tokens 98% of cost-state
ok    d81f02bb  agents=3 api=230 tools=161 cost=4.60 output tokens 98% of cost-state
all checks passed
```

## runlens score --kind skill --json
```json
{"kind": "skill", "population": {"runs": 17, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"}, "unit_of_analysis": "invocation",
 "units": [{"unit": "skill:m-review", "name": "m-review", "kind": "skill", "runs": 17, "invocations": 17, "versions": 2, "current": "v3",
            "verdict": "no clear change", "direction": null, "vs": "v2", "confounders": [],
            "outcome": {"measure": "review_check complete rate", "value": 0.67, "n": 9},
            "difference": {"score": 91.0, "ci95": [74.0, 108.0], "measures": {}}}]}
```

## runlens versions m-review --json
```json
{"skill": "m-review", "unit": "skill:m-review", "unit_of_analysis": "invocation", "versions": [
  {"id": "skill:m-review@a0a0a0a0", "label": "v2", "hash": "a0a0a0a0", "runs": 8, "invocations": 8, "score": 104.0,
   "verdict": null, "vs": null, "confounders": [], "difference": null,
   "outcome": {"measure": "review_check complete rate", "value": 0.88, "n": 8}},
  {"id": "skill:m-review@b1b1b1b1", "label": "v3", "hash": "b1b1b1b1", "runs": 9, "invocations": 9, "score": 95.0,
   "verdict": "no clear change", "direction": null, "vs": "v2", "confounders": [],
   "difference": {"score": 91.0, "ci95": [74.0, 108.0], "measures": {}},
   "outcome": {"measure": "review_check complete rate", "value": 0.67, "n": 9},
   "diff": "@@ -9 +9,2 @@\n Report each finding with the file and line it concerns.\n+Stop after 5 comments; summarise the rest in one line."}
], "skill_dirs": ["evals/files/refuted-edit/m-review"]}
```

## runlens proposals list --json
```json
{"proposals": [
  {"id": "p-0005", "created": "2026-10-02 09:12:00+00", "skill": "m-review", "base_version": "a0a0a0a0",
   "hypothesis": "Capping the review at 5 comments cuts cost", "measure": "cost", "direction": "lower", "evidence": ["4c3d", "4d4e"],
   "verdict": "refuted", "checked_at": "2026-10-20 18:00:00+00", "result": null}
]}
```

## runlens verify --json
```json
{"proposals": [
  {"id": "p-0005", "skill": "m-review", "base": "a0a0a0a0", "hypothesis": "Capping the review at 5 comments cuts cost",
   "measure": "cost", "direction": "lower", "evidence": ["4c3d", "4d4e"], "after_versions": ["v3"], "runs_before": 8, "runs_after": 9,
   "verdict": "refuted", "observed": "worse", "confounders": [],
   "difference": {"measure": "cost", "before": 2.1, "after": 2.9, "effect": 0.72, "ci95": [0.6, 0.9], "note": "effect > 1 means the after side is better on this measure"}}
]}
```

## runlens incidents --skill m-review --json
```json
[
  {"incident_id": "e1", "run": "c66287aa", "type": "bad_marker", "n": 1, "skill": "m-review", "role": "main", "key": "review_check: INCOMPLETE", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null},
  {"incident_id": "e2", "run": "d81f02bb", "type": "bad_marker", "n": 1, "skill": "m-review", "role": "main", "key": "review_check: INCOMPLETE", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null},
  {"incident_id": "e3", "run": "e93a1c44", "type": "bad_marker", "n": 1, "skill": "m-review", "role": "main", "key": "review_check: INCOMPLETE", "policy": false, "label": null, "fault": null, "label_source": null, "instruction": null, "skill_hash": null}
]
```

## runlens agreement --json
```json
{"pairs": 0, "min_pairs": 30, "enough": false, "categories": []}
```

## runlens show e1
```
incident bad_marker: review_check: INCOMPLETE
   22 [Read] src/cart.mjs -> ok
   23 [say] That is 5 comments, so I stop here and summarise: 3 more files have style nits.
>> 24 [say] REVIEW: INCOMPLETE
   25 [user] The review skipped src/checkout.mjs, which has the bug. Review the rest.
   26 [Read] src/checkout.mjs -> ok
```

## runlens show e2
```
incident bad_marker: review_check: INCOMPLETE
   15 [say] Fifth comment written. The skill caps reviews at 5, so the remaining 4 files go into one summary line.
>> 16 [say] REVIEW: INCOMPLETE
   17 [user] Please finish reading the other files.
   18 [Read] src/search.mjs -> ok
```

## runlens show e3
```
incident bad_marker: review_check: INCOMPLETE
   30 [say] Comment cap reached (5). Remaining files not read.
>> 31 [say] REVIEW: INCOMPLETE
   32 [Agent] m-review (second pass) -> ok: 4 findings
```

## runlens proposals add (any arguments)
```
p-0006 recorded: m-review b1b1b1b1
```
