"""runlens: history of Claude Code runs, to find where a flow struggles.

  archive    copy selected runs from ~/.claude/projects into the archive
  ingest     load the archive into DuckDB (incremental: unchanged runs are skipped)
  refresh    archive + ingest, including the sessions the hook queued
  check      compare the database against the archive and the archive against ~/.claude/projects
  prune      delete runs from the database and the archive
  migrate-evidence  convert evidence archived by runlens 0.1 into deduplicated blobs
  summary    one table per run and per skill in the terminal
  report     write the HTML diagnosis report
  dashboard  write the HTML benchmark dashboard: scores, versions, diffs and comparisons
  score      each skill's (or role's, or group's) current version against its previous one
  versions   every version of one skill: runs, invocations, outcome, verdict, confounders, diff
  proposals  record a proposed skill edit (add) or list them (list)
  verify     check recorded proposals against the runs since: confirmed, refuted, inconclusive, not enough runs, confounded
  show       print the timeline around an incident or tool call
  incidents  list incidents
  classify   label incidents with a failure taxonomy, using `claude -p`
  labels     export labels to CSV for human review, or import the reviewed CSV
  agreement  how well the LLM labels match the human ones
  export-eval  turn real incidents into eval cases for `claude plugin eval` and skill-creator
  hook       entry point for Claude Code hooks (reads the hook JSON on stdin)
  install    install the SessionEnd hook and the retro skill
  uninstall  remove the hook
  sql        run a SQL query against the database
"""
import argparse
import sys
import time

from . import config

