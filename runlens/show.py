"""Print the timeline around an incident or a tool call: what the agent said and did, in order."""
import sys

from . import config, store
from .fs import fs_path, plain


def locate(con, ident):
    row = con.execute("SELECT session_id, agent_id, seq, type, key, context FROM incidents WHERE incident_id = ?", [ident]).fetchone()
    if row:
        return row[0], row[1], row[2], f"incident {row[3]}: {row[4]}"
    row = con.execute("SELECT session_id, agent_id, seq, tool FROM tool_calls WHERE tool_use_id = ?", [ident]).fetchone()
    if row:
        return row[0], row[1], row[2], f"tool call {row[3]}"
    return None


def show(ident, steps=12, after=4):
    con = store.connect(read_only=True)
    try:
        return _show(con, ident, steps, after)
    finally:
        con.close()


def _show(con, ident, steps, after):
    found = locate(con, ident)
    if not found:
        print(f"no incident or tool call with id {ident}; `runlens incidents` lists incident ids", file=sys.stderr)
        return 1
    sid, agent_id, seq, what = found
    agent = con.execute("""SELECT agent_type, role, model, skills, parent_agent_id, description, prompt FROM agents
                           WHERE session_id = ? AND agent_id = ?""", [sid, agent_id]).fetchone() or (None,) * 7
    print(f"{what}\nrun {sid}  agent {agent_id}  type={agent[0]}  role={agent[1]}  model={agent[2]}  skills={agent[3]}")
    if agent[4]:
        print(f"spawned by {agent[4]}: {agent[5]}")
        if agent[6]:
            print(f"asked to: {' '.join(agent[6].split())[:700]}")
    files = list(fs_path(config.ARCHIVE).glob(f"*/{sid}.jsonl"))
    if files:
        sub = files[0].with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
        print(f"transcript {plain(sub if agent_id != 'main' else files[0])}")
    if seq is None:
        return 0
    lo, hi = seq - steps, seq + after
    items = con.execute("""
        SELECT seq, 'tool' AS kind, tool, input_summary, is_error, error_class, result_head, duration_ms, skill
        FROM tool_calls WHERE session_id = $1 AND agent_id = $2 AND seq BETWEEN $3 AND $4
        UNION ALL
        SELECT seq, 'text', NULL, text, NULL, NULL, NULL, NULL, skill
        FROM texts WHERE session_id = $1 AND agent_id = $2 AND seq BETWEEN $3 AND $4
        ORDER BY seq""", [sid, agent_id, lo, hi]).fetchall()
    print()
    for s, kind, tool, body, err, cls, head, ms, _skill in items:
        mark = ">>" if s == seq else "  "
        if kind == "text":
            print(f"{mark}{s:>5} [say] {' '.join((body or '').split())[:1500]}")
            continue
        status = f"ERROR {cls}" if err else "ok"
        print(f"{mark}{s:>5} [{tool}] {' '.join((body or '').split())[:600]}")
        flat = " | ".join(line.strip() for line in (head or "").splitlines() if line.strip())
        print(f"         -> {status} ({ms if ms is not None else '?'} ms): {flat[:600]}")
    return 0
