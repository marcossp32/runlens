"""Read one run (main transcript + subagent transcripts) into table rows.

Only the Claude Code transcript format is assumed here. The format is internal
to Claude Code and changes between versions, so every field is read defensively
and `runlens check` compares the rows against the raw files.
"""
import hashlib
import json
import re
from datetime import datetime

# USD per million tokens, Anthropic first-party list prices (claude-api skill, cached 2026-09-25).
# Cache writes use the standard 1.25x (5m) and 2x (1h) of input. Override or extend under [prices] in config.
# Used to split a run's real cost (cost-state) across its calls, and to estimate runs without cost-state.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-fable-5": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20), "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
DEFAULT_PRICE = (4.0, 20.0, 0.40)


def price_of(model, overrides=None):
    """(input, output, cache_read, cache_write_5m, cache_write_1h) in USD per million tokens."""
    name = re.sub(r"\[.*\]$", "", model or "")
    name = re.sub(r"-\d{8}$", "", name)
    table = {**PRICES, **{k: tuple(v) if isinstance(v, (list, tuple)) else (v["input"], v["output"], v["cache_read"])
                          for k, v in (overrides or {}).items()}}
    inp, out, read = table.get(name, DEFAULT_PRICE)
    return inp, out, read, inp * 1.25, inp * 2.0

SUMMARY_KEYS = ("command", "file_path", "notebook_path", "path", "pattern", "url", "query", "skill",
                "subagent_type", "description", "prompt", "to", "message", "action")

