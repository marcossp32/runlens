"""Read one run (main transcript + subagent transcripts) into table rows.

Only the Claude Code transcript format is assumed here. The format is internal
to Claude Code and changes between versions, so every field is read defensively
and `runlens check` compares the rows against the raw files.
"""
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .fs import fs_path

# Bump whenever a change here alters the rows a transcript produces: every run is re-ingested on the next refresh.
# 2: usage from the last record of each message, one compaction per compact_boundary, api limits apart from errors,
#    structured tool results, permission decisions, run status, pr links, cost-state tokens, skill mentions.
#    4: idle detection splits on pipes and needs a poll loop to be the whole command, "FAIL" matches upper case
#    only, roles ignore punctuation; cost allocated per token category, resumed sessions (one cost-state per
#    process), web searches, geo scope, Bedrock/Vertex ids.
PARSER_VERSION = 4

# USD per million tokens (input, output, cache_read), Anthropic first-party list prices, checked against
# https://platform.claude.com/docs/en/about-claude/pricing on 2026-10-13. Cache writes are 1.25x (5m) and 2x (1h)
# of input on every model. Haiku 5.5 has a second tier for prompts over 100K tokens (HAIKU_LONG).
# Override or extend under [prices] in config. A model in neither table gets no list price: its calls are
# flagged (runs.unpriced_models) instead of being priced with a guess.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0), "claude-mythos-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-opus-4-5": (5.0, 25.0, 0.50), "claude-opus-4-1": (15.0, 75.0, 1.50), "claude-opus-4": (15.0, 75.0, 1.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10), "claude-sonnet-5": (2.0, 10.0, 0.20), "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-sonnet-4-5": (3.0, 15.0, 0.30), "claude-sonnet-4": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10), "claude-3-5-haiku": (0.80, 4.0, 0.08),
}
HAIKU_LONG = {"claude-haiku-5-5": ((0.50, 2.50, 0.05), 100_000)}
FAST = {"claude-opus-5-5": 2.0, "claude-opus-5": 2.0, "claude-opus-4-8": 2.0}  # speed=fast: $8/$40 and $10/$50
US_GEO = 1.1  # inference_geo "us"; Claude 4.6 and later only (NO_GEO)
NO_GEO = {"claude-opus-4-5", "claude-opus-4-1", "claude-opus-4", "claude-sonnet-4-5", "claude-sonnet-4", "claude-haiku-4-5",
          "claude-3-5-haiku"}  # older models the 1.1x does not apply to; any other model is charged it
WEB_SEARCH_USD = 10.0  # per 1,000 searches
FREE_MODELS = {"<synthetic>"}  # Claude Code's own messages (API errors, limits): no tokens, no cost

SUMMARY_KEYS = ("command", "file_path", "notebook_path", "path", "pattern", "url", "query", "skill",
                "subagent_type", "description", "prompt", "to", "message", "action")

SKILL_LOAD = re.compile(r"^Base directory for this skill:\s*(.+?)\s*$", re.M)
TASK_NOTE = re.compile(r"<task-id>([\w-]+)</task-id>.*?<status>(\w+)</status>", re.S)
EXIT_CODE = re.compile(r"^(?:Error: )?Exit code (-?\d+)", re.M)
SHELL_TOOLS = {"Bash", "PowerShell"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
HUMAN_SOURCES = {"typed", "suggestion_accepted", "queued"}
# What Claude Code writes into user turns for local commands and shell output: the harness's, not a person's.
HARNESS_OUTPUT = ("<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>", "<bash-stdout>",
                  "<bash-stderr>", "<bash-input>")
# A typed slash command is a person asking for something (/m-feature, /review-pr); these built-ins only change the
# session (clear, compact, switch model...) and send no request.
COMMAND_NAME = re.compile(r"<command-name>/?([\w:-]+)</command-name>")
HOUSEKEEPING = frozenset({
    "clear", "compact", "model", "effort", "fast", "config", "cost", "usage", "status", "context", "help", "login",
    "logout", "memory", "permissions", "resume", "rewind", "exit", "export", "hooks", "mcp", "agents", "add-dir",
    "doctor", "ide", "vim", "theme", "statusline", "terminal-setup", "output-style", "todos", "bashes", "plan",
    "privacy-settings", "release-notes", "upgrade", "feedback", "bug", "plugin", "plugins", "skills", "keybindings"})

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
    ("test_failure", r"\b\d+ (failed|failing)\b|AssertionError|^\s*(?-i:FAIL(ED)?)[:\s]"),
    ("nonzero_exit", r"^(Error: )?Exit code \d+"),
]
ERROR_RX = [(name, re.compile(rx, re.I | re.M)) for name, rx in ERROR_CLASSES]


