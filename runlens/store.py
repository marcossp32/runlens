"""DuckDB schema, ingest and analysis views.

Ingest is incremental: each archived run is fingerprinted (size and mtime of its
transcript files), and a run is parsed again only when its fingerprint, the
parser version or the parts of config.toml that shape the rows changed. Rows go
in by bulk load (newline-delimited JSON read by DuckDB), because row-by-row
inserts cost tens of milliseconds each. A run that fails to parse or load is
recorded in `ingest_errors` and the others carry on.
"""
import hashlib
import json
import os
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta, timezone

from . import config, incidents
from .fs import fs_path, makedirs, plain, read_json, signature
from .privacy import redact_rows
from .transcripts import FAST, HAIKU_LONG, NO_GEO, PARSER_VERSION, PRICES, US_GEO, WEB_SEARCH_USD, parse_run, run_files

SCHEMA = {
    "runs": [
        ("session_id", "VARCHAR"), ("project", "VARCHAR"), ("cwd", "VARCHAR"), ("git_branch", "VARCHAR"),
        ("cc_version", "VARCHAR"), ("title", "VARCHAR"), ("skills", "VARCHAR[]"),
        ("started", "TIMESTAMPTZ"), ("ended", "TIMESTAMPTZ"), ("active_ms", "BIGINT"),
        ("human_prompts", "INTEGER"), ("n_agents", "INTEGER"), ("cost_usd", "DOUBLE"), ("cost_estimated", "BOOLEAN"),
        ("api_ms", "BIGINT"), ("tool_ms", "BIGINT"), ("lines_added", "INTEGER"), ("lines_removed", "INTEGER"),
        ("model_usage", "JSON"), ("archived_at", "TIMESTAMPTZ"),
        ("status", "VARCHAR"), ("ended_by", "VARCHAR"), ("is_stub", "BOOLEAN"), ("entrypoint", "VARCHAR"),
        ("pr_urls", "VARCHAR[]"), ("api_ms_no_retries", "BIGINT"), ("total_ms", "BIGINT"),
        ("unknown_model_cost", "BOOLEAN"), ("unpriced_models", "VARCHAR[]"), ("n_api_calls", "INTEGER"),
        ("bad_lines", "INTEGER"), ("parser_version", "INTEGER"), ("cost_uncovered_usd", "DOUBLE"),
    ],
    "agents": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("parent_agent_id", "VARCHAR"),
        ("parent_tool_use_id", "VARCHAR"), ("agent_type", "VARCHAR"), ("description", "VARCHAR"), ("role", "VARCHAR"), ("prompt", "VARCHAR"),
        ("model", "VARCHAR"), ("spawn_depth", "INTEGER"), ("background", "BOOLEAN"), ("status", "VARCHAR"),
        ("started", "TIMESTAMPTZ"), ("ended", "TIMESTAMPTZ"), ("skills", "VARCHAR[]"),
        ("api_calls", "INTEGER"), ("tool_calls", "INTEGER"), ("tool_errors", "INTEGER"), ("compactions", "INTEGER"),
        ("input_tokens", "BIGINT"), ("output_tokens", "BIGINT"), ("cache_read_tokens", "BIGINT"),
        ("cache_write_tokens", "BIGINT"), ("peak_context", "BIGINT"), ("cost_usd", "DOUBLE"), ("last_stop_reason", "VARCHAR"),
        ("thinking_tokens", "BIGINT"), ("effort", "VARCHAR"), ("stopped_by_user", "BOOLEAN"),
    ],
    "api_calls": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("msg_id", "VARCHAR"), ("request_id", "VARCHAR"),
        ("ts", "TIMESTAMPTZ"), ("model", "VARCHAR"), ("effort", "VARCHAR"), ("skill", "VARCHAR"), ("skill_inferred", "BOOLEAN"),
        ("input_tokens", "BIGINT"), ("cache_read_tokens", "BIGINT"), ("cache_write_5m", "BIGINT"),
        ("cache_write_1h", "BIGINT"), ("output_tokens", "BIGINT"), ("thinking_tokens", "BIGINT"),
        ("thinking_ms", "BIGINT"), ("stop_reason", "VARCHAR"), ("api_error", "BOOLEAN"), ("cost_usd", "DOUBLE"),
        ("api_limit", "BOOLEAN"), ("api_error_kind", "VARCHAR"), ("api_error_status", "INTEGER"),
        ("requested_model", "VARCHAR"), ("speed", "VARCHAR"), ("inference_geo", "VARCHAR"),
        ("attribution_agent", "VARCHAR"), ("mcp_server", "VARCHAR"), ("mcp_tool", "VARCHAR"), ("web_searches", "INTEGER"),
    ],
    "tool_calls": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("tool_use_id", "VARCHAR"), ("msg_id", "VARCHAR"),
        ("seq", "INTEGER"), ("ts", "TIMESTAMPTZ"), ("ts_result", "TIMESTAMPTZ"), ("duration_ms", "BIGINT"),
        ("tool", "VARCHAR"), ("skill", "VARCHAR"), ("skill_inferred", "BOOLEAN"), ("input_hash", "VARCHAR"), ("input_summary", "VARCHAR"),
        ("input_json", "VARCHAR"), ("is_error", "BOOLEAN"), ("error_class", "VARCHAR"), ("denied", "VARCHAR"),
        ("interrupted", "BOOLEAN"), ("idle", "BOOLEAN"), ("touches_test", "BOOLEAN"),
        ("result_len", "INTEGER"), ("result_head", "VARCHAR"),
        ("exit_code", "INTEGER"), ("return_code_info", "VARCHAR"), ("timed_out_ms", "BIGINT"), ("tool_duration_ms", "BIGINT"),
        ("patch_added", "INTEGER"), ("patch_removed", "INTEGER"), ("git_op", "VARCHAR"),
        ("permission", "VARCHAR"), ("permission_source", "VARCHAR"),
    ],
    "texts": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("seq", "INTEGER"), ("ts", "TIMESTAMPTZ"),
        ("skill", "VARCHAR"), ("text", "VARCHAR"),
    ],
    "events": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("kind", "VARCHAR"),
        ("value", "BIGINT"), ("detail", "VARCHAR"), ("source", "VARCHAR"),
    ],
    "markers": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("marker", "VARCHAR"),
        ("value", "VARCHAR"), ("bad", "BOOLEAN"), ("source", "VARCHAR"), ("tool_use_id", "VARCHAR"), ("skill", "VARCHAR"),
    ],
    "skill_loads": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("seq", "INTEGER"),
        ("skill", "VARCHAR"), ("skill_dir", "VARCHAR"), ("content_hash", "VARCHAR"), ("content_len", "INTEGER"), ("args", "VARCHAR"),
    ],
    "incidents": [
        ("incident_id", "VARCHAR"), ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("role", "VARCHAR"),
        ("agent_type", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("type", "VARCHAR"), ("key", "VARCHAR"),
        ("n", "INTEGER"), ("skill", "VARCHAR"), ("seq", "INTEGER"), ("anchor", "VARCHAR"), ("context", "VARCHAR"),
        ("policy", "BOOLEAN"), ("detail", "VARCHAR"),
    ],
    "compactions": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("trigger", "VARCHAR"),
        ("pre_tokens", "BIGINT"), ("post_tokens", "BIGINT"), ("duration_ms", "BIGINT"),
    ],
    "model_usage": [
        ("session_id", "VARCHAR"), ("model", "VARCHAR"), ("input_tokens", "BIGINT"), ("output_tokens", "BIGINT"),
        ("thinking_tokens", "BIGINT"), ("cache_read_tokens", "BIGINT"), ("cache_write_tokens", "BIGINT"),
        ("web_search_requests", "INTEGER"), ("cost_usd", "DOUBLE"),
    ],
    "skill_mentions": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("skill", "VARCHAR"), ("invoked", "BOOLEAN"),
    ],
}
RUN_TABLES = list(SCHEMA)

