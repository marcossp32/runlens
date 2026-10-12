"""Autonomous benchmarks of skills, agent roles and groups, computed from the database alone.

Nothing is labelled by hand. Every skill that ran has its own unit, every agent role has
one, and each group in config.toml is a unit of its own. A unit's runs are split into
versions by the skill text that ran (see `compute`), and each version gets a score with
an interval, so a change to a skill can be compared with what came before.

The score is 100 x the weighted geometric mean of each metric's ratio to the average run
of the same kind: 100 is average, above 100 is better. Before the ratio is taken, a unit's
mean is shrunk toward that average, so a few runs cannot push it far from 100. Each ratio
is clipped to [1/2, 2], so one extreme metric cannot dominate. The interval is the 5th to
95th percentile of the score over resamples of the unit's runs.
"""
import bisect
import difflib
import math
import random
import re
from collections import defaultdict
from datetime import datetime, timezone

KINDS = ("skill", "agent", "group")
METRICS = [
    {"key": "cost", "label": "Cost per run", "unit": "usd", "weight": 3, "kinds": KINDS,
     "what": "Model spend attributed to the unit, averaged over its runs."},
    {"key": "seconds", "label": "Time per run", "unit": "s", "weight": 2, "kinds": KINDS,
     "what": "Time attributed to the unit: from each of its model turns to the next, capped per turn."},
    {"key": "error_rate", "label": "Tool error rate", "unit": "rate", "weight": 2, "kinds": KINDS,
     "what": "Failing tool calls over all its tool calls, averaged over runs."},
    {"key": "incidents", "label": "Incidents per run", "unit": "count", "weight": 2, "kinds": KINDS,
     "what": "Incidents of any type: error streaks, repeated calls, interrupts, failed agents and so on."},
    {"key": "interventions", "label": "Human prompts per run", "unit": "count", "weight": 2, "kinds": ("skill", "group"),
     "what": "Human prompts sent while the unit was the active skill. Agent roles get no prompts, so they are not scored on this."},
    {"key": "idle_rate", "label": "Idle call rate", "unit": "rate", "weight": 1, "kinds": KINDS,
     "what": "Tool calls that only wait or print, over all its tool calls."},
    {"key": "api_error_rate", "label": "API error rate", "unit": "rate", "weight": 1, "kinds": KINDS,
     "what": "API error messages over its model turns."},
    {"key": "bad_markers", "label": "Bad markers per run", "unit": "count", "weight": 1, "kinds": KINDS,
     "what": "Config markers whose value is declared bad, such as a failed check printed by the flow."},
]
SHRINK = 3        # pseudo-runs at the average that every unit starts with
MAX_RATIO = 2.0   # each metric's ratio to the average is clipped to [1 / MAX_RATIO, MAX_RATIO]
FLOOR = 0.01      # fraction of the average added to both sides of a ratio, so zero values stay finite
TURN_CAP = 600.0  # seconds: the gap between two model turns counts for at most this long
RESAMPLES = 200   # bootstrap resamples per interval
MIN_RUNS = 5      # below this many runs a score is flagged as low sample
DIFF_LINES = 800  # longest diff kept per changed skill
CLIP_LOG = math.log(MAX_RATIO)
NEVER = datetime.min.replace(tzinfo=timezone.utc)
FAR = datetime.max.replace(tzinfo=timezone.utc)


# ---- the score -------------------------------------------------------------------------

def unit_score(values, ref, kind):
    """`values`: one dict per run, metric -> number or None. `ref`: metric -> average over
    every run of this kind. Returns the score and its per-metric detail, or None if no
    metric has data."""
    metrics, acc, weight = {}, 0.0, 0.0
    for m in METRICS:
        key, avg = m["key"], ref.get(m["key"])
        if kind not in m["kinds"] or not avg:
            continue
        xs = [v[key] for v in values if v.get(key) is not None]
        if not xs:
            continue
        n, mean = len(xs), sum(xs) / len(xs)
        counted = (n * mean + SHRINK * avg) / (n + SHRINK)
        floor = FLOOR * avg
        log_ratio = min(CLIP_LOG, max(-CLIP_LOG, math.log((avg + floor) / (counted + floor))))
        metrics[key] = {"value": mean, "counted": counted, "n": n, "ref": avg,
                        "ratio": math.exp(log_ratio), "weight": m["weight"]}
        acc += m["weight"] * log_ratio
        weight += m["weight"]
    if not weight:
        return None
    return {"score": 100 * math.exp(acc / weight), "metrics": metrics}


