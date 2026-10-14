"""Turn a parsed run into incidents: moments worth a human or a judge looking at.

Every incident is generic (no flow knowledge) except `bad_marker`, whose
meaning comes from the markers declared in config.toml. Each carries the
timeline that led to it, so it can be read without opening the transcript.

Two kinds of moment are deliberately not held against the work:
- an API limit (quota, session or rate limit) is an `api_limit` event, never an incident;
- a tool call blocked by the user's permission rules or by auto mode is still a
  `permission_denied` incident, with `policy = true`, so a score can leave it out.
"""
import hashlib
from collections import defaultdict
from datetime import timedelta

TYPES = {
    "error_streak": "consecutive failing tool calls in one agent",
    "repeated_call": "the same tool call with identical input, repeated in one agent",
    "idle_loop": "shell calls that only wait or print, repeated in one agent",
    "bad_marker": "a config marker whose value is declared bad",
    "agent_failed": "a subagent that ended failed, killed or errored",
    "permission_denied": "a tool call blocked by permissions (policy = true when the block came from rules or auto mode)",
    "interrupt": "a run or tool interrupted",
    "compaction": "context compacted",
    "api_error": "an API error that is not a quota, session or rate limit",
    "test_edit_after_failure": "an edit to an existing test file right after a failing test run in the same agent (possible test tampering)",
}
HUMAN_DENIALS = {"user-rejected"}  # a person said no: an intervention, not a permission rule