# Labels survive re-ingest: they are keyed by incident_id, which is stable for the same run content.
# The text of each skill version, once per (skill, hash): what a diff between versions compares.
OTHER_DDL = [
    """CREATE TABLE IF NOT EXISTS skill_texts (
        skill VARCHAR, content_hash VARCHAR, text VARCHAR, PRIMARY KEY (skill, content_hash))""",
    """CREATE TABLE IF NOT EXISTS labels (
        incident_id VARCHAR, source VARCHAR, category VARCHAR, fault VARCHAR, confidence VARCHAR, note VARCHAR,
        evidence VARCHAR, model VARCHAR, labeled_at TIMESTAMPTZ DEFAULT current_timestamp)""",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS fault VARCHAR",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS confidence VARCHAR",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS instruction VARCHAR",
    "ALTER TABLE labels ADD COLUMN IF NOT EXISTS skill_hash VARCHAR",
    # What each archived run looked like when it was last ingested; a run is parsed again only when this changes.
    """CREATE TABLE IF NOT EXISTS ingest_state (
        session_id VARCHAR PRIMARY KEY, fingerprint VARCHAR, parser_version INTEGER, config_hash VARCHAR,
        ingested_at TIMESTAMPTZ)""",
    # The last failure per run and stage (read, parse, load); cleared when the run ingests cleanly.
    """CREATE TABLE IF NOT EXISTS ingest_errors (
        session_id VARCHAR, path VARCHAR, stage VARCHAR, error VARCHAR, detail VARCHAR, failed_at TIMESTAMPTZ)""",
    "CREATE TABLE IF NOT EXISTS meta (key VARCHAR PRIMARY KEY, value VARCHAR)",
]
STATE_COLS = [("session_id", "VARCHAR"), ("fingerprint", "VARCHAR"), ("parser_version", "INTEGER"),
              ("config_hash", "VARCHAR"), ("ingested_at", "TIMESTAMPTZ")]
