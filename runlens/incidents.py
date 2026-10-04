"""Turn a parsed run into incidents: moments worth a human or a judge looking at.

Every incident is generic (no flow knowledge) except `bad_marker`, whose
meaning comes from the markers declared in config.toml. Each carries the
timeline that led to it, so it can be read without opening the transcript.
"""
import hashlib
from collections import defaultdict

TYPES = {
    "error_streak": "consecutive failing tool calls in one agent",
    "repeated_call": "the same tool call with identical input, repeated in one agent",
    "idle_loop": "shell calls that only wait or print, repeated in one agent",
    "bad_marker": "a config marker whose value is declared bad",
    "agent_failed": "a subagent that ended failed, killed or errored",
    "permission_denied": "a tool call blocked by permissions",
    "interrupt": "a run or tool interrupted",
    "compaction": "context compacted",
    "api_error": "an API error message",
    "test_edit_after_failure": "an edit to a test file right after a failing call in the same agent (possible test tampering)",
}


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
    return f"[{item['tool']}] {item['input_summary'][:300]} -> {status}: {head}"


def context(tl, agent_id, seq, steps):
    before = [x for x in tl.get(agent_id, []) if x[1] <= seq][-steps:]
    return "\n".join(f"{s:>4} {step_line(k, it)}" for k, s, it in before)


def build(rows, cfg):
    an = cfg["analysis"]
    steps = an["context_steps"]
    tl = timelines(rows)
    sid = rows["runs"][0]["session_id"]
    agents = {a["agent_id"]: a for a in rows["agents"]}
    out = []

    def add(agent_id, ts, kind, key, count, skill, seq, anchor=None, extra=""):
        a = agents.get(agent_id, {})
        out.append({
            "incident_id": iid(sid, agent_id, kind, key, seq), "session_id": sid, "agent_id": agent_id,
            "role": a.get("role"), "agent_type": a.get("agent_type"), "ts": ts, "type": kind, "key": str(key)[:300],
            "n": count, "skill": skill, "seq": seq, "anchor": anchor,
            "context": (extra + "\n" if extra else "") + (context(tl, agent_id, seq, steps) if seq is not None else ""),
        })

    for agent_id, items in tl.items():
        calls = [it for k, _, it in items if k == "tool"]
        # error streaks
        streak = []
        for c in calls + [None]:
            if c is not None and c["is_error"]:
                streak.append(c)
                continue
            if len(streak) >= an["error_streak_min"]:
                last = streak[-1]
                classes = sorted({s.get("error_class") or "other" for s in streak})
                add(agent_id, last["ts"], "error_streak", f"{last['tool']}: {','.join(classes)}", len(streak),
                    last["skill"], last["seq"], last["tool_use_id"])
            streak = []
        # repeated identical calls and idle loops
        by_hash = defaultdict(list)
        for c in calls:
            by_hash[c["input_hash"]].append(c)
        for group in by_hash.values():
            if group[0]["idle"] or len(group) < an["repeat_min"]:
                continue
            last = group[-1]
            add(agent_id, last["ts"], "repeated_call", f"{last['tool']}: {last['input_summary'][:200]}", len(group),
                last["skill"], last["seq"], last["tool_use_id"])
        idle = [c for c in calls if c["idle"]]
        if len(idle) >= an["idle_min"]:
            last = idle[-1]
            add(agent_id, last["ts"], "idle_loop", f"{len(idle)} idle calls, e.g. {last['input_summary'][:120]}",
                len(idle), last["skill"], last["seq"], last["tool_use_id"])
        for i, c in enumerate(calls):
            if c.get("denied"):
                add(agent_id, c["ts"], "permission_denied", f"{c['tool']}: {c['input_summary'][:200]}", 1,
                    c["skill"], c["seq"], c["tool_use_id"], extra=f"denial kind: {c['denied']}")
            failed = [p for p in calls[max(0, i - 5):i] if p["is_error"]]
            if c["touches_test"] and failed:
                add(agent_id, c["ts"], "test_edit_after_failure", f"{c['tool']}: {c['input_summary'][:200]}", 1,
                    c["skill"], c["seq"], c["tool_use_id"],
                    extra=f"after failing call: [{failed[-1]['tool']}] {failed[-1]['input_summary'][:200]}")

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
                (a["skills"] or [None])[0], last[-1][1] if last else None, a["parent_tool_use_id"],
                extra=f"spawned by {parent[0]} at step {parent[1]}")

    for e in rows["events"]:
        if e["kind"] in ("interrupt", "compaction", "api_error"):
            before = [x for x in tl.get(e["agent_id"], []) if x[2].get("ts") and e["ts"] and x[2]["ts"] <= e["ts"]]
            seq = before[-1][1] if before else None
            add(e["agent_id"], e["ts"], e["kind"], e["kind"] if not e["detail"] else e["detail"][:200], 1,
                before[-1][2].get("skill") if before else None, seq)
    return out