def iter_records(path, stats=None):
    """Each JSON object in a transcript. Lines that are not JSON objects are skipped and counted in stats["bad_lines"]."""
    with open(fs_path(path), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                r = None
            if isinstance(r, dict):
                yield r
            elif stats is not None:
                stats["bad_lines"] = stats.get("bad_lines", 0) + 1


def run_files(main):
    """Main transcript first, then each subagent transcript."""
    main = fs_path(main)
    return [main] + sorted(main.with_suffix("").glob("subagents/*.jsonl"))


def ts(value):
    """An aware UTC datetime. A timestamp without a zone is taken as UTC, which is what Claude Code writes."""
    if not value or not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def union_ms(spans):
    """Milliseconds covered by the turn spans with overlaps counted once; a turn without a timestamp counts in full."""
    total = sum(w for s, w in spans if s is None)
    cur_s = cur_e = None
    for s, e in sorted((x for x in spans if x[0] is not None), key=lambda x: x[0]):
        if cur_e is not None and s <= cur_e:
            cur_e = max(cur_e, e)
            continue
        if cur_e is not None:
            total += (cur_e - cur_s).total_seconds() * 1000
        cur_s, cur_e = s, e
    if cur_e is not None:
        total += (cur_e - cur_s).total_seconds() * 1000
    return int(round(total))


def as_dict(v):
    return v if isinstance(v, dict) else {}


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


def typed_text(content):
    """Only what a person or the harness typed into a user turn: the string, or its text blocks, never tool output."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x["text"] for x in content if isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str))
    return ""


def summarize(inp):
    if not isinstance(inp, dict):
        return str(inp)[:300]
    for k in SUMMARY_KEYS:
        if inp.get(k):
            return f"{k}={str(inp[k])[:300]}"
    return json.dumps(inp, ensure_ascii=False)[:300]


def role_of(description):
    """Group agents by what they were asked to do: digits and ids folded, so 'Repro F-013' -> 'Repro F-#'."""
    if not description or not isinstance(description, str):
        return None
    d = re.sub(r"#?\d+", "#", description.strip())
    d = re.sub(r"\(#\)|[:;,.]+(?=\s|$)", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
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


def api_error_kind(r, msg):
    """What an API error message was. `quota` and `rate_limit` are limits on the account, not failures of the work."""
    status = r.get("apiErrorStatus")
    quota = as_dict(r.get("quotaLimits"))
    text = text_of(msg.get("content")).lower()
    if quota.get("status") == "rejected" or quota.get("rateLimitType") or re.search(r"(session|usage|weekly) limit", text):
        return "quota"
    if r.get("error") == "rate_limit" or status == 429:
        return "rate_limit"
    if status == 529 or "overloaded" in text:
        return "overloaded"
    if isinstance(status, int) and status >= 500 or r.get("error") == "server_error":
        return "server"
    return "other"


POLL_LOOP = re.compile(r"""^(\s*(?:[A-Za-z_]\w*=(?:"[^"]*"|'[^']*'|\S+)|cd\s+\S+)\s*(?:;|&&)\s*)*"""
                       r"(until|while)\b.*?;\s*do\s+sleep\s+[\d.]+\s*;?\s*done\b", re.S)
# What may follow a poll loop without making it work: reading back what it waited for.
POLL_TAIL = re.compile(r"\s*(?:(?:;|&&)\s*(?:tail|head|cat|grep|echo|ls|wc)\b[^;&|\n]*)*;?\s*")


def is_idle(command, parts):
    """A shell command whose every part only waits or prints, or a loop that only sleeps until a condition holds."""
    m = POLL_LOOP.match(command) if command else None
    if m and POLL_TAIL.fullmatch(command, m.end()):
        return True
    if not command or "$(" in command or "`" in command or ">" in command:
        return False
    pieces = [p.strip() for p in re.split(r"&&|\|\||\||;|\n", command) if p.strip()]
    return bool(pieces) and all(any(re.fullmatch(rx, p, re.I) for rx in parts) for p in pieces)


def model_key(model):
    """The price-table name of a model id: no context suffix, date or cloud wrapper (Bedrock `anthropic.claude-...-v1:0`,
    Vertex `claude-...@20250929`)."""
    name = re.sub(r"\[.*\]$", "", model or "")
    if "claude" in name:
        name = name[name.index("claude"):]
    name = re.sub(r"-v\d+(:\d+)?$", "", name)
    return re.sub(r"[-@]\d{8}$", "", name)


def price_table(overrides=None):
    return {**PRICES, **{k: tuple(v[:3]) if isinstance(v, (list, tuple)) else (v["input"], v["output"], v["cache_read"])
                         for k, v in (overrides or {}).items()}}


def price_of(model, overrides=None, prompt_tokens=0, speed=None, geo=None):
    """(input, output, cache_read, cache_write_5m, cache_write_1h) in USD per million tokens, or None if unknown."""
    name = model_key(model)
    if name in FREE_MODELS:
        return (0.0,) * 5
    table = price_table(overrides)
    if name not in table:
        return None
    inp, out, read = table[name]
    if name in HAIKU_LONG and name not in (overrides or {}) and prompt_tokens > HAIKU_LONG[name][1]:
        inp, out, read = HAIKU_LONG[name][0]
    k = (FAST.get(name, 1.0) if speed == "fast" else 1.0) * (US_GEO if geo == "us" and name not in NO_GEO else 1.0)
    return inp * k, out * k, read * k, inp * 1.25 * k, inp * 2.0 * k


def prompt_tokens(a):
    return (a["input_tokens"] or 0) + (a["cache_read_tokens"] or 0) + (a["cache_write_5m"] or 0) + (a["cache_write_1h"] or 0)


def list_cost(a, overrides=None):
    """List-price cost of one API call in USD, or None when the model has no known price."""
    p = price_of(a["model"], overrides, prompt_tokens(a), a.get("speed"), a.get("inference_geo"))
    if p is None:
        return None
    inp, out, read, w5, w1 = p
    return ((a["input_tokens"] or 0) * inp + (a["output_tokens"] or 0) * out + (a["cache_read_tokens"] or 0) * read
            + (a["cache_write_5m"] or 0) * w5 + (a["cache_write_1h"] or 0) * w1) / 1e6 + (a.get("web_searches") or 0) * WEB_SEARCH_USD / 1000


class SkillStack:
    """Which skill an agent is working under.

    A subagent's records carry the `attributionSkill` it inherited from its parent
    (the skill that was active when it was spawned). That value is only the spawn
    default: once the subagent loads a skill itself, the load wins and the inherited
    value, or its absence, no longer moves the stack. Without an inherited value a
    skill load pushes and the outermost skill an agent loaded is never popped.

    In the main session Claude Code records the skill on each turn and None after
    every turn that skill did not run in, so skills invoked there run one after
    another under the outermost one rather than nested in each other: a new skill
    replaces the one on top (never the outermost), and a change from a skill to None
    goes back to the outermost skill. That fallback is an inference (`inferred`),
    and it ends at the next human prompt (`new_prompt`).
    """

    def __init__(self, main=False):
        self.stack, self.prev, self.main = [], None, main
        self.inherited, self.loaded, self.inferred = None, False, False

    def push(self, skill):
        """A skill the agent loaded."""
        if skill and skill not in self.stack[-1:]:
            self.loaded = True
        self._push(skill)

    def _push(self, skill):
        if not skill or skill in self.stack[-1:]:
            return
        if self.main and skill in self.stack:
            del self.stack[self.stack.index(skill) + 1:]
        elif self.main and len(self.stack) > 1:
            self.stack[-1] = skill
        else:
            self.stack.append(skill)

    def new_prompt(self):
        """A person typed a prompt in the main session: the skills of the earlier prompts have ended."""
        if self.main:
            self.stack, self.prev = [], None

    def on_attribution(self, attr):
        if attr and not isinstance(attr, str):
            attr = None
        if not self.main:
            if self.inherited is None and not self.loaded and attr:
                self.inherited = attr
            elif self.loaded and self.inherited and attr in (None, self.inherited):
                return self.stack[-1] if self.stack else None
        if attr:
            if attr in self.stack:
                del self.stack[self.stack.index(attr) + 1:]
            else:
                self._push(attr)
        elif self.prev and len(self.stack) > 1:
            # the outermost skill stays: Claude Code also drops it to None mid-run
            del self.stack[1 if self.main else -1:]
        self.prev = attr
        top = self.stack[-1] if self.stack else None
        self.inferred = bool(self.main and top and attr != top)
        return top


class Markers:
    def __init__(self, cfg):
        self.items = []
        for m in cfg.get("marker", []):
            bad = m.get("bad", [])
            self.items.append((m["name"], re.compile(m["pattern"], re.M), m.get("source", "any"),
                               "*" if bad == "*" else set(bad)))

    def scan(self, rows, text, source, **where):
        for name, rx, want, bad in self.items:
            if want not in ("any", source):
                continue
            for m in rx.finditer(text):
                value = (m.group(1) if rx.groups else m.group(0)) or ""
                rows["markers"].append({**where, "marker": name, "value": value[:300], "source": source,
                                        "bad": bad == "*" or value in bad})


TABLES = ("runs", "agents", "api_calls", "tool_calls", "texts", "events", "markers", "skill_loads", "skill_texts",
          "compactions", "model_usage", "skill_mentions")


def parse_run(main, info, cfg, now=None):
    main = fs_path(main)
    an = cfg["analysis"]
    markers = Markers(cfg)
    test_rx = re.compile(an["test_path"], re.I)
    rows = {t: [] for t in TABLES}
    sid = main.stem
    meta_by_agent = {}
    for meta in main.with_suffix("").glob("subagents/*.meta.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                meta_by_agent[meta.name.removesuffix(".meta.json").removeprefix("agent-")] = data
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    run = {"session_id": sid, "project": info["project"], "archived_at": ts(info.get("archived_at")),
           "active_ms": 0, "human_prompts": 0, "parser_version": PARSER_VERSION}
    stats = {"bad_lines": 0}
    turn_spans = []  # (start, end) of each main-agent turn; active_ms is their union, so nested turns count once
    cost_states, cost_state_ts, last_msg_ts = {}, None, None  # cost-state by startTime: one per Claude Code process
    tool_owner, statuses, spawn_prompts, pr_urls = {}, {}, {}, {}

    for f in run_files(main):
        is_main = f == main
        agent_id = "main" if is_main else f.stem.removeprefix("agent-")
        msg_rows, calls, mentions = {}, {}, []
        stamps, agent_skills = [], set()
        seq = 0
        skills = SkillStack(main=is_main)
        skill_calls, loaded_calls = {}, set()
        inherited = inherited_uuids(main, f, meta_by_agent.get(agent_id, {}))
        for r in iter_records(f, stats):
            msg = as_dict(r.get("message"))
            if inherited and (r.get("uuid") in inherited or (msg.get("id") or "-") in inherited):
                continue  # a fork starts with a copy of its parent's history; that work belongs to the parent
            t = ts(r.get("timestamp"))
            if t:
                stamps.append(t)
            kind = r.get("type")
            if is_main:
                for key, field in (("cwd", "cwd"), ("git_branch", "gitBranch"), ("cc_version", "version"), ("entrypoint", "entrypoint")):
                    if not run.get(key) and isinstance(r.get(field), str) and r[field]:
                        run[key] = r[field]
                if kind == "ai-title":
                    run["title"] = r.get("aiTitle")
                if kind == "cost-state":
                    cost_state_ts = t or cost_state_ts
                    key = r.get("startTime")
                    if key not in cost_states or (r.get("totalCostUSD") or 0) >= (cost_states[key].get("totalCostUSD") or 0):
                        cost_states[key] = r
                if kind in ("user", "assistant") and t:
                    last_msg_ts = max(last_msg_ts or t, t)
            if kind == "pr-link" and r.get("prUrl"):
                pr_urls.setdefault(str(r["prUrl"]), t)
            if kind == "queue-operation":
                for task, status in TASK_NOTE.findall(str(r.get("content", ""))):
                    statuses[task] = status

            if kind == "assistant":
                skill = skills.on_attribution(r.get("attributionSkill"))
                inferred = skills.inferred
                if skill:
                    agent_skills.add(skill)
                mid = msg.get("id") or r.get("uuid")
                u = as_dict(msg.get("usage"))
                cc = as_dict(u.get("cache_creation"))
                w1h = cc.get("ephemeral_1h_input_tokens") or 0
                w5m = cc.get("ephemeral_5m_input_tokens", (u.get("cache_creation_input_tokens") or 0) - w1h) or 0
                tokens = {"input_tokens": u.get("input_tokens") or 0, "cache_read_tokens": u.get("cache_read_input_tokens") or 0,
                          "cache_write_5m": w5m, "cache_write_1h": w1h, "output_tokens": u.get("output_tokens") or 0,
                          "thinking_tokens": as_dict(u.get("output_tokens_details")).get("thinking_tokens") or 0,
                          "web_searches": as_dict(u.get("server_tool_use")).get("web_search_requests") or 0}
                a = msg_rows.get(mid)
                if a is None:
                    is_err = bool(r.get("isApiErrorMessage"))
                    err_kind = api_error_kind(r, msg) if is_err else None
                    limit = err_kind in ("quota", "rate_limit")
                    a = msg_rows[mid] = {
                        "session_id": sid, "agent_id": agent_id, "msg_id": mid, "request_id": r.get("requestId"),
                        "ts": t, "model": msg.get("model"), "requested_model": r.get("requestedModel"),
                        "effort": r.get("effort"), "skill": skill, "skill_inferred": inferred, **tokens,
                        "thinking_ms": r.get("thinkingDurationMs"), "stop_reason": msg.get("stop_reason"),
                        "api_error": is_err and not limit, "api_limit": limit, "api_error_kind": err_kind,
                        "api_error_status": r.get("apiErrorStatus") if isinstance(r.get("apiErrorStatus"), int) else None,
                        "speed": u.get("speed"), "inference_geo": u.get("inference_geo"),
                        "attribution_agent": r.get("attributionAgent"), "mcp_server": r.get("attributionMcpServer"),
                        "mcp_tool": r.get("attributionMcpTool"),
                    }
                    rows["api_calls"].append(a)
                    if is_err:
                        rows["events"].append(ev(sid, agent_id, t, "api_limit" if limit else "api_error",
                                                 a["api_error_status"], text_of(msg.get("content"))[:500], err_kind))
                else:
                    # Claude Code writes one record per content block while the message streams. The usage on the
                    # first record is partial (output_tokens grows), so keep the largest value of each count and
                    # the last stop_reason that was set.
                    for k, v in tokens.items():
                        if v > (a[k] or 0):
                            a[k] = v
                    a["stop_reason"] = msg.get("stop_reason") or a["stop_reason"]
                    if (r.get("thinkingDurationMs") or 0) > (a["thinking_ms"] or 0):
                        a["thinking_ms"] = r.get("thinkingDurationMs")
                content = msg.get("content")
                a["_len"] = a.get("_len", 0) + content_len(content)  # weighs the output tokens a message is missing
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use":
                        inp = b.get("input") if b.get("input") is not None else {}
                        seq += 1
                        raw = json.dumps(inp, ensure_ascii=False, sort_keys=True)
                        name = b.get("name")
                        command = inp.get("command") if isinstance(inp, dict) and name in SHELL_TOOLS else None
                        path = (inp.get("file_path") or inp.get("notebook_path") or "") if isinstance(inp, dict) else ""
                        calls[b.get("id")] = {
                            "session_id": sid, "agent_id": agent_id, "tool_use_id": b.get("id"), "msg_id": mid, "seq": seq,
                            "ts": t, "tool": name, "skill": skill, "skill_inferred": inferred, "input_hash": hashlib.sha1(raw.encode()).hexdigest()[:16],
                            "input_summary": summarize(inp), "input_json": raw[:4000], "is_error": False,
                            "idle": is_idle(command if isinstance(command, str) else None, an["idle_parts"]),
                            "touches_test": name in EDIT_TOOLS and isinstance(path, str) and bool(test_rx.search(path)),
                        }
                        tool_owner.setdefault(b.get("id"), agent_id)  # the first agent to issue a call owns it
                        if name in ("Agent", "Task") and isinstance(inp, dict):
                            spawn_prompts[b.get("id")] = str(inp.get("prompt") or "")[:8000]
                        if name == "Skill" and isinstance(inp, dict) and inp.get("skill"):
                            skill_calls[b.get("id")] = skill_name(inp["skill"])
                            mentions.append(("invoke", t, skill_name(inp["skill"])))
                        markers.scan(rows, raw, "tool_input", session_id=sid, agent_id=agent_id, ts=t,
                                     tool_use_id=b.get("id"), skill=skill)
                    elif b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                        seq += 1
                        rows["texts"].append({"session_id": sid, "agent_id": agent_id, "seq": seq, "ts": t,
                                              "skill": skill, "text": b["text"][:4000]})
                        markers.scan(rows, b["text"], "assistant_text", session_id=sid, agent_id=agent_id, ts=t,
                                     tool_use_id=None, skill=skill)

            elif kind == "user":
                content = msg.get("content")
                flat = text_of(content)
                prompt = typed_text(content)
                if is_main and not r.get("isMeta") and not has_tool_result(content) and is_human_prompt(r, prompt):
                    run["human_prompts"] += 1
                    skills.new_prompt()
                    rows["events"].append(ev(sid, agent_id, t, "human_prompt", None, prompt[:500],
                                             r.get("promptSource") or as_dict(r.get("origin")).get("kind")))
                # not inside a tool result that happens to quote it, nor a compaction summary that does
                if "[Request interrupted" in typed_text(content) and not r.get("isCompactSummary"):
                    rows["events"].append(ev(sid, agent_id, t, "interrupt", None, None, None))
                for task, status in TASK_NOTE.findall(flat):
                    statuses[task] = status
                if r.get("isMeta"):
                    load = skill_load(flat)
                    call_id = r.get("sourceToolUseID")
                    if not load and call_id in skill_calls and call_id not in loaded_calls and flat.strip():
                        # some skills have no base directory: their text follows the Skill call without the header
                        load = (skill_calls[call_id], None, flat.strip(), None)
                    if load:
                        loaded_calls.add(call_id)
                        loaded, skill_dir, body, args = load
                        skills.push(loaded)
                        digest = hashlib.sha1(body.encode()).hexdigest()[:12]
                        rows["skill_loads"].append({
                            "session_id": sid, "agent_id": agent_id, "ts": t, "seq": seq,
                            "skill": loaded, "skill_dir": skill_dir,
                            "content_hash": digest, "content_len": len(body), "args": args,
                        })
                        rows["skill_texts"].append({"skill": loaded, "content_hash": digest, "text": body})
                        mentions.append(("invoke", t, loaded))
                results = [x for x in content if isinstance(x, dict) and x.get("type") == "tool_result"] if isinstance(content, list) else []
                tur = as_dict(r.get("toolUseResult"))
                single = len(results) == 1
                for x in results:
                    c = calls.get(x.get("tool_use_id"))
                    if c is None:
                        continue
                    body = text_of(x.get("content"))
                    interrupted = bool(tur.get("interrupted")) if single else False
                    if tur.get("agentId") and tur.get("status"):
                        statuses.setdefault(str(tur["agentId"]), tur["status"])
                    c.update({
                        "ts_result": t, "duration_ms": int((t - c["ts"]).total_seconds() * 1000) if t and c["ts"] else None,
                        "is_error": bool(x.get("is_error")), "denied": r.get("toolDenialKind"), "interrupted": interrupted,
                        "result_len": len(body), "result_head": body[:2000],
                    })
                    c.update(tool_result_fields(body, tur if single else {}, as_dict(r.get("permissionDecision"))))
                    if c["is_error"]:
                        c["error_class"] = error_class(body, c["denied"], interrupted)
                    markers.scan(rows, body, "tool_result", session_id=sid, agent_id=agent_id, ts=t,
                                 tool_use_id=c["tool_use_id"], skill=c["skill"])

            elif kind == "attachment":
                att = as_dict(r.get("attachment"))
                if att.get("type") == "skill_mention" and att.get("skillName"):
                    mentions.append(("mention", t, skill_name(att["skillName"])))
                elif att.get("type") == "invoked_skills":
                    names = [s.get("name") for s in att.get("skills") or [] if isinstance(s, dict) and s.get("name")]
                    rows["events"].append(ev(sid, agent_id, t, "skills_reinjected", len(names), ", ".join(names)[:500], None))

            elif kind == "system":
                sub = r.get("subtype")
                if sub == "turn_duration":
                    ms = r.get("durationMs") if isinstance(r.get("durationMs"), (int, float)) else None
                    rows["events"].append(ev(sid, agent_id, t, "turn", int(ms) if ms is not None else None, None, None))
                    if is_main and ms:
                        turn_spans.append((t - timedelta(milliseconds=ms), t) if t else (None, int(ms)))
                elif sub == "compact_boundary":
                    # Claude Code also writes an isCompactSummary user record for the same compaction: counting
                    # only the boundary gives one event per real compaction.
                    cm = as_dict(r.get("compactMetadata"))
                    rows["compactions"].append({"session_id": sid, "agent_id": agent_id, "ts": t, "trigger": cm.get("trigger"),
                                                "pre_tokens": cm.get("preTokens"), "post_tokens": cm.get("postTokens"),
                                                "duration_ms": cm.get("durationMs")})
                    rows["events"].append(ev(sid, agent_id, t, "compaction", cm.get("preTokens"), None, cm.get("trigger")))
                elif isinstance(sub, str) and sub:
                    rows["events"].append(ev(sid, agent_id, t, sub, r.get("durationMs") if isinstance(r.get("durationMs"), int) else None,
                                             text_of(r.get("content"))[:500], None))

        rows["tool_calls"].extend(calls.values())
        rows["skill_mentions"].extend(skill_mentions(sid, agent_id, mentions))
        meta = meta_by_agent.get(agent_id, {})
        last_stop = None
        for a in msg_rows.values():
            last_stop = a["stop_reason"] or last_stop
        rows["agents"].append({
            "session_id": sid, "agent_id": agent_id, "parent_tool_use_id": meta.get("toolUseId"),
            "agent_type": meta.get("agentType", "main" if is_main else None), "description": meta.get("description"),
            "role": "main" if is_main else role_of(meta.get("description")),
            "model": meta.get("model"), "effort": meta.get("effort"), "spawn_depth": meta.get("spawnDepth", 0),
            "background": meta.get("requestShape") == "background", "stopped_by_user": bool(meta.get("stoppedByUser")),
            "started": min(stamps) if stamps else None, "ended": max(stamps) if stamps else None,
            "skills": sorted(agent_skills), "last_stop_reason": last_stop, "meta_parent": meta.get("parentAgentId"),
        })

    for a in rows["agents"]:
        a["prompt"] = spawn_prompts.get(a["parent_tool_use_id"])
    run["pr_urls"] = sorted(pr_urls, key=lambda u: pr_urls[u] or datetime.min.replace(tzinfo=timezone.utc))
    run["bad_lines"] = stats["bad_lines"]
    run["active_ms"] = union_ms(turn_spans)
    finish(rows, run, merge_cost_states(cost_states), tool_owner, statuses, cfg.get("prices"))
    run_status(run, cost_state_ts, last_msg_ts, cfg.get("runs") or {}, now, stale=bool(info.get("stale")))
    return rows


def is_human_prompt(r, content):
    """A prompt a person sent, across Claude Code versions.

    Newer versions mark it with origin.kind = human or promptSource typed/suggestion_accepted/queued; some older
    ones wrote typed slash commands with neither field. Task notifications and SDK prompts are not human.
    """
    if r.get("isCompactSummary") or content.lstrip().startswith(HARNESS_OUTPUT):
        return False
    command = COMMAND_NAME.search(content[:500])
    if command and command.group(1).lower() in HOUSEKEEPING:
        return False
    origin = as_dict(r.get("origin")).get("kind")
    source = r.get("promptSource")
    if origin == "human" or source in HUMAN_SOURCES:
        return True
    if origin or source:
        return False
    return not content.lstrip().startswith("<task-notification>")


def has_tool_result(content):
    return isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content)


def skill_load(flat):
    """(skill, skill_dir, body, args) if a user record is Claude Code injecting a skill's text."""
    m = SKILL_LOAD.search(flat[:2000])
    if not m:
        return None
    body, _, args = flat[m.end():].partition("\nARGUMENTS: ")  # invocation args are not the skill
    skill_dir = m.group(1)
    return re.split(r"[\\/]", skill_dir.rstrip("\\/"))[-1], skill_dir, body.strip(), args.strip()[:2000] or None


def skill_name(name):
    """A skill's name without its plugin prefix: the Skill tool says `plugin:skill`, the load says `skill`."""
    return str(name).rsplit(":", 1)[-1]


def tool_result_fields(body, tur, decision):
    """What Claude Code records about a tool result beyond its text: exit code, timeout, own duration, diff size, permission."""
    out = {"exit_code": None, "return_code_info": tur.get("returnCodeInterpretation") if isinstance(tur.get("returnCodeInterpretation"), str) else None,
           "timed_out_ms": tur.get("timedOutAfterMs") if isinstance(tur.get("timedOutAfterMs"), int) else None,
           "tool_duration_ms": None, "patch_added": None, "patch_removed": None, "git_op": None,
           "permission": decision.get("decision"), "permission_source": None}
    m = EXIT_CODE.search(body[:300])
    if m:
        out["exit_code"] = int(m.group(1))
    if isinstance(tur.get("durationMs"), (int, float)):
        out["tool_duration_ms"] = int(tur["durationMs"])
    elif isinstance(tur.get("durationSeconds"), (int, float)):
        out["tool_duration_ms"] = int(tur["durationSeconds"] * 1000)
    patch = tur.get("structuredPatch")
    if isinstance(patch, list) and patch:
        lines = [ln for h in patch if isinstance(h, dict) for ln in h.get("lines") or [] if isinstance(ln, str)]
        out["patch_added"] = sum(1 for ln in lines if ln.startswith("+"))
        out["patch_removed"] = sum(1 for ln in lines if ln.startswith("-"))
    elif tur.get("type") == "create" and isinstance(tur.get("content"), str):
        out["patch_added"], out["patch_removed"] = tur["content"].count("\n") + 1, 0
    if isinstance(tur.get("gitOperation"), dict):
        out["git_op"] = ",".join(sorted(tur["gitOperation"]))[:100] or None
    if decision:
        out["permission_source"] = ":".join(str(x) for x in (decision.get("source"), decision.get("reasonType")) if x) or None
    return out


def skill_mentions(sid, agent_id, items):
    """Each time a skill's name came up without the Skill tool being called, and whether it was invoked afterwards."""
    out = []
    for i, (kind, t, skill) in enumerate(items):
        if kind != "mention":
            continue
        later = any(k == "invoke" and s == skill for k, _, s in items[i + 1:])
        out.append({"session_id": sid, "agent_id": agent_id, "ts": t, "skill": skill, "invoked": later})
    return out


def inherited_uuids(main, f, meta):
    """Record uuids and API message ids a fork copied from its parent's transcript."""
    if not (meta.get("isFork") or meta.get("agentType") == "fork"):
        return set()
    parent = meta.get("parentAgentId")
    pf = main.with_suffix("") / "subagents" / f"agent-{parent}.jsonl" if parent else main
    if not pf.exists():
        pf = main
    out = set()
    for r in iter_records(pf):  # a new-style fork's second record repeats the spawning message, usage included
        out.add(r.get("uuid"))
        if r.get("type") == "assistant":
            out.add(as_dict(r.get("message")).get("id"))
    out.discard(None)
    return out


def finish(rows, run, cost_state, tool_owner, statuses, prices=None):
    for a in rows["agents"]:
        a["parent_agent_id"] = a.pop("meta_parent", None) or (tool_owner.get(a["parent_tool_use_id"]) if a["parent_tool_use_id"] else None)
        a["status"] = statuses.get(a["agent_id"]) if a["agent_id"] != "main" else None
    inherit_skills(rows)
    unpriced = allocate_cost(rows, cost_state, prices)
    uncovered = sum(c["cost_usd"] or 0 for c in rows["api_calls"] if not covered(cost_state, c))
    for c in rows["api_calls"]:
        c.pop("_len", None)
    by_agent = {}
    for c in rows["api_calls"]:
        s = by_agent.setdefault(c["agent_id"], {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0,
                                                "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": None,
                                                "model": None, "peak_context": 0})
        s["api_calls"] += 1
        s["model"] = s["model"] or c["model"]
        for k in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens"):
            s[k] += c[k] or 0
        s["cache_write_tokens"] += (c["cache_write_5m"] or 0) + (c["cache_write_1h"] or 0)
        s["peak_context"] = max(s["peak_context"], prompt_tokens(c))
        if c["cost_usd"] is not None:
            s["cost_usd"] = (s["cost_usd"] or 0) + c["cost_usd"]
    tools = defaultdict(lambda: [0, 0])
    for c in rows["tool_calls"]:
        tools[c["agent_id"]][0] += 1
        tools[c["agent_id"]][1] += (bool(c["is_error"]) and not c.get("denied"))
    compactions = defaultdict(int)
    for c in rows["compactions"]:
        compactions[c["agent_id"]] += 1
    for a in rows["agents"]:
        s = by_agent.get(a["agent_id"], {})
        a.update({k: s.get(k, 0) for k in ("api_calls", "input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens",
                                           "cache_write_tokens", "peak_context")})
        a["cost_usd"] = s.get("cost_usd")
        a["model"] = a["model"] or s.get("model")
        a["tool_calls"], a["tool_errors"] = tools[a["agent_id"]]
        a["compactions"] = compactions[a["agent_id"]]

    stamps = [a[k] for a in rows["agents"] for k in ("started", "ended") if a[k]]
    cs = cost_state or {}
    usage = as_dict(cs.get("modelUsage"))
    for model, u in usage.items():
        u = as_dict(u)
        rows["model_usage"].append({
            "session_id": run["session_id"], "model": model, "input_tokens": u.get("inputTokens"),
            "output_tokens": u.get("outputTokens"), "thinking_tokens": u.get("thinkingTokens"),
            "cache_read_tokens": u.get("cacheReadInputTokens"), "cache_write_tokens": u.get("cacheCreationInputTokens"),
            "web_search_requests": u.get("webSearchRequests"), "cost_usd": u.get("costUSD"),
        })
    real_calls = [c for c in rows["api_calls"] if model_key(c["model"]) not in FREE_MODELS]
    if not cost_state:
        total_cost = sum(c["cost_usd"] or 0 for c in rows["api_calls"])
    else:
        total_cost = None if cs.get("totalCostUSD") is None else cs["totalCostUSD"] + uncovered
    run.update({
        "started": min(stamps) if stamps else None, "ended": max(stamps) if stamps else None,
        "n_agents": len(rows["agents"]) - 1, "skills": sorted({s for a in rows["agents"] for s in a["skills"]}),
        "cost_usd": total_cost,
        "cost_estimated": cost_state is None or uncovered > 0, "cost_uncovered_usd": uncovered if cost_state else None,
        "api_ms": cs.get("totalAPIDuration"), "api_ms_no_retries": cs.get("totalAPIDurationWithoutRetries"),
        "tool_ms": cs.get("totalToolDuration"), "total_ms": cs.get("totalDuration"),
        "lines_added": cs.get("totalLinesAdded"), "lines_removed": cs.get("totalLinesRemoved"),
        "model_usage": json.dumps(cs.get("modelUsage")) if cs else None,
        "unknown_model_cost": bool(cs.get("hasUnknownModelCost")) if cost_state else None,
        "unpriced_models": sorted(unpriced), "n_api_calls": len(real_calls),
    })
    rows["runs"].append(run)


def run_status(run, cost_state_ts, last_msg_ts, opts, now=None, stale=False):
    """complete: Claude Code wrote its closing cost-state after the last turn, or nothing was added for idle_hours.
    An archive older than its source (stale) is never complete through idleness: its numbers are partial.
    open: the session may still be going, so its numbers are partial. stub: too small to say anything."""
    now = now or datetime.now(timezone.utc)
    if cost_state_ts and (not last_msg_ts or cost_state_ts >= last_msg_ts):
        run["status"], run["ended_by"] = "complete", "session_end"
    elif run["ended"] and not stale and now - run["ended"] > timedelta(hours=opts.get("idle_hours", 12)):
        run["status"], run["ended_by"] = "complete", "idle"
    else:
        run["status"], run["ended_by"] = "open", None
    run["is_stub"] = (run["n_api_calls"] < opts.get("stub_api_calls", 3)
                      or (run["cost_usd"] is not None and run["cost_usd"] < opts.get("stub_cost_usd", 0.02)))


def ev(sid, agent_id, t, kind, value, detail, source):
    return {"session_id": sid, "agent_id": agent_id, "ts": t, "kind": kind,
            "value": value if isinstance(value, int) else None, "detail": detail, "source": source}


def inherit_skills(rows):
    """A subagent with no skill of its own runs under the skill active where it was spawned."""
    spawn_skill = {c["tool_use_id"]: c["skill"] for c in rows["tool_calls"]}
    by_agent = defaultdict(lambda: defaultdict(list))
    for table in ("api_calls", "tool_calls", "markers", "texts"):
        for r in rows[table]:
            by_agent[r["agent_id"]][table].append(r)
    for ag in sorted(rows["agents"], key=lambda a: a["spawn_depth"] or 0):
        inherited = spawn_skill.get(ag["parent_tool_use_id"])
        if not inherited:
            continue
        for table, items in by_agent[ag["agent_id"]].items():
            for r in items:
                if not r["skill"]:
                    r["skill"] = inherited
                    if table == "tool_calls":
                        spawn_skill[r["tool_use_id"]] = inherited
        if not ag["skills"]:
            ag["skills"] = [inherited]


def merge_cost_states(states):
    """One cost-state for the run. A resumed session writes one per Claude Code process, each covering only its own
    process (`startTime` onward), so the totals and token counts of all of them are added up."""
    states = [s for s in states.values() if isinstance(s, dict)]
    if len(states) < 2:
        return states[0] if states else None
    out = dict(max(states, key=lambda s: s.get("totalCostUSD") or 0))
    for key in {k for s in states for k, v in s.items() if k.startswith("total") and isinstance(v, (int, float))}:
        out[key] = sum(s.get(key) or 0 for s in states)
    usage = {}
    for s in states:
        for model, u in as_dict(s.get("modelUsage")).items():
            acc = usage.setdefault(model, {})
            for k, v in as_dict(u).items():
                if isinstance(v, (int, float)):
                    acc[k] = acc.get(k, 0) + v
    out["modelUsage"] = usage
    out["hasUnknownModelCost"] = any(s.get("hasUnknownModelCost") for s in states)
    starts = [s["startTime"] for s in states if isinstance(s.get("startTime"), (int, float))]
    out["startTime"] = min(starts) if starts else None
    return out


def covered(cost_state, a):
    """Whether cost-state accounts for this call: it only counts from the start of the process that wrote it."""
    start = (cost_state or {}).get("startTime")
    if not cost_state or not isinstance(start, (int, float)) or not a["ts"]:
        return True
    return a["ts"] >= datetime.fromtimestamp(start / 1000, timezone.utc)


def content_len(content):
    """Characters of text, thinking and tool input in a message: what its output tokens were spent on."""
    if isinstance(content, str):
        return len(content)
    n = 0
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_use":
            n += len(json.dumps(b.get("input"), ensure_ascii=False))
        else:
            n += len(b.get("text") or b.get("thinking") or "")
    return n


# cost-state field behind each token count of a call. The cache writes are one count there.
USAGE_FIELDS = {"input_tokens": "inputTokens", "cache_read_tokens": "cacheReadInputTokens"}


def allocate_cost(rows, cost_state, prices=None):
    """Each call gets its list-price cost; when cost-state exists, each model's calls are scaled to its real cost.

    The transcript holds fewer tokens than cost-state: most messages never get their final `output_tokens` (only the
    value from the start of the stream), and calls that never appear in it (titles, classifiers, advisors) add input.
    Before scaling, each category's gap is handed to the calls: input, cache reads and cache writes in proportion
    to the call's own tokens, output only to the calls with no `stop_reason` (their count is the stale one), in
    proportion to the text, thinking and tool input they carry. The rest is one factor per model. Calls before the
    process cost-state starts at keep their list price.

    Returns the models that have no list price. Their calls keep a NULL cost unless cost-state gives the model's
    real cost, in which case it is split across them by tokens.
    """
    usage = as_dict((cost_state or {}).get("modelUsage"))
    real, tokens = defaultdict(float), defaultdict(lambda: defaultdict(float))
    for k, v in usage.items():
        v = as_dict(v)
        real[model_key(k)] += v.get("costUSD") or 0
        for field in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"):
            if isinstance(v.get(field), (int, float)):
                tokens[model_key(k)][field] += v[field]
    for a in rows["api_calls"]:
        a["cost_usd"] = list_cost(a, prices)
    if not cost_state:
        return {model_key(a["model"]) or "(unknown)" for a in rows["api_calls"] if a["cost_usd"] is None}
    by_model = defaultdict(list)
    for a in rows["api_calls"]:
        if covered(cost_state, a) and model_key(a["model"]) in real:
            by_model[model_key(a["model"])].append(a)
    unpriced = {model_key(a["model"]) or "(unknown)" for a in rows["api_calls"] if a["cost_usd"] is None}
    for key, calls in by_model.items():
        est = [dict(a) for a in calls]  # the call with the tokens it should have had
        for field, name in USAGE_FIELDS.items():
            scale_category(est, [field], tokens[key].get(name))
        scale_category(est, ["cache_write_5m", "cache_write_1h"], tokens[key].get("cacheCreationInputTokens"))
        gap = tokens[key].get("outputTokens", 0) - sum(a["output_tokens"] or 0 for a in calls) if "outputTokens" in tokens[key] else 0
        if gap > 0:
            stale = [(a, e) for a, e in zip(calls, est) if not a["stop_reason"] and not a["api_error"]]
            weights = [(e, a.get("_len", 0)) for a, e in stale or zip(calls, est)]
            if not sum(w for _, w in weights):
                weights = [(e, 1) for e, _ in weights]
            total = sum(w for _, w in weights)
            for e, w in weights:
                e["output_tokens"] = (e["output_tokens"] or 0) + gap * w / total
        listed = {id(a): list_cost(e, prices) for a, e in zip(calls, est)}
        total = sum(c for c in listed.values() if c is not None)
        weight = {id(a): prompt_tokens(e) + 5 * (e["output_tokens"] or 0) for a, e in zip(calls, est)}
        wtotal = sum(weight[id(a)] for a in calls if listed[id(a)] is None)
        for a in calls:
            c = listed[id(a)]
            if c is not None and total:
                a["cost_usd"] = c * real[key] / total
            elif c is None and wtotal:
                a["cost_usd"] = real[key] * weight[id(a)] / wtotal
    return unpriced


def scale_category(calls, fields, real):
    """Raise the `fields` of each call by the factor that brings their sum up to cost-state's count, if it is higher."""
    seen = sum(a[f] or 0 for a in calls for f in fields)
    if real and seen and real > seen:
        for a in calls:
            for f in fields:
                a[f] = (a[f] or 0) * real / seen
