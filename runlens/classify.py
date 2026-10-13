"""Label incidents with a failure taxonomy, and measure the labels against human ones.

The judge is `claude -p` with a JSON schema, so it runs on the user's own Claude
Code login and needs no API key. LLM labels are a first pass for axial coding,
not ground truth: unvalidated judges find few trace errors (TRAIL, arXiv
2505.08638). Export a sample, correct it by hand, import, and read
`runlens agreement` before trusting a category's counts.

What the judge sees, and why:
- the text of the skill version that was active at the incident (from
  skill_loads + skill_texts), so `fault = skill_instructions` can be decided
  and backed by a quoted instruction instead of guessed;
- the timeline before the incident AND a few steps after it, so it can tell a
  failure the agent recovered from from one it did not;
- the detector's verdict only after the timeline, flagged as a heuristic, so the
  incident type does not anchor the category;
- an explicit `unknown` outcome: judges forced to choose invent a cause
  (Anthropic, "Demystifying evals for AI agents": give the judge a way out).

Which incidents get labelled matters as much: `--sample stratified` (default)
draws at random within each incident type, the same number per type, so
per-category agreement is not biased by a priority order; `--sample priority`
keeps the old highest-signal-first order for a quick triage.
"""
import csv
import json
import os
import random
import re
import shutil
import subprocess
import tomllib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, store
from .incidents import TYPES

PRIORITY = ["bad_marker", "agent_failed", "error_streak", "test_edit_after_failure", "repeated_call", "idle_loop",
            "permission_denied", "interrupt", "api_error", "compaction"]
UNKNOWN = "unknown"  # the judge's way out: not enough evidence to name a category or a fault
FAULTS = ["skill_instructions", "agent_judgment", "tooling_or_environment", "external", "none", UNKNOWN]
ALIASES = {"role_disobeyed": "spec_disobeyed"}  # retired taxonomy ids, read as their replacement
MIN_PAIRS = 30       # paired labels before agreement numbers are more than a hint (kappa's 95% CI is about +-0.3 at 30)
MIN_POSITIVES = 5    # human labels of a category before its TPR can be called verified
VERIFIED = 0.8       # TPR and TNR a category needs before its counts are trusted
# Prompt budget. A skill text longer than this keeps its head and tail: the steps and the rules
# that close a skill are where its failure-relevant instructions usually are.
DEFAULTS = {"model": "sonnet", "before": 12, "after": 4, "skill_chars": 14000, "timeline_chars": 9000}
NEW_LABEL_COLUMNS = {"instruction": "VARCHAR", "skill_hash": "VARCHAR"}
STEP = re.compile(r"^\s*\d+ [\[>]")


def taxonomy():
    p = config.HOME / "taxonomy.toml"
    p = p if p.exists() else config.PACKAGE / "taxonomy.toml"
    return tomllib.loads(p.read_text(encoding="utf-8"))["category"]


def settings(cfg):
    return {**DEFAULTS, **(cfg or {}).get("classify", {})}


