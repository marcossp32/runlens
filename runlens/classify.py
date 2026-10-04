"""Label incidents with a failure taxonomy, and measure the labels against human ones.

The judge is `claude -p` with a JSON schema, so it runs on the user's own Claude
Code login and needs no API key. LLM labels are a first pass for axial coding,
not ground truth: unvalidated judges find few trace errors (TRAIL, arXiv
2505.08638). Export them, correct a sample by hand, import, and read
`runlens agreement` before trusting a category's counts.
"""
import csv
import json
import os
import shutil
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, store
from .incidents import TYPES

PRIORITY = ["bad_marker", "agent_failed", "error_streak", "test_edit_after_failure", "repeated_call", "idle_loop",
            "permission_denied", "interrupt", "api_error", "compaction"]
FAULTS = ["skill_instructions", "agent_judgment", "tooling_or_environment", "external", "none"]


def taxonomy():
    p = config.HOME / "taxonomy.toml"
    p = p if p.exists() else config.PACKAGE / "taxonomy.toml"
    return tomllib.loads(p.read_text(encoding="utf-8"))["category"]


def schema(cats):
    return {
        "type": "object", "additionalProperties": False,
        "required": ["category", "new_category", "fault", "note", "evidence", "confidence"],
        "properties": {
            "category": {"type": "string", "enum": [c["id"] for c in cats] + ["other"]},
            "new_category": {"type": "string", "description": "a short snake_case name when category is other, else empty"},
            "fault": {"type": "string", "enum": FAULTS},
            "note": {"type": "string", "description": "one or two sentences: what happened and why"},
            "evidence": {"type": "string", "description": "a short verbatim quote from the timeline"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
    }


def prompt(inc, spawn_prompt, cats):
    cat_lines = "\n".join(f"- {c['id']}: {c['definition']}" for c in cats)
    return f"""You are labeling one incident from an autonomous Claude Code run, for failure analysis.
Read the timeline and pick the single category that best explains why this incident happened.

Incident type: {inc['type']} ({TYPES.get(inc['type'], '')})
Detail: {inc['key']}  (occurrences: {inc['n']})
Agent: type={inc['agent_type']} role={inc['role']} skill={inc['skill']}

What this agent was asked to do (truncated):
{(spawn_prompt or '(main session)')[:1500]}

Timeline, oldest first. [say] is the agent's own text; [Tool] is a call and its result:
{inc['context'][:6000]}

Categories:
{cat_lines}
- other: none fits; give a short snake_case name in new_category.

Rules:
- Choose expected_behavior when nothing went wrong, e.g. a check correctly catching a real defect.
- fault says where a fix would go: skill_instructions (the instructions the agent followed caused it or failed to prevent it),
  agent_judgment (instructions were fine, the agent chose badly), tooling_or_environment, external, or none.
- evidence is a short quote copied from the timeline. Do not invent details that are not in the timeline.
- Answer only through the JSON schema."""


def judge(text, sch, model):
    env = {**os.environ, "RUNLENS_JUDGE": "1"}
    out = subprocess.run(
        [shutil.which("claude") or "claude", "-p", "--model", model, "--output-format", "json", "--no-session-persistence",
         "--tools", "", "--setting-sources", "", "--json-schema", json.dumps(sch)],
        input=text, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600, cwd=str(config.HOME))
    data = json.loads(out.stdout)
    if data.get("is_error") or not data.get("structured_output"):
        raise RuntimeError(data.get("result") or out.stderr[:300])
    return data["structured_output"], data.get("total_cost_usd") or 0


def classify(cfg, types=None, limit=20, model=None, workers=4, relabel=False):
    model = model or cfg.get("classify", {}).get("model", "sonnet")
    cats = taxonomy()
    sch = schema(cats)
    con = store.connect()
    where = ["1=1"]
    if types:
        where.append(f"i.type IN ({', '.join(repr(t) for t in types)})")
    if not relabel:
        where.append("i.incident_id NOT IN (SELECT incident_id FROM v_labels WHERE source = 'llm')")
    order = "CASE i.type " + " ".join(f"WHEN '{t}' THEN {n}" for n, t in enumerate(PRIORITY)) + " ELSE 99 END"
    rows = con.execute(f"""
        SELECT i.incident_id, i.type, i.key, i.n, i.agent_type, i.role, i.skill, i.context, a.prompt
        FROM incidents i
        LEFT JOIN agents a ON a.session_id = i.session_id AND a.agent_id = i.agent_id
        WHERE {' AND '.join(where)} ORDER BY {order}, i.ts LIMIT {int(limit)}""").fetchall()
    keys = ["incident_id", "type", "key", "n", "agent_type", "role", "skill", "context", "spawn_prompt"]
    incidents = [dict(zip(keys, r)) for r in rows]
    if not incidents:
        print("nothing to label")
        return
    spent, done = 0.0, 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for inc in incidents:
            futures[pool.submit(judge, prompt(inc, inc["spawn_prompt"], cats), sch, model)] = inc
        for fut in as_completed(futures):
            inc = futures[fut]
            try:
                label, cost = fut.result()
            except Exception as e:  # one failed judgement must not lose the others
                print(f"FAIL  {inc['incident_id']}  {e}")
                continue
            spent += cost
            done += 1
            category = label["category"] if label["category"] != "other" else f"other:{label['new_category'] or '?'}"
            con.execute("""INSERT INTO labels (incident_id, source, category, fault, confidence, note, evidence, model)
                           VALUES (?, 'llm', ?, ?, ?, ?, ?, ?)""",
                        [inc["incident_id"], category, label["fault"], label["confidence"], label["note"], label["evidence"], model])
            print(f"{inc['incident_id']}  {inc['type']:<16} {category:<26} {label['fault']:<22} {label['note'][:90]}")
    con.close()
    print(f"labeled {done}/{len(incidents)} incidents with {model}, ${spent:.2f}")


def export_labels(path):
    con = store.connect(read_only=True)
    rows = con.execute("""
        SELECT i.incident_id, i.session_id[:8], i.type, i.skill, i.role, i.key,
               l.category, l.fault, l.confidence, l.note, l.evidence, h.category, h.note, left(i.context, 3000)
        FROM incidents i
        LEFT JOIN v_labels l ON l.incident_id = i.incident_id AND l.source = 'llm'
        LEFT JOIN v_labels h ON h.incident_id = i.incident_id AND h.source = 'human'
        ORDER BY i.ts""").fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["incident_id", "run", "type", "skill", "role", "key", "llm_category", "llm_fault", "llm_confidence",
                    "llm_note", "llm_evidence", "human_category", "human_note", "context"])
        w.writerows(rows)
    print(f"{len(rows)} incidents -> {path}\nFill human_category (a taxonomy id, 'other:<name>', or the llm_category if it is right), "
          f"then: runlens labels import {path}")


def import_labels(path):
    con = store.connect()
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("human_category") or "").strip():
                con.execute("INSERT INTO labels (incident_id, source, category, note) VALUES (?, 'human', ?, ?)",
                            [row["incident_id"], row["human_category"].strip(), (row.get("human_note") or "").strip()])
                n += 1
    con.close()
    print(f"imported {n} human labels")