HIDDEN = {"drain"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="runlens", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help=f"config file (default {config.HOME / 'config.toml'})")
    sub = ap.add_subparsers(dest="command", required=True)

    def filters(p):
        p.add_argument("--since", help="runs started on or after this ISO date")
        p.add_argument("--skill", action="append", help="only runs that used this skill (repeatable)")
        p.add_argument("--project", action="append", help="only runs whose cwd contains this text (repeatable)")
        p.add_argument("--session", action="append", help="only this session id (repeatable)")
        p.add_argument("--quiet", action="store_true")

    for name in ("archive", "ingest", "refresh"):
        p = sub.add_parser(name)
        filters(p)
        if name != "archive":
            p.add_argument("--force", action="store_true", help="parse every run again, changed or not")
    p = sub.add_parser("check")
    p.add_argument("--session", action="append")
    p.add_argument("--no-sources", action="store_true", help="skip comparing the archive with ~/.claude/projects")
    p = sub.add_parser("prune")
    p.add_argument("--before", help="runs started before this ISO date")
    p.add_argument("--session", action="append", help="this session id or 8-character prefix (repeatable)")
    p.add_argument("--keep-archive", action="store_true", help="delete database rows only, keep the archived transcripts")
    p.add_argument("--yes", action="store_true", help="delete; without it, only list what would be deleted")
    p = sub.add_parser("migrate-evidence")
    p.add_argument("--yes", action="store_true", help="convert and delete the old folders; without it, a dry run")
    p.add_argument("--keep-excluded", action="store_true",
                   help="also keep files the default exclude list drops (browser profiles, databases, node_modules)")
    sub.add_parser("drain")  # the hook's detached worker: kept out of --help by the metavar set below
    sub.add_parser("summary")
    p = sub.add_parser("report")
    p.add_argument("--out", help=f"output file (default {config.HOME / 'report.html'})")
    p.add_argument("--session", action="append", help="limit the report to these runs")
    p = sub.add_parser("dashboard")
    p.add_argument("--out", help=f"output file (default {config.HOME / 'dashboard.html'})")
    p = sub.add_parser("score")
    p.add_argument("--kind", choices=["skill", "agent", "group"], default="skill")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("versions")
    p.add_argument("skill", help="skill name, or a unit id such as group:my-flow")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("proposals")
    psub = p.add_subparsers(dest="action", required=True, metavar="action")
    pa = psub.add_parser("add", help="record a proposal; prints its id")
    pa.add_argument("--skill", required=True)
    pa.add_argument("--hypothesis", required=True, help="what the edit should change, and why")
    pa.add_argument("--measure", required=True,
                    help="score, outcome, cost, seconds, error_rate, incidents, interventions, idle_rate, api_error_rate or bad_markers")
    pa.add_argument("--direction", required=True, choices=["lower", "higher"])
    pa.add_argument("--evidence", nargs="*", default=[], help="incident ids behind it")
    pa.add_argument("--base-version", help="hash of the skill text being edited (default: its current version)")
    pl = psub.add_parser("list", help="list recorded proposals")
    pl.add_argument("--json", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("id", nargs="?", help="proposal id (default: every proposal)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show")
    p.add_argument("id", help="incident id or tool_use id")
    p.add_argument("--steps", type=int, default=12)
    p.add_argument("--after", type=int, default=4)
    p = sub.add_parser("incidents")
    p.add_argument("--type")
    p.add_argument("--skill")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--all", action="store_true", help="also list policy permission denials")
    output_flags(p)
    p = sub.add_parser("classify")
    p.add_argument("--type", action="append", help="only these incident types")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--model", default=None, help="model alias for the judge (default from config, else sonnet)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--relabel", action="store_true", help="label again incidents that already have an llm label")
    p.add_argument("--skill", action="append", help="only incidents of this skill (repeatable)")
    p.add_argument("--sample", choices=["stratified", "priority"], default="stratified",
                   help="stratified: random, the same number per incident type (unbiased agreement); priority: highest-signal types first")
    p.add_argument("--seed", type=int, help="seed for the stratified sample, to pick the same incidents again")
    p.add_argument("--dry-run", action="store_true", help="list the chosen incidents and print one judge prompt; no model call")
    p = sub.add_parser("labels")
    p.add_argument("action", choices=["export", "import"])
    p.add_argument("file")
    p.add_argument("--limit", type=int, help="export: a stratified random sample of this many LLM-labelled incidents")
    p.add_argument("--seed", type=int, help="export: seed for the sample")
    p.add_argument("--blind", action="store_true", help="export: leave the LLM labels out, so they cannot anchor the reviewer")
    p = sub.add_parser("agreement")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("export-eval")
    p.add_argument("--incident", action="append", help="incident id (repeatable)")
    p.add_argument("--skill", action="append", help="incidents of this skill (repeatable)")
    p.add_argument("--label", action="append", help="incidents whose latest label is this category (repeatable)")
    p.add_argument("--type", action="append", help="incidents of this type (repeatable)")
    p.add_argument("--format", choices=["plugin-eval", "skill-creator", "both"], default="both")
    p.add_argument("--out", help=f"output folder (default {config.HOME / 'evals' / '<timestamp>'})")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--history", action="store_true",
                   help="for main-session incidents, resume the transcript cut just before the failing step")
    sub.add_parser("hook")
    p = sub.add_parser("install")
    p.add_argument("--no-skill", action="store_true")
    sub.add_parser("uninstall")
    p = sub.add_parser("sql")
    p.add_argument("query")
    output_flags(p)

    # argparse prints help=SUPPRESS subcommands as "==SUPPRESS==", so hidden ones are left out of the metavar instead.
    sub.metavar = "{" + ",".join(c for c in sub.choices if c not in HIDDEN) + "}"
    a = ap.parse_args(argv)
    if a.command in ("hook", "drain"):
        return hook_command(a)
    cfg = config.load(a.config)
    flt = lambda: {"since": a.since, "skills": a.skill, "projects": a.project, "sessions": a.session}

    if a.command == "refresh":
        from .hooks import drain, pending
        if pending():  # sessions the hook queued: archive and ingest them first, then the rest
            drain(cfg, wait_lock=True)
    lock = None
    if a.command == "refresh":  # the drain lock keeps a parallel drain from copying the same files at once
        from .hooks import DrainLock
        lock = DrainLock()
        while not lock.acquire():
            time.sleep(1)
    try:
        if a.command in ("archive", "refresh"):
            from .archive import archive
            archive(cfg, quiet=a.quiet, **flt())
        if a.command in ("ingest", "refresh"):
            from .store import ingest
            ingest(cfg, since=a.since, sessions=a.session, quiet=a.quiet, force=a.force)
    finally:
        if lock:
            lock.release()
    if a.command == "check":
        from .check import check
        return 1 if check(a.session, cfg, sources=not a.no_sources) else 0
    elif a.command == "prune":
        from .store import prune
        prune(before=a.before, sessions=a.session, keep_archive=a.keep_archive, yes=a.yes)
    elif a.command == "migrate-evidence":
        from .archive import migrate_evidence
        s = migrate_evidence(dry_run=not a.yes, keep_excluded=a.keep_excluded)
        gb = lambda b: f"{b / 1e9:.2f} GB"
        print(f"{s['runs']} run folder(s), {s['files']} file(s), {gb(s['bytes'])}; excluded {s['excluded_files']} file(s) "
              f"({gb(s['excluded_bytes'])}); {'at most ' if not a.yes else ''}{s['blobs_new']} distinct file(s) to keep, {gb(s['blob_bytes_new'])}")
        print(f"deleted {s['folders_deleted']} old evidence folder(s)" if a.yes else "dry run: add --yes to convert and delete the old folders")
    elif a.command == "summary":
        from .store import connect
        con = connect(read_only=True)
        print(con.sql("""SELECT session_id[:8] AS run, started::DATE AS day, regexp_extract(cwd, '[^\\\\/]+$') AS repo,
                                round(cost_usd, 2) AS usd, cost_estimated AS est, round(active_ms / 3.6e6, 1) AS active_h,
                                n_agents AS agents, tool_calls, tool_errors, idle_calls, incidents, bad_markers
                         FROM v_runs ORDER BY started"""))
        print(con.sql("""SELECT skill, runs, api_calls, round(cost_usd, 2) AS usd, cost_pct AS pct, tool_calls,
                                tool_errors, idle_calls, incidents, bad_markers
                         FROM v_skill ORDER BY cost_usd DESC NULLS LAST"""))
    elif a.command == "report":
        from .report import write_report
        print(write_report(cfg, a.out, a.session))
    elif a.command == "dashboard":
        from .dashboard import write_dashboard
        print(write_dashboard(cfg, a.out))
    elif a.command in ("score", "versions", "proposals", "verify"):
        return method_command(a, cfg)
    elif a.command == "show":
        from .show import show
        return show(a.id, a.steps, a.after)
    elif a.command == "incidents":
        from .store import connect
        con = connect(read_only=True)
        where, args = ["1=1"], []
        if a.type:
            where.append("type = ?")
            args.append(a.type)
        if a.skill:
            where.append("skill = ?")
            args.append(a.skill)
        if not a.all:
            where.append("NOT coalesce(policy, false)")
        args.append(a.limit)
        # Each incident's latest label, a human one before an LLM one; the quote and the skill hash only in --json/--csv.
        from .classify import latest_labels
        quote = ", l.instruction, l.skill_hash" if a.json or a.csv else ""
        emit(con.execute(f"""SELECT incident_id, session_id[:8] AS run, type, n, skill, role, left(key, 80) AS key, policy,
                                    l.category AS label, l.fault, l.source AS label_source{quote}
                             FROM incidents
                             LEFT JOIN (SELECT * FROM {latest_labels(con)}
                                        QUALIFY row_number() OVER (PARTITION BY incident_id ORDER BY (source = 'human') DESC) = 1) l
                               USING (incident_id)
                             WHERE {' AND '.join(where)} ORDER BY ts LIMIT ?""", args), a)
        con.close()
    elif a.command == "classify":
        from .classify import classify
        classify(cfg, types=a.type, skills=a.skill, limit=a.limit, model=a.model, workers=a.workers, relabel=a.relabel,
                 mode=a.sample, seed=a.seed, dry_run=a.dry_run)
    elif a.command == "labels":
        from .classify import export_labels, import_labels
        if a.action == "export":
            export_labels(a.file, limit=a.limit, seed=a.seed, blind=a.blind)
        else:
            import_labels(a.file)
    elif a.command == "agreement":
        from .classify import agreement
        agreement(as_json=a.json)
    elif a.command == "export-eval":
        from .evals import export
        return 0 if export(cfg, ids=a.incident, skills=a.skill, labels=a.label, types=a.type, fmt=a.format, out=a.out,
                           limit=a.limit, use_history=a.history) else 1
    elif a.command == "install":
        from .hooks import install
        install(skill=not a.no_skill)
    elif a.command == "uninstall":
        from .hooks import uninstall
        uninstall()
    elif a.command == "sql":
        from .store import connect
        con = connect(read_only=True)
        try:
            emit(con.execute(a.query), a)
        finally:
            con.close()
    return 0


