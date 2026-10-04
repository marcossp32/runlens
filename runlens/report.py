"""Write a self-contained HTML diagnosis report from the database.

Facts only: every number comes from a view in views.sql, every incident links
to `runlens show <id>`. The report draws no conclusions.
"""
import html
from datetime import datetime
from pathlib import Path

from . import config
from .incidents import TYPES

TABLES = ["runs", "agents", "api_calls", "tool_calls", "texts", "events", "markers", "skill_loads", "incidents"]


def load(sessions=None):
    """An in-memory copy of the database, optionally limited to some runs, with the views on top."""
    import duckdb
    mem = duckdb.connect()
    mem.execute(f"ATTACH '{config.DB.as_posix()}' AS src (READ_ONLY)")
    where = ""
    if sessions:
        ids = ", ".join("'" + s.replace("'", "") + "'" for s in sessions)
        where = f" WHERE session_id IN (SELECT session_id FROM src.runs WHERE session_id IN ({ids}) OR session_id[:8] IN ({ids}))"
    for t in TABLES:
        mem.execute(f"CREATE TABLE {t} AS SELECT * FROM src.{t}{where}")
    mem.execute("CREATE TABLE labels AS SELECT * FROM src.labels WHERE incident_id IN (SELECT incident_id FROM incidents)")
    mem.execute((config.PACKAGE / "views.sql").read_text(encoding="utf-8"))
    return mem