def iid(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def timelines(rows):
    """Per agent, tool calls and assistant texts in the order they happened."""
    tl = defaultdict(list)
    for c in rows["tool_calls"]:
        tl[c["agent_id"]].append(("tool", c["seq"], c))
    for t in rows["texts"]:
        tl[t["agent_id"]].append(("text", t["seq"], t))
    for k in tl:
        tl[k].sort(key=lambda x: x[1])
    return tl


def step_line(kind, item):
    if kind == "text":
        return f"[say] {item['text'][:400]}"
    status = "ERROR" if item["is_error"] else "ok"
    head = (item.get("result_head") or "")[:300].replace("\n", " | ")
    return f"[{item['tool']}] {(item.get('input_summary') or '')[:300]} -> {status}: {head}"


def context(tl, agent_id, seq, steps):
    before = [x for x in tl.get(agent_id, []) if x[1] <= seq][-steps:]
    return "\n".join(f"{s:>4} {step_line(k, it)}" for k, s, it in before)


def build(rows, cfg):
    an = cfg["analysis"]
    steps = an["context_steps"]
    tl = timelines(rows)
    sid = rows["runs"][0]["session_id"]
    agents = {a["agent_id"]: a for a in rows["agents"]}
    out, seen = [], set()

    def add(agent_id, ts, kind, key, count, skill, seq, anchor=None, extra="", ident=None, policy=False, detail=None):
        """`ident` overrides what the id is made of, for incidents that grow as a run goes on (a streak, a loop):
        they are identified by their first call, so the id and its labels survive re-ingesting a resumed run."""
        a = agents.get(agent_id, {})
        # Anchored incidents are identified by their tool call, never by `key` (built from input text, which
        # redaction rewrites) or `seq`, so labels survive redaction and re-ingest.
        parts = ident if ident else (("anchor", anchor) if anchor else (key, seq))
        incident_id = iid(sid, agent_id, kind, *parts)
        n = 1
        while incident_id in seen:  # two identical moments at the same step
            n += 1
            incident_id = iid(sid, agent_id, kind, *parts, n)
        seen.add(incident_id)
        out.append({
            "incident_id": incident_id, "session_id": sid, "agent_id": agent_id,
            "role": a.get("role"), "agent_type": a.get("agent_type"), "ts": ts, "type": kind, "key": str(key)[:300],
            "n": count, "skill": skill, "seq": seq, "anchor": anchor, "policy": policy, "detail": detail,
            "context": (extra + "\n" if extra else "") + (context(tl, agent_id, seq, steps) if seq is not None else ""),
        })

    for agent_id, items in tl.items():
        calls = [it for k, _, it in items if k == "tool"]
        # error streaks
        streak = []
        for c in calls + [None]:
            if c is not None and c["is_error"] and not c.get("denied"):  # a denial is a permission_denied, not a failure
                streak.append(c)
                continue
            if len(streak) >= an["error_streak_min"]:
                last = streak[-1]
                classes = sorted({s.get("error_class") or "other" for s in streak})
                add(agent_id, last["ts"], "error_streak", f"{last['tool']}: {','.join(classes)}", len(streak),
                    last["skill"], last["seq"], last["tool_use_id"], ident=("first", streak[0]["tool_use_id"]))
            streak = []
        # repeated identical calls and idle loops
        # Identical input AND identical output: re-reading a log that keeps changing is progress, not a repeat.
        by_hash = defaultdict(list)
        for c in calls:
            by_hash[(c["input_hash"], c.get("result_head"))].append(c)
        window = timedelta(seconds=an.get("repeat_window_s", 600))
        for group in by_hash.values():
            if group[0]["idle"]:
                continue
            chunk = []
            for c in group + [None]:
                if c is not None and (not chunk or c["ts"] is None or chunk[0]["ts"] is None or c["ts"] - chunk[0]["ts"] <= window):
                    chunk.append(c)
                    continue
                if len(chunk) >= an["repeat_min"]:
                    last = chunk[-1]
                    add(agent_id, last["ts"], "repeated_call", f"{last['tool']}: {(last['input_summary'] or '')[:200]}", len(chunk),
                        last["skill"], last["seq"], last["tool_use_id"], ident=("first", chunk[0]["tool_use_id"]))
                chunk = [c] if c is not None else []
        # Idle loops are runs of consecutive idle calls: any other call in between ends the run.
        run = []
        for c in calls + [None]:
            if c is not None and c["idle"]:
                run.append(c)
                continue
            if len(run) >= an["idle_min"]:
                last = run[-1]
                add(agent_id, last["ts"], "idle_loop", f"{len(run)} idle calls, e.g. {(last['input_summary'] or '')[:120]}",
                    len(run), last["skill"], last["seq"], last["tool_use_id"], ident=("first", run[0]["tool_use_id"]))
            run = []
        for i, c in enumerate(calls):
            if c.get("denied"):
                add(agent_id, c["ts"], "permission_denied", f"{c['tool']}: {(c['input_summary'] or '')[:200]}", 1,
                    c["skill"], c["seq"], c["tool_use_id"], extra=f"denial kind: {c['denied']}",
                    policy=c["denied"] not in HUMAN_DENIALS, detail=c["denied"])
            failed = [p for p in calls[max(0, i - 5):i] if p["is_error"]]
            # Creating a new test file after a probe that found nothing is what a repro step is for.
            creates = c["tool"] == "Write" and (c.get("result_head") or "").startswith("File created")
            if c["touches_test"] and failed and not creates and failed[-1].get("error_class") == "test_failure":
                add(agent_id, c["ts"], "test_edit_after_failure", f"{c['tool']}: {(c['input_summary'] or '')[:200]}", 1,
                    c["skill"], c["seq"], c["tool_use_id"],
                    extra=f"after failing call: [{failed[-1]['tool']}] {(failed[-1]['input_summary'] or '')[:200]}")

    seq_of = {c["tool_use_id"]: (c["agent_id"], c["seq"]) for c in rows["tool_calls"]}
    for m in rows["markers"]:
        if m["bad"]:
            agent_id, seq = seq_of.get(m["tool_use_id"], (m["agent_id"], None))
            add(agent_id, m["ts"], "bad_marker", f"{m['marker']}={m['value']}", 1, m["skill"], seq, m["tool_use_id"])

    for a in rows["agents"]:
        if a.get("status") and a["status"] not in ("completed", "async_launched", "running"):
            parent = seq_of.get(a["parent_tool_use_id"], (a.get("parent_agent_id"), None))
            last = tl.get(a["agent_id"], [])
            add(a["agent_id"], a["ended"], "agent_failed", f"{a['role']}: {a['status']}", 1,
                (last[-1][2].get("skill") if last else None) or (a["skills"] or [None])[0], last[-1][1] if last else None, a["parent_tool_use_id"],
                extra=f"spawned by {parent[0]} at step {parent[1]}" + ("; stopped by the user" if a.get("stopped_by_user") else ""),
                detail="stopped_by_user" if a.get("stopped_by_user") else None)

    for e in rows["events"]:
        if e["kind"] in ("interrupt", "compaction", "api_error"):
            before = [x for x in tl.get(e["agent_id"], []) if x[2].get("ts") and e["ts"] and x[2]["ts"] <= e["ts"]]
            seq = before[-1][1] if before else None
            detail = e.get("source")
            if e["kind"] == "compaction" and e.get("value"):
                detail = f"{e.get('source') or 'unknown'}, {e['value']} tokens before"
            add(e["agent_id"], e["ts"], e["kind"], e["kind"] if not e["detail"] else e["detail"][:200], 1,
                before[-1][2].get("skill") if before else None, seq, detail=detail)
    return out
