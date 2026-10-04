"""Compare the database against the raw archived transcripts.

The transcript format is internal to Claude Code and changes between versions.
This catches a silent parse break: counts that no longer match, costs that no
longer add up, subagents that lost their parent.
"""
import json

from . import config, store
from .transcripts import iter_records, run_files


def raw_counts(main):
    msgs, tools, results, agents = set(), set(), set(), 0
    for f in run_files(main):
        agents += 1
        for r in iter_records(f):
            content = (r.get("message") or {}).get("content")
            if r.get("type") == "assistant":
                msgs.add((r.get("message") or {}).get("id") or r.get("uuid"))
                for b in content or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tools.add(b.get("id"))
            elif r.get("type") == "user" and isinstance(content, list):
                for x in content:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        results.add(x.get("tool_use_id"))
    return {"agents": agents, "api_calls": len(msgs), "tool_calls": len(tools), "tool_results": len(tools & results)}


def check(sessions=None):
    con = store.connect(read_only=True)
    failures = 0
    for mf in sorted(config.ARCHIVE.glob("*/*.runlens.json")):
        info = json.loads(mf.read_text(encoding="utf-8"))
        sid = info["session_id"]
        if sessions and sid not in sessions:
            continue
        in_db = con.execute("SELECT count(*) FROM runs WHERE session_id = ?", [sid]).fetchone()[0]
        if not in_db:
            continue
        raw = raw_counts(mf.with_name(f"{sid}.jsonl"))
        db = dict(zip(["agents", "api_calls", "tool_calls", "tool_results"], con.execute("""
            SELECT (SELECT count(*) FROM agents WHERE session_id = $1),
                   (SELECT count(*) FROM api_calls WHERE session_id = $1),
                   (SELECT count(*) FROM tool_calls WHERE session_id = $1),
                   (SELECT count(*) FROM tool_calls WHERE session_id = $1 AND ts_result IS NOT NULL)""", [sid]).fetchone()))
        cost, est, allocated, orphans, unpriced = con.execute("""
            SELECT r.cost_usd, r.cost_estimated, (SELECT sum(cost_usd) FROM api_calls WHERE session_id = $1),
                   (SELECT count(*) FROM agents WHERE session_id = $1 AND agent_id <> 'main' AND parent_agent_id IS NULL),
                   (SELECT count(*) FROM api_calls WHERE session_id = $1 AND cost_usd IS NULL AND NOT api_error
                        AND model IS NOT NULL AND model <> '<synthetic>')
            FROM runs r WHERE session_id = $1""", [sid]).fetchone()
        problems = [f"{k}: raw {raw[k]} vs db {db[k]}" for k in raw if raw[k] != db[k]]
        if cost and allocated is not None and not est and abs(cost - allocated) > max(0.01 * cost, 0.05):
            problems.append(f"cost: cost-state {cost:.2f} vs allocated {allocated:.2f}")
        if orphans:
            problems.append(f"{orphans} subagent(s) without a parent")
        if unpriced:
            problems.append(f"{unpriced} api call(s) without a cost")
        failures += bool(problems)
        print(f"{'FAIL' if problems else 'ok  '}  {sid[:8]}  " + ("; ".join(problems) if problems else
              f"agents={db['agents']} api={db['api_calls']} tools={db['tool_calls']} cost={cost or 0:.2f}{' (est)' if est else ''}"))
    con.close()
    return failures
