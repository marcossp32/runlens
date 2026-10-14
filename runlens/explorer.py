"""Run-level facts for the dashboard: what the page needs to filter, re-aggregate and explore runs.

`bench.build` gives the scores and a few global aggregates. The page also has to answer "what happened in
this run?" and to re-draw every chart for any slice the reader picks (dates, repo, branch, model, effort,
skills, Claude Code version). Aggregates cannot be sliced after the fact, so this module hands the page
small per-run facts instead: per run and model, effort and skill; per run and tool; per run and day. The page
sums whatever rows the filters keep.

Everything here is read-only. Tables are written as {"c": columns, "r": rows of values} rather than one
object per row, which keeps the embedded JSON small. A run's start is in epoch seconds; times inside a run
(its agents, incidents, markers, errors) are whole seconds from that start. Model names are normalised
(`claude-opus-5-5[1m]` and `...-20251001` suffixes dropped) so the transcript and Claude Code's own totals
name a model the same way.
"""
import math
import re
from collections import defaultdict
from datetime import datetime

from . import config
from .transcripts import model_key, price_of

TITLE = 120          # longest run title kept
ROLE = 80            # longest agent role kept
CURVE_POINTS = 60    # points kept of each run's cumulative cost curve
ERRORS_PER_RUN = 150  # tool errors listed per run on its page (the counts are never capped)
# Tool call durations, in half-decade bins: <10 ms, 10-32 ms, ..., 316-1000 s, >= 1000 s.
DURATION_EDGES = [10 ** (k / 2) for k in range(2, 13)]  # ms
TOKEN_TYPES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")


def table(cols, rows, codes=()):
    """Rows as lists under one list of column names. Columns in `codes` repeat a few values many times (types,
    models, skills): they are stored once in "d" and each row holds the value's position."""
    out = {"c": list(cols), "r": [list(r) for r in rows]}
    if codes:
        out["d"] = {}
        for name in codes:
            j = out["c"].index(name)
            seen = {}
            for r in out["r"]:
                r[j] = seen.setdefault(r[j], len(seen))
            out["d"][name] = list(seen)
    return out


def epoch(ts):
    return round(ts.timestamp()) if isinstance(ts, datetime) else None


def num(v, d=6):
    if v is None:
        return None
    if isinstance(v, float):
        return round(v, d) if math.isfinite(v) else None
    return v


def clip(text, n):
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def repo_name(cwd):
    return re.split(r"[\\/]", cwd.rstrip("\\/"))[-1] if cwd else None


def duration_bin(ms):
    if ms is None:
        return None
    for i, edge in enumerate(DURATION_EDGES):
        if ms < edge:
            return i
    return len(DURATION_EDGES)