ERROR_COLS = [("session_id", "VARCHAR"), ("path", "VARCHAR"), ("stage", "VARCHAR"), ("error", "VARCHAR"),
              ("detail", "VARCHAR"), ("failed_at", "TIMESTAMPTZ")]
BATCH_ROWS = 200_000  # rows parsed before they are written; bounds memory on a full re-ingest


def schema_version():
    """A hash of everything that defines the database: tables, columns and views. Changing any of it migrates."""
    views = (config.PACKAGE / "views.sql").read_text(encoding="utf-8")
    return hashlib.sha1(json.dumps([SCHEMA, OTHER_DDL, views]).encode()).hexdigest()[:16]


def is_locked(e):
    """DuckDB allows one writer per file. The error says so differently per OS and language (on Windows:
    "being used by another process" / "already open"), so match the exception type and the known phrasings."""
    import duckdb
    text = str(e).lower()
    return isinstance(e, duckdb.IOException) or any(w in text for w in ("lock", "already open", "being used", "used by another"))


def open_db(read_only=False, wait=30.0):
    """A DuckDB connection, waiting up to `wait` seconds while another process holds the write lock."""
    import duckdb
    delay, deadline = 0.25, time.monotonic() + wait
    while True:
        try:
            return duckdb.connect(str(config.DB), read_only=read_only)
        except Exception as e:
            if not is_locked(e) or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 5.0)


def connect(read_only=False, wait=30.0):
    """A connection with the current schema. A read-only one migrates first if the database is older than the code."""
    makedirs(config.HOME)
    if read_only and config.DB.exists():
        con = open_db(read_only=True, wait=wait)
        try:
            current = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        except Exception:
            current = None
        if current and current[0] == schema_version():
            return con
        con.close()
    con = open_db(wait=wait)
    try:
        migrate(con)
    except Exception:
        con.close()
        raise
    if read_only:
        con.close()
        return open_db(read_only=True, wait=wait)
    return con


def migrate(con):
    """Create or update the schema, but only when it changed since the last connection (it is checked by hash)."""
    version = schema_version()
    try:
        have = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except Exception:
        have = None
    if have and have[0] == version:
        return
    for table, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'{c} {t}' for c, t in cols)})")
        present = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()}
        for c, t in cols:
            if c not in present:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")
    for ddl in OTHER_DDL:
        con.execute(ddl)
    con.execute((config.PACKAGE / "views.sql").read_text(encoding="utf-8"))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", [version])