def hook_command(a):
    """The hook and its detached drain. Neither has a terminal to print to (the drain's stderr goes nowhere), so a
    config that cannot load is written to hooks.log, and the hook still queues the session before anything else."""
    from . import hooks
    try:
        cfg, error = config.load(a.config), None
    except Exception as e:
        cfg, error = None, e
    if a.command == "hook":
        return hooks.handle(cfg, sys.stdin.read(), config_error=error)
    if error:
        hooks.log(f"drain: {hooks.config_error_text(error)}")
        return 1
    hooks.drain(cfg)
    return 0


def method_command(a, cfg):
    """score, versions, proposals and verify: the method's verdicts as text, or as the JSON the retro skill reads."""
    import json

    from . import bench, proposals
    from .store import connect
    listing = a.command == "proposals" and a.action == "list"
    con = connect(read_only=a.command in ("score", "versions") or listing)
    dump = lambda obj: print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    try:
        if listing:
            rows = proposals.listing(con)
            if a.json:
                dump({"proposals": rows})
            else:
                cols = ["id", "skill", "base_version", "measure", "direction", "verdict", "hypothesis"]
                print(_table(cols, [[r[c] for c in cols] for r in rows]))
            return 0
        model = bench.compute(bench.load(con), cfg=cfg)
        if a.command == "score":
            out = bench.score_summary(model, a.kind)
            dump(out) if a.json else print(_score_text(out))
        elif a.command == "versions":
            out = bench.versions_summary(model, proposals.unit_id(a.skill))
            if out is None:
                raise ValueError(f"no finished, non-stub runs of {a.skill!r}; `runlens score` lists the units")
            # where the skill's files live, most recently loaded first, so its text can be read and cited
            out["skill_dirs"] = [r[0] for r in con.execute(
                """SELECT skill_dir FROM skill_loads WHERE skill = ? AND skill_dir IS NOT NULL
                   GROUP BY skill_dir ORDER BY max(ts) DESC""", [out["skill"]]).fetchall()]
            dump(out) if a.json else print(_versions_text(out))
        elif a.command == "proposals":
            p = proposals.add(con, model, a.skill, a.hypothesis, a.measure, a.direction, a.evidence, a.base_version)
            print(f"{p['id']} recorded: {p['skill']} {p['base_version']}")
        else:
            results = proposals.verify(con, model, a.id)
            if a.json:
                dump({"proposals": results})
            else:
                cols = ["id", "skill", "measure", "direction", "verdict", "observed", "runs_before", "runs_after"]
                print(_table(cols, [[r.get(c) for c in cols] for r in results]))
                for r in results:
                    if r["confounders"]:
                        print(f"{r['id']} confounded by: {'; '.join(r['confounders'])}")
    finally:
        con.close()
    return 0


