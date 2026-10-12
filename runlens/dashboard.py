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

from . import bench, config, store

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


def render(model):
    page = (WEB / "template.html").read_text(encoding="utf-8")
    parts = {"CSS": (WEB / "app.css").read_text(encoding="utf-8"),
             "JS": (WEB / "app.js").read_text(encoding="utf-8"),
             "DATA": embed(model)}
    # One pass: text that is inserted is never searched for placeholders again.
    return PLACEHOLDER.sub(lambda m: parts[m.group(1)], page)


def write_dashboard(cfg, out=None):
    con = store.connect(read_only=True)
    try:
        model = bench.build(con, cfg.get("group", []))
    finally:
        con.close()
    path = Path(out) if out else config.HOME / "dashboard.html"
    path.write_text(render(model), encoding="utf-8")
    return path