def set_meta(con, **values):
    for k, v in values.items():
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", [k, str(v)])


# --- bulk load ---------------------------------------------------------------------------------------------

def _value(v, typ):
    """A row value coerced to what its column accepts, so one odd transcript field cannot fail a whole load."""
    if v is None:
        return None
    if typ == "JSON":
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v
    if typ in ("BIGINT", "INTEGER"):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v) if abs(v) < 2 ** 62 else None
        return None
    if typ == "DOUBLE":
        return float(v) if isinstance(v, (int, float)) else None
    if typ == "BOOLEAN":
        return bool(v)
    if typ == "TIMESTAMPTZ":
        return v.isoformat() if isinstance(v, (datetime, date)) else (v if isinstance(v, str) else None)
    if typ == "VARCHAR[]":
        return [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in v] if isinstance(v, (list, tuple)) else None
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)


def bulk_insert(con, table, cols, rows, tmpdir, on_conflict=""):
    if not rows:
        return
    path = os.path.join(tmpdir, f"{table}.ndjson")
    names = [c for c, _ in cols]
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({c: _value(r.get(c), t) for c, t in cols}, ensure_ascii=False))
            fh.write("\n")
    spec = "{" + ", ".join(f"'{c}': '{t}'" for c, t in cols) + "}"
    select = f"SELECT {', '.join(names)} FROM read_json(?, format = 'newline_delimited', columns = {spec}, maximum_object_size = 268435456)"
    if on_conflict:
        select = f"SELECT DISTINCT ON (skill, content_hash) * FROM ({select})"
    con.execute(f"INSERT INTO {table} ({', '.join(names)}) {select} {on_conflict}", [path])


def write_runs(parsed, cfg_hash):
    """Replace every listed run's rows in one short transaction."""
    sids = [p["sid"] for p in parsed]
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="runlens-ingest-") as tmp:
        con = connect(wait=300)
        try:
            con.execute("BEGIN")
            for table, cols in SCHEMA.items():
                con.execute(f"DELETE FROM {table} WHERE session_id IN (SELECT unnest(?::VARCHAR[]))", [sids])
                bulk_insert(con, table, cols, [r for p in parsed for r in p["rows"].get(table, [])], tmp)
            bulk_insert(con, "skill_texts", [("skill", "VARCHAR"), ("content_hash", "VARCHAR"), ("text", "VARCHAR")],
                        [r for p in parsed for r in p["rows"]["skill_texts"]], tmp, on_conflict="ON CONFLICT DO NOTHING")
            for t in ("ingest_state", "ingest_errors"):
                con.execute(f"DELETE FROM {t} WHERE session_id IN (SELECT unnest(?::VARCHAR[]))", [sids])
            bulk_insert(con, "ingest_state", STATE_COLS,
                        [{"session_id": p["sid"], "fingerprint": p["fingerprint"], "parser_version": PARSER_VERSION,
                          "config_hash": cfg_hash, "ingested_at": now} for p in parsed], tmp)
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            con.close()


def record_errors(errors):
    if not errors:
        return
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="runlens-ingest-") as tmp:
        con = connect(wait=300)
        try:
            con.execute("BEGIN")
            con.execute("DELETE FROM ingest_errors WHERE session_id IN (SELECT unnest(?::VARCHAR[]))", [[e["session_id"] for e in errors]])
            bulk_insert(con, "ingest_errors", ERROR_COLS, [{**e, "failed_at": now} for e in errors], tmp)
            con.execute("COMMIT")
        finally:
            con.close()


# --- ingest ------------------------------------------------------------------------------------------------

def config_hash(cfg):
    """The parts of config.toml, and the built-in price table, that change the rows a run produces. Editing them re-ingests every run."""
    keys = ("marker", "analysis", "prices", "runs", "privacy")
    built_in = [PRICES, HAIKU_LONG, FAST, US_GEO, sorted(NO_GEO), WEB_SEARCH_USD]
    return hashlib.sha1(json.dumps({**{k: cfg.get(k) for k in keys}, "built_in_prices": built_in},
                                   sort_keys=True, default=str).encode()).hexdigest()[:12]