def schema(cats):
    return {
        "type": "object", "additionalProperties": False,
        "required": ["category", "new_category", "fault", "instruction", "note", "evidence", "confidence"],
        "properties": {
            "category": {"type": "string", "enum": [c["id"] for c in cats] + ["other", UNKNOWN]},
            "new_category": {"type": "string", "description": "a short snake_case name when category is other, else empty"},
            "fault": {"type": "string", "enum": FAULTS},
            "instruction": {"type": "string",
                            "description": "when fault is skill_instructions: the instruction copied verbatim from the skill text, "
                                           "or 'missing: <what the skill should say>'; else empty"},
            "note": {"type": "string", "description": "one or two sentences: what happened and why"},
            "evidence": {"type": "string", "description": "a short verbatim quote from the timeline"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        },
    }


# ---------------------------------------------------------------- context for the judge

def clip(text, limit):
    """Keep a long text's head and tail, cut on line boundaries, and say how much was dropped."""
    if not text or len(text) <= limit:
        return text or ""
    head, tail = text[: limit * 2 // 3], text[-(limit // 3):]
    head = head[: head.rfind("\n")] if "\n" in head else head
    tail = tail[tail.find("\n") + 1:] if "\n" in tail else tail
    return f"{head}\n[... {len(text) - len(head) - len(tail)} characters omitted ...]\n{tail}"


def timeline(con, inc, before, after):
    """The agent's steps around the incident, the incident step marked >>. Falls back to the stored context."""
    if inc.get("seq") is None or not inc.get("agent_id"):
        return steps_only(inc.get("context") or "")
    rows = con.execute("""
        SELECT seq, 'tool', tool, input_summary, is_error, error_class, result_head FROM tool_calls
        WHERE session_id = $1 AND agent_id = $2 AND seq BETWEEN $3 AND $4
        UNION ALL
        SELECT seq, 'text', NULL, text, NULL, NULL, NULL FROM texts
        WHERE session_id = $1 AND agent_id = $2 AND seq BETWEEN $3 AND $4
        ORDER BY 1""", [inc["session_id"], inc["agent_id"], inc["seq"] - before, inc["seq"] + after]).fetchall()
    if not rows:
        return steps_only(inc.get("context") or "")
    out = []
    for seq, kind, tool, body, err, cls, head in rows:
        mark = ">>" if seq == inc["seq"] else "  "
        flat = " ".join((body or "").split())
        if kind == "text":
            out.append(f"{mark}{seq:>4} [say] {flat[:600]}")
            continue
        result = " | ".join(x.strip() for x in (head or "").splitlines() if x.strip())[:400]
        status = f"ERROR {cls}" if err and cls else "ERROR" if err else "ok"
        out.append(f"{mark}{seq:>4} [{tool}] {flat[:400]} -> {status}: {result}")
    return "\n".join(out)


def steps_only(context):
    return "\n".join(line for line in context.splitlines() if STEP.match(line))


def detector_notes(context):
    """The lines incidents.py puts before the timeline (denial kind, the failing call before a test edit...)."""
    notes = []
    for line in (context or "").splitlines():
        if STEP.match(line):
            break
        notes.append(line.strip())
    return " ".join(n for n in notes if n)


def has_table(con, name):
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0])


def active_skill(con, inc):
    """The version of the incident's skill that was loaded when it happened: same agent before the step,
    else the latest load in the run before it (a subagent inherits its parent's skill), else any load."""
    if not inc.get("skill"):
        return None
    texts = "skill_texts" if has_table(con, "skill_texts") else "(SELECT NULL::VARCHAR AS skill, NULL::VARCHAR AS content_hash, NULL::VARCHAR AS text)"
    row = con.execute(f"""
        SELECT l.content_hash, l.args, l.skill_dir, t.text FROM skill_loads l
        LEFT JOIN {texts} t ON t.skill = l.skill AND t.content_hash = l.content_hash
        WHERE l.session_id = $1 AND l.skill = $2
        ORDER BY coalesce(l.agent_id = $3 AND l.seq <= $4, false) DESC, coalesce(l.ts <= $5, false) DESC, l.ts DESC
        LIMIT 1""", [inc["session_id"], inc["skill"], inc.get("agent_id"), inc.get("seq"), inc.get("ts")]).fetchone()
    if not row:
        return None
    return {"skill": inc["skill"], "hash": row[0], "args": row[1], "dir": row[2], "text": row[3]}


def task_of(con, inc):
    """What the agent was asked: its spawn prompt, or the run's first human prompt for the main session."""
    if inc.get("spawn_prompt"):
        return inc["spawn_prompt"]
    row = con.execute("""SELECT detail FROM events WHERE session_id = ? AND kind = 'human_prompt' ORDER BY ts LIMIT 1""",
                      [inc["session_id"]]).fetchone()
    return row[0] if row and row[0] else None


