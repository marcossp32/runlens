"""runlens: history of Claude Code runs, to find where a flow struggles.

  archive    copy selected runs from ~/.claude/projects into the archive
  ingest     load the archive into DuckDB (idempotent)
  refresh    archive + ingest
  check      compare the database against the raw transcripts
  summary    one table per run and per skill in the terminal
  report     write the HTML diagnosis report
  dashboard  write the HTML benchmark dashboard: scores, versions, diffs and comparisons
  show       print the timeline around an incident or tool call
  incidents  list incidents
  classify   label incidents with a failure taxonomy, using `claude -p`
  labels     export labels to CSV for human review, or import the reviewed CSV
  agreement  how well the LLM labels match the human ones
  hook       entry point for Claude Code hooks (reads the hook JSON on stdin)
  install    install the SessionEnd hook and the retro skill
  uninstall  remove the hook
  sql        run a SQL query against the database
"""
import argparse
import sys

from . import config


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
        filters(sub.add_parser(name))
    p = sub.add_parser("check")
    p.add_argument("--session", action="append")
    sub.add_parser("summary")
    p = sub.add_parser("report")
    p.add_argument("--out", help=f"output file (default {config.HOME / 'report.html'})")
    p.add_argument("--session", action="append", help="limit the report to these runs")
    p = sub.add_parser("dashboard")
    p.add_argument("--out", help=f"output file (default {config.HOME / 'dashboard.html'})")
    p = sub.add_parser("show")
    p.add_argument("id", help="incident id or tool_use id")
    p.add_argument("--steps", type=int, default=12)
    p.add_argument("--after", type=int, default=4)
    p = sub.add_parser("incidents")
    p.add_argument("--type")
    p.add_argument("--skill")
    p.add_argument("--limit", type=int, default=50)
    p = sub.add_parser("classify")
    p.add_argument("--type", action="append", help="only these incident types")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--model", default=None, help="model alias for the judge (default from config, else sonnet)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--relabel", action="store_true", help="label again incidents that already have an llm label")
    p = sub.add_parser("labels")
    p.add_argument("action", choices=["export", "import"])
    p.add_argument("file")
    sub.add_parser("agreement")
    sub.add_parser("hook")
    p = sub.add_parser("install")
    p.add_argument("--no-skill", action="store_true")
    sub.add_parser("uninstall")
    p = sub.add_parser("sql")
    p.add_argument("query")

    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    flt = lambda: {"since": a.since, "skills": a.skill, "projects": a.project, "sessions": a.session}

    if a.command in ("archive", "refresh"):
        from .archive import archive
        archive(cfg, quiet=a.quiet, **flt())
    if a.command in ("ingest", "refresh"):
        from .store import ingest
        ingest(cfg, since=a.since, sessions=a.session, quiet=a.quiet)
    elif a.command == "check":
        from .check import check
        return 1 if check(a.session) else 0
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
    elif a.command == "show":
        from .show import show
        return show(a.id, a.steps, a.after)
    elif a.command == "incidents":
        from .store import connect
        con = connect(read_only=True)
        where, args = ["1=1"], []
        if a.type:
            where.append("type = ?"); args.append(a.type)
        if a.skill:
            where.append("skill = ?"); args.append(a.skill)
        print(con.sql(f"""SELECT incident_id, session_id[:8] AS run, type, n, skill, role, left(key, 80) AS key
                          FROM incidents WHERE {' AND '.join(where)} ORDER BY ts LIMIT {int(a.limit)}""", params=args))
    elif a.command == "classify":
        from .classify import classify
        classify(cfg, types=a.type, limit=a.limit, model=a.model, workers=a.workers, relabel=a.relabel)
    elif a.command == "labels":
        from .classify import export_labels, import_labels
        (export_labels if a.action == "export" else import_labels)(a.file)
    elif a.command == "agreement":
        from .classify import agreement
        agreement()
    elif a.command == "hook":
        from .hooks import handle
        return handle(cfg, sys.stdin.read())
    elif a.command == "install":
        from .hooks import install
        install(skill=not a.no_skill)
    elif a.command == "uninstall":
        from .hooks import uninstall
        uninstall()
    elif a.command == "sql":
        from .store import connect
        print(connect(read_only=True).sql(a.query))
    return 0


def run():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