def _num(x, d=1):
    return "-" if x is None else f"{x:.{d}f}"


def _diff_text(d):
    if not d:
        return "-"
    return f"{_num(d['score'])} [{_num(d['ci95'][0])}, {_num(d['ci95'][1])}]" if d["ci95"] else _num(d["score"])


def _outcome_text(o):
    return f"{o['value']:.0%} of {o['n']}" if o and o["value"] is not None else "-"


def _score_text(out):
    pop = out["population"]
    head = (f"{pop['runs']} finished runs ({pop['open']} open and {pop['stub']} stub runs left out). Each unit's current "
            "version against its previous one (difference: 100 = no change); units are not ranked against each other.")
    cols = ["unit", "runs", "invocations", "current", "verdict", "vs", "difference", "outcome", "cost/inv"]
    rows = [[u["unit"], u["runs"], u["invocations"], u["current"] or "-", u["verdict"] or "-", u["vs"] or "-",
             _diff_text(u["difference"]), _outcome_text(u["outcome"]), _num(u["typical"].get("cost"), 2)] for u in out["units"]]
    notes = [f"{u['unit']}: confounded by {'; '.join(u['confounders'])}" for u in out["units"] if u["verdict"] == "confounded"]
    return "\n".join([head, _table(cols, rows)] + notes)