def quantile(xs, q):
    """Linear interpolation between the sorted values xs."""
    i = q * (len(xs) - 1)
    lo = math.floor(i)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (i - lo)


def scored(runs, ref, kind, seed, resamples=RESAMPLES):
    """Score of a set of runs plus its 5-95% interval. The seed makes the interval repeatable."""
    values = [r["values"] for r in runs]
    base = unit_score(values, ref, kind)
    if base is None:
        return None
    ci, n = None, len(values)
    if n > 1:
        rng, draws = random.Random(seed), []
        for _ in range(resamples):
            s = unit_score([values[rng.randrange(n)] for _ in range(n)], ref, kind)
            if s:
                draws.append(s["score"])
        draws.sort()
        if draws:
            ci = [quantile(draws, 0.05), quantile(draws, 0.95)]
    return {"score": base["score"], "ci": ci, "metrics": base["metrics"]}


def references(records):
    """The average of each metric over every run of each kind: the 100 mark."""
    sums = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    for kind, values in records:
        for key, x in values.items():
            if x is not None:
                cell = sums[kind][key]
                cell[0] += x
                cell[1] += 1
    return {kind: {key: s / n for key, (s, n) in per.items()} for kind, per in sums.items()}


def overlaps(a, b):
    """True if two intervals overlap, None if either is missing."""
    if not a or not b:
        return None
    return a[0] <= b[1] and b[0] <= a[1]


# ---- versions and diffs ----------------------------------------------------------------

def short(digest):
    """A version's display name: its hash, or 'unversioned' when Claude Code never recorded the skill text."""
    return "unversioned" if digest is None else digest[:8]


def version_key(vmap):
    """A run's version: the version of each skill it belongs to, as one string."""
    if not vmap:
        return "-"
    return "|".join(f"{s}={h or 'unversioned'}" for s, h in sorted(vmap.items()))


def diff_entry(skill, old, new, texts):
    """What changed for one skill between two versions: counts and the diff lines."""
    entry = {"skill": skill, "from": short(old), "to": short(new),
             "added": 0, "removed": 0, "lines": None, "truncated": False, "note": None}
    old_text = texts.get((skill, old)) if old else None
    new_text = texts.get((skill, new)) if new else None
    if not old or not new:
        entry["note"] = "There is no earlier version of this skill in your history, so there is nothing to diff against."
    elif old_text is None or new_text is None:
        entry["note"] = "The text of this version is not recorded yet. Run `runlens refresh` to record it."
    else:
        raw = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), n=2, lineterm=""))[2:]
        lines = []
        for line in raw:
            if line.startswith("@@"):
                lines.append(["@", line])
            elif line.startswith("+"):
                lines.append(["+", line[1:]])
                entry["added"] += 1
            elif line.startswith("-"):
                lines.append(["-", line[1:]])
                entry["removed"] += 1
            else:
                lines.append([" ", line[1:]])
        entry["truncated"] = len(lines) > DIFF_LINES
        entry["lines"] = lines[:DIFF_LINES]
    return entry


def changes(prev, cur, texts):
    """The skills whose version differs between two version maps."""
    return [diff_entry(s, prev.get(s), cur.get(s), texts)
            for s in sorted(set(prev) | set(cur)) if prev.get(s) != cur.get(s)]


# ---- groups ----------------------------------------------------------------------------

def parse_groups(groups):
    """Validate the [[group]] tables. A member is "skill:<name>" or "agent:<type>"."""
    out, seen = [], set()
    for g in groups or []:
        name = str(g.get("name") or "").strip()
        members = g.get("members") or []
        if not name or not members:
            raise ValueError("every [[group]] needs a name and at least one member")
        if name in seen:
            raise ValueError(f"group {name!r} is defined twice")
        seen.add(name)
        skills, types, listed = set(), set(), []
        for m in members:
            kind, _, value = str(m).partition(":")
            value = value.strip()
            if kind == "skill" and value:
                skills.add(value)
                listed.append(f"skill:{value}")
            elif kind == "agent" and value:
                types.add(value)
                listed.append(f"agent:{value}")
            else:
                raise ValueError(f"group {name!r}: member {m!r} must be 'skill:<name>' or 'agent:<type>'")
        out.append({"id": f"group:{name}", "name": name, "skills": skills, "types": types, "members": listed})
    return out