def q(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def esc(v):
    return html.escape("" if v is None else str(v))


def num(v, d=0):
    if v is None:
        return "–"
    if isinstance(v, float) and d == 0 and abs(v) < 10 and v != int(v):
        d = 2
    return f"{v:,.{d}f}"


def usd(v):
    return "–" if v is None else f"${v:,.2f}"


def pct(v):
    return "–" if v is None else f"{100 * v:.1f}%"


def dur(ms):
    if ms is None:
        return "–"
    s = ms / 1000
    return f"{s:.0f}s" if s < 90 else f"{s / 60:.0f}m" if s < 5400 else f"{s / 3600:.1f}h"


def table(rows, cols, cls=""):
    """cols: list of (key, header, formatter, align)."""
    if not rows:
        return '<p class="empty">No rows.</p>'
    head = "".join(f'<th class="{a}">{esc(h)}</th>' for _, h, _, a in cols)
    body = "".join("<tr>" + "".join(f'<td class="{a}">{f(r.get(k)) if f else esc(r.get(k))}</td>'
                                    for k, _, f, a in cols) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def bars(rows, label, value, fmt, title):
    """Single-series horizontal bar chart, inline SVG: value at the tip, native tooltip, table view beside it."""
    rows = [r for r in rows if r.get(value)]
    if not rows:
        return ""
    top = max(r[value] for r in rows)
    lw, bw, rh = 210, 360, 26
    h = rh * len(rows) + 8
    out = [f'<figure><figcaption>{esc(title)}</figcaption><svg viewBox="0 0 {lw + bw + 90} {h}" role="img" aria-label="{esc(title)}">']
    for i, r in enumerate(rows):
        y = 4 + i * rh
        w = max(2, bw * r[value] / top)
        lab = str(r[label])
        short = lab if len(lab) <= 30 else lab[:29] + "…"
        out.append(f'<g class="bar"><title>{esc(lab)}: {esc(fmt(r[value]))}</title>'
                   f'<rect class="hit" x="0" y="{y}" width="{lw + bw + 90}" height="{rh}"/>'
                   f'<text x="{lw - 8}" y="{y + rh / 2 + 4}" text-anchor="end" class="lab">{esc(short)}</text>'
                   f'<path class="mark" d="M{lw},{y + 5}h{w - 4}a4,4 0 0 1 4,4v{rh - 18}a4,4 0 0 1 -4,4h{-(w - 4)}z"/>'
                   f'<text x="{lw + w + 6}" y="{y + rh / 2 + 4}" class="val">{esc(fmt(r[value]))}</text></g>')
    out.append("</svg></figure>")
    return "".join(out)


def tile(label, value, sub=""):
    return f'<div class="tile"><div class="tl">{esc(label)}</div><div class="tv">{esc(value)}</div><div class="ts">{esc(sub)}</div></div>'


def section(id_, title, intro, *parts):
    return f'<section id="{id_}"><h2>{esc(title)}</h2>' + (f'<p class="intro">{intro}</p>' if intro else "") + "".join(parts) + "</section>"


def show_cmd(v):
    return f'<code class="cmd">python -m runlens show {esc(v)}</code>' if v else "–"


def incident_list(con, limit=400):
    rows = q(con, f"""
        SELECT i.incident_id, i.session_id[:8] AS run, i.type, i.n, i.skill, i.role, i.key, i.context,
               l.category AS llm, l.fault, l.note, h.category AS human
        FROM incidents i
        LEFT JOIN v_labels l ON l.incident_id = i.incident_id AND l.source = 'llm'
        LEFT JOIN v_labels h ON h.incident_id = i.incident_id AND h.source = 'human'
        ORDER BY i.type, i.skill, i.ts LIMIT {limit}""")
    if not rows:
        return '<p class="empty">No incidents.</p>'
    out = ['<div class="incidents">']
    for r in rows:
        label = ""
        if r["llm"] or r["human"]:
            label = (f'<span class="chip">llm: {esc(r["llm"])} · {esc(r["fault"])}</span>' if r["llm"] else "") + \
                    (f'<span class="chip human">human: {esc(r["human"])}</span>' if r["human"] else "")
        out.append(
            f'<details data-type="{esc(r["type"])}" data-skill="{esc(r["skill"])}"><summary>'
            f'<span class="itype">{esc(r["type"])}</span> <span class="muted">×{r["n"]}</span> '
            f'<b>{esc(r["skill"] or "(none)")}</b> · {esc(r["role"])} · <span class="muted">{esc(r["run"])}</span> '
            f'{label}<div class="ikey">{esc(r["key"])}</div></summary>'
            + (f'<p class="note">{esc(r["note"])}</p>' if r["note"] else "")
            + f'<pre>{esc(r["context"])}</pre>{show_cmd(r["incident_id"])}</details>')
    out.append("</div>")
    return "".join(out)


def write_report(cfg, out=None, sessions=None):
    con = load(sessions)
    runs = q(con, "SELECT * FROM v_runs ORDER BY started")
    if not runs:
        raise SystemExit("no runs in the database: run `python -m runlens refresh` first")
    tot = q(con, """SELECT sum(cost_usd) AS cost, bool_or(cost_estimated) AS est, sum(active_ms) AS active,
                           sum(n_agents) AS agents, sum(tool_calls) AS tools, sum(tool_errors) AS errors,
                           sum(incidents) AS incidents, sum(idle_calls) AS idle FROM v_runs""")[0]
    skills = q(con, "SELECT * FROM v_skill ORDER BY cost_usd DESC NULLS LAST")
    roles = q(con, "SELECT * FROM v_role ORDER BY cost_usd DESC NULLS LAST")
    flow = q(con, "SELECT * FROM v_skill_flow ORDER BY transitions DESC")
    errs_class = q(con, "SELECT error_class, sum(errors) AS errors FROM v_tool_errors GROUP BY 1 ORDER BY 2 DESC")
    errs = q(con, "SELECT * FROM v_tool_errors ORDER BY errors DESC LIMIT 40")
    tools = q(con, "SELECT * FROM v_tools ORDER BY calls DESC")
    idle = q(con, "SELECT skill, sum(idle_turns) AS idle_turns, sum(idle_cost_usd) AS idle_cost_usd FROM v_idle GROUP BY 1 ORDER BY 3 DESC")
    repeats = q(con, """SELECT incident_id, session_id[:8] AS run, skill, role, n, key FROM incidents
                        WHERE type IN ('repeated_call', 'idle_loop') ORDER BY n DESC LIMIT 40""")
    markers = q(con, "SELECT * FROM v_markers ORDER BY marker, n DESC")
    inc_types = q(con, "SELECT type, count(*) AS incidents, sum(n) AS occurrences, count(DISTINCT session_id) AS runs FROM incidents GROUP BY 1 ORDER BY 2 DESC")
    inc_matrix = q(con, "SELECT * FROM v_incident_summary ORDER BY incidents DESC LIMIT 60")
    label_sum = q(con, """SELECT source, category, count(*) AS incidents FROM v_labels l JOIN incidents USING (incident_id)
                          GROUP BY ALL ORDER BY source, incidents DESC""")
    faults = q(con, "SELECT fault, count(*) AS incidents FROM v_labels WHERE source = 'llm' GROUP BY 1 ORDER BY 2 DESC")
    versions = q(con, "SELECT * FROM v_skill_version_stats ORDER BY skill, cost_usd DESC")
    models = q(con, "SELECT * FROM v_model ORDER BY cost_usd DESC")
    slow = q(con, """SELECT tool_use_id, session_id[:8] AS run, tool, skill, duration_ms, input_summary FROM tool_calls
                     WHERE duration_ms IS NOT NULL AND tool NOT IN ('Agent', 'Task') ORDER BY duration_ms DESC LIMIT 15""")
    events = q(con, """SELECT kind, count(*) AS n, count(DISTINCT session_id) AS runs FROM events
                       WHERE kind NOT IN ('turn', 'human_prompt') GROUP BY 1 ORDER BY 2 DESC""")
    inc_html = incident_list(con)
    con.close()

    span = f"{runs[0]['started']:%Y-%m-%d} → {runs[-1]['ended']:%Y-%m-%d}"
    est_note = " · includes list-price estimates for runs still open" if tot["est"] else ""
    L, R, C, N = "l", "r", "c", "n"
    parts = [
        section("overview", "Overview", f"{len(runs)} run(s), {span}{est_note}.",
                '<div class="tiles">' + tile("Runs", len(runs)) + tile("Cost", usd(tot["cost"]), "estimated" if tot["est"] else "from cost-state")
                + tile("Active time", dur(tot["active"])) + tile("Subagents", num(tot["agents"]))
                + tile("Tool calls", num(tot["tools"])) + tile("Tool errors", num(tot["errors"]), pct((tot["errors"] or 0) / max(tot["tools"] or 1, 1)))
                + tile("Incidents", num(tot["incidents"])) + "</div>",
                table(runs, [("session_id", "Run", lambda v: esc(v[:8]), L), ("started", "Started", lambda v: f"{v:%Y-%m-%d %H:%M}", L),
                             ("cwd", "Repo", lambda v: esc((v or "").replace("\\", "/").rstrip("/").split("/")[-1]), L),
                             ("title", "Title", None, L), ("cost_usd", "Cost", usd, R), ("cost_estimated", "Est.", lambda v: "yes" if v else "", C),
                             ("active_ms", "Active", dur, R), ("n_agents", "Agents", num, R), ("tool_calls", "Tool calls", num, R),
                             ("error_rate", "Error rate", pct, R), ("idle_calls", "Idle", num, R), ("incidents", "Incidents", num, R),
                             ("bad_markers", "Bad markers", num, R)])),
        section("skills", "By skill", "Cost, work and trouble attributed to the skill each turn ran under.",
                bars(skills, "skill", "cost_usd", usd, "Cost by skill"),
                table(skills, [("skill", "Skill", None, N), ("runs", "Runs", num, R), ("api_calls", "API calls", num, R),
                               ("cost_usd", "Cost", usd, R), ("cost_pct", "Share", lambda v: "–" if v is None else f"{v}%", R),
                               ("tool_calls", "Tool calls", num, R), ("tool_errors", "Errors", num, R), ("error_rate", "Error rate", pct, R),
                               ("idle_calls", "Idle", num, R), ("tool_ms", "Tool time", dur, R), ("incidents", "Incidents", num, R),
                               ("bad_markers", "Bad markers", num, R)]),
                "<h3>Skill hand-offs in the main session</h3>",
                table(flow, [("from_skill", "From", None, N), ("to_skill", "To", None, N), ("transitions", "Transitions", num, R), ("runs", "Runs", num, R)])),
        section("roles", "By agent role", "Subagents grouped by agent type and by what they were asked to do (numbers in the description folded to #).",
                bars(roles[:15], "role", "cost_usd", usd, "Cost by role (top 15)"),
                table(roles, [("agent_type", "Type", None, N), ("role", "Role", None, L), ("agents", "Agents", num, R), ("runs", "Runs", num, R),
                              ("cost_usd", "Cost", usd, R), ("avg_cost_usd", "Avg cost", usd, R), ("avg_seconds", "Avg time", lambda v: dur(v * 1000 if v else None), R),
                              ("avg_tool_calls", "Avg tools", lambda v: num(v, 1), R), ("error_rate", "Error rate", pct, R),
                              ("not_completed", "Not completed", num, R), ("peak_context", "Peak context", num, R),
                              ("compactions", "Compactions", num, R), ("models", "Models", None, L)])),
        section("errors", "Tool errors", "Failing tool calls, grouped by a generic error class read from the tool output.",
                bars(errs_class, "error_class", "errors", num, "Errors by class"),
                table(errs, [("tool", "Tool", None, N), ("error_class", "Class", None, N), ("skill", "Skill", None, N), ("errors", "Errors", num, R),
                             ("example", "Example output", lambda v: f'<span class="mono">{esc(v)}</span>', L),
                             ("example_tool_use_id", "Trace", show_cmd, L)], "wide"),
                "<h3>All tools</h3>",
                table(tools, [("tool", "Tool", None, N), ("calls", "Calls", num, R), ("errors", "Errors", num, R), ("error_rate", "Error rate", pct, R),
                              ("median_ms", "Median", dur, R), ("p95_ms", "p95", dur, R), ("total_ms", "Total", dur, R)])),
        section("waste", "Repetition and waiting", "Identical tool calls repeated within one agent, and turns spent only waiting or printing.",
                table(idle, [("skill", "Skill", None, N), ("idle_turns", "Idle turns", num, R), ("idle_cost_usd", "Cost of idle turns", usd, R)]),
                table(repeats, [("run", "Run", None, N), ("skill", "Skill", None, N), ("role", "Role", None, L), ("n", "Times", num, R),
                                ("key", "Call", lambda v: f'<span class="mono">{esc(v)}</span>', L), ("incident_id", "Trace", show_cmd, L)], "wide")),
        section("markers", "Flow markers", "Matches of the markers declared in config.toml; bad values become incidents.",
                table(markers, [("marker", "Marker", None, N), ("value", "Value", None, L), ("bad", "Bad", lambda v: "yes" if v else "", C),
                                ("skill", "Skill", None, N), ("n", "Matches", num, R), ("runs", "Runs", num, R)])),
        section("incidents", "Incidents", "Moments worth reading. Each one carries the timeline that led to it.",
                bars(inc_types, "type", "incidents", num, "Incidents by type"),
                table(inc_types, [("type", "Type", None, N), ("incidents", "Incidents", num, R), ("occurrences", "Occurrences", num, R), ("runs", "Runs", num, R)]),
                '<p class="muted">' + " · ".join(f"<b>{esc(k)}</b>: {esc(v)}" for k, v in TYPES.items()) + "</p>",
                "<h3>By type, skill and role</h3>",
                table(inc_matrix, [("type", "Type", None, N), ("skill", "Skill", None, N), ("role", "Role", None, L), ("incidents", "Incidents", num, R),
                                   ("occurrences", "Occurrences", num, R), ("runs", "Runs", num, R)]),
                '<h3>Every incident</h3><div class="filters"><input id="f" placeholder="Filter by type, skill, role or text" aria-label="Filter incidents"></div>',
                inc_html),
        section("labels", "Failure categories", "Labels from <code>runlens classify</code> (llm) and from human review (<code>runlens labels</code>). "
                "LLM labels are a first pass; check <code>runlens agreement</code> before trusting a category.",
                bars([r for r in label_sum if r["source"] == "llm"], "category", "incidents", num, "LLM labels by category"),
                bars(faults, "fault", "incidents", num, "LLM labels by where a fix would go"),
                table(label_sum, [("source", "Source", None, N), ("category", "Category", None, L), ("incidents", "Incidents", num, R)])),
        section("versions", "Skill versions", "Each version is a hash of the skill text as it was loaded in the run; compare a skill's rows to see a change's effect.",
                table(versions, [("skill", "Skill", None, N), ("content_hash", "Version", None, L), ("runs", "Runs", num, R), ("cost_usd", "Cost", usd, R),
                                 ("cost_per_run", "Cost/run", usd, R), ("tool_calls", "Tool calls", num, R), ("error_rate", "Error rate", pct, R),
                                 ("idle_calls", "Idle", num, R), ("incidents", "Incidents", num, R), ("bad_markers", "Bad markers", num, R)])),
        section("models", "Models, latency and context", "",
                table(models, [("model", "Model", None, N), ("api_calls", "API calls", num, R), ("cost_usd", "Cost", usd, R),
                               ("output_tokens", "Output tokens", num, R), ("thinking_tokens", "Thinking tokens", num, R), ("cache_hit", "Cache hit", pct, R)]),
                "<h3>Slowest tool calls</h3>",
                table(slow, [("run", "Run", None, N), ("tool", "Tool", None, N), ("skill", "Skill", None, N), ("duration_ms", "Duration", dur, R),
                             ("input_summary", "Call", lambda v: f'<span class="mono">{esc(v)}</span>', L), ("tool_use_id", "Trace", show_cmd, L)], "wide"),
                "<h3>Other events</h3>",
                table(events, [("kind", "Event", None, N), ("n", "Count", num, R), ("runs", "Runs", num, R)])),
    ]
    nav = "".join(f'<a href="#{i}">{t}</a>' for i, t in [("overview", "Overview"), ("skills", "Skills"), ("roles", "Roles"), ("errors", "Errors"),
                                                         ("waste", "Waste"), ("markers", "Markers"), ("incidents", "Incidents"),
                                                         ("labels", "Categories"), ("versions", "Versions"), ("models", "Models")])
    page = TEMPLATE.replace("{{NAV}}", nav).replace("{{BODY}}", "".join(parts)).replace(
        "{{META}}", esc(f"generated {datetime.now():%Y-%m-%d %H:%M} from {config.DB}"))
    path = Path(out) if out else config.HOME / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Run Diagnosis</title>
<style>
:root{color-scheme:light;--bg:#fcfcfb;--surface:#ffffff;--border:#e6e5e0;--grid:#ecebe6;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--series:#2a78d6;--series-hover:#1c5cab;--chip:#eef4fc;--code:#f4f3ef;--critical:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#141413;--surface:#1a1a19;--border:#33332f;--grid:#2a2a27;
--text:#ffffff;--text2:#c3c2b7;--muted:#8f8e86;--series:#3987e5;--series-hover:#6da7ec;--chip:#1d2a3a;--code:#222220}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#141413;--surface:#1a1a19;--border:#33332f;--grid:#2a2a27;--text:#ffffff;--text2:#c3c2b7;
--muted:#8f8e86;--series:#3987e5;--series-hover:#6da7ec;--chip:#1d2a3a;--code:#222220}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--border);padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0}nav{display:flex;gap:12px;flex-wrap:wrap}nav a{color:var(--text2);text-decoration:none;font-size:13px}nav a:hover{color:var(--text)}
main{max-width:1200px;margin:0 auto;padding:8px 16px 64px}section{margin:28px 0}h2{font-size:18px;margin:0 0 4px}h3{font-size:14px;margin:20px 0 6px;color:var(--text2)}
.intro,.muted,.empty{color:var(--muted)}.meta{color:var(--muted);font-size:12px;margin-left:auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;margin:12px 0}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px}.tl{color:var(--text2);font-size:12px}.tv{font-size:22px;font-weight:600}.ts{color:var(--muted);font-size:12px;min-height:1em}
.tw{overflow-x:auto;margin:8px 0;border:1px solid var(--border);border-radius:8px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:6px 10px;border-bottom:1px solid var(--grid);vertical-align:top}
th{position:sticky;top:0;background:var(--surface);color:var(--text2);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
td.r,th.r{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td.c,th.c{text-align:center}th.l,td.l{text-align:left}td.n,th.n{text-align:left;white-space:nowrap}
table.wide td.l{max-width:520px;overflow-wrap:anywhere}.mono,code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
code.cmd{background:var(--code);padding:1px 6px;border-radius:4px;white-space:nowrap;user-select:all}
figure{margin:12px 0;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px}figcaption{color:var(--text2);font-size:13px;margin-bottom:4px}
svg{width:100%;max-width:680px;height:auto;display:block}.lab{fill:var(--text2);font-size:12px}.val{fill:var(--text);font-size:12px;font-variant-numeric:tabular-nums}
.mark{fill:var(--series)}.hit{fill:transparent}.bar:hover .mark{fill:var(--series-hover)}.bar:hover .lab{fill:var(--text)}
.filters input{width:100%;max-width:420px;padding:7px 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font:inherit}
.incidents details{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin:6px 0;padding:6px 10px}
.incidents summary{cursor:pointer}.itype{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:var(--code);padding:1px 6px;border-radius:4px}
.ikey{color:var(--text2);font-family:ui-monospace,Consolas,monospace;font-size:12px;overflow-wrap:anywhere;margin-top:2px}
.chip{display:inline-block;background:var(--chip);border-radius:10px;padding:0 8px;font-size:12px;margin-left:6px}.chip.human{outline:1px solid var(--series)}
.note{margin:6px 0;color:var(--text2)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--code);padding:8px;border-radius:6px;max-height:420px;overflow:auto}
@media (max-width:640px){.tv{font-size:18px}header{position:static}}
</style></head>
<body><header><h1>Run Diagnosis</h1><nav>{{NAV}}</nav><span class="meta">{{META}}</span></header>
<main>{{BODY}}</main>
<script>
const f=document.getElementById('f');
if(f)f.addEventListener('input',()=>{const t=f.value.toLowerCase();document.querySelectorAll('.incidents details').forEach(d=>{d.style.display=d.textContent.toLowerCase().includes(t)?'':'none'})});
</script></body></html>"""
