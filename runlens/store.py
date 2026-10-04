"""DuckDB schema, ingest and analysis views."""
import json

from . import config, incidents
from .transcripts import parse_run

SCHEMA = {
    "runs": [
        ("session_id", "VARCHAR"), ("project", "VARCHAR"), ("cwd", "VARCHAR"), ("git_branch", "VARCHAR"),
        ("cc_version", "VARCHAR"), ("title", "VARCHAR"), ("skills", "VARCHAR[]"),
        ("started", "TIMESTAMPTZ"), ("ended", "TIMESTAMPTZ"), ("active_ms", "BIGINT"),
        ("human_prompts", "INTEGER"), ("n_agents", "INTEGER"), ("cost_usd", "DOUBLE"), ("cost_estimated", "BOOLEAN"),
        ("api_ms", "BIGINT"), ("tool_ms", "BIGINT"), ("lines_added", "INTEGER"), ("lines_removed", "INTEGER"),
        ("model_usage", "JSON"), ("archived_at", "TIMESTAMPTZ"),
    ],
    "agents": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("parent_agent_id", "VARCHAR"),
        ("parent_tool_use_id", "VARCHAR"), ("agent_type", "VARCHAR"), ("description", "VARCHAR"), ("role", "VARCHAR"), ("prompt", "VARCHAR"),
        ("model", "VARCHAR"), ("spawn_depth", "INTEGER"), ("background", "BOOLEAN"), ("status", "VARCHAR"),
        ("started", "TIMESTAMPTZ"), ("ended", "TIMESTAMPTZ"), ("skills", "VARCHAR[]"),
        ("api_calls", "INTEGER"), ("tool_calls", "INTEGER"), ("tool_errors", "INTEGER"), ("compactions", "INTEGER"),
        ("input_tokens", "BIGINT"), ("output_tokens", "BIGINT"), ("cache_read_tokens", "BIGINT"),
        ("cache_write_tokens", "BIGINT"), ("peak_context", "BIGINT"), ("cost_usd", "DOUBLE"), ("last_stop_reason", "VARCHAR"),
    ],
    "api_calls": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("msg_id", "VARCHAR"), ("request_id", "VARCHAR"),
        ("ts", "TIMESTAMPTZ"), ("model", "VARCHAR"), ("effort", "VARCHAR"), ("skill", "VARCHAR"),
        ("input_tokens", "BIGINT"), ("cache_read_tokens", "BIGINT"), ("cache_write_5m", "BIGINT"),
        ("cache_write_1h", "BIGINT"), ("output_tokens", "BIGINT"), ("thinking_tokens", "BIGINT"),
        ("thinking_ms", "BIGINT"), ("stop_reason", "VARCHAR"), ("api_error", "BOOLEAN"), ("cost_usd", "DOUBLE"),
    ],
    "tool_calls": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("tool_use_id", "VARCHAR"), ("msg_id", "VARCHAR"),
        ("seq", "INTEGER"), ("ts", "TIMESTAMPTZ"), ("ts_result", "TIMESTAMPTZ"), ("duration_ms", "BIGINT"),
        ("tool", "VARCHAR"), ("skill", "VARCHAR"), ("input_hash", "VARCHAR"), ("input_summary", "VARCHAR"),
        ("input_json", "VARCHAR"), ("is_error", "BOOLEAN"), ("error_class", "VARCHAR"), ("denied", "VARCHAR"),
        ("interrupted", "BOOLEAN"), ("idle", "BOOLEAN"), ("touches_test", "BOOLEAN"),
        ("result_len", "INTEGER"), ("result_head", "VARCHAR"),
    ],
    "texts": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("seq", "INTEGER"), ("ts", "TIMESTAMPTZ"),
        ("skill", "VARCHAR"), ("text", "VARCHAR"),
    ],
    "events": [
        ("session_id", "VARCHAR"), ("agent_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("kind", "VARCHAR"),
        ("value", "BIGINT"), ("detail", "VARCHAR"),
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
    ],
}
RUN_TABLES = list(SCHEMA)

# Labels survive re-ingest: they are keyed by incident_id, which is stable for the same run content.
LABELS = """CREATE TABLE IF NOT EXISTS labels (
    incident_id VARCHAR, source VARCHAR, category VARCHAR, fault VARCHAR, confidence VARCHAR, note VARCHAR,
    evidence VARCHAR, model VARCHAR, labeled_at TIMESTAMPTZ DEFAULT current_timestamp)"""


def connect(read_only=False):
    import duckdb
    config.HOME.mkdir(parents=True, exist_ok=True)
    if read_only and config.DB.exists():
        return duckdb.connect(str(config.DB), read_only=True)
    con = duckdb.connect(str(config.DB))
    for table, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'{c} {t}' for c, t in cols)})")
        have = {r[0] for r in con.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'").fetchall()}
        for c, t in cols:
            if c not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")
    con.execute(LABELS)
    for col in ("fault", "confidence"):
        con.execute(f"ALTER TABLE labels ADD COLUMN IF NOT EXISTS {col} VARCHAR")
    con.execute((config.PACKAGE / "views.sql").read_text(encoding="utf-8"))
    return con


def ingest(cfg, since=None, sessions=None, quiet=False):
    con = connect()
    done = 0
    for mf in sorted(config.ARCHIVE.glob("*/*.runlens.json")):
        info = json.loads(mf.read_text(encoding="utf-8"))
        if since and (info.get("started") or "") < since:
            continue
        if sessions and info["session_id"] not in sessions:
            continue
        main = mf.with_name(f"{info['session_id']}.jsonl")
        if not main.exists():
            continue
        rows = parse_run(main, info, cfg)
        rows["incidents"] = incidents.build(rows, cfg)
        con.execute("BEGIN")
        for table, cols in SCHEMA.items():
            con.execute(f"DELETE FROM {table} WHERE session_id = ?", [info["session_id"]])
            if rows.get(table):
                names = [c for c, _ in cols]
                con.executemany(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                                [[r.get(n) for n in names] for r in rows[table]])
        con.execute("COMMIT")
        done += 1
        if not quiet:
            print(f"{info['session_id'][:8]}  agents={len(rows['agents'])}  api={len(rows['api_calls'])}  "
                  f"tools={len(rows['tool_calls'])}  markers={len(rows['markers'])}  incidents={len(rows['incidents'])}")
    con.close()
    return done