# ---- the computation -------------------------------------------------------------------

def compute(data, groups=(), resamples=RESAMPLES):
    """`data` holds the rows read by `load`. Returns the model the dashboard renders."""
    groups = parse_groups(groups)
    group_of = {g["id"]: g for g in groups}
    sessions = {r["session_id"]: r for r in data["runs"]}
    texts = {(t["skill"], t["content_hash"]): t["text"] for t in data.get("texts", [])}

    agent_of, agent_desc = {}, {}
    for a in data["agents"]:
        ident = (a["agent_type"] or "?", a["role"] or "-")
        if a["agent_id"] != "main":
            agent_of[(a["session_id"], a["agent_id"])] = ident
        agent_desc.setdefault((a["session_id"], *ident), a.get("description"))

    # Skill versions. A run uses the version it loaded; a run that never loaded a skill
    # (it inherited it from its parent) uses the version that was current when it started.
    loads = defaultdict(list)
    latest, first_args = {}, {}
    for r in sorted((x for x in data["loads"] if x["ts"]), key=lambda x: x["ts"]):
        loads[r["skill"]].append((r["ts"], r["content_hash"]))
        k = (r["session_id"], r["skill"])
        latest[k] = r["content_hash"]
        if r.get("args"):
            first_args.setdefault(k, r["args"])
    load_ts = {s: [t for t, _ in v] for s, v in loads.items()}

    def version_before(skill, ts):
        if ts is None or skill not in loads:
            return None
        i = bisect.bisect_right(load_ts[skill], ts)
        return loads[skill][i - 1][1] if i else None

    # Human prompts count against the skill the main agent was running when they arrived.
    turns = defaultdict(list)
    for a in sorted((x for x in data["api"] if x["agent_id"] == "main" and x["ts"]), key=lambda x: x["ts"]):
        turns[a["session_id"]].append((a["ts"], a["skill"]))
    turn_ts = {s: [t for t, _ in v] for s, v in turns.items()}

    def active_skill(sid, ts):
        i = bisect.bisect_right(turn_ts.get(sid, []), ts)
        return turns[sid][i - 1][1] if i else None

    def units_of(sid, agent_id, skill):
        """Every unit a piece of work belongs to. Work is counted once per unit."""
        out = set()
        if skill:
            out.add(f"skill:{skill}")
        ident = agent_of.get((sid, agent_id))
        if ident:
            out.add(f"agent:{ident[0]}|{ident[1]}")
        for g in groups:
            if (skill and skill in g["skills"]) or (ident and ident[0] in g["types"]):
                out.add(g["id"])
        return out

    # Time: the gap from each model turn to the same agent's next turn, capped.
    api = data["api"]
    seconds = [0.0] * len(api)
    chains = defaultdict(list)
    for i, a in enumerate(api):
        if a["ts"]:
            chains[(a["session_id"], a["agent_id"])].append((a["ts"], i))
    for chain in chains.values():
        chain.sort()
        for (t, i), (t_next, _) in zip(chain, chain[1:]):
            seconds[i] = min(TURN_CAP, max(0.0, (t_next - t).total_seconds()))

    acc = {}

    def cell(uid, sid):
        k = (uid, sid)
        if k not in acc:
            acc[k] = {"cost": 0.0, "seconds": 0.0, "turns": 0, "api_errors": 0, "calls": 0, "call_errors": 0,
                      "idle": 0, "incidents": 0, "bad": 0, "prompts": 0}
        return acc[k]

    for i, a in enumerate(api):
        for uid in units_of(a["session_id"], a["agent_id"], a["skill"]):
            c = cell(uid, a["session_id"])
            c["turns"] += 1
            c["cost"] += a["cost_usd"] or 0.0
            c["seconds"] += seconds[i]
            c["api_errors"] += bool(a["api_error"])
    for t in data["tools"]:
        for uid in units_of(t["session_id"], t["agent_id"], t["skill"]):
            c = cell(uid, t["session_id"])
            c["calls"] += 1
            c["call_errors"] += bool(t["is_error"])
            c["idle"] += bool(t["idle"])
    for x in data["incidents"]:
        for uid in units_of(x["session_id"], x["agent_id"], x["skill"]):
            cell(uid, x["session_id"])["incidents"] += 1
    for x in data["markers"]:
        for uid in units_of(x["session_id"], x["agent_id"], x["skill"]):
            cell(uid, x["session_id"])["bad"] += 1
    for p in data["prompts"]:
        skill = active_skill(p["session_id"], p["ts"]) if p["ts"] else None
        if skill:
            for uid in units_of(p["session_id"], None, skill):
                cell(uid, p["session_id"])["prompts"] += 1

    def kind_of(uid):
        return uid.split(":", 1)[0]

    records = []
    for (uid, sid), c in acc.items():
        kind = kind_of(uid)
        values = {
            "cost": c["cost"],
            "seconds": c["seconds"],
            "error_rate": c["call_errors"] / c["calls"] if c["calls"] else None,
            "incidents": c["incidents"],
            "interventions": c["prompts"] if kind != "agent" else None,
            "idle_rate": c["idle"] / c["calls"] if c["calls"] else None,
            "api_error_rate": c["api_errors"] / c["turns"] if c["turns"] else None,
            "bad_markers": c["bad"],
        }
        records.append((uid, sid, kind, values, c))
    ref = references([(kind, values) for _, _, kind, values, _ in records])

    def version_map(uid, kind, sid, started):
        if kind == "agent":
            return {}
        skills = [uid.split(":", 1)[1]] if kind == "skill" else sorted(group_of[uid]["skills"])
        return {s: latest.get((sid, s)) or version_before(s, started) for s in skills}

    unit_runs = defaultdict(list)
    for uid, sid, kind, values, c in records:
        started = sessions.get(sid, {}).get("started")
        vmap = version_map(uid, kind, sid, started)
        unit_runs[uid].append({"sid": sid, "values": values, "c": c, "started": started,
                               "vmap": vmap, "vkey": version_key(vmap)})

    def name_of(uid):
        kind, _, rest = uid.partition(":")
        if kind == "agent":
            t, _, role = rest.partition("|")
            return f"{t} · {role}"
        return group_of[uid]["name"] if kind == "group" else rest

    def task_of(uid, kind, sid):
        if kind == "agent":
            t, _, role = uid.split(":", 1)[1].partition("|")
            text = agent_desc.get((sid, t, role))
        elif kind == "skill":
            text = first_args.get((sid, uid.split(":", 1)[1]))
        else:
            text = next((first_args[(sid, s)] for s in sorted(group_of[uid]["skills"]) if (sid, s) in first_args), None)
        return text or sessions.get(sid, {}).get("title")

    def repo_of(sid):
        cwd = (sessions.get(sid, {}).get("repo") or "").rstrip("\\/")
        return re.split(r"[\\/]", cwd)[-1] or None

    def earliest(xs):
        return min((x["started"] for x in xs if x["started"]), default=None)

    def latest_start(xs):
        return max((x["started"] for x in xs if x["started"]), default=None)

    units, versions_out, runs_out = [], {}, {}
    unit_ids = set(unit_runs) | {g["id"] for g in groups}
    for uid in sorted(unit_ids):
        kind = kind_of(uid)
        rs = unit_runs.get(uid, [])
        by_version = defaultdict(list)
        for x in rs:
            by_version[x["vkey"]].append(x)
        ordered = sorted(by_version.items(), key=lambda kv: earliest(kv[1]) or FAR)

        vlist, prev_vmap, prev = [], None, None
        for i, (vkey, xs) in enumerate(ordered):
            res = scored(xs, ref.get(kind, {}), kind, f"{uid}|{vkey}", resamples)
            vmap = xs[0]["vmap"]
            entry = {
                "id": uid, "label": f"v{i + 1}", "key": vkey,
                "parts": [{"skill": s, "hash": short(h)} for s, h in sorted(vmap.items())],
                "recorded": bool(vmap) and all(h is not None for h in vmap.values()),
                "first_seen": earliest(xs), "last_seen": latest_start(xs),
                "runs": len(xs), "low_sample": len(xs) < MIN_RUNS,
                "score": res["score"] if res else None,
                "ci": res["ci"] if res else None,
                "metrics": res["metrics"] if res else {},
                "changes": changes(prev_vmap, vmap, texts) if prev_vmap is not None else [],
                "delta": None, "overlap": None,
            }
            if prev and entry["score"] is not None and prev["score"] is not None:
                entry["delta"] = entry["score"] - prev["score"]
                entry["overlap"] = overlaps(entry["ci"], prev["ci"])
            vlist.append(entry)
            prev_vmap, prev = vmap, entry

        label_of = {v["key"]: v["label"] for v in vlist}
        overall = scored(rs, ref.get(kind, {}), kind, f"{uid}|*", resamples)
        kpi = {m["key"]: _mean([x["values"][m["key"]] for x in rs if x["values"][m["key"]] is not None])
               for m in METRICS}
        last = vlist[-1] if vlist else None
        units.append({
            "id": uid, "kind": kind, "name": name_of(uid),
            "members": group_of[uid]["members"] if kind == "group" else [],
            "runs": len(rs), "versions": len(vlist), "current": last["label"] if last else None,
            "score": overall["score"] if overall else None, "ci": overall["ci"] if overall else None,
            "low_sample": len(rs) < MIN_RUNS,
            "delta": last["delta"] if last else None, "overlap": last["overlap"] if last else None,
            "kpi": kpi, "first_seen": earliest(rs), "last_seen": latest_start(rs),
        })
        versions_out[uid] = vlist
        runs_out[uid] = sorted(
            ({"started": x["started"], "session": x["sid"][:8], "task": _clip(task_of(uid, kind, x["sid"])),
              "version": label_of[x["vkey"]], "repo": repo_of(x["sid"]),
              "cost": x["values"]["cost"], "seconds": x["values"]["seconds"],
              "calls": x["c"]["calls"], "call_errors": x["c"]["call_errors"], "idle": x["c"]["idle"],
              "turns": x["c"]["turns"], "api_errors": x["c"]["api_errors"], "incidents": x["values"]["incidents"],
              "interventions": x["values"]["interventions"], "bad": x["values"]["bad_markers"]} for x in rs),
            key=lambda r: r["started"] or NEVER, reverse=True)

    starts = [r["started"] for r in data["runs"] if r["started"]]
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="minutes"),
        "window": {"first": min(starts, default=None), "last": max(starts, default=None), "runs": len(data["runs"])},
        "texts": bool(texts),
        "method": {"metrics": [{**{k: v for k, v in m.items() if k != "kinds"}, "kinds": list(m["kinds"])} for m in METRICS],
                   "shrink": SHRINK, "max_ratio": MAX_RATIO, "floor": FLOOR, "turn_cap": TURN_CAP,
                   "resamples": resamples, "min_runs": MIN_RUNS},
        "reference": ref,
        "units": units,
        "versions": versions_out,
        "runs": runs_out,
    }


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _clip(text, n=300):
    return None if text is None else (text if len(text) <= n else text[: n - 1] + "…")


