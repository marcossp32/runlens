"""Proposed skill edits, and whether the runs since then bear them out.

A retro (or a person) records a proposal before editing a skill: the skill, the version it
edits, the hypothesis, the measure that should move and in which direction, and the
incidents behind it. `verify` later compares the runs of the edited skill's newer versions
with the runs of the base version, using the same bootstrap of the difference as version
verdicts (bench.compare), and records one of:

  confirmed        the measure moved the predicted way, beyond noise
  inconclusive     no clear change: the interval holds 0, which is not evidence that the edit did nothing
                   (with a handful of runs a real effect usually looks like this)
  refuted          the measure moved the other way, and the whole interval is on that side (see `observed`)
  not enough runs  fewer than [method] min_runs runs on either side (or no newer version yet)
  confounded       something else changed between the two sides, named in `confounders`

Proposals live in the `proposals` table of the runlens database. Labels and proposals are
the only rows a re-ingest never touches.
"""
import json
import math
from datetime import datetime, timezone

from . import bench

DDL = """CREATE TABLE IF NOT EXISTS proposals (
    id VARCHAR PRIMARY KEY, created TIMESTAMPTZ, skill VARCHAR, base_version VARCHAR, hypothesis VARCHAR,
    measure VARCHAR, direction VARCHAR, evidence VARCHAR[], verdict VARCHAR, checked_at TIMESTAMPTZ, result JSON)"""
MEASURES = ("score", *bench.MEASURE)
DIRECTIONS = ("lower", "higher")
COLS = ("id", "created", "skill", "base_version", "hypothesis", "measure", "direction", "evidence", "verdict", "checked_at", "result")


def ensure(con):
    con.execute(DDL)


def _rows(con, where="", args=()):
    import duckdb
    try:
        cur = con.execute(f"SELECT {', '.join(COLS)} FROM proposals {where} ORDER BY id", list(args))
    except duckdb.CatalogException:  # a read-only connection to a database that never had a proposal
        return []
    out = []
    for r in cur.fetchall():
        d = dict(zip(COLS, r))
        d["result"] = json.loads(d["result"]) if d["result"] else None
        out.append(d)
    return out


def unit_id(name):
    """`m-build` -> `skill:m-build`; a full unit id (`group:flow`) is kept."""
    return name if ":" in name else f"skill:{name}"


def add(con, model, skill, hypothesis, measure, direction, evidence=(), base_version=None, now=None):
    """Record a proposal. The base version defaults to the skill's current version. Returns the row."""
    if measure not in MEASURES:
        raise ValueError(f"unknown measure {measure!r}; one of: {', '.join(MEASURES)}")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be 'lower' or 'higher', not {direction!r}")
    if not hypothesis or not hypothesis.strip():
        raise ValueError("a proposal needs a hypothesis")
    uid = unit_id(skill)
    versions = model["versions"].get(uid) or []
    if base_version:
        hit = [v for v in versions if any(p["hash"].startswith(base_version[:8]) for p in v["parts"]) or v["label"] == base_version]
        base = "+".join(p["hash"] for p in hit[-1]["parts"]) if hit else base_version[:8]
    elif versions:
        base = "+".join(p["hash"] for p in versions[-1]["parts"])
    else:
        raise ValueError(f"{skill!r} has no recorded runs; pass --base-version with the hash of the text you edit")
    ensure(con)
    last = con.execute("SELECT max(id) FROM proposals").fetchone()[0]
    pid = f"p-{(int(last.split('-')[1]) if last else 0) + 1:04d}"
    con.execute("INSERT INTO proposals (id, created, skill, base_version, hypothesis, measure, direction, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [pid, now or datetime.now(timezone.utc), uid.split(":", 1)[1] if uid.startswith("skill:") else uid, base,
                 hypothesis.strip(), measure, direction, list(evidence or [])])
    return _rows(con, "WHERE id = ?", [pid])[0]


def listing(con):
    return _rows(con)