def _versions_text(out):
    cols = ["version", "hash", "runs", "invocations", "score", "verdict", "vs", "difference", "outcome", "cost/success"]
    rows = [[v["label"], v["hash"], v["runs"], v["invocations"], _num(v["score"]), v["verdict"] or "first", v["vs"] or "-",
             _diff_text(v["difference"]), _outcome_text(v["outcome"]), _num(v["cost_per_success_usd"], 2)] for v in out["versions"]]
    notes = [f"{v['label']}: confounded by {'; '.join(v['confounders'])}" for v in out["versions"] if v["confounders"]]
    dirs = [f"files: {'; '.join(out['skill_dirs'])}"] if out.get("skill_dirs") else []
    return "\n".join([f"{out['skill']}: score 100 = its own typical run; difference = the version against the one before "
                      "(100 = no change)", _table(cols, rows)] + notes + dirs)


def output_flags(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="print the rows as a JSON array")
    g.add_argument("--csv", action="store_true", help="print the rows as CSV")


def emit(cur, a):
    """Print a query result as a table, JSON or CSV."""
    if cur.description is None:
        return
    cols = [d[0] for d in cur.description]
    if getattr(a, "json", False) or getattr(a, "csv", False):
        rows = cur.fetchall()
        if a.json:
            import json
            print(json.dumps([dict(zip(cols, r)) for r in rows], ensure_ascii=False, indent=2, default=str))
        else:
            import csv
            w = csv.writer(sys.stdout, lineterminator="\n")
            w.writerow(cols)
            w.writerows(rows)
        return
    print(_table(cols, cur.fetchall()))


def _table(cols, rows, width=60):
    """A plain text table, without depending on DuckDB's own printer (which needs a relation, not a result)."""
    cell = lambda v: ("NULL" if v is None else str(v)).replace("\n", " ")[:width]
    body = [[cell(v) for v in r] for r in rows]
    w = [max([len(c)] + [len(r[i]) for r in body]) for i, c in enumerate(cols)]
    line = lambda vals: "  ".join(v.ljust(w[i]) for i, v in enumerate(vals)).rstrip()
    out = [line(cols), "  ".join("-" * x for x in w)] + [line(r) for r in body] + [f"({len(rows)} row{'s' if len(rows) != 1 else ''})"]
    return "\n".join(out)


def run():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        code = main()
    except KeyboardInterrupt:
        code = 130
    except Exception as e:
        code = friendly(e)
    sys.exit(code)


def friendly(e):
    """One line on stderr for errors a user can fix (bad SQL, bad config, the database busy), not a traceback."""
    from .config import ConfigError
    try:
        import duckdb
        db_error = isinstance(e, duckdb.Error)
    except ImportError:
        db_error = False
    if isinstance(e, ConfigError):
        print(f"runlens: config error: {e}", file=sys.stderr)
    elif db_error:
        from .store import is_locked
        msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        if is_locked(e):
            msg = f"the database is in use by another runlens process; try again in a moment ({msg})"
        print(f"runlens: {type(e).__name__.removesuffix('Exception')} error: {msg}", file=sys.stderr)
    elif isinstance(e, (ValueError, OSError)):
        print(f"runlens: {e}", file=sys.stderr)
    else:
        raise e
    return 1