def build(con, cfg=None):
    """Every per-run fact the page uses, as compact tables. Missing tables or columns (an older database)
    leave their part empty instead of failing the dashboard."""
    import duckdb

    def rows(sql, params=None):
        try:
            cur = con.execute(sql, params or [])
        except (duckdb.CatalogException, duckdb.BinderException):
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    cfg = cfg or {}
    runs = rows("""SELECT session_id, started, ended, cwd, git_branch, cc_version, title, status, is_stub, ended_by,
                          cost_usd, cost_estimated, unknown_model_cost, active_ms, api_ms, tool_ms, human_prompts,
                          n_agents, lines_added, lines_removed, pr_urls, unpriced_models, parser_version, bad_lines,
                          entrypoint, skills
                   FROM runs ORDER BY started""")
    rid = {r["session_id"]: r["session_id"][:8] for r in runs}
    start = {r["session_id"]: epoch(r["started"]) for r in runs}
    known = lambda sid: sid in rid

    def rel(sid, ts):
        """Whole seconds since the run started (the run's own start is in epoch seconds in the runs table)."""
        t = epoch(ts)
        return None if t is None else t - (start.get(sid) or t)

    call_cols = ("calls", "cost", "input", "cw5", "cw1", "cread", "output", "thinking", "think_ms", "errors", "limits", "unpriced")
    merged = {}
    for c in rows("""SELECT session_id, model, coalesce(effort, '(default)') AS effort, coalesce(skill, '(none)') AS skill,
                            count(*) AS calls, sum(cost_usd) AS cost, sum(input_tokens) AS input,
                            sum(cache_write_5m) AS cw5, sum(cache_write_1h) AS cw1, sum(cache_read_tokens) AS cread,
                            sum(output_tokens) AS output, sum(thinking_tokens) AS thinking, sum(thinking_ms) AS think_ms,
                            count(*) FILTER (WHERE api_error) AS errors, count(*) FILTER (WHERE api_limit) AS limits,
                            count(*) FILTER (WHERE cost_usd IS NULL) AS unpriced
                     FROM api_calls GROUP BY ALL"""):
        if not known(c["session_id"]):
            continue
        acc = merged.setdefault((rid[c["session_id"]], model_key(c["model"]) or "?", c["effort"], c["skill"]), defaultdict(float))
        for f in call_cols:
            acc[f] += c[f] or 0
    calls_t = table(("run", "model", "effort", "skill") + call_cols,
                    (list(k) + [num(v[f], 5) if f == "cost" else int(v[f]) for f in call_cols] for k, v in sorted(merged.items())),
                    codes=("run", "model", "effort", "skill"))
    by_run = defaultdict(lambda: {"models": set(), "efforts": set(), "skills": set()})
    for (run, model, effort, skill) in merged:
        by_run[run]["models"].add(model)
        by_run[run]["efforts"].add(effort)
        if skill != "(none)":
            by_run[run]["skills"].add(skill)

    day_acc = defaultdict(lambda: [0.0, 0])
    for d in rows("""SELECT session_id, strftime(ts, '%Y-%m-%d') AS day, model, coalesce(skill, '(none)') AS skill,
                            sum(cost_usd) AS cost, count(*) AS calls
                     FROM api_calls WHERE ts IS NOT NULL GROUP BY ALL"""):
        if known(d["session_id"]):
            a = day_acc[(rid[d["session_id"]], d["day"], model_key(d["model"]) or "?", d["skill"])]
            a[0] += d["cost"] or 0
            a[1] += d["calls"] or 0
    days_t = table(("run", "day", "model", "skill", "cost", "calls"),
                   (list(k) + [num(v[0], 5), v[1]] for k, v in sorted(day_acc.items())), codes=("run", "day", "model", "skill"))

    tools, durations = {}, {}
    for t in rows("""SELECT session_id, tool, coalesce(skill, '(none)') AS skill, duration_ms,
                            is_error AND denied IS NULL AS failed, denied IS NOT NULL AS denied
                     FROM tool_calls"""):
        if not known(t["session_id"]):
            continue
        acc = tools.setdefault((rid[t["session_id"]], t["tool"] or "?", t["skill"]), [0, 0, 0, 0])
        acc[0] += 1
        acc[1] += bool(t["failed"])
        acc[2] += bool(t["denied"])
        if t["duration_ms"] is not None:
            acc[3] += t["duration_ms"]
            bins = durations.setdefault((rid[t["session_id"]], t["tool"] or "?"), [0] * (len(DURATION_EDGES) + 1))
            bins[duration_bin(t["duration_ms"])] += 1
    tools_t = table(("run", "tool", "skill", "calls", "errors", "denied", "ms"),
                    (list(k) + v for k, v in sorted(tools.items())), codes=("run", "tool", "skill"))
    durations_t = table(("run", "tool", "bins"), (list(k) + [v] for k, v in sorted(durations.items())), codes=("run", "tool"))

    errors_t = table(("run", "tool", "class", "skill", "n"),
                     ([rid[e["session_id"]], e["tool"], e["class"], e["skill"], e["n"]]
                      for e in rows("""SELECT session_id, tool, coalesce(error_class, 'other') AS class,
                                              coalesce(skill, '(none)') AS skill, count(*) AS n
                                       FROM tool_calls WHERE is_error AND denied IS NULL GROUP BY ALL""")
                      if known(e["session_id"])),
                     codes=("run", "tool", "class", "skill"))

    # Agents: numbered per run in start order (the main session is 0); a parent is given by its number.
    agents = rows("""SELECT session_id, agent_id, parent_agent_id, agent_type, role, model, started, ended, cost_usd,
                            status, spawn_depth, background, tool_calls, tool_errors, stopped_by_user, peak_context,
                            compactions, last_stop_reason
                     FROM agents ORDER BY session_id, (agent_id <> 'main'), started NULLS LAST, agent_id""")
    index, seq = {}, defaultdict(int)
    for a in agents:
        if known(a["session_id"]):
            index[(a["session_id"], a["agent_id"])] = seq[a["session_id"]]
            seq[a["session_id"]] += 1
    agent_of = lambda sid, aid: index.get((sid, aid))
    agents_t = table(("run", "i", "parent", "type", "role", "model", "t0", "t1", "cost", "status", "depth", "bg", "tools",
                      "errors", "stopped", "peak", "compactions", "stop"),
                     ([rid[a["session_id"]], index[(a["session_id"], a["agent_id"])],
                       index.get((a["session_id"], a["parent_agent_id"])) if a["parent_agent_id"] else None,
                       a["agent_type"] or "?", clip(a["role"], ROLE), model_key(a["model"]) or None,
                       rel(a["session_id"], a["started"]), rel(a["session_id"], a["ended"]), num(a["cost_usd"], 4), a["status"],
                       a["spawn_depth"], int(bool(a["background"])), a["tool_calls"], a["tool_errors"],
                       int(bool(a["stopped_by_user"])), a["peak_context"], a["compactions"], a["last_stop_reason"]]
                      for a in agents if known(a["session_id"])),
                     codes=("run", "type", "role", "model", "status", "stop"))

    label = """(SELECT category FROM labels l WHERE l.incident_id = i.incident_id
                ORDER BY (l.source = 'human') DESC, l.labeled_at DESC LIMIT 1)"""
    cols = """session_id, agent_id, ts, type, coalesce(skill, '(none)') AS skill, role, incident_id, detail,
              coalesce(policy, false) AS policy, n"""
    incidents = rows(f"SELECT {cols}, {label} AS label FROM incidents i ORDER BY ts") \
        or rows(f"SELECT {cols}, NULL AS label FROM incidents ORDER BY ts")
    incidents_t = table(("run", "t", "type", "skill", "agent", "role", "id", "detail", "policy", "n", "label"),
                        ([rid[i["session_id"]], rel(i["session_id"], i["ts"]), i["type"], i["skill"],
                          agent_of(i["session_id"], i["agent_id"]), clip(i["role"], ROLE), i["incident_id"], clip(i["detail"], 120),
                          int(bool(i["policy"])), i["n"], i["label"]]
                         for i in incidents if known(i["session_id"])),
                        codes=("run", "type", "skill", "role", "label"))

    markers_t = table(("run", "t", "marker", "value", "bad", "skill"),
                      ([rid[m["session_id"]], rel(m["session_id"], m["ts"]), m["marker"], clip(m["value"], 40), int(bool(m["bad"])),
                        m["skill"]]
                       for m in rows("""SELECT session_id, ts, marker, value, bad, coalesce(skill, '(none)') AS skill
                                        FROM markers ORDER BY ts""") if known(m["session_id"])),
                      codes=("run", "marker", "value", "skill"))

    events_t = table(("run", "t", "kind", "agent", "value", "source"),
                     ([rid[e["session_id"]], rel(e["session_id"], e["ts"]), e["kind"], agent_of(e["session_id"], e["agent_id"]),
                       e["value"], e["source"]]
                      for e in rows("""SELECT session_id, agent_id, ts, kind, value, source FROM events
                                       WHERE kind <> 'turn' AND ts IS NOT NULL ORDER BY ts""") if known(e["session_id"])),
                     codes=("run", "kind", "source"))

    stop_acc = defaultdict(int)
    for s in rows("""SELECT session_id, model, coalesce(stop_reason, '(not recorded)') AS stop, count(*) AS n
                     FROM api_calls GROUP BY ALL"""):
        if known(s["session_id"]):
            stop_acc[(rid[s["session_id"]], model_key(s["model"]) or "?", s["stop"])] += s["n"]
    stops_t = table(("run", "model", "stop", "n"), (list(k) + [v] for k, v in sorted(stop_acc.items())),
                    codes=("run", "model", "stop"))

    apierr_t = table(("run", "model", "kind", "status", "limit", "n"),
                     ([rid[e["session_id"]], model_key(e["model"]) or "?", e["kind"], e["status"], int(bool(e["is_limit"])), e["n"]]
                      for e in rows("""SELECT session_id, model, coalesce(api_error_kind, 'other') AS kind,
                                              api_error_status AS status, coalesce(api_limit, false) AS is_limit, count(*) AS n
                                       FROM api_calls WHERE api_error OR api_limit GROUP BY ALL""") if known(e["session_id"])),
                     codes=("run", "model", "kind"))

    comps_t = table(("run", "t", "agent", "trigger", "pre", "post", "ms", "skill"),
                    ([rid[c["session_id"]], rel(c["session_id"], c["ts"]), agent_of(c["session_id"], c["agent_id"]), c["trigger"],
                      c["pre_tokens"], c["post_tokens"], c["duration_ms"], c["skill"] or "(none)"]
                     for c in rows("""SELECT session_id, agent_id, ts, trigger, pre_tokens, post_tokens, duration_ms, skill
                                      FROM v_compactions ORDER BY ts""") if known(c["session_id"])),
                    codes=("run", "trigger", "skill"))

    # The main session's skill timeline: consecutive model turns under the same skill make one segment, and a
    # change of skill is one hand-over (what the flow chart draws).
    segments, flow, cur = [], defaultdict(int), None
    for m in rows("""SELECT session_id, ts, coalesce(skill, '(none)') AS skill, cost_usd FROM api_calls
                     WHERE agent_id = 'main' AND ts IS NOT NULL ORDER BY session_id, ts"""):
        if not known(m["session_id"]):
            continue
        if cur and cur[0] == m["session_id"] and cur[1] == m["skill"]:
            cur[3], cur[4], cur[5] = m["ts"], cur[4] + (m["cost_usd"] or 0), cur[5] + 1
            continue
        if cur and cur[0] == m["session_id"]:
            flow[(rid[m["session_id"]], cur[1], m["skill"])] += 1
        if cur:
            segments.append(cur)
        cur = [m["session_id"], m["skill"], m["ts"], m["ts"], m["cost_usd"] or 0, 1]
    if cur:
        segments.append(cur)
    segments_t = table(("run", "skill", "t0", "t1", "cost", "calls"),
                       ([rid[s[0]], s[1], rel(s[0], s[2]), rel(s[0], s[3]), num(s[4], 4), s[5]] for s in segments),
                       codes=("run", "skill"))
    flow_t = table(("run", "source", "target", "n"), (list(k) + [v] for k, v in sorted(flow.items())),
                   codes=("run", "source", "target"))

    # Each run's cumulative spend over time, thinned to at most CURVE_POINTS points: [seconds from start, US$].
    per = defaultdict(list)
    for s in rows("""SELECT session_id, ts, cost_usd FROM api_calls WHERE ts IS NOT NULL AND cost_usd IS NOT NULL
                     ORDER BY session_id, ts"""):
        if known(s["session_id"]):
            per[s["session_id"]].append((s["ts"], s["cost_usd"]))
    curves = {}
    for sid, pts in per.items():
        total, line = 0.0, []
        for ts, c in pts:
            total += c
            line.append((rel(sid, ts), total))
        step = max(1, math.ceil(len(line) / CURVE_POINTS))
        thin = line[::step]
        if thin[-1] != line[-1]:
            thin.append(line[-1])
        curves[rid[sid]] = [[t, round(v, 3)] for t, v in thin]

    kept, count = [], defaultdict(int)
    for e in rows("""SELECT session_id, agent_id, ts, tool, coalesce(error_class, 'other') AS class, tool_use_id
                     FROM tool_calls WHERE is_error AND denied IS NULL AND ts IS NOT NULL ORDER BY session_id, ts"""):
        if known(e["session_id"]) and count[e["session_id"]] < ERRORS_PER_RUN:
            count[e["session_id"]] += 1
            kept.append([rid[e["session_id"]], rel(e["session_id"], e["ts"]), agent_of(e["session_id"], e["agent_id"]), e["tool"],
                         e["class"], e["tool_use_id"]])
    toolerr_t = table(("run", "t", "agent", "tool", "class", "id"), kept, codes=("run", "tool", "class"))

    out_runs = []
    for r in runs:
        run = rid[r["session_id"]]
        d = by_run[run]
        out_runs.append([run, r["session_id"], epoch(r["started"]), rel(r["session_id"], r["ended"]), repo_name(r["cwd"]),
                         r["git_branch"], r["cc_version"], clip(r["title"], TITLE), r["status"] or "complete", int(bool(r["is_stub"])),
                         r["ended_by"], num(r["cost_usd"], 4), int(bool(r["cost_estimated"])), int(bool(r["unknown_model_cost"])),
                         r["active_ms"], r["api_ms"], r["tool_ms"], r["human_prompts"], r["n_agents"], r["lines_added"],
                         r["lines_removed"], list(r["pr_urls"] or [])[:5], list(r["unpriced_models"] or []), r["parser_version"],
                         r["bad_lines"], r["entrypoint"], sorted(d["models"]), sorted(d["efforts"]),
                         sorted(d["skills"] | set(r["skills"] or [])), len(r["pr_urls"] or [])])
    runs_t = table(("run", "sid", "started", "ended", "repo", "branch", "cc", "title", "status", "stub", "ended_by", "cost",
                    "estimated", "unknown_cost", "active_ms", "api_ms", "tool_ms", "prompts", "agents", "added", "removed",
                    "prs", "unpriced", "parser", "bad_lines", "entry", "models", "efforts", "skills", "npr"), out_runs)

    return {
        "duration_edges": DURATION_EDGES,
        "runs": runs_t, "calls": calls_t, "days": days_t, "tools": tools_t, "durations": durations_t, "errors": errors_t,
        "agents": agents_t, "incidents": incidents_t, "markers": markers_t, "events": events_t, "stops": stops_t,
        "apierr": apierr_t, "compactions": comps_t, "segments": segments_t, "flow": flow_t, "curves": curves,
        "toolerr": toolerr_t, "tokens": token_cost(rows, rid, cfg.get("prices")), "health": health(rows, rid),
    }