def check(model, p, min_runs=None):
    """The verdict of one proposal against the model: before = runs of the base version, after = runs of
    versions first used after the proposal was made."""
    uid = unit_id(p["skill"])
    unit = next((u for u in model["units"] if u["id"] == uid), None)
    versions = model["versions"].get(uid) or []
    runs = model["runs"].get(uid) or []
    min_runs = min_runs or model["method"]["min_runs"]
    created = p["created"]
    base_hashes = p["base_version"].split("+")
    is_base = lambda v: [x["hash"] for x in v["parts"]] == base_hashes
    before = [v for v in versions if is_base(v)]
    after = [v for v in versions if not is_base(v) and v["first_seen"] and _ts(v["first_seen"]) >= _ts(created)]
    rows_a = [r for r in runs if r["version"] in {v["label"] for v in before}]
    rows_b = [r for r in runs if r["version"] in {v["label"] for v in after}]
    out = {"id": p["id"], "skill": p["skill"], "base": p["base_version"], "hypothesis": p["hypothesis"],
           "measure": p["measure"], "direction": p["direction"], "evidence": p["evidence"],
           "after_versions": [v["label"] for v in after], "runs_before": bench.n_runs(rows_a), "runs_after": bench.n_runs(rows_b),
           "invocations_before": sum(r["invocations"] for r in rows_a), "invocations_after": sum(r["invocations"] for r in rows_b),
           "verdict": "not enough runs", "observed": None, "difference": None, "confounders": []}
    if unit is None or not rows_a or not rows_b:
        out["note"] = "no runs of the base version" if not rows_a else "no runs of a newer version since the proposal"
        return out
    if p["measure"] != "score" and p["measure"] not in unit["baseline"]:
        out["note"] = f"{p['measure']} is not measured for {p['skill']} (no data, or no [outcome] configured)"
        return out
    weights = dict(unit["weights"])
    if p["measure"] != "score":
        weights.setdefault(p["measure"], 1.0)
    enough = out["runs_before"] >= min_runs and out["runs_after"] >= min_runs
    res = bench.compare(rows_a, rows_b, unit["baseline"], unit["pseudo"], weights, f"{p['id']}|{uid}",
                        model["method"]["resamples"], model["method"]["confidence"], interval=enough)
    ctx_conf = _confounders(model, uid, versions, before, after)
    if p["measure"] == "score":
        value = 100 * math.exp(res["d"]) if res["d"] is not None else None
        ci = [100 * math.exp(x) for x in res["ci"]] if res["ci"] else None
        moved = None if not ci else "better" if ci[0] > 100 else "worse" if ci[1] < 100 else "no clear change"
        out["difference"] = {"measure": "score", "value": value, "ci95": ci}
    else:
        m = res["measures"].get(p["measure"])
        if not m:
            out["note"] = f"{p['measure']} has no data on one side"
            return out
        moved = None if not m["ci"] else "better" if m["ci"][0] > 1 else "worse" if m["ci"][1] < 1 else "no clear change"
        out["difference"] = {"measure": p["measure"], "before": m["a"], "after": m["b"], "effect": m["effect"], "ci95": m["ci"],
                             "note": "effect > 1 means the after side is better on this measure"}
        if p["measure"] == "outcome" and res["outcome"]:
            out["difference"]["value"] = res["outcome"]["value"]
            out["difference"]["value_ci95"] = res["outcome"]["ci"]
    out["confounders"] = ctx_conf
    if not enough or moved is None:
        return out
    predicted_better = (p["direction"] == "higher") == (p["measure"] in ("score", "outcome"))
    hit = moved == ("better" if predicted_better else "worse")
    out["observed"] = moved
    out["verdict"] = "confounded" if ctx_conf else ("confirmed" if hit else "inconclusive" if moved == "no clear change" else "refuted")
    return out


def _confounders(model, uid, versions, before, after):
    """What else changed between the base version and the newer ones, as the model found it: the direct pairs
    when the model compared them, else every consecutive pair from the base to the newest version checked."""
    labels_a = {v["label"] for v in before}
    labels_b = {v["label"] for v in after}
    pairs = model["pairs"].get(uid, [])
    direct = [x for x in pairs if x["a"] in labels_a and x["b"] in labels_b]
    if not direct:
        order = [v["label"] for v in versions]
        lo = min(order.index(x) for x in labels_a)
        hi = max(order.index(x) for x in labels_b)
        span = set(order[lo:hi + 1])
        direct = [x for x in pairs if x["vs_previous"] and x["a"] in span and x["b"] in span]
    out = []
    for x in direct:
        out += [c for c in x["confounders"] if c not in out]
    return out


def _ts(x):
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(x).replace("Z", "+00:00"))


def verify(con, model, pid=None, now=None):
    """Check one proposal (or every one) and store each verdict. Returns the results."""
    ensure(con)
    ps = _rows(con, "WHERE id = ?", [pid]) if pid else _rows(con)
    if pid and not ps:
        raise ValueError(f"no proposal {pid!r}; `runlens proposals list` shows them")
    results = []
    for p in ps:
        r = check(model, p)
        con.execute("UPDATE proposals SET verdict = ?, checked_at = ?, result = ? WHERE id = ?",
                    [r["verdict"], now or datetime.now(timezone.utc), json.dumps(r, default=str), p["id"]])
        results.append(r)
    return results