def prompt(inc, task, cats, skill=None, steps=None, limits=None):
    """The judge's prompt. `steps` is the timeline (defaults to the incident's stored context)."""
    lim = {**DEFAULTS, **(limits or {})}
    cat_lines = "\n".join(f"- {c['id']}: {c['definition']}" for c in cats)
    if skill and skill.get("text"):
        args = f", invoked with arguments: {skill['args'][:300]}" if skill.get("args") else ""
        skill_block = (f'<skill name="{skill["skill"]}" version="{skill["hash"]}">\n'
                       f"The instructions of skill {skill['skill']} as this run loaded them{args}:\n\n"
                       f"{clip(skill['text'], lim['skill_chars'])}\n</skill>")
    elif inc.get("skill"):
        skill_block = (f'<skill name="{inc["skill"]}">\nThe text of this skill was not recorded, so you cannot quote it. '
                       "Use fault skill_instructions only if the timeline itself shows the instruction.\n</skill>")
    else:
        skill_block = "<skill>\nNo skill was active at this step. Do not use fault skill_instructions.\n</skill>"
    notes = detector_notes(inc.get("context"))
    return f"""You are reviewing one moment of an autonomous Claude Code run, for failure analysis.
Read the task, the skill instructions and the timeline, then classify what happened at the step marked >>.

<agent>type={inc.get('agent_type')} role={inc.get('role')} skill={inc.get('skill')}</agent>

<task>
What this agent was asked to do (truncated):
{(task or '(no prompt recorded)')[:1500]}
</task>

{skill_block}

<timeline>
This agent's steps, oldest first: the steps before the marked step (>>), the marked step, and up to {lim['after']} steps after it,
so you can see whether it recovered. [say] is the agent's own text; [Tool] is a call and its result.
{clip(steps if steps is not None else steps_only(inc.get('context') or ''), lim['timeline_chars'])}
</timeline>

<detector>
A heuristic detector flagged the marked step as {inc['type']} ({TYPES.get(inc['type'], '')}).
Detail: {inc.get('key')} (occurrences: {inc.get('n')}){f'. {notes}' if notes else ''}
Detectors are often wrong. Judge from the timeline, not from this line.
</detector>

<categories>
{cat_lines}
- other: a failure none of these fits; give a short snake_case name in new_category.
- {UNKNOWN}: the task, skill and timeline are not enough to tell what went wrong or why.
</categories>

<rules>
- Choose expected_behavior when nothing went wrong, e.g. a check correctly catching a real defect.
- Choose {UNKNOWN} rather than guess when the evidence is not there. Use fault {UNKNOWN} for the same reason.
- fault says where a fix would go:
  skill_instructions: an instruction in <skill> caused it, or the skill lacks an instruction that would have prevented it.
    Only with a quote in instruction: copy the instruction verbatim from <skill>, or write "missing: <what the skill should say>".
  agent_judgment: the instructions were fine and the agent chose badly.
  tooling_or_environment, external: the cause is outside the agent and its instructions.
  none: nothing went wrong.
- instruction is empty unless fault is skill_instructions.
- evidence is a short quote copied from the timeline. Do not invent details that are not shown.
- Answer only through the JSON schema."""


# ---------------------------------------------------------------- the judge

def judge(text, sch, model):
    """One tool-less, settings-less `claude -p` call that must answer through the JSON schema.

    Flags (code.claude.com/docs/en/cli-reference, /headless): --tools "" removes built-in tools but not MCP
    tools, so --strict-mcp-config (no --mcp-config: no servers) and --disallowedTools mcp__* remove those;
    --setting-sources "" skips user/project settings (hooks, plugins, permissions); --disable-slash-commands
    turns skills off. --bare would also skip CLAUDE.md but refuses subscription logins, so it is not used.
    The prompt goes through stdin (never the command line), and RUNLENS_JUDGE=1 lets runlens' own hook
    ignore the judge's sessions."""
    env = {**os.environ, "RUNLENS_JUDGE": "1"}
    out = subprocess.run(
        [shutil.which("claude") or "claude", "-p", "--model", model, "--output-format", "json",
         "--no-session-persistence", "--tools", "", "--strict-mcp-config", "--disallowedTools", "mcp__*",
         "--setting-sources", "", "--disable-slash-commands", "--json-schema", json.dumps(sch)],
        input=text, capture_output=True, text=True, encoding="utf-8", env=env, timeout=600, cwd=str(config.HOME))
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise RuntimeError((out.stderr or out.stdout or f"claude exited {out.returncode}").strip()[:300]) from None
    if data.get("is_error") or not data.get("structured_output"):
        raise RuntimeError(data.get("result") or out.stderr[:300])
    return data["structured_output"], data.get("total_cost_usd") or 0


