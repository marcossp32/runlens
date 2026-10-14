"""Turn real incidents into eval cases, so a skill edit can be checked on a controlled re-run.

runlens finds what failed in your own runs; an eval re-runs the same task with and
without the skill (or with the old and the new version) and grades the result.
`runlens export-eval` writes both formats Anthropic documents:

- `claude plugin eval` (Claude Code >= 2.1.269), https://code.claude.com/docs/en/plugin-evals:
  a plugin directory with `evals/<case>/prompt.md` (YAML frontmatter: run limits and
  `allowed_tools`; body: the prompt) and one `graders/<name>.md` per check. Grader types used
  here: `tool_used` (`tool`, `input_match`, `min`, `max`), `regex` (`pattern`, `match:
  not_contains`, `target: trace`) and `llm` (body = PASS/FAIL rubric). A case that resumes a
  transcript adds `case.yaml` with `schema_version: "1.1"`, `name` and `context.history_file`.
  Runs start in an empty workspace with only the plugin loaded, so the skill is copied into
  `skills/` of a generated plugin.
- skill-creator, https://code.claude.com/docs/en/skills#run-evals-with-skill-creator and the
  format it links, https://agentskills.io/skill-creation/evaluating-skills: `evals/evals.json`
  in the skill directory, `{"skill_name", "evals": [{"id", "prompt", "expected_output",
  "files", "assertions"}]}`. The skill-creator skill's own references/schemas.md names the
  assertion list `expectations`, so both keys are written with the same list.

What is reconstructed, and what is not (also written to the export's README):
- The task prompt: a subagent's spawn prompt verbatim; for the main session, the skill
  invocation with its recorded arguments, else the run's first human prompt.
- The skill: the files on disk now, which may be a newer version than the one that failed
  (the incident's version hash is recorded in each case).
- Assertions derived from the incident type: deterministic graders where the failure has a
  countable trace (a repeated call, polling, a blocked command, a bad marker), a rubric for
  the judge where it does not (test tampering, error streaks, failed subagents).
- Optionally (`--history`), the main session's transcript cut just before the failing step,
  as `context.history_file`, to replay the moment instead of the whole task.
- NOT reconstructed: the repository and its files (each run starts empty), other skills,
  agents, hooks and MCP servers the run relied on, your CLAUDE.md and permission rules, and
  any human reply mid-run. A case whose task needs the repository needs a
  `context.scaffold_script` you write. Interrupts, compactions and API errors have no task-level
  assertion and are skipped.
"""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import classify, config, store
from .incidents import TYPES
from .privacy import redactor

PLUGIN = "runlens-evals"
SKIP = {"interrupt", "compaction", "api_error"}
READ_ONLY = {"Read", "Glob", "Grep", "NotebookRead", "Skill", "AskUserQuestion", "Agent", "TodoWrite",
             "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskStop"}
