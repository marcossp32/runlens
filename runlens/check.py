"""Check that the database tells the whole, current story.

The transcript format is internal to Claude Code and changes between versions.
This catches a silent parse break (counts that no longer match the raw files,
costs that no longer add up, subagents that lost their parent) and silent gaps:
runs whose source kept growing after they were archived, sessions [select]
wants that were never archived, archived runs that failed to ingest, runs still
open, models with no price, and sessions still waiting in the hook's queue.
"""
from . import config, store
from .fs import fs_path, read_json
from .transcripts import PARSER_VERSION, iter_records, price_of, run_files


def raw_counts(main):
    msgs, tools, results, agents = set(), set(), set(), 0
    for f in run_files(main):
        agents += 1
        for r in iter_records(f):
            msg = r.get("message") if isinstance(r.get("message"), dict) else {}
            content = msg.get("content")
            if r.get("type") == "assistant":
                msgs.add(msg.get("id") or r.get("uuid"))
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tools.add(b.get("id"))
            elif r.get("type") == "user" and isinstance(content, list):
                for x in content:
                    if isinstance(x, dict) and x.get("type") == "tool_result":
                        results.add(x.get("tool_use_id"))
    return {"agents": agents, "api_calls": len(msgs), "tool_calls": len(tools), "tool_results": len(tools & results)}


def check(sessions=None, cfg=None, sources=True):
    """Print one line per run and per gap. Returns the number of problems (FAIL and WARN lines)."""
    con = store.connect(read_only=True)
    failures = 0
    try:
        in_db = {r[0]: r[1:] for r in con.execute("SELECT session_id, status, is_stub, parser_version FROM runs").fetchall()}
        failed = {r[0] for r in con.execute("SELECT session_id FROM ingest_errors").fetchall()}
        for mf in sorted(fs_path(config.ARCHIVE).glob("*/*.runlens.json")):
            sid = mf.name.removesuffix(".runlens.json")
            if sessions and sid not in sessions and sid[:8] not in sessions:
                continue
            if sid not in in_db:
                if sid in failed:
                    continue  # reported with its error below
                failures += 1
                print(f"WARN  {sid[:8]}  archived but not in the database: run `runlens ingest`")
                continue
            problems, notes = run_problems(con, sid, mf.with_name(f"{sid}.jsonl"))
            status, stub, version = in_db[sid]
            if version != PARSER_VERSION:
                problems.append(f"ingested by parser v{version}, current is v{PARSER_VERSION}: run `runlens ingest`")
            if status == "open":
                notes.append("open: the session may still be running, its numbers are partial")
            if stub:
                notes.append("stub")
            failures += bool(problems)
            print(f"{'FAIL' if problems else 'ok  '}  {sid[:8]}  " + "; ".join(problems + notes))
        failures += gaps(con, cfg or config.load(), sessions, sources)
    finally:
        con.close()
    print(f"{failures} problem(s)" if failures else "all checks passed")
    return failures


def run_problems(con, sid, main):
    raw = raw_counts(main)
    db = dict(zip(["agents", "api_calls", "tool_calls", "tool_results"], con.execute("""
        SELECT (SELECT count(*) FROM agents WHERE session_id = $1),
               (SELECT count(*) FROM api_calls WHERE session_id = $1),
               (SELECT count(*) FROM tool_calls WHERE session_id = $1),
               (SELECT count(*) FROM tool_calls WHERE session_id = $1 AND ts_result IS NOT NULL)""", [sid]).fetchone()))
    cost, est, uncovered, allocated, orphans, unpriced, models = con.execute("""
        SELECT r.cost_usd, r.cost_estimated, r.cost_uncovered_usd, (SELECT sum(cost_usd) FROM api_calls WHERE session_id = $1),
               (SELECT count(*) FROM agents WHERE session_id = $1 AND agent_id <> 'main' AND parent_agent_id IS NULL),
               (SELECT count(*) FROM api_calls WHERE session_id = $1 AND cost_usd IS NULL),
               r.unpriced_models
        FROM runs r WHERE session_id = $1""", [sid]).fetchone()
    problems = [f"{k}: raw {raw[k]} vs db {db[k]}" for k in raw if raw[k] != db[k]]
    if cost and allocated is not None and not est and abs(cost - allocated) > max(0.01 * cost, 0.05):
        problems.append(f"cost: cost-state {cost:.2f} vs allocated {allocated:.2f} (a model in cost-state has no calls in the transcript)")
    if orphans:
        problems.append(f"{orphans} subagent(s) without a parent")
    if unpriced:
        problems.append(f"{unpriced} api call(s) without a cost: no price for {', '.join(models or ['?'])} (add it under [prices])")
    # Output tokens seen in the transcript against Claude Code's own count. The transcript does not hold every
    # call (titles, classifiers) nor always the final usage of the last message, so this is a note, not a failure.
    seen, total = con.execute("""SELECT (SELECT sum(output_tokens) FROM api_calls WHERE session_id = $1),
                                        (SELECT sum(output_tokens) FROM model_usage WHERE session_id = $1)""", [sid]).fetchone()
    notes = [f"agents={db['agents']} api={db['api_calls']} tools={db['tool_calls']} cost={cost or 0:.2f}{' (est)' if est else ''}"]
    if uncovered:
        notes.append(f"cost-state covers only part of the run (a resumed session): {uncovered:.2f} USD before its start is estimated at list price")
    notes += price_notes(con, sid)
    if total:
        notes.append(f"output tokens {100 * (seen or 0) / total:.0f}% of cost-state")
    return problems, notes