def checked_instruction(label, skill):
    """Keep the judge honest: a quote that is not in the skill text is marked, not silently trusted."""
    quote = (label.get("instruction") or "").strip()
    if label.get("fault") != "skill_instructions" or not quote or quote.lower().startswith("missing:"):
        return quote
    norm = lambda s: " ".join(s.split()).strip(" \"'`").lower()
    if skill and skill.get("text") and norm(quote) in norm(skill["text"]):
        return quote
    return f"[quote not found in the skill text] {quote}"


def ensure_label_columns(con):
    for col, typ in NEW_LABEL_COLUMNS.items():
        con.execute(f"ALTER TABLE labels ADD COLUMN IF NOT EXISTS {col} {typ}")


def label_columns(con):
    return {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'labels'").fetchall()}


def latest_labels(con):
    """SQL for the latest label per incident and source, with the newer columns as NULL on an old database."""
    have = label_columns(con)
    extra = ", ".join(f"{c}" if c in have else f"NULL::VARCHAR AS {c}" for c in NEW_LABEL_COLUMNS)
    return f"""(SELECT incident_id, source, category, fault, confidence, note, evidence, {extra} FROM labels
               QUALIFY row_number() OVER (PARTITION BY incident_id, source ORDER BY labeled_at DESC) = 1)"""


# ---------------------------------------------------------------- choosing what to label

def sample(cands, limit, mode="stratified", seed=None):
    """Pick `limit` incidents from (incident_id, type, ts) rows.

    stratified: random within each type, types taken in turns (equal allocation), so every type gets the
    same chance to be checked and per-category agreement is not skewed by a fixed order. priority: the
    fixed PRIORITY order, oldest first within a type."""
    if mode == "priority":
        rank = {t: n for n, t in enumerate(PRIORITY)}
        return sorted(cands, key=lambda c: (rank.get(c[1], 99), c[2] is None, str(c[2])))[:limit]
    rng = random.Random(seed)
    by = defaultdict(list)
    for c in sorted(cands, key=lambda c: c[0]):
        by[c[1]].append(c)
    for group in by.values():
        rng.shuffle(group)
    order = sorted(by)
    rng.shuffle(order)
    out = []
    while len(out) < limit and any(by.values()):
        for t in order:
            if by[t] and len(out) < limit:
                out.append(by[t].pop())
    return out


def candidates(con, types=None, skills=None, unlabeled_by=None):
    where, args = ["1=1"], []
    if types:
        where.append("list_contains(?, type)")
        args.append(list(types))
    if skills:
        where.append("list_contains(?, skill)")
        args.append(list(skills))
    if unlabeled_by:
        where.append("incident_id NOT IN (SELECT incident_id FROM labels WHERE source = ?)")
        args.append(unlabeled_by)
    return con.execute(f"SELECT incident_id, type, ts FROM incidents WHERE {' AND '.join(where)}", args).fetchall()


def load_incidents(con, ids):
    if not ids:
        return []
    rows = con.execute("""
        SELECT i.incident_id, i.session_id, i.agent_id, i.type, i.key, i.n, i.agent_type, i.role, i.skill, i.seq, i.ts,
               i.context, a.prompt
        FROM incidents i LEFT JOIN agents a ON a.session_id = i.session_id AND a.agent_id = i.agent_id
        WHERE list_contains(?, i.incident_id)""", [list(ids)]).fetchall()
    keys = ["incident_id", "session_id", "agent_id", "type", "key", "n", "agent_type", "role", "skill", "seq", "ts",
            "context", "spawn_prompt"]
    found = {r[0]: dict(zip(keys, r)) for r in rows}
    return [found[i] for i in ids if i in found]


def build_prompt(con, inc, cats, lim):
    skill = active_skill(con, inc)
    return prompt(inc, task_of(con, inc), cats, skill, timeline(con, inc, lim["before"], lim["after"]), lim), skill


def classify(cfg, types=None, skills=None, limit=20, model=None, workers=4, relabel=False, mode="stratified",
             seed=None, dry_run=False):
    lim = settings(cfg)
    model = model or lim["model"]
    cats = taxonomy()
    sch = schema(cats)
    con = store.connect(read_only=dry_run)
    if not dry_run:
        ensure_label_columns(con)
    if mode == "stratified" and seed is None:
        seed = random.randrange(10 ** 6)
    picked = sample(candidates(con, types, skills, None if relabel else "llm"), int(limit), mode, seed)
    incidents = load_incidents(con, [c[0] for c in picked])
    if not incidents:
        print("nothing to label")
        con.close()
        return []
    print(f"{len(incidents)} incidents, {mode} sample" + (f" (seed {seed}: --seed {seed} picks the same ones)" if mode == "stratified" else ""))
    prompts = {inc["incident_id"]: build_prompt(con, inc, cats, lim) for inc in incidents}
    if dry_run:
        for inc in incidents:
            print(f"{inc['incident_id']}  {inc['type']:<24} skill={inc['skill']}")
        first = incidents[0]["incident_id"]
        print(f"\n--- judge prompt for {first} ---\n{prompts[first][0]}")
        con.close()
        return incidents
    spent, done = 0.0, 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(judge, prompts[inc["incident_id"]][0], sch, model): inc for inc in incidents}
        for fut in as_completed(futures):
            inc = futures[fut]
            try:
                label, cost = fut.result()
            except Exception as e:  # one failed judgement must not lose the others
                print(f"FAIL  {inc['incident_id']}  {e}")
                continue
            spent += cost
            done += 1
            skill = prompts[inc["incident_id"]][1]
            category = label["category"] if label["category"] != "other" else f"other:{label['new_category'] or '?'}"
            instruction = checked_instruction(label, skill)
            con.execute("""INSERT INTO labels (incident_id, source, category, fault, confidence, note, evidence, model,
                                               instruction, skill_hash)
                           VALUES (?, 'llm', ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [inc["incident_id"], category, label["fault"], label["confidence"], label["note"], label["evidence"],
                         model, instruction or None, skill["hash"] if skill else None])
            print(f"{inc['incident_id']}  {inc['type']:<16} {category:<26} {label['fault']:<22} {label['note'][:90]}")
    con.close()
    print(f"labeled {done}/{len(incidents)} incidents with {model}, ${spent:.2f}")
    return incidents


# ---------------------------------------------------------------- human labels

def export_labels(path, limit=None, seed=None, blind=False):
    """All incidents, or with `limit` a stratified random sample of the LLM-labelled ones still lacking a human
    label: the sample agreement should be measured on. `blind` leaves the LLM's answer out of the file."""
    con = store.connect(read_only=True)
    ids = None
    if limit:
        pool = con.execute("""SELECT incident_id, type, ts FROM incidents
                              WHERE incident_id IN (SELECT incident_id FROM labels WHERE source = 'llm')
                                AND incident_id NOT IN (SELECT incident_id FROM labels WHERE source = 'human')""").fetchall()
        if not pool:
            pool = candidates(con, unlabeled_by="human")
        if seed is None:
            seed = random.randrange(10 ** 6)
        ids = [c[0] for c in sample(pool, int(limit), "stratified", seed)] or ["-"]
    lab = latest_labels(con)
    rows = con.execute(f"""
        SELECT i.incident_id, i.session_id[:8], i.type, i.skill, i.role, i.key,
               l.category, l.fault, l.instruction, l.confidence, l.note, l.evidence,
               h.category, h.fault, h.note, left(i.context, 3000)
        FROM incidents i
        LEFT JOIN {lab} l ON l.incident_id = i.incident_id AND l.source = 'llm'
        LEFT JOIN {lab} h ON h.incident_id = i.incident_id AND h.source = 'human'
        WHERE {'list_contains(?, i.incident_id)' if ids is not None else '1=1'}
        ORDER BY i.ts""", [ids] if ids is not None else []).fetchall()
    con.close()
    header = ["incident_id", "run", "type", "skill", "role", "key", "llm_category", "llm_fault", "llm_instruction",
              "llm_confidence", "llm_note", "llm_evidence", "human_category", "human_fault", "human_note", "context"]
    keep = [i for i, h in enumerate(header) if not (blind and h.startswith("llm_"))]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow([header[i] for i in keep])
        w.writerows([[r[i] for i in keep] for r in rows])
    what = f"a stratified sample of {len(rows)} incidents (seed {seed})" if limit else f"{len(rows)} incidents"
    print(f"{what} -> {path}\nFill human_category (a taxonomy id, 'other:<name>' or '{UNKNOWN}') and, if you can, "
          f"human_fault ({', '.join(FAULTS)}). Then: runlens labels import {path}")
    return rows


def import_labels(path):
    known = {c["id"] for c in taxonomy()} | {UNKNOWN, "other"}
    con = store.connect()
    n, odd = 0, set()
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            category = (row.get("human_category") or "").strip()
            if not category:
                continue
            fault = (row.get("human_fault") or "").strip() or None
            if fault and fault not in FAULTS:
                odd.add(f"fault {fault}")
                fault = None
            if category.split(":")[0] not in known:
                odd.add(category)
            con.execute("INSERT INTO labels (incident_id, source, category, fault, note) VALUES (?, 'human', ?, ?, ?)",
                        [row["incident_id"], category, fault, (row.get("human_note") or "").strip()])
            n += 1
    con.close()
    print(f"imported {n} human labels")
    if odd:
        print(f"not in the taxonomy (kept as written, check the spelling): {', '.join(sorted(odd))}")
    return n


# ---------------------------------------------------------------- agreement

def norm_category(c):
    c = (c or "").strip().lower()
    c = "other" if c.startswith("other:") else c  # a free-text name cannot be compared, only "it fits nothing"
    return ALIASES.get(c, c)


def kappa(pairs):
    """Cohen's kappa for (a, b) pairs; None when chance agreement is total (one category only)."""
    n = len(pairs)
    if not n:
        return None
    agree = sum(a == b for a, b in pairs) / n
    cats = {c for p in pairs for c in p}
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return None if pe >= 1 else (agree - pe) / (1 - pe)


def kappa_ci(pairs, resamples=2000, seed=0):
    """Percentile bootstrap 95% interval for kappa: with tens of labels it is wide, and that is the point."""
    if len(pairs) < 2:
        return None
    rng = random.Random(seed)
    ks = sorted(k for k in (kappa([rng.choice(pairs) for _ in pairs]) for _ in range(resamples)) if k is not None)
    if len(ks) < resamples // 2:
        return None
    return ks[int(0.025 * len(ks))], ks[min(len(ks) - 1, int(0.975 * len(ks)))]


def per_category(pairs):
    """One-vs-rest rates per category, the human label taken as truth."""
    n = len(pairs)
    out = []
    for c in sorted({x for p in pairs for x in p}):
        tp = sum(a == c and h == c for a, h in pairs)
        fp = sum(a == c and h != c for a, h in pairs)
        fn = sum(a != c and h == c for a, h in pairs)
        tn = n - tp - fp - fn
        tpr = tp / (tp + fn) if tp + fn else None
        tnr = tn / (tn + fp) if tn + fp else None
        out.append({"category": c, "human": tp + fn, "llm": tp + fp, "tp": tp, "fn": fn, "fp": fp, "tn": tn,
                    "tpr": tpr, "tnr": tnr, "precision": tp / (tp + fp) if tp + fp else None,
                    "verified": tp + fn >= MIN_POSITIVES and (tpr or 0) >= VERIFIED and (tnr or 0) >= VERIFIED})
    return out


def agreement_report(rows):
    """rows: (llm_category, human_category, llm_fault, human_fault). Returns the numbers `agreement` prints."""
    pairs = [(norm_category(a), norm_category(h)) for a, h, _, _ in rows]
    faults = [(a, h) for _, _, a, h in rows if a and h]
    n = len(pairs)
    return {
        "pairs": n, "min_pairs": MIN_PAIRS, "enough": n >= MIN_PAIRS,
        "agreement": sum(a == h for a, h in pairs) / n if n else None,
        "kappa": kappa(pairs), "kappa_ci95": kappa_ci(pairs),
        "llm_unknown": sum(a == UNKNOWN for a, _ in pairs),
        "fault": {"pairs": len(faults), "agreement": sum(a == h for a, h in faults) / len(faults) if faults else None,
                  "kappa": kappa(faults)},
        "categories": per_category(pairs),
    }


def agreement(as_json=False):
    con = store.connect(read_only=True)
    lab = latest_labels(con)
    rows = con.execute(f"""SELECT l.category, h.category, l.fault, h.fault FROM {lab} l JOIN {lab} h USING (incident_id)
                           WHERE l.source = 'llm' AND h.source = 'human'""").fetchall()
    con.close()
    rep = agreement_report(rows)
    if as_json:
        print(json.dumps(rep, indent=2))
        return rep
    if not rep["pairs"]:
        print("Not enough human labels: no incident has both an LLM and a human label yet.\n"
              "Label a sample: runlens labels export sample.csv --limit 50, fill human_category, "
              "then runlens labels import sample.csv")
        return rep
    pct = lambda x: "-" if x is None else f"{x:.0%}"
    num = lambda x: "-" if x is None else f"{x:.2f}"
    ci = rep["kappa_ci95"]
    print(f"{rep['pairs']} incidents labelled by both the LLM and a human")
    if not rep["enough"]:
        print(f"Not enough human labels: {rep['pairs']} of {MIN_PAIRS}. Treat these numbers as a rough hint and label more "
              f"(runlens labels export sample.csv --limit {MIN_PAIRS * 2 - rep['pairs']}).")
    print(f"category: agreement {pct(rep['agreement'])}, Cohen's kappa {num(rep['kappa'])}"
          + (f" (95% CI {ci[0]:.2f} to {ci[1]:.2f})" if ci else "")
          + (f"; the LLM answered '{UNKNOWN}' {rep['llm_unknown']} times" if rep["llm_unknown"] else ""))
    f = rep["fault"]
    print(f"fault:    agreement {pct(f['agreement'])}, Cohen's kappa {num(f['kappa'])} on {f['pairs']} pairs"
          if f["pairs"] else "fault:    no human fault labels yet (fill human_fault in the CSV to measure it)")
    rate = lambda x, y: f"{x / (x + y):.0%} ({x}/{x + y})" if x + y else "-"
    print(f"\n{'category':<28}{'human':>6}{'llm':>6}{'TP':>5}{'FN':>5}{'FP':>5}{'TN':>5}  {'TPR':<13}{'TNR':<13}verified")
    for c in rep["categories"]:
        why = "yes" if c["verified"] else ("no" if c["human"] >= MIN_POSITIVES else f"no (<{MIN_POSITIVES} human)")
        print(f"{c['category']:<28}{c['human']:>6}{c['llm']:>6}{c['tp']:>5}{c['fn']:>5}{c['fp']:>5}{c['tn']:>5}  "
              f"{rate(c['tp'], c['fn']):<13}{rate(c['tn'], c['fp']):<13}{why}")
    print(f"\nverified = at least {MIN_POSITIVES} human labels of the category and TPR and TNR of at least {VERIFIED:.0%}. "
          "Counts of an unverified category are hypotheses, not findings.")
    return rep