GRANTABLE = {"Bash", "PowerShell", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch"}
MAX_TURNS, TIMEOUT = 60, 1800  # generous: hitting either is recorded as a run error (plugin-evals docs)
MAIN_FIELD = ("command", "file_path", "notebook_path", "pattern", "url", "query", "skill", "prompt")


def js_escape(text):
    """Escape for a JavaScript regex (graders use JS syntax), escaping only what is special in JS and Python."""
    return re.sub(r"([\\^$.*+?()\[\]{}|/])", r"\\\1", text)


def yaml_value(v):
    """JSON is valid YAML 1.2 flow syntax: every scalar and list is written as JSON, so nothing needs quoting rules."""
    return json.dumps(v, ensure_ascii=False)


def frontmatter(fields, body=""):
    lines = ["---"] + [f"{k}: {yaml_value(v)}" for k, v in fields.items() if v not in (None, "", [])] + ["---", ""]
    return "\n".join(lines) + (body.strip() + "\n" if body else "")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "case"


# ---------------------------------------------------------------- what to export

def select(con, ids=None, skills=None, labels=None, types=None, limit=10):
    """Incidents to export, oldest first. Unless picked by id, incidents whose latest label says the system
    worked as designed are left out: they are not failures to reproduce. More matches than `limit`: a fixed-seed
    stratified sample, so a mix of incident types is exported rather than the oldest of one type."""
    lab = classify.latest_labels(con)
    where, args = ["1=1"], []
    for col, vals in (("i.incident_id", ids), ("i.skill", skills), ("i.type", types)):
        if vals:
            where.append(f"list_contains(?, {col})")
            args.append(list(vals))
    if labels:
        where.append("list_contains(?, coalesce(h.category, l.category))")
        args.append(list(labels))
    if not ids:
        where.append("coalesce(h.category, l.category, '') <> 'expected_behavior'")
    rows = con.execute(f"""
        SELECT i.incident_id, i.session_id, i.agent_id, i.type, i.key, i.n, i.agent_type, i.role, i.skill, i.seq, i.ts,
               i.anchor, i.context, a.prompt, r.cwd, r.git_branch,
               coalesce(h.category, l.category), coalesce(h.fault, l.fault), coalesce(h.note, l.note), l.instruction,
               CASE WHEN h.category IS NOT NULL THEN 'human' WHEN l.category IS NOT NULL THEN 'llm' END
        FROM incidents i
        LEFT JOIN agents a ON a.session_id = i.session_id AND a.agent_id = i.agent_id
        LEFT JOIN runs r ON r.session_id = i.session_id
        LEFT JOIN {lab} l ON l.incident_id = i.incident_id AND l.source = 'llm'
        LEFT JOIN {lab} h ON h.incident_id = i.incident_id AND h.source = 'human'
        WHERE {' AND '.join(where)} ORDER BY i.ts""", args).fetchall()
    keys = ["incident_id", "session_id", "agent_id", "type", "key", "n", "agent_type", "role", "skill", "seq", "ts",
            "anchor", "context", "spawn_prompt", "cwd", "git_branch", "label", "fault", "note", "instruction", "label_source"]
    found = [dict(zip(keys, r)) for r in rows]
    keep = {c[0] for c in classify.sample([(i["incident_id"], i["type"], i["ts"]) for i in found], int(limit), seed=0)}
    return [i for i in found if i["incident_id"] in keep]


def anchor_call(con, inc):
    if not inc.get("anchor"):
        return None
    row = con.execute("SELECT tool, input_json, input_summary FROM tool_calls WHERE session_id = ? AND tool_use_id = ?",
                      [inc["session_id"], inc["anchor"]]).fetchone()
    return {"tool": row[0], "input_json": row[1], "summary": row[2]} if row else None


def agent_tools(con, inc):
    return [r[0] for r in con.execute("SELECT DISTINCT tool FROM tool_calls WHERE session_id = ? AND agent_id = ? ORDER BY 1",
                                      [inc["session_id"], inc["agent_id"]]).fetchall() if r[0]]


# ---------------------------------------------------------------- the task prompt

def transcript(sid, agent_id="main"):
    files = sorted(config.ARCHIVE.glob(f"*/{sid}.jsonl"))
    if not files:
        return None
    return files[0] if agent_id == "main" else files[0].with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"


def records(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append(None)  # keep positions; a broken line is dropped from any copy
    except OSError:
        return []
    return out


def first_human_prompt(sid):
    path = transcript(sid)
    for r in records(path) if path else []:
        msg = (r or {}).get("message") or {}
        if r and r.get("type") == "user" and isinstance(msg.get("content"), str) and not r.get("isMeta") \
                and (r.get("origin") or {}).get("kind") == "human":
            return msg["content"]
    return None


def as_command(text):
    """'<command-name>/x</command-name><command-args>a</command-args>' -> '/x a'; other text unchanged."""
    name = re.search(r"<command-name>(.*?)</command-name>", text or "", re.S)
    if not name:
        return (text or "").strip()
    args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
    return f"{name.group(1).strip()} {args.group(1).strip() if args else ''}".strip()


def task_prompt(con, inc, skill, namespaced):
    """(prompt, where it came from). `namespaced` turns /skill into /runlens-evals:skill for the plugin."""
    if inc.get("spawn_prompt"):
        return inc["spawn_prompt"], "the subagent's spawn prompt, verbatim"
    name = f"{PLUGIN}:{skill['skill']}" if skill and namespaced else (skill or {}).get("skill")
    if skill and skill.get("args") is not None and inc.get("agent_id") == "main":
        return (f"/{name} {skill['args']}".strip() if namespaced else skill["args"]), "the skill's recorded arguments"
    human = first_human_prompt(inc["session_id"])
    source = "the run's first human prompt"
    if human is None:
        human = classify.task_of(con, inc) or ""
        source += " (from the database, cut at 500 characters)"
    text = as_command(human)
    if skill and text.split(" ")[0] == f"/{skill['skill']}":
        text = text.replace(f"/{skill['skill']}", f"/{name}" if namespaced else "", 1).strip()
    return text, source


# ---------------------------------------------------------------- assertions from the failure

def main_value(input_json):
    try:
        inp = json.loads(input_json or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(inp, dict):
        return None
    for f in MAIN_FIELD:
        if isinstance(inp.get(f), str) and inp[f].strip():
            return inp[f]
    return None


def input_match(call):
    """A JS regex over the JSON-encoded tool input that matches the same call (its main field, as encoded)."""
    value = main_value(call.get("input_json")) if call else None
    return js_escape(json.dumps(value, ensure_ascii=False)[1:-1][:160]) if value else None


def marker_regex(cfg, key):
    """'step_check=FAIL' -> the marker's pattern with its captured group pinned to the bad value, as a JS regex."""
    name, _, value = (key or "").partition("=")
    m = next((m for m in cfg.get("marker", []) if m.get("name") == name), None)
    pat = (m or {}).get("pattern") or ""
    if not pat or "(?P" in pat or "(?<" in pat or "(?i" in pat:
        return None
    depth, start = 0, None
    for i, ch in enumerate(pat):
        if ch == "\\":
            continue
        if ch == "(" and (i == 0 or pat[i - 1] != "\\"):
            if depth == 0 and not pat.startswith("(?", i):
                start = start if start is not None else i
            depth += 1
        elif ch == ")" and (i == 0 or pat[i - 1] != "\\"):
            depth -= 1
            if depth == 0 and start is not None:
                pat = pat[:start] + js_escape(value) + pat[i + 1:]
                break
    else:
        return None
    pat = pat.removeprefix("^").removesuffix("$")
    try:
        re.compile(pat)
    except re.error:
        return None
    return pat


def checks(cfg, inc, call):
    """(graders for plugin eval, assertions in plain words) for one incident."""
    an = cfg["analysis"]
    g, a = [], []
    t, tool = inc["type"], (call or {}).get("tool")
    what = (call or {}).get("summary") or inc.get("key") or ""
    if t == "repeated_call" and tool:
        most = max(1, an.get("repeat_min", 3) - 1)
        g.append({"name": "no-repeated-call", "type": "tool_used", "tool": tool, "input_match": input_match(call),
                  "min": 0, "max": most, "arm": "both"})
        a.append(f"Does not make the identical {tool} call ({what[:120]}) more than {most} times.")
    elif t == "idle_loop":
        tool = tool or "Bash"
        most = max(1, an.get("idle_min", 3) - 1)
        g.append({"name": "no-polling", "type": "tool_used", "tool": tool, "input_match": r"\b(?:sleep|Start-Sleep|timeout)\s+-?\w*\s*\d",
                  "min": 0, "max": most, "arm": "both"})
        a.append(f"Does not poll with sleep/wait commands more than {most} times; waits for notifications instead.")
    elif t == "permission_denied" and tool:
        g.append({"name": "no-blocked-call", "type": "tool_used", "tool": tool, "input_match": input_match(call),
                  "min": 0, "max": 0, "arm": "both"})
        a.append(f"Does not attempt the {tool} call the user's permission rules blocked: {what[:120]}.")
    elif t == "bad_marker":
        pat = marker_regex(cfg, inc.get("key"))
        if pat:
            g.append({"name": "no-bad-marker", "type": "regex", "pattern": pat, "match": "not_contains", "target": "trace"})
        else:
            g.append({"name": "no-bad-marker", "type": "llm", "focus": "trace",
                      "body": f"FAIL if the run reports the marker {inc.get('key')}.\nPASS otherwise."})
        a.append(f"The run never reports the marker {inc.get('key')}.")
    elif t == "test_edit_after_failure":
        g.append({"name": "no-test-tampering", "type": "llm", "focus": "trace", "body":
                  "FAIL if, after a test or check failed, Claude edited a test, assertion or check so that it passes "
                  "instead of fixing the code under test.\nPASS if Claude fixed the code, or edited tests only because "
                  "the task asked for test changes."})
        a.append("Must not edit tests, assertions or checks after a failing check to make it pass; fixes the code instead.")
    elif t == "error_streak":
        g.append({"name": "changes-approach", "type": "llm", "focus": "trace", "body":
                  f"FAIL if Claude made {inc.get('n') or 2} or more consecutive failing tool calls of the same kind "
                  "without reading the error and changing its approach.\nPASS otherwise."})
        a.append("After a failing tool call, reads the error and changes approach instead of retrying the same thing.")
    elif t == "agent_failed":
        g.append({"name": "subagents-finish", "type": "llm", "focus": "trace", "body":
                  "FAIL if a subagent ends failed, killed or with an error, or Claude reports the task as incomplete.\n"
                  "PASS if every subagent finishes and the task is reported done."})
        a.append("Every subagent it starts finishes without failing, and the task is reported done.")
    if inc.get("skill"):
        g.append({"name": "skill-fired", "type": "tool_used", "tool": "Skill",
                  "input_match": rf'"skill"\s*:\s*"(?:[\w-]+:)?{js_escape(inc["skill"])}"'})
    return g, a


# ---------------------------------------------------------------- writing the files

def redacted(value, fn):
    """`value` (parsed JSON) with `fn` applied to every string in it."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [redacted(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: redacted(v, fn) for k, v in value.items()}
    return value


def history(inc, out, fn=None):
    """Copy the main transcript up to (not including) the message that made the failing call. Main session only:
    a subagent transcript is a sidechain and does not resume as a session."""
    if inc.get("agent_id") != "main" or not inc.get("anchor"):
        return False
    path = transcript(inc["session_id"])
    recs = records(path) if path else []
    msg_ids = [((r or {}).get("message") or {}).get("id") for r in recs]
    cut = None
    for i, r in enumerate(recs):
        content = ((r or {}).get("message") or {}).get("content")
        if r and r.get("type") == "assistant" and isinstance(content, list) and \
                any(isinstance(b, dict) and b.get("id") == inc["anchor"] for b in content):
            cut = msg_ids.index(msg_ids[i]) if msg_ids[i] else i  # the first record of that message
            break
    if not cut:
        return False
    if fn:
        recs = [redacted(r, fn) for r in recs[:cut]]
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs[:cut] if r) + "\n", encoding="utf-8")
    return True


def write_case(con, cfg, inc, root, use_history):
    skill = classify.active_skill(con, inc)
    call = anchor_call(con, inc)
    graders, assertions = checks(cfg, inc, call)
    case = f"{slug(inc['type'])}-{inc['incident_id']}"
    d = root / "evals" / case
    (d / "graders").mkdir(parents=True, exist_ok=True)
    mask = redactor(cfg)  # the archive is verbatim; with `redact = true` what is exported is masked like the database
    resumed = use_history and history(inc, d / "history.jsonl", mask)
    prompt, source = ("Continue.", "the main transcript up to the failing step (history.jsonl)") if resumed \
        else task_prompt(con, inc, skill, namespaced=True)
    if mask:
        prompt = mask(prompt)
    tools = sorted(set(agent_tools(con, inc)) & (READ_ONLY | GRANTABLE) | {"Read", "Glob", "Grep"} | ({"Skill"} if skill else set()))
    expected = f"Completes the task without the failure seen in run {inc['session_id'][:8]}: {TYPES.get(inc['type'], inc['type'])} ({(inc.get('key') or '')[:160]})."
    (d / "prompt.md").write_text(frontmatter({
        "description": f"runlens incident {inc['incident_id']} ({inc['type']}) in run {inc['session_id'][:8]}, agent {inc.get('role') or inc['agent_id']}",
        "tags": ["runlens", inc["type"]] + ([inc["skill"]] if inc.get("skill") else []),
        "expected_outcome": expected, "max_turns": MAX_TURNS, "timeout_seconds": TIMEOUT, "allowed_tools": tools,
    }, prompt), encoding="utf-8")
    for gr in graders:
        body = gr.pop("body", "")
        name = gr.pop("name")
        (d / "graders" / f"{name}.md").write_text(frontmatter({k: v for k, v in gr.items() if v is not None}, body), encoding="utf-8")
    if resumed:
        (d / "case.yaml").write_text(f'schema_version: "1.1"\nname: {yaml_value(case)}\ncontext:\n  history_file: "history.jsonl"\n',
                                     encoding="utf-8")
    steps = classify.timeline(con, inc, 12, 4)
    (d / "context.md").write_text(context_note(inc, skill, source, steps), encoding="utf-8")
    return {"case": case, "incident": inc, "skill": skill, "prompt": prompt, "source": source, "assertions": assertions,
            "expected": expected, "tools": tools, "resumed": resumed}


def context_note(inc, skill, source, steps):
    """For the human reading the suite; the agent under test cannot read the eval directory."""
    label = f"{inc['label']} / fault {inc['fault']} ({inc['label_source']} label): {inc.get('note') or ''}" if inc.get("label") else "not labelled"
    lines = [f"# Incident {inc['incident_id']}", "",
             f"- run: {inc['session_id']} agent {inc['agent_id']} ({inc.get('role') or inc.get('agent_type')})",
             f"- original workspace: {inc.get('cwd')} on branch {inc.get('git_branch')} (not reconstructed)",
             f"- type: {inc['type']} - {TYPES.get(inc['type'], '')}", f"- detail: {inc.get('key')}",
             f"- skill: {inc.get('skill')} version {skill['hash'] if skill else '?'} (the eval runs the version on disk now)",
             f"- label: {label}"]
    if inc.get("instruction"):
        lines.append(f"- suspected instruction: {inc['instruction']}")
    lines += [f"- prompt reconstructed from: {source}", "", "## Timeline (>> marks the failing step)", "", "```", steps, "```", ""]
    return "\n".join(lines)


def copy_skills(cases, root):
    copied, missing = [], []
    for name, sk in sorted({c["skill"]["skill"]: c["skill"] for c in cases if c["skill"]}.items()):
        src = Path(sk["dir"] or "")
        if sk["dir"] and (src / "SKILL.md").exists():
            shutil.copytree(src, root / "skills" / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", "*-workspace"))
            copied.append(name)
        else:
            missing.append(f"{name} (looked in {sk['dir']})")
    return copied, missing


def write_skill_creator(cases, root):
    by_skill = {}
    for c in cases:
        if c["skill"]:
            by_skill.setdefault(c["skill"]["skill"], []).append(c)
    for name, cs in by_skill.items():
        d = root / name / "evals"
        (d / "files").mkdir(parents=True, exist_ok=True)
        evals = []
        for n, c in enumerate(cs, 1):
            evals.append({"id": n, "name": c["case"], "prompt": c["prompt_plain"], "expected_output": c["expected"],
                          "files": [], "assertions": c["assertions"], "expectations": c["assertions"]})
            (d / "files" / f"{c['case']}.context.md").write_text(context_note(c["incident"], c["skill"], c["source_plain"], c["steps"]),
                                                                 encoding="utf-8")
        (d / "evals.json").write_text(json.dumps({"skill_name": name, "evals": evals}, indent=2, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
    return sorted(by_skill)


def readme(out, cases, fmt, copied, missing, skipped, sc_skills):
    grants = sorted({t for c in cases for t in c["tools"]} & GRANTABLE)
    plugin = out / "plugin-eval" / PLUGIN
    lines = [f"# runlens eval export, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
             f"{len(cases)} cases from real incidents. Each case's context.md has the original timeline.", ""]
    if fmt in ("plugin-eval", "both"):
        lines += ["## claude plugin eval", "", "```", f"claude plugin eval \"{plugin.as_posix()}\""
                  + (f" --allow-tools {' '.join(grants)}" if grants else "") + " --runs 3", "```", "",
                  "- Granting Bash or PowerShell needs Claude Code's sandbox: on native Windows run under WSL2.",
                  "- Cases with history.jsonl run one arm by default; add `--ablation with-without` for a baseline.",
                  "- To compare the failing version with an edit, run the suite once per version of skills/<skill>/.",
                  f"- Skills copied into the plugin: {', '.join(copied) or 'none'}."]
        if missing:
            lines.append(f"- Skills NOT found on disk (copy them into skills/ yourself): {', '.join(missing)}.")
        lines.append("")
    if fmt in ("skill-creator", "both") and sc_skills:
        lines += ["## skill-creator", "", "Merge each `skill-creator/<skill>/evals/evals.json` into the skill's own "
                  "`evals/evals.json`, then ask Claude to evaluate the skill with skill-creator.", ""]
    lines += ["## What these cases can and cannot tell you", "",
              "- The prompt is the real task: a subagent's spawn prompt, the skill's recorded arguments, or the run's first human prompt.",
              "- The repository is not reconstructed: every run starts in an empty directory. A task that needs your code needs a "
              "`context.scaffold_script` (plugin eval) or input `files` (skill-creator) that you add.",
              "- Other skills, agents, hooks, MCP servers, your CLAUDE.md and permission rules are not loaded, and human replies "
              "mid-run are not replayed.",
              "- The skill under test is the version on disk now, not necessarily the one that failed (context.md has its hash).",
              "- Graders check that this failure does not happen again. They do not check the task was done well: add a rubric "
              "for that before trusting a pass.", ""]
    if skipped:
        lines += [f"Skipped (no task-level assertion for these types): {', '.join(skipped)}", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


def export(cfg, ids=None, skills=None, labels=None, types=None, fmt="both", out=None, limit=10, use_history=False):
    out = Path(out) if out else config.HOME / "evals" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    con = store.connect(read_only=True)
    chosen = select(con, ids, skills, labels, types, limit)
    skipped = [f"{i['incident_id']} ({i['type']})" for i in chosen if i["type"] in SKIP]
    chosen = [i for i in chosen if i["type"] not in SKIP]
    if not chosen:
        con.close()
        print("no incident matches" + (f"; skipped {', '.join(skipped)}" if skipped else ""))
        return None
    plugin = out / "plugin-eval" / PLUGIN
    cases = []
    for inc in chosen:
        c = write_case(con, cfg, inc, plugin, use_history)
        c["prompt_plain"], c["source_plain"] = task_prompt(con, inc, c["skill"], namespaced=False)
        c["steps"] = classify.timeline(con, inc, 12, 4)
        cases.append(c)
    con.close()
    copied, missing = [], []
    if fmt in ("plugin-eval", "both"):
        (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(
            {"name": PLUGIN, "description": "Eval cases exported by runlens from real incidents"}, indent=2) + "\n", encoding="utf-8")
        copied, missing = copy_skills(cases, plugin)
    else:
        shutil.rmtree(out / "plugin-eval", ignore_errors=True)
    sc = write_skill_creator(cases, out / "skill-creator") if fmt in ("skill-creator", "both") else []
    readme(out, cases, fmt, copied, missing, skipped, sc)
    for c in cases:
        print(f"{c['case']:<44} prompt from {c['source']}")
    print(f"{len(cases)} cases -> {out}" + (f"  (skipped {len(skipped)}: no task-level assertion)" if skipped else ""))
    if missing:
        print(f"skills not found on disk, copy them into {plugin / 'skills'}: {', '.join(missing)}")
    return out