def token_cost(rows, rid, price_overrides=None):
    """Per run and model, Claude Code's own token totals (model_usage) by type and what each type cost.
    The transcript undercounts tokens, cost-state does not; cache writes are split 5-minute / 1-hour by the
    transcript's split of that run and model. List-price parts are scaled to the cost Claude Code recorded,
    so the parts of a run add up to its real cost. A run with no model_usage uses its transcript's totals and
    cost instead (lower bounds on tokens). A model with no known price gets tokens and no cost."""
    usage = rows("""SELECT session_id, model, sum(input_tokens) AS input, sum(output_tokens) AS output,
                           sum(cache_read_tokens) AS cache_read, sum(cache_write_tokens) AS cache_write, sum(cost_usd) AS cost
                    FROM model_usage GROUP BY ALL""")
    split = defaultdict(lambda: [0, 0])
    for r in rows("SELECT session_id, model, sum(cache_write_5m) AS w5, sum(cache_write_1h) AS w1 FROM api_calls GROUP BY ALL"):
        s = split[(r["session_id"], model_key(r["model"]))]
        s[0] += r["w5"] or 0
        s[1] += r["w1"] or 0
    out = []
    # A run without model_usage (an older Claude Code, or none recorded) falls back to its transcript's own totals.
    have = {u["session_id"] for u in usage}
    for r in rows("""SELECT session_id, model, sum(input_tokens) AS input, sum(output_tokens) AS output,
                          sum(cache_read_tokens) AS cache_read, sum(cache_write_5m) + sum(cache_write_1h) AS cache_write,
                          sum(cost_usd) AS cost
                   FROM api_calls GROUP BY ALL"""):
        if r["session_id"] not in have:
            usage.append(r)
    for u in usage:
        if u["session_id"] not in rid:
            continue
        w5, w1 = split[(u["session_id"], model_key(u["model"]))]
        share_1h = w1 / (w5 + w1) if (w5 + w1) else 0.0
        tokens = {"input": u["input"] or 0, "output": u["output"] or 0, "cache_read": u["cache_read"] or 0,
                  "cache_write_5m": (u["cache_write"] or 0) * (1 - share_1h), "cache_write_1h": (u["cache_write"] or 0) * share_1h}
        p = price_of(u["model"], price_overrides)
        costs = {t: None for t in TOKEN_TYPES}
        if p is not None:
            rate = dict(zip(("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"), p))
            listed = {t: tokens[t] * rate[t] / 1e6 for t in TOKEN_TYPES}
            total = sum(listed.values())
            k = (u["cost"] / total) if (u["cost"] and total) else 1.0
            costs = {t: listed[t] * k for t in TOKEN_TYPES}
        for t in TOKEN_TYPES:
            if tokens[t] or costs[t]:
                out.append([rid[u["session_id"]], model_key(u["model"]), t, round(tokens[t]), num(costs[t], 5)])
    return table(("run", "model", "type", "tokens", "cost"), out, codes=("run", "model", "type"))