def agreement():
    con = store.connect(read_only=True)
    pairs = con.execute("""SELECT l.category, h.category FROM v_labels l JOIN v_labels h USING (incident_id)
                           WHERE l.source = 'llm' AND h.source = 'human'""").fetchall()
    if not pairs:
        print("no incident has both an llm and a human label yet (runlens labels export / import)")
        return
    n = len(pairs)
    agree = sum(a == b for a, b in pairs)
    cats = sorted({c for p in pairs for c in p})
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    kappa = (agree / n - pe) / (1 - pe) if pe < 1 else 1.0
    print(f"{n} incidents with both labels: agreement {agree / n:.0%}, Cohen's kappa {kappa:.2f}")
    if n < 30:
        print("fewer than 30 paired labels: too few to trust these rates")
    print(f"\n{'category':<28}{'human':>6}{'llm':>6}{'TP':>5}{'TPR':>7}{'TNR':>7}{'precision':>11}")
    for c in cats:
        tp = sum(a == c and b == c for a, b in pairs)
        fp = sum(a == c and b != c for a, b in pairs)
        fn = sum(a != c and b == c for a, b in pairs)
        tn = n - tp - fp - fn
        rate = lambda x, y: f"{x / (x + y):.0%}" if x + y else "-"
        print(f"{c:<28}{tp + fn:>6}{tp + fp:>6}{tp:>5}{rate(tp, fn):>7}{rate(tn, fp):>7}{rate(tp, fp):>11}")
    con.close()
