"""Write the benchmark dashboard: one static HTML file, built from the database.

The page is generated, not hosted. Its data is embedded as JSON inside the file, and
its script and style are inlined, so it opens offline from any folder. The JSON is
escaped for a <script> element: nothing from a transcript can close the element or
start a tag. The page draws every value as text, never as markup.
"""
import json
import math
import re
from datetime import datetime
from pathlib import Path

from . import bench, config, explorer, store
from .fs import write_atomic

WEB = config.PACKAGE / "web"


def clean(o):
    """JSON-safe: datetimes as ISO text, non-finite numbers as null, floats rounded for size."""
    if isinstance(o, datetime):
        return o.isoformat(timespec="seconds")
    if isinstance(o, float):
        return round(o, 6) if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [clean(v) for v in o]
    return o


def embed(obj):
    """JSON that is safe inside <script>: '<', '>', '&' and the line separators are written as escapes."""
    text = json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for raw, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(raw, esc)
    return text


PLACEHOLDER = re.compile(r"\{\{(CSS|JS|DATA)\}\}")

# The script is split into small modules under web/js. They are joined in this order inside one function,
# so a name declared by an earlier module is visible to the later ones and nothing leaks into the page.
# core: data, preferences, formatting, elements, URL state, colour, meaning, filters, scoring; charts: the toolkit;
# ui: the filter bar, score panel and views menu; pages; app last.
MODULES = (
    "core/boot.js", "core/data.js", "core/prefs.js", "core/format.js", "core/dom.js", "core/state.js",
    "core/colour.js", "core/meaning.js", "core/filters.js", "core/scoring.js", "core/table.js",
    "charts/tooltip.js", "charts/frame.js", "charts/kit.js", "charts/kit2.js",
    "ui/filterbar.js", "ui/scorepanel.js", "ui/views.js",
    "pages/skills.js", "pages/unit.js", "pages/compare.js", "pages/runs.js", "pages/diagnostics.js", "pages/health.js",
    "pages/method.js",
    "app.js",
)


def script():
    """Every module, in order, inside one strict-mode function. No module may close the <script> element."""
    parts = []
    for name in MODULES:
        text = (WEB / "js" / name).read_text(encoding="utf-8")
        if re.search(r"</script|<!--", text, re.I):
            raise ValueError(f"web/js/{name} contains text that would end its <script> element")
        parts.append(f"/* ---- {name} ---- */\n{text.rstrip()}\n")
    return '(function () {\n"use strict";\n' + "\n".join(parts) + "})();\n"


def render(model):
    page = (WEB / "template.html").read_text(encoding="utf-8")
    parts = {"CSS": (WEB / "app.css").read_text(encoding="utf-8"),
             "JS": script(),
             "DATA": embed(model)}
    # One pass: text that is inserted is never searched for placeholders again.
    return PLACEHOLDER.sub(lambda m: parts[m.group(1)], page)


def views(cfg):
    """Views declared in config.toml as [[dashboard.view]] (name, hash): shared starting points for the page."""
    out = []
    for v in (cfg.get("dashboard") or {}).get("view") or []:
        if not isinstance(v, dict):
            continue
        name, link = str(v.get("name") or "").strip(), str(v.get("hash") or "").strip()
        if not link.startswith("#"):
            link = "#" + link if link.startswith("/") else "#/" + link
        if name and len(name) <= 80 and len(link) <= 2000:
            out.append({"name": name, "hash": link})
    return out


def model_of(con, cfg):
    """The page's data: the benchmark model (bench.build, with outcome and weights from config), the per-run facts
    the page filters and explores (explorer.build), and the views declared in config.toml."""
    model = bench.build(con, cfg)
    model["explore"] = explorer.build(con, cfg)
    model["views"] = views(cfg)
    return model


def write_dashboard(cfg, out=None):
    con = store.connect(read_only=True)
    try:
        model = model_of(con, cfg or {})
    finally:
        con.close()
    path = Path(out) if out else config.HOME / "dashboard.html"
    write_atomic(path, render(model))
    return path