# ---- reading the database --------------------------------------------------------------

def load(con):
    """The rows `compute` needs, read from a DuckDB connection."""
    def rows(sql):
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    has_texts = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'skill_texts'").fetchone()[0]
    return {
        "runs": rows("SELECT session_id, started, title, cwd AS repo FROM runs"),
        "agents": rows("SELECT session_id, agent_id, agent_type, role, description FROM agents"),
        "api": rows("SELECT session_id, agent_id, ts, skill, cost_usd, api_error FROM api_calls"),
        "tools": rows("SELECT session_id, agent_id, skill, is_error, idle FROM tool_calls"),
        "incidents": rows("SELECT session_id, agent_id, skill FROM incidents"),
        "markers": rows("SELECT session_id, agent_id, skill FROM markers WHERE bad"),
        "prompts": rows("SELECT session_id, ts FROM events WHERE kind = 'human_prompt' AND agent_id = 'main'"),
        "loads": rows("SELECT session_id, agent_id, ts, skill, content_hash, args FROM skill_loads"),
        "texts": rows("SELECT skill, content_hash, text FROM skill_texts") if has_texts else [],
    }


def diagnostics(con):
    """The rest of what the database records, as small aggregates for the Diagnostics page."""
    def rows(sql):
        try:
            cur = con.execute(sql)
        except Exception:  # an older database may lack a table; the page then shows that part as empty
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    return {
        "runs": rows("""
            SELECT r.session_id[:8] AS run, r.started, regexp_extract(r.cwd, '[^\\\\/]+$') AS repo, r.git_branch AS branch,
                   r.cc_version, r.title, r.cost_usd AS cost, r.cost_estimated AS estimated, r.active_ms,
                   r.human_prompts AS prompts, r.n_agents AS agents, r.lines_added, r.lines_removed,
                   (SELECT count(*) FROM incidents i WHERE i.session_id = r.session_id) AS incidents,
                   (SELECT count(*) FROM tool_calls t WHERE t.session_id = r.session_id) AS tool_calls,
                   (SELECT count(*) FROM tool_calls t WHERE t.session_id = r.session_id AND t.is_error) AS tool_errors
            FROM runs r ORDER BY r.started"""),
        "incidents": rows("""SELECT type, coalesce(skill, '(none)') AS skill, count(*) AS incidents, sum(n) AS occurrences
                             FROM incidents GROUP BY 1, 2"""),
        "incident_roles": rows("""SELECT coalesce(role, '?') AS role, count(*) AS incidents FROM incidents
                                  GROUP BY 1 ORDER BY 2 DESC LIMIT 12"""),
        "tool_errors": rows("""SELECT coalesce(error_class, 'other') AS class, tool, count(*) AS errors
                               FROM tool_calls WHERE is_error GROUP BY 1, 2"""),
        "tools": rows("""SELECT tool, count(*) AS calls, count(*) FILTER (WHERE is_error) AS errors,
                                median(duration_ms) AS median_ms, quantile_cont(duration_ms, 0.95) AS p95_ms,
                                sum(duration_ms) AS total_ms
                         FROM tool_calls GROUP BY 1 ORDER BY calls DESC"""),
        "idle": rows("""SELECT coalesce(skill, '(none)') AS skill, count(*) FILTER (WHERE idle) AS idle_calls, count(*) AS calls
                        FROM tool_calls GROUP BY 1 ORDER BY 2 DESC"""),
        "models": rows("""SELECT model, count(*) AS calls, sum(cost_usd) AS cost, sum(output_tokens) AS output,
                                 sum(thinking_tokens) AS thinking, sum(input_tokens + cache_write_5m + cache_write_1h) AS fresh_input,
                                 sum(cache_read_tokens) AS cache_read
                          FROM api_calls GROUP BY 1 ORDER BY cost DESC"""),
        "efforts": rows("""SELECT coalesce(effort, '(default)') AS effort, count(*) AS calls, sum(cost_usd) AS cost
                           FROM api_calls GROUP BY 1 ORDER BY cost DESC"""),
        "agent_types": rows("""SELECT coalesce(agent_type, '?') AS agent_type, count(*) AS agents, sum(cost_usd) AS cost,
                                      sum(tool_calls) AS tool_calls, sum(tool_errors) AS tool_errors, max(peak_context) AS peak_context,
                                      sum(compactions) AS compactions,
                                      count(*) FILTER (WHERE status NOT IN ('completed', 'async_launched', 'running')) AS not_completed
                               FROM agents WHERE agent_id <> 'main' GROUP BY 1 ORDER BY cost DESC NULLS LAST"""),
        "agent_status": rows("""SELECT coalesce(status, '(none)') AS status, count(*) AS agents FROM agents
                                WHERE agent_id <> 'main' GROUP BY 1 ORDER BY 2 DESC"""),
        "flow": rows("""WITH s AS (SELECT session_id, ts, coalesce(skill, '(none)') AS skill,
                               lag(coalesce(skill, '(none)')) OVER (PARTITION BY session_id ORDER BY ts) AS prev
                        FROM api_calls WHERE agent_id = 'main')
                        SELECT prev AS source, skill AS target, count(*) AS transitions FROM s
                        WHERE prev IS NOT NULL AND prev <> skill GROUP BY 1, 2"""),
        "markers": rows("""SELECT marker, value, bad, coalesce(skill, '(none)') AS skill, count(*) AS n
                           FROM markers GROUP BY ALL"""),
        "events": rows("""SELECT kind, count(*) AS n FROM events WHERE kind NOT IN ('turn', 'human_prompt')
                          GROUP BY 1 ORDER BY 2 DESC"""),
        "labels": rows("SELECT category, count(*) AS n FROM labels GROUP BY 1 ORDER BY 2 DESC"),
        # models, effort and thinking
        "model_effort": rows("""SELECT model, coalesce(effort, '(default)') AS effort, count(*) AS calls, sum(cost_usd) AS cost,
                                       avg(output_tokens) AS avg_output, avg(thinking_tokens) AS avg_thinking, avg(thinking_ms) AS avg_thinking_ms
                                FROM api_calls GROUP BY 1, 2"""),
        "model_skill": rows("""SELECT model, coalesce(skill, '(none)') AS skill, count(*) AS calls, sum(cost_usd) AS cost
                               FROM api_calls GROUP BY 1, 2"""),
        "model_day": rows("""SELECT strftime(ts, '%Y-%m-%d') AS day, model, sum(cost_usd) AS cost, count(*) AS calls
                             FROM api_calls WHERE ts IS NOT NULL GROUP BY 1, 2 ORDER BY 1"""),
        "api_errors": rows("""SELECT model, count(*) FILTER (WHERE api_error) AS errors, count(*) AS calls FROM api_calls GROUP BY 1"""),
        # the subagents that runs generated
        "agents_by_run": rows("""SELECT session_id[:8] AS run, coalesce(agent_type, '?') AS agent_type, count(*) AS n, sum(cost_usd) AS cost
                                 FROM agents WHERE agent_id <> 'main' GROUP BY 1, 2"""),
        "agents_by_skill": rows("""SELECT s AS skill, coalesce(agent_type, '?') AS agent_type, count(*) AS n, sum(cost_usd) AS cost
                                   FROM (SELECT agent_type, cost_usd, unnest(skills) AS s FROM agents WHERE agent_id <> 'main')
                                   GROUP BY 1, 2"""),
        "agent_shape": rows("""SELECT spawn_depth AS depth, coalesce(background, false) AS background, count(*) AS n
                               FROM agents WHERE agent_id <> 'main' GROUP BY 1, 2"""),
        "agent_models": rows("""SELECT coalesce(agent_type, '?') AS agent_type, coalesce(model, '?') AS model, count(*) AS n, sum(cost_usd) AS cost
                                FROM agents WHERE agent_id <> 'main' GROUP BY 1, 2"""),
        "agent_roles": rows("""SELECT coalesce(agent_type, '?') AS agent_type, coalesce(role, '?') AS role, count(*) AS agents,
                                      sum(cost_usd) AS cost, avg(epoch(ended - started)) AS avg_seconds, avg(tool_calls) AS avg_tools,
                                      max(peak_context) AS peak_context
                               FROM agents WHERE agent_id <> 'main' GROUP BY 1, 2 ORDER BY cost DESC NULLS LAST LIMIT 25"""),
        "agent_time": rows("""SELECT coalesce(agent_type, '?') AS agent_type, avg(epoch(ended - started)) AS avg_s,
                                     median(epoch(ended - started)) AS median_s, quantile_cont(epoch(ended - started), 0.95) AS p95_s
                              FROM agents WHERE agent_id <> 'main' AND ended IS NOT NULL GROUP BY 1"""),
        "agent_day": rows("""SELECT strftime(started, '%Y-%m-%d') AS day, count(*) AS n, sum(cost_usd) AS cost FROM agents
                             WHERE agent_id <> 'main' AND started IS NOT NULL GROUP BY 1 ORDER BY 1"""),
    }


def build(con, groups=(), resamples=RESAMPLES):
    model = compute(load(con), groups, resamples)
    model["diag"] = diagnostics(con)
    return model