SKILL_LOAD = re.compile(r"^Base directory for this skill:\s*(.+?)\s*$", re.M)
TASK_NOTE = re.compile(r"<task-id>([\w-]+)</task-id>.*?<status>(\w+)</status>", re.S)
SHELL_TOOLS = {"Bash", "PowerShell"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Checked in order against the head of the tool output; the first match wins.
ERROR_CLASSES = [
    ("harness_blocked", r"^(<tool_use_error>)?Blocked: "),
    ("permission_denied", r"Permission to use .* has been denied|denied by the Claude Code auto mode"),
    ("edit_without_read", r"has not been read yet|must read .* before"),
    ("stale_read", r"modified since read"),
    ("edit_mismatch", r"String to replace not found|old_string .*not (found|unique)|Found \d+ matches of the string"),
    ("invalid_tool_input", r"InputValidationError|Invalid tool parameters|No such tool available"),
    ("syntax", r"SyntaxError|syntax error|unexpected (token|EOF)|ParserError|unterminated|Unexpected end of"),
    ("command_not_found", r"command not found|is not recognized as (an internal|the name)"),
    ("not_found", r"No such file or directory|ENOENT|cannot find the path|Cannot find path|File does not exist|Path does not exist|ModuleNotFoundError|Cannot find module"),
    ("timeout", r"timed out|ETIMEDOUT|TimeoutError|exceeded .{0,40}timeout"),
    ("os_permission", r"Permission denied|Access is denied|EACCES|EPERM"),
    ("network", r"ECONNREFUSED|ECONNRESET|getaddrinfo|Could not resolve host"),
    ("rate_limit", r"rate.?limit|\bHTTP[ /]\S* ?429\b|status(code)?\W{0,3}429\b|overloaded_error"),
    ("git", r"^fatal: |^error: (failed to push|Your local changes)|merge conflict|non-fast-forward"),
    ("test_failure", r"\b\d+ (failed|failing)\b|AssertionError|^\s*FAIL(ED)?[:\s]"),
    ("nonzero_exit", r"^(Error: )?Exit code \d+"),
]
ERROR_RX = [(name, re.compile(rx, re.I | re.M)) for name, rx in ERROR_CLASSES]


def iter_records(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def run_files(main):
    """Main transcript first, then each subagent transcript."""
    return [main] + sorted(main.with_suffix("").glob("subagents/*.jsonl"))


def ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def text_of(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(text_of(x.get("text", x.get("content")) if isinstance(x, dict) else x) for x in content)
    if isinstance(content, dict):
        return text_of(content.get("text", content.get("content")))
    return str(content)


def summarize(inp):
    if not isinstance(inp, dict):
        return str(inp)[:300]
    for k in SUMMARY_KEYS:
        if inp.get(k):
            return f"{k}={str(inp[k])[:300]}"
    return json.dumps(inp, ensure_ascii=False)[:300]


def role_of(description):
    """Group agents by what they were asked to do: digits and ids folded, so 'Repro F-013' -> 'Repro F-#'."""
    if not description:
        return None
    d = re.sub(r"#?\d+", "#", description.strip())
    d = re.sub(r"\(#\)|\s+", " ", d).strip()
    return d[:60]


def error_class(body, denied, interrupted):
    if denied:
        return "permission_denied"
    if interrupted:
        return "interrupted"
    # Harness messages and the exit code come first; the actual error is usually the last thing printed.
    window = body if len(body) <= 1200 else body[:300] + "\n" + body[-900:]
    for name, rx in ERROR_RX:
        if rx.search(window):
            return name
    return "other"


POLL_LOOP = re.compile(r"""^(\s*(?:[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|\S+)|cd\s+\S+)\s*(?:;|&&)\s*)*"""
                       r"(until|while)\b.*?;\s*do\s+sleep\s+[\d.]+\s*;?\s*done\b", re.S)


def is_idle(command, parts):
    """A shell command whose every part only waits or prints, or a loop that only sleeps until a condition holds."""
    if command and POLL_LOOP.match(command):
        return True
    if not command or "$(" in command or "`" in command or ">" in command:
        return False
    pieces = [p.strip() for p in re.split(r"&&|\|\||;|\n", command) if p.strip()]
    return bool(pieces) and all(any(re.fullmatch(rx, p, re.I) for rx in parts) for p in pieces)


def list_cost(a, overrides=None):
    """List-price cost of one API call in USD."""
    inp, out, read, w5, w1 = price_of(a["model"], overrides)
    return ((a["input_tokens"] or 0) * inp + (a["output_tokens"] or 0) * out + (a["cache_read_tokens"] or 0) * read
            + (a["cache_write_5m"] or 0) * w5 + (a["cache_write_1h"] or 0) * w1) / 1e6


class SkillStack:
    """Which skill an agent is working under.

    Claude Code records `attributionSkill` on main-session turns but not inside
    subagents, and when a nested skill ends it records None instead of the outer
    skill. So: a skill load pushes, an explicit attribution wins, and a change
    from a skill to None pops back to the outer skill. The outermost skill an
    agent loaded is never popped.
    """

    def __init__(self):
        self.stack, self.prev = [], None

    def push(self, skill):
        if skill and (not self.stack or self.stack[-1] != skill):
            self.stack.append(skill)

    def on_attribution(self, attr):
        if attr:
            if attr in self.stack:
                del self.stack[self.stack.index(attr) + 1:]
            else:
                self.stack.append(attr)
        elif self.prev and len(self.stack) > 1:
            self.stack.pop()  # the outermost skill stays: Claude Code also drops it to None mid-run
        self.prev = attr
        return self.stack[-1] if self.stack else None


class Markers:
    def __init__(self, cfg):
        self.items = []
        for m in cfg.get("marker", []):
            bad = m.get("bad", [])
            self.items.append((m["name"], re.compile(m["pattern"], re.M), m.get("source", "any"), bad))

    def scan(self, rows, text, source, **where):
        for name, rx, want, bad in self.items:
            if want not in ("any", source):
                continue
            for m in rx.finditer(text):
                value = (m.group(1) if rx.groups else m.group(0)) or ""
                rows["markers"].append({**where, "marker": name, "value": value[:300], "source": source,
                                        "bad": bad == "*" or value in bad})


def parse_run(main, info, cfg):
    an = cfg["analysis"]
    markers = Markers(cfg)
    test_rx = re.compile(an["test_path"], re.I)
    rows = {t: [] for t in ("runs", "agents", "api_calls", "tool_calls", "texts", "events", "markers", "skill_loads")}
    sid = main.stem
    meta_by_agent = {}
    for meta in main.with_suffix("").glob("subagents/*.meta.json"):
        try:
            meta_by_agent[meta.name.removesuffix(".meta.json").removeprefix("agent-")] = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    run = {"session_id": sid, "project": info["project"], "archived_at": ts(info.get("archived_at")),
           "active_ms": 0, "human_prompts": 0}
    cost_state = None
    tool_owner, statuses, spawn_prompts = {}, {}, {}

    for f in run_files(main):
        agent_id = "main" if f == main else f.stem.removeprefix("agent-")
        seen_msgs, calls = set(), {}
        stamps, agent_skills, last_stop = [], set(), None
        seq = 0
        skills = SkillStack()
        inherited = inherited_uuids(main, meta_by_agent.get(agent_id, {}))
        for r in iter_records(f):
            if inherited and (r.get("uuid") in inherited or ((r.get("message") or {}).get("id") or "-") in inherited):
                continue  # a fork starts with a copy of its parent's history; that work belongs to the parent
            t = ts(r.get("timestamp"))
            if t:
                stamps.append(t)
            kind = r.get("type")
            if f == main:
                for key, field in (("cwd", "cwd"), ("git_branch", "gitBranch"), ("cc_version", "version")):
                    if not run.get(key) and r.get(field):
                        run[key] = r[field]
                if kind == "ai-title":
                    run["title"] = r.get("aiTitle")
                if kind == "cost-state" and (cost_state is None or (r.get("totalCostUSD") or 0) >= (cost_state.get("totalCostUSD") or 0)):
                    cost_state = r
            if kind == "queue-operation":
                for task, status in TASK_NOTE.findall(str(r.get("content", ""))):
                    statuses[task] = status

            if kind == "assistant":
                msg = r.get("message") or {}
                skill = skills.on_attribution(r.get("attributionSkill"))
                if skill:
                    agent_skills.add(skill)
                mid = msg.get("id") or r.get("uuid")
                if mid not in seen_msgs:
                    seen_msgs.add(mid)
                    u = msg.get("usage") or {}
                    cc = u.get("cache_creation") or {}
                    w1h = cc.get("ephemeral_1h_input_tokens") or 0
                    w5m = cc.get("ephemeral_5m_input_tokens", (u.get("cache_creation_input_tokens") or 0) - w1h) or 0
                    last_stop = msg.get("stop_reason") or last_stop
                    rows["api_calls"].append({
                        "session_id": sid, "agent_id": agent_id, "msg_id": mid, "request_id": r.get("requestId"),
                        "ts": t, "model": msg.get("model"), "effort": r.get("effort"), "skill": skill,
                        "input_tokens": u.get("input_tokens") or 0, "cache_read_tokens": u.get("cache_read_input_tokens") or 0,
                        "cache_write_5m": w5m, "cache_write_1h": w1h, "output_tokens": u.get("output_tokens") or 0,
                        "thinking_tokens": (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0,
                        "thinking_ms": r.get("thinkingDurationMs"), "stop_reason": msg.get("stop_reason"),
                        "api_error": bool(r.get("isApiErrorMessage")),
                    })
                    if r.get("isApiErrorMessage"):
                        rows["events"].append(ev(sid, agent_id, t, "api_error", None, text_of(msg.get("content"))[:500]))
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        inp = b.get("input") or {}
                        seq += 1
                        raw = json.dumps(inp, ensure_ascii=False, sort_keys=True)
                        name = b.get("name")
                        command = inp.get("command") if isinstance(inp, dict) and name in SHELL_TOOLS else None
                        path = (inp.get("file_path") or inp.get("notebook_path") or "") if isinstance(inp, dict) else ""
                        calls[b.get("id")] = {
                            "session_id": sid, "agent_id": agent_id, "tool_use_id": b.get("id"), "msg_id": mid, "seq": seq,
                            "ts": t, "tool": name, "skill": skill, "input_hash": hashlib.sha1(raw.encode()).hexdigest()[:16],
                            "input_summary": summarize(inp), "input_json": raw[:4000], "is_error": False,
                            "idle": is_idle(command, an["idle_parts"]),
                            "touches_test": name in EDIT_TOOLS and bool(test_rx.search(path)),
                        }
                        tool_owner[b.get("id")] = agent_id
                        if name in ("Agent", "Task") and isinstance(inp, dict):
                            spawn_prompts[b.get("id")] = str(inp.get("prompt") or "")[:8000]
                        markers.scan(rows, raw, "tool_input", session_id=sid, agent_id=agent_id, ts=t,
                                     tool_use_id=b.get("id"), skill=skill)
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        seq += 1
                        rows["texts"].append({"session_id": sid, "agent_id": agent_id, "seq": seq, "ts": t,
                                              "skill": skill, "text": b["text"][:4000]})
                        markers.scan(rows, b["text"], "assistant_text", session_id=sid, agent_id=agent_id, ts=t,
                                     tool_use_id=None, skill=skill)

            elif kind == "user":
                msg = r.get("message") or {}
                content = msg.get("content")
                flat = text_of(content)
                if f == main and isinstance(content, str) and not r.get("isMeta") and (r.get("origin") or {}).get("kind") == "human":
                    run["human_prompts"] += 1
                    rows["events"].append(ev(sid, agent_id, t, "human_prompt", None, content[:500]))
                if "[Request interrupted" in flat:
                    rows["events"].append(ev(sid, agent_id, t, "interrupt", None, None))
                if r.get("isCompactSummary"):
                    rows["events"].append(ev(sid, agent_id, t, "compaction", None, None))
                for task, status in TASK_NOTE.findall(flat):
                    statuses[task] = status
                if r.get("isMeta"):
                    m = SKILL_LOAD.search(flat[:2000])
                    if m:
                        body, _, args = flat[m.end():].partition("\nARGUMENTS: ")  # invocation args are not the skill
                        skill_dir = m.group(1)
                        loaded = re.split(r"[\\/]", skill_dir.rstrip("\\/"))[-1]
                        skills.push(loaded)
                        rows["skill_loads"].append({
                            "session_id": sid, "agent_id": agent_id, "ts": t, "seq": seq,
                            "skill": loaded, "skill_dir": skill_dir,
                            "content_hash": hashlib.sha1(body.strip().encode()).hexdigest()[:12], "content_len": len(body),
                            "args": args.strip()[:2000] or None,
                        })
                results = [x for x in content if isinstance(x, dict) and x.get("type") == "tool_result"] if isinstance(content, list) else []
                tur = r.get("toolUseResult")
                for x in results:
                    c = calls.get(x.get("tool_use_id"))
                    if c is None:
                        continue
                    body = text_of(x.get("content"))
                    interrupted = bool(tur.get("interrupted")) if isinstance(tur, dict) and len(results) == 1 else False
                    if isinstance(tur, dict) and tur.get("agentId") and tur.get("status"):
                        statuses.setdefault(tur["agentId"], tur["status"])
                    c.update({
                        "ts_result": t, "duration_ms": int((t - c["ts"]).total_seconds() * 1000) if t and c["ts"] else None,
                        "is_error": bool(x.get("is_error")), "denied": r.get("toolDenialKind"), "interrupted": interrupted,
                        "result_len": len(body), "result_head": body[:2000],
                    })
                    if c["is_error"]:
                        c["error_class"] = error_class(body, c["denied"], interrupted)
                    markers.scan(rows, body, "tool_result", session_id=sid, agent_id=agent_id, ts=t,
                                 tool_use_id=c["tool_use_id"], skill=c["skill"])

            elif kind == "system":
                sub = r.get("subtype")
                if sub == "turn_duration":
                    rows["events"].append(ev(sid, agent_id, t, "turn", r.get("durationMs"), None))
                    if f == main:
                        run["active_ms"] += r.get("durationMs") or 0
                elif sub == "compact_boundary":
                    rows["events"].append(ev(sid, agent_id, t, "compaction", None, None))
                elif sub:
                    rows["events"].append(ev(sid, agent_id, t, sub, r.get("durationMs"), text_of(r.get("content"))[:500]))

        rows["tool_calls"].extend(calls.values())
        meta = meta_by_agent.get(agent_id, {})
        rows["agents"].append({
            "session_id": sid, "agent_id": agent_id, "parent_tool_use_id": meta.get("toolUseId"),
            "agent_type": meta.get("agentType", "main" if f == main else None), "description": meta.get("description"),
            "role": "main" if f == main else role_of(meta.get("description")),
            "model": meta.get("model"), "spawn_depth": meta.get("spawnDepth", 0),
            "background": meta.get("requestShape") == "background",
            "started": min(stamps) if stamps else None, "ended": max(stamps) if stamps else None,
            "skills": sorted(agent_skills), "last_stop_reason": last_stop, "meta_parent": meta.get("parentAgentId"),
        })

    for a in rows["agents"]:
        a["prompt"] = spawn_prompts.get(a["parent_tool_use_id"])
    finish(rows, run, cost_state, tool_owner, statuses, cfg.get("prices"))
    return rows


def inherited_uuids(main, meta):
    """Record uuids and API message ids a fork copied from its parent's transcript."""
    if not (meta.get("isFork") or meta.get("agentType") == "fork"):
        return set()
    parent = meta.get("parentAgentId")
    pf = main.with_suffix("") / "subagents" / f"agent-{parent}.jsonl" if parent else main
    if not pf.exists():
        pf = main
    out = set()
    for r in iter_records(pf):
        out.add(r.get("uuid"))
        if r.get("type") == "assistant":
            out.add((r.get("message") or {}).get("id"))
    out.discard(None)
    return out


def finish(rows, run, cost_state, tool_owner, statuses, prices=None):
    for a in rows["agents"]:
        a["parent_agent_id"] = a.pop("meta_parent", None) or (tool_owner.get(a["parent_tool_use_id"]) if a["parent_tool_use_id"] else None)
        a["status"] = statuses.get(a["agent_id"]) if a["agent_id"] != "main" else None
    inherit_skills(rows)
    allocate_cost(rows, cost_state, prices)
    by_agent = {}
    for c in rows["api_calls"]:
        s = by_agent.setdefault(c["agent_id"], {"api_calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": None, "model": None})
        s["api_calls"] += 1
        s["model"] = s["model"] or c["model"]
        for k in ("input_tokens", "output_tokens", "cache_read_tokens"):
            s[k] += c[k] or 0
        s["cache_write_tokens"] += (c["cache_write_5m"] or 0) + (c["cache_write_1h"] or 0)
        s["peak_context"] = max(s.get("peak_context", 0), (c["input_tokens"] or 0) + (c["cache_read_tokens"] or 0)
                                + (c["cache_write_5m"] or 0) + (c["cache_write_1h"] or 0))
        if c["cost_usd"] is not None:
            s["cost_usd"] = (s["cost_usd"] or 0) + c["cost_usd"]
    for a in rows["agents"]:
        s = by_agent.get(a["agent_id"], {})
        calls = [c for c in rows["tool_calls"] if c["agent_id"] == a["agent_id"]]
        a.update({k: s.get(k, 0) for k in ("api_calls", "input_tokens", "output_tokens", "cache_read_tokens",
                                           "cache_write_tokens", "peak_context")})
        a["cost_usd"] = s.get("cost_usd")
        a["model"] = a["model"] or s.get("model")
        a["tool_calls"] = len(calls)
        a["tool_errors"] = sum(1 for c in calls if c["is_error"])
        a["compactions"] = sum(1 for e in rows["events"] if e["agent_id"] == a["agent_id"] and e["kind"] == "compaction")

    stamps = [a[k] for a in rows["agents"] for k in ("started", "ended") if a[k]]
    cs = cost_state or {}
    run.update({
        "started": min(stamps) if stamps else None, "ended": max(stamps) if stamps else None,
        "n_agents": len(rows["agents"]) - 1, "skills": sorted({s for a in rows["agents"] for s in a["skills"]}),
        "cost_usd": cs.get("totalCostUSD") if cost_state else sum(c["cost_usd"] or 0 for c in rows["api_calls"]),
        "cost_estimated": cost_state is None,
        "api_ms": cs.get("totalAPIDuration"), "tool_ms": cs.get("totalToolDuration"),
        "lines_added": cs.get("totalLinesAdded"), "lines_removed": cs.get("totalLinesRemoved"),
        "model_usage": json.dumps(cs.get("modelUsage")) if cs else None,
    })
    rows["runs"].append(run)


def ev(sid, agent_id, t, kind, value, detail):
    return {"session_id": sid, "agent_id": agent_id, "ts": t, "kind": kind, "value": value, "detail": detail}


def inherit_skills(rows):
    """A subagent with no skill of its own runs under the skill active where it was spawned."""
    spawn_skill = {c["tool_use_id"]: c["skill"] for c in rows["tool_calls"]}
    for ag in sorted(rows["agents"], key=lambda a: a["spawn_depth"] or 0):
        inherited = spawn_skill.get(ag["parent_tool_use_id"])
        if not inherited:
            continue
        for table in ("api_calls", "tool_calls", "markers", "texts"):
            for r in rows[table]:
                if r["agent_id"] == ag["agent_id"] and not r["skill"]:
                    r["skill"] = inherited
                    if table == "tool_calls":
                        spawn_skill[r["tool_use_id"]] = inherited
        if not ag["skills"]:
            ag["skills"] = [inherited]


def allocate_cost(rows, cost_state, prices=None):
    """Each call gets its list-price cost; when cost-state exists, each model's calls are scaled to its real cost."""
    usage = (cost_state or {}).get("modelUsage") or {}
    real = {}
    for k, v in usage.items():
        real[re.sub(r"\[.*\]$", "", k)] = real.get(re.sub(r"\[.*\]$", "", k), 0) + ((v or {}).get("costUSD") or 0)
    listed = {}
    for a in rows["api_calls"]:
        a["cost_usd"] = list_cost(a, prices)
        listed[a["model"]] = listed.get(a["model"], 0) + a["cost_usd"]
    if not cost_state:
        return
    for a in rows["api_calls"]:
        if a["model"] in real and listed.get(a["model"]):
            a["cost_usd"] *= real[a["model"]] / listed[a["model"]]