def price_notes(con, sid):
    """Where Claude Code's cost for a model differs from the list price of its own token counts by more than 10%.
    cost-state is Claude Code's estimate, not the invoice, so a gap points at a price it applied that the table does not."""
    out = []
    for model, inp, outp, read, write, cost in con.execute("""SELECT model, input_tokens, output_tokens, cache_read_tokens,
            cache_write_tokens, cost_usd FROM model_usage WHERE session_id = $1""", [sid]).fetchall():
        p = price_of(model, prompt_tokens=(inp or 0) + (read or 0) + (write or 0))
        if p is None or not cost:
            continue
        listed = ((inp or 0) * p[0] + (outp or 0) * p[1] + (read or 0) * p[2] + (write or 0) * p[3]) / 1e6  # writes as 5-minute
        if listed and abs(cost / listed - 1) > 0.10:
            out.append(f"cost-state for {model} is {100 * (cost / listed - 1):+.0f}% against list price")
    return out


def gaps(con, cfg, sessions=None, sources=True):
    """Problems that are not about one ingested run. Returns how many lines were printed."""
    from .archive import load_cache, select, stale_runs
    from .hooks import pending
    n = 0
    for sid, stage, error, path in con.execute("SELECT session_id, stage, error, path FROM ingest_errors ORDER BY failed_at").fetchall():
        if sessions and sid not in sessions and sid[:8] not in sessions:
            continue
        n += 1
        print(f"FAIL  {sid[:8]}  ingest {stage} failed: {error} ({path})")
    for p in pending():
        n += 1
        print(f"WARN  {p.name[:8]}  queued by the hook but not ingested yet: run `runlens refresh`")
    missing = evidence_check()
    if missing:
        n += 1
        print(f"FAIL  evidence  {missing} evidence file(s) listed in a manifest have no blob in {config.BLOBS}")
    orphans = orphan_labels(con)
    if orphans:
        n += 1
        print(f"WARN  labels  {orphans} label(s) match no incident (incident ids changed, or their run was deleted): "
              "they are ignored until the incident is labelled again")
    if not sources or not fs_path(config.PROJECTS).is_dir():
        return n
    for sid, _project, reason in stale_runs():
        if sessions and sid not in sessions and sid[:8] not in sessions:
            continue
        n += 1
        print(f"WARN  {sid[:8]}  {reason}: run `runlens refresh`")
    archived = {mf.name.removesuffix(".runlens.json") for mf in fs_path(config.ARCHIVE).glob("*/*.runlens.json")}
    for main, info in select(cfg, cache=load_cache(), sessions=sessions):
        if main.stem not in archived:
            n += 1
            print(f"WARN  {main.stem[:8]}  selected by [select] but never archived ({(info['started'] or '')[:10]}): run `runlens refresh`")
    return n


def orphan_labels(con):
    """Labels whose incident no longer exists. Returns how many distinct incident ids they name."""
    if not con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'labels'").fetchone()[0]:
        return 0
    return con.execute("SELECT count(DISTINCT incident_id) FROM labels WHERE incident_id NOT IN (SELECT incident_id FROM incidents)").fetchone()[0]


def evidence_check():
    """Evidence manifests whose blobs are missing. Returns the number of missing blobs."""
    from .archive import blob_path
    missing = 0
    for mf in fs_path(config.ARCHIVE).glob("*/*.evidence.json"):
        for e in read_json(mf).get("files", []):
            if not fs_path(blob_path(e["sha256"])).exists():
                missing += 1
    return missing