def health(rows, rid):
    """Is the data complete and current? The one-row v_data_health view, plus the lists behind its counts."""
    h = (rows("SELECT * FROM v_data_health") or [{}])[0]
    for k, v in list(h.items()):
        if isinstance(v, datetime):
            h[k] = v.isoformat(timespec="seconds")
    errors = rows("""SELECT session_id, path, stage, error, detail, failed_at FROM ingest_errors
                     ORDER BY failed_at DESC LIMIT 100""")
    coverage = rows("""SELECT session_id, sum(transcript_output) AS seen, sum(cost_state_output) AS counted,
                              sum(cost_state_usd) AS cost
                       FROM v_token_coverage GROUP BY 1""")
    try:
        pending = sorted(p.name for p in config.PENDING.iterdir() if p.is_file() and not p.name.startswith(".")) \
            if config.PENDING.is_dir() else []
    except OSError:
        pending = []
    hook_errors = []
    log = config.HOME / "hooks.log"
    try:
        if log.is_file():
            with open(log, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()[-400:]
            hook_errors = [clip(x, 240) for x in lines if re.search(r"error|exception|traceback|failed", x, re.I)][-10:]
    except OSError:
        pass
    return {
        "summary": h,
        "ingest_errors": [{"run": (e["session_id"] or "")[:8], "sid": e["session_id"], "path": e["path"], "stage": e["stage"],
                           "error": clip(e["error"], 300), "detail": clip(e["detail"], 600),
                           "failed_at": e["failed_at"].isoformat(timespec="seconds") if isinstance(e["failed_at"], datetime) else e["failed_at"]}
                          for e in errors],
        "coverage": [[rid[c["session_id"]], c["seen"], c["counted"], num(c["cost"])] for c in coverage if c["session_id"] in rid],
        "pending": pending[:50], "pending_count": len(pending),
        "hook_errors": hook_errors,
    }