def fingerprint(main):
    """Size and mtime of every transcript file of a run: changes whenever the archive copy of the run changes."""
    parts = []
    for f in run_files(main):
        parts.append([f.name, *signature(f)])
    for meta in sorted(fs_path(main).with_suffix("").glob("subagents/*.meta.json")):
        parts.append([meta.name, *signature(meta)])
    return hashlib.sha1(json.dumps(parts).encode()).hexdigest()[:16]


def manifests(sessions=None):
    """(manifest path, info or exception) for every archived run, optionally only some sessions."""
    for mf in sorted(fs_path(config.ARCHIVE).glob("*/*.runlens.json")):
        sid = mf.name.removesuffix(".runlens.json")
        if sessions and sid not in sessions:
            continue
        try:
            yield mf, read_json(mf)
        except Exception as e:
            yield mf, e


def ingest(cfg, since=None, sessions=None, quiet=False, force=False):
    """Load archived runs into DuckDB. Returns how many runs were (re)loaded."""
    since_dt = config.since_utc(since)
    cfg_hash = config_hash(cfg)
    con = connect(wait=300)
    try:
        state = {r[0]: r[1:] for r in con.execute("SELECT session_id, fingerprint, parser_version, config_hash FROM ingest_state").fetchall()}
    finally:
        con.close()
    done, skipped, errors, batch, batch_rows = 0, 0, [], [], 0

    def flush():
        nonlocal done, batch, batch_rows
        if not batch:
            return
        try:
            write_runs(batch, cfg_hash)
            ok = batch
        except Exception as e:
            if len(batch) == 1 or is_locked(e):
                if is_locked(e):
                    raise
                errors.append(err(batch[0]["sid"], batch[0]["path"], "load", e))
                ok = []
            else:  # isolate the run that broke the load
                ok = []
                for p in batch:
                    try:
                        write_runs([p], cfg_hash)
                        ok.append(p)
                    except Exception as e1:
                        if is_locked(e1):
                            raise
                        errors.append(err(p["sid"], p["path"], "load", e1))
        done += len(ok)
        if not quiet:
            for p in ok:
                r = p["rows"]
                print(f"{p['sid'][:8]}  {r['runs'][0]['status']:<8}  agents={len(r['agents'])}  api={len(r['api_calls'])}  "
                      f"tools={len(r['tool_calls'])}  markers={len(r['markers'])}  incidents={len(r['incidents'])}")
        batch, batch_rows = [], 0

    from .archive import stale_runs  # a stale archive holds only part of its source: never complete through idleness
    stale = {sid for sid, _, _ in stale_runs()}
    for mf, info in manifests(sessions):
        sid = mf.name.removesuffix(".runlens.json")
        if isinstance(info, Exception):
            errors.append(err(sid, mf, "read", info))
            continue
        if since_dt and (config.parse_ts(info.get("started")) or since_dt) < since_dt:
            continue
        main = mf.with_name(f"{sid}.jsonl")
        if not main.exists():
            errors.append(err(sid, main, "read", FileNotFoundError("the archived transcript is missing")))
            continue
        try:
            fp = fingerprint(main) + ("-stale" if sid in stale else "")
            if not force and state.get(sid) == (fp, PARSER_VERSION, cfg_hash):
                skipped += 1
                continue
            rows = parse_run(main, {**info, "stale": sid in stale}, cfg)
            redact_rows(rows, cfg)
            rows["incidents"] = incidents.build(rows, cfg)
        except Exception as e:
            errors.append(err(sid, main, "parse", e))
            continue
        batch.append({"sid": sid, "path": main, "fingerprint": fp, "rows": rows})
        batch_rows += sum(len(v) for v in rows.values())
        if batch_rows >= BATCH_ROWS:
            flush()
    flush()
    record_errors(errors)
    close_idle_runs(cfg)
    if not quiet:
        print(f"{done} run(s) ingested, {skipped} unchanged" + (f", {len(errors)} failed (see `runlens check`)" if errors else ""))
        for e in errors:
            print(f"error  {e['session_id'][:8]}  {e['stage']}: {e['error']}")
    return done


def outdated_sessions():
    """Runs last ingested by an older parser, which a drain re-ingests so the database never mixes versions."""
    con = connect(wait=300)
    try:
        return sorted(r[0] for r in con.execute("SELECT session_id FROM ingest_state WHERE parser_version IS DISTINCT FROM ?", [PARSER_VERSION]).fetchall())
    finally:
        con.close()


def failed_sessions(sessions):
    """Which of these sessions have a recorded ingest error."""
    con = connect(wait=300)
    try:
        return {r[0] for r in con.execute("SELECT session_id FROM ingest_errors WHERE session_id IN (SELECT unnest(?::VARCHAR[]))", [list(sessions)]).fetchall()}
    finally:
        con.close()


def err(sid, path, stage, e):
    return {"session_id": sid, "path": str(plain(path)), "stage": stage, "error": f"{type(e).__name__}: {e}"[:1000],
            "detail": "".join(traceback.format_exception(e))[-4000:]}


def close_idle_runs(cfg):
    """A run that had no cost-state when it was parsed becomes complete once nothing was added for idle_hours."""
    from .archive import stale_runs  # a stale archive holds only part of its source: it stays open until archived again
    hours = (cfg.get("runs") or {}).get("idle_hours", config.RUNS["idle_hours"])
    stale = [sid for sid, _, _ in stale_runs()]
    con = connect(wait=300)
    try:
        con.execute("""UPDATE runs SET status = 'complete', ended_by = 'idle'
                       WHERE status = 'open' AND ended < ? AND session_id NOT IN (SELECT unnest(?::VARCHAR[]))""",
                    [datetime.now(timezone.utc) - timedelta(hours=hours), stale])
        set_meta(con, parser_version=PARSER_VERSION, last_ingest=datetime.now(timezone.utc).isoformat())
    finally:
        con.close()


def prune(before=None, sessions=None, keep_archive=False, yes=False):
    """Delete runs (database rows, and unless keep_archive their archived transcripts and evidence)."""
    from . import archive as arch
    con = connect(read_only=True)
    try:
        where, args = [], []
        if before:
            where.append("started < ?")
            args.append(config.since_utc(before))
        if sessions:
            where.append("(session_id IN (SELECT unnest(?::VARCHAR[])) OR session_id[:8] IN (SELECT unnest(?::VARCHAR[])))")
            args += [sessions, sessions]
        if not where:
            raise ValueError("say what to prune: --before DATE or --session ID")
        rows = con.execute(f"SELECT session_id, project, started FROM runs WHERE {' AND '.join(where)} ORDER BY started", args).fetchall()
    finally:
        con.close()
    for sid, project, started in rows:
        print(f"{'delete' if yes else 'would delete'}  {sid[:8]}  {started:%Y-%m-%d}  {project}")
    if not yes:
        print(f"{len(rows)} run(s). Nothing deleted: add --yes to delete" + ("" if keep_archive else " (database rows and archive)"))
        return len(rows)
    sids = [r[0] for r in rows]
    con = connect(wait=300)
    try:
        con.execute("BEGIN")
        con.execute("DELETE FROM labels WHERE incident_id IN (SELECT incident_id FROM incidents WHERE session_id IN (SELECT unnest(?::VARCHAR[])))", [sids])
        for t in RUN_TABLES + ["ingest_state", "ingest_errors"]:
            con.execute(f"DELETE FROM {t} WHERE session_id IN (SELECT unnest(?::VARCHAR[]))", [sids])
        con.execute("""DELETE FROM skill_texts t WHERE NOT EXISTS
                       (SELECT 1 FROM skill_loads l WHERE l.skill = t.skill AND l.content_hash = t.content_hash)""")
        con.execute("COMMIT")
    finally:
        con.close()
    if not keep_archive:
        for sid, project, _ in rows:
            arch.remove_run(project, sid)
        arch.collect_garbage()
    print(f"{len(rows)} run(s) deleted")
    return len(rows)
