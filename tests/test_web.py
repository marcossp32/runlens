"""Tests for the dashboard page: how its script is assembled, what it may contain, and that every page renders.

The rendering tests open the generated file in a headless Chromium (Chrome, Chromium or Edge) and are skipped
when none is installed; RUNLENS_BROWSER can point at one. The syntax test needs node and is skipped without it.
The recompute tests build the made-up demo history (scripts/make_demo.py) in a separate process, so they never
touch the database other tests use, and check that the page works a score out exactly as bench.py does.

Run: python -m unittest tests.test_web -v
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="runlens-web-"))
os.environ.setdefault("RUNLENS_HOME", str(TMP / "home"))

from runlens import bench, dashboard, explorer  # noqa: E402

WEB = dashboard.WEB
ROOT = Path(__file__).resolve().parent.parent
METRICS = [{**{k: v for k, v in m.items() if k != "kinds"}, "kinds": list(m["kinds"])} for m in bench.MEASURES if m["key"] != "outcome"]
EVIL = "</script><b>x</b>"
T0 = 1_790_000_000  # 2026-09-21, epoch seconds


def metrics(ratio, n):
    return {m["key"]: {"value": 1.0 / ratio, "counted": 1.0 / ratio, "n": n, "ref": 1.0, "ratio": ratio, "weight": m["weight"]}
            for m in METRICS if "skill" in m["kinds"]}


def run(day, version, cost, session=None, task=EVIL):
    """A run row as bench.run_row writes it: the display fields and every measure's num and den."""
    return {"started": f"2026-10-0{day}T10:00:00+02:00", "session": session or f"s{day}{version}aaaa"[:8], "task": task, "version": version,
            "repo": "r", "inv": 2, "inv_cost": 2, "invocations": 2, "cost": cost, "seconds": 600.0, "lc": 2 * (cost / 2 + 0.01), "ls": 2 * 6.0,
            "calls": 10, "call_errors": 1, "idle": 0, "turns": 5, "api_errors": 0, "incidents": 1, "interventions": 0, "bad": 0, "lines": 12}


def version(label, key, day0, day1, score, ci, n, uid="skill:flow"):
    return {"id": uid, "vid": f"{uid}@{key}", "label": label, "key": key, "parts": [{"skill": uid.split(":")[1], "hash": key}], "recorded": True,
            "first_seen": f"2026-10-0{day0}T10:00:00+02:00", "last_seen": f"2026-10-0{day1}T10:00:00+02:00", "runs": n, "invocations": 2 * n,
            "low_sample": n < 5, "score": score, "ci": ci, "metrics": metrics(score / 100, n), "outcome": None,
            "kpi": {"spend": 3.0, "cost_per_success": None, "cost_per_kloc": None, "lines": 30, "invocations": 2 * n},
            "changes": [], "verdict": None, "direction": None, "vs": None, "difference": None, "confounders": [], "delta": None, "overlap": None}


def unit(uid, kind, name, runs, score, ci, current, weights=True):
    keys = [m["key"] for m in METRICS if kind in m["kinds"]]
    return {"id": uid, "kind": kind, "name": name, "members": [], "runs": runs, "invocations": 2 * runs, "versions": 1, "current": current,
            "score": score, "ci": ci, "verdict": None, "direction": None, "vs": None, "difference": None, "confounders": [], "delta": None,
            "low_sample": runs < 5, "outcome": None, "first_seen": "2026-10-01T10:00:00+02:00", "last_seen": "2026-10-06T10:00:00+02:00",
            "kpi": {"cost": 1.2, "seconds": 600.0, "error_rate": 0.1, "incidents": 10.0, "interventions": 0.0, "spend": 7.0, "invocations": 2 * runs},
            "baseline": {k: 0.1 for k in keys}, "pseudo": {k: 2.0 for k in keys},
            "weights": {k: float(bench.MEASURE[k]["weight"]) for k in keys} if weights else {}}


def explore():
    """Per-run facts in the shape explorer.build writes, with hostile titles to prove they stay text."""
    t = explorer.table
    runs = [[f"s{d}{'v1' if d <= 3 else 'v2'}aaaa"[:8], f"session-{d}", T0 + d * 86400, 3600, "r" if d % 2 else "other", "main", "2.1.0" if d < 4 else "2.2.0",
             EVIL, "complete" if d < 6 else "open", 0, "session_end", 2.0 * d, int(d == 6), 0, 3_600_000, 1_000_000, 500_000, 1, d, 10, 2,
             ["https://example.com/pr/1"] if d == 2 else [], [], 2, 0, "cli", ["claude-opus-5-5"], ["high"], ["flow"]] for d in range(1, 7)]
    ids = [r[0] for r in runs]
    return {
        "duration_edges": explorer.DURATION_EDGES,
        "runs": t(("run", "sid", "started", "ended", "repo", "branch", "cc", "title", "status", "stub", "ended_by", "cost", "estimated",
                   "unknown_cost", "active_ms", "api_ms", "tool_ms", "prompts", "agents", "added", "removed", "prs", "unpriced", "parser",
                   "bad_lines", "entry", "models", "efforts", "skills"), runs),
        "calls": t(("run", "model", "effort", "skill", "calls", "cost", "input", "cw5", "cw1", "cread", "output", "thinking", "think_ms", "errors", "limits", "unpriced"),
                   [[r, "claude-opus-5-5", "high", "flow", 30, 2.0, 1000, 200, 100, 9000, 500, 50, 900, 0, 1, 0] for r in ids], codes=("run", "model", "effort", "skill")),
        "days": t(("run", "day", "model", "skill", "cost", "calls"), [[r, f"2026-09-2{i + 2}", "claude-opus-5-5", "flow", 2.0, 30] for i, r in enumerate(ids)]),
        "tools": t(("run", "tool", "skill", "calls", "errors", "denied", "ms"), [[r, "Read", "flow", 40, 2, 1, 5000] for r in ids]),
        "durations": t(("run", "tool", "bins"), [[r, "Read", [0, 1, 5, 10, 8, 4, 2, 1, 0, 0, 0, 0]] for r in ids]),
        "errors": t(("run", "tool", "class", "skill", "n"), [[r, "Read", "not_found", "flow", 2] for r in ids]),
        "agents": t(("run", "i", "parent", "type", "role", "model", "t0", "t1", "cost", "status", "depth", "bg", "tools", "errors", "stopped", "peak", "compactions", "stop"),
                    [x for r in ids for x in ([r, 0, None, "main", "main", None, 0, 3600, 1.0, None, 0, 0, None, None, 0, None, None, None],
                                                [r, 1, 0, "Explore", EVIL, "claude-sonnet-5-5", 60, 600, 0.5, "completed", 1, 0, 10, 1, 0, 50000, 0, "end_turn"],
                                                [r, 2, 1, "Explore", "scan", "claude-haiku-5-5", 120, None, 0.1, "running", 2, 1, 3, 0, 0, 20000, 0, None])]),
        "incidents": t(("run", "t", "type", "skill", "agent", "role", "id", "detail", "policy", "n", "label"),
                       [[r, 300, "idle_loop", "flow", 0, "main", f"inc{i}", EVIL, 0, 3, "tool_misuse"] for i, r in enumerate(ids)]),
        "markers": t(("run", "t", "marker", "value", "bad", "skill"), [[r, 900, "step_check", "PASS" if i % 2 else "FAIL", int(not i % 2), "flow"] for i, r in enumerate(ids)]),
        "events": t(("run", "t", "kind", "agent", "value", "source"), [[r, 30, "human_prompt", 0, None, "typed"] for r in ids]),
        "stops": t(("run", "model", "stop", "n"), [[r, "claude-opus-5-5", "end_turn", 10] for r in ids]),
        "apierr": t(("run", "model", "kind", "status", "limit", "n"), [[ids[0], "claude-opus-5-5", "rate_limit", 429, 1, 1]]),
        "compactions": t(("run", "t", "agent", "trigger", "pre", "post", "ms", "skill"), [[ids[1], 1200, 0, "auto", 170000, 20000, 30000, "flow"]]),
        "segments": t(("run", "skill", "t0", "t1", "cost", "calls"), [x for r in ids for x in ([r, "flow", 10, 1800, 1.5, 20], [r, "once_only", 1900, 3500, 0.5, 8])]),
        "flow": t(("run", "source", "target", "n"), [[r, "flow", "once_only", 1] for r in ids]),
        "curves": {r: [[0, 0.0], [1800, 1.0], [3500, 2.0]] for r in ids},
        "toolerr": t(("run", "t", "agent", "tool", "class", "id"), [[r, 700, 1, "Read", "not_found", f"toolu_{i}"] for i, r in enumerate(ids)]),
        "tokens": t(("run", "model", "type", "tokens", "cost"), [[r, "claude-opus-5-5", ty, 1000, 0.4] for r in ids for ty in explorer.TOKEN_TYPES]),
        "health": {"summary": {"runs": 6, "open_runs": 1, "stub_runs": 0, "estimated_cost_runs": 1, "unknown_model_cost_runs": 0,
                               "unpriced_models": ["claude-new-9"], "runs_failed_to_ingest": 1, "min_parser_version": 2, "parser_version": "2",
                               "last_ingest": "2026-10-07T09:00:00+02:00", "unreadable_lines": 0, "output_token_coverage": 0.16},
                   "ingest_errors": [{"run": "deadbeef", "sid": "deadbeef-1", "path": EVIL, "stage": "parse", "error": EVIL, "detail": EVIL, "failed_at": "2026-10-07T09:00:00"}],
                   "coverage": [[r, 100, 600, 2.0] for r in ids], "pending": [], "pending_count": 0, "hook_errors": [EVIL]},
    }


def model():
    """A small model in the shape dashboard.model_of returns, with hostile text to prove nothing runs as markup."""
    units = [unit("skill:flow", "skill", "flow", 6, 112.0, [101.0, 125.0], "v2"),
             unit("skill:once_only", "skill", "once_only", 1, 90.0, None, "v1"),
             unit("agent:Explore|scan", "agent", "Explore · scan", 2, None, None, None)]
    units[0].update(versions=2, verdict="no clear change", direction="no clear change", vs="v1", delta=9.0,
                    difference={"score": 109.0, "ci": [95.0, 125.0], "measures": {}, "outcome": None})
    v2 = version("v2", "b2", 4, 6, 112.0, [101.0, 125.0], 3)
    v2.update(verdict="no clear change", direction="no clear change", vs="v1", delta=9.0, difference=units[0]["difference"])
    versions = {"skill:flow": [version("v1", "a1", 1, 3, 103.0, [92.0, 115.0], 3), v2],
                "skill:once_only": [version("v1", "c3", 2, 2, 90.0, None, 1, uid="skill:once_only")]}
    pairs = {"skill:flow": [{"a": "v1", "b": "v2", "vs_previous": True, "runs_a": 3, "runs_b": 3, "invocations_a": 6, "invocations_b": 6,
                             "verdict": "not enough runs", "direction": None, "confounders": ["Claude Code 2.1 → 2.2"],
                             "difference": {"score": 109.0, "ci": None, "outcome": None,
                                            "measures": {"cost": {"a": 1.0, "b": 0.8, "effect": 1.25, "ci": None, "weight": 2}}}}]}
    ex = explore()
    sid = [r[0] for r in ex["runs"]["r"]]
    runs = {"skill:flow": [run(d, "v1" if d <= 3 else "v2", 1.0 + d / 10, session=sid[d - 1]) for d in range(1, 7)],
            "skill:once_only": [run(2, "v1", 3.0, session=sid[1])], "agent:Explore|scan": [run(3, "all", 0.4, session=sid[2]), run(4, "all", 0.6, session=sid[3])]}
    return {
        "generated": "2026-10-07T09:00+02:00", "texts": True,
        "window": {"first": "2026-10-01T10:00:00+02:00", "last": "2026-10-06T10:00:00+02:00", "runs": 6, "excluded": {"open": 0}},
        "population": {"runs": 6, "open": 0, "stub": 0, "rule": "status = 'complete' AND NOT is_stub"},
        "method": {"metrics": METRICS, "shrink": 2, "max_ratio": 2.0, "floor": 0.5, "turn_cap": 600, "resamples": 500, "min_runs": 5,
                   "confidence": 0.95, "mix_shift": 0.3, "cc_version": "patch", "outcomes": [], "verdicts": list(bench.VERDICTS)},
        "units": units, "versions": versions, "pairs": pairs, "runs": runs,
        "explore": ex, "views": [{"name": EVIL, "hash": "#/runs"}],
    }


def visible(dom):
    """The text a reader sees: the DOM without its scripts, styles and tags."""
    return re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style)\b.*?</\1>", " ", dom)).replace("&nbsp;", " ")


def wording_model():
    """The model with a PR outcome on one skill, a check outcome on another, and a confounded group whose range starts at 100.2."""
    m = copy.deepcopy(model())
    out = next(x for x in bench.MEASURES if x["key"] == "outcome")
    m["method"]["metrics"] = [{**{k: v for k, v in out.items() if k != "kinds"}, "kinds": list(out["kinds"])}] + m["method"]["metrics"]
    m["method"]["outcomes"] = [{"name": "PR opened", "kind": "pr", "marker": None, "skills": ["flow"], "success": [], "failure": []},
                               {"name": "step_check first-pass rate", "kind": "marker", "marker": "step_check", "skills": ["once_only"], "success": ["PASS"], "failure": []}]
    flow, once = m["units"][0], m["units"][1]
    for u, name, rate in ((flow, "PR opened", 0.6), (once, "step_check first-pass rate", 0.8)):
        u["outcome"] = {"measure": name, "value": rate, "n": 4}
        u["kpi"]["outcome"] = rate
        u["baseline"]["outcome"], u["pseudo"]["outcome"], u["weights"]["outcome"] = 0.9, 2.0, 3.0
    for r in m["runs"]["skill:flow"] + m["runs"]["skill:once_only"]:
        r.update(on=1, os=1, oe=1)
    # the latest flow version did far worse than usual on the rate: its ratio sits at the cap (2.0)
    m["versions"]["skill:flow"][-1]["metrics"]["outcome"] = {"value": 0.6, "counted": 0.6, "n": 6, "ref": 0.9, "ratio": 2.0, "weight": 3}
    group = unit("group:release-flow", "group", "release-flow", 6, 130.0, [100.2, 174.0], "g1", weights=False)
    group.update(members=["skill:flow"], verdict="confounded", direction="better", vs="g0", confounders=["Claude Code 2.1 → 2.2"], delta=30.0)
    m["units"].append(group)
    g1 = version("g1", "g1", 4, 6, 130.0, [100.2, 174.0], 6, uid="group:release-flow")
    g1.update(verdict="confounded", direction="better", vs="g0", confounders=["Claude Code 2.1 → 2.2"], delta=30.0)
    m["versions"]["group:release-flow"] = [version("g0", "g0", 1, 3, 100.0, [90.0, 110.0], 6, uid="group:release-flow"), g1]
    m["runs"]["group:release-flow"] = [run(d, "g0" if d <= 3 else "g1", 1.0, session=f"g{d}aaaaaa") for d in range(1, 7)]
    return m


def empty_model():
    m = model()
    m.update(units=[], versions={}, pairs={}, runs={}, explore={}, views=[],
             window={"first": None, "last": None, "runs": 0, "excluded": {}})
    return m


def find_browser():
    names = [os.environ.get("RUNLENS_BROWSER"), "chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge"]
    for n in filter(None, names):
        path = shutil.which(n) or (n if os.path.isfile(n) else None)
        if path:
            return path
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if os.path.isfile(p):
            return p
    return None


def dump(path, route, budget=5000, until=None, tries=4):
    """The DOM of the page at a route, after its scripts ran, in a fresh headless browser profile.

    The virtual-time budget runs timers, not frames: on a loaded machine Chrome can spend it and dump before it
    paints once, so nothing that waits on a frame (ResizeObserver, IntersectionObserver, requestAnimationFrame)
    has run, and no budget is long enough to prevent it. A test that needs a frame passes `until`, a regex the
    DOM must match, and the page is dumped again in a fresh browser, up to `tries` times, until it does."""
    dom = ""
    hung = False
    for _ in range(tries):
        prof = tempfile.mkdtemp(prefix="runlens-browser-", dir=TMP)
        cmd = [find_browser(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={prof}",
               f"--virtual-time-budget={budget}", "--window-size=1280,900", "--dump-dom", path.as_uri() + route]
        try:
            dom = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
        except subprocess.TimeoutExpired:
            if hung:  # headless Chrome now and then hangs on a CI runner (seen on macOS): one retry
                raise
            hung = True
            continue
        if until is None or re.search(until, dom):
            break
    return dom


class Assembly(unittest.TestCase):
    def test_every_module_is_listed_once_and_exists(self):
        on_disk = sorted(p.relative_to(WEB / "js").as_posix() for p in (WEB / "js").rglob("*.js"))
        self.assertEqual(sorted(dashboard.MODULES), on_disk, "a module on disk is not assembled, or a listed one is missing")
        self.assertEqual(len(set(dashboard.MODULES)), len(dashboard.MODULES))

    def test_module_order(self):
        mods = list(dashboard.MODULES)
        self.assertEqual(mods[0], "core/boot.js")  # counts errors from everything after it
        self.assertEqual(mods[-1], "app.js")  # starts the router once every page exists
        kinds = [m.split("/")[0] if "/" in m else "app" for m in mods]
        rank = {"core": 0, "charts": 1, "ui": 2, "pages": 3, "app": 4}
        self.assertEqual(kinds, sorted(kinds, key=rank.get), "core, then charts, then ui, then pages, then app")
        for a, b in (("core/data.js", "core/colour.js"), ("core/prefs.js", "core/format.js"), ("charts/frame.js", "charts/kit.js"),
                     ("charts/kit.js", "charts/kit2.js"), ("core/meaning.js", "core/scoring.js"), ("core/filters.js", "core/scoring.js")):
            self.assertLess(mods.index(a), mods.index(b))

    def test_script_is_one_strict_function(self):
        js = dashboard.script()
        self.assertTrue(js.startswith('(function () {\n"use strict";'))
        self.assertTrue(js.rstrip().endswith("})();"))
        self.assertNotRegex(js, r"(?i)</script|<!--")

    def test_a_module_that_could_close_its_script_is_refused(self):
        bad = TMP / "web"
        shutil.copytree(WEB, bad, dirs_exist_ok=True)
        (bad / "js" / "app.js").write_text('const x = "</script>";\n', encoding="utf-8")
        with mock.patch.object(dashboard, "WEB", bad):
            with self.assertRaises(ValueError):
                dashboard.script()

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_assembled_script_parses(self):
        path = TMP / "assembled.js"
        path.write_text(dashboard.script(), encoding="utf-8")
        out = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


class Model(unittest.TestCase):
    def test_views_from_config(self):
        cfg = {"dashboard": {"view": [{"name": "Last week", "hash": "#/?range=7d"}, {"name": "Runs", "hash": "/runs"},
                                      {"name": "", "hash": "#/"}, {"hash": "#/x"}, "not a table"]}}
        self.assertEqual(dashboard.views(cfg), [{"name": "Last week", "hash": "#/?range=7d"}, {"name": "Runs", "hash": "#/runs"}])
        self.assertEqual(dashboard.views({}), [])

    def test_tables_code_repeated_values(self):
        t = explorer.table(("a", "b"), [["x", 1], ["y", 2], ["x", 3]], codes=("a",))
        self.assertEqual(t["d"]["a"], ["x", "y"])
        self.assertEqual([r[0] for r in t["r"]], [0, 1, 0])

    def test_duration_bins(self):
        self.assertEqual(explorer.duration_bin(5), 0)
        self.assertEqual(explorer.duration_bin(10), 1)
        self.assertEqual(explorer.duration_bin(10 ** 7), len(explorer.DURATION_EDGES))


class Page(unittest.TestCase):
    def setUp(self):
        self.page = dashboard.render(model())

    def test_self_contained(self):
        self.assertNotIn("{{", self.page)
        self.assertEqual(self.page.count("</script>"), 2)
        self.assertIsNone(re.search(r'(?i)(src|href)\s*=\s*["\']?(https?:)?//', self.page))
        self.assertIsNone(re.search(r"(?i)<link\b|@import|url\(\s*['\"]?https?:", self.page))
        js = dashboard.script()
        for needle in ("fetch(", "XMLHttpRequest", "import(", "sendBeacon", "WebSocket", "eval(", "innerHTML", "document.write"):
            self.assertNotIn(needle, js, needle)
        urls = set(re.findall(r"https?://[^\s\"'`)]+", js))
        self.assertLessEqual(urls, {"http://www.w3.org/2000/svg"}, "the script names no URL except the SVG namespace")

    def test_hostile_text_stays_data(self):
        blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', self.page, re.S).group(1)
        self.assertNotIn("<", blob)
        data = json.loads(blob)
        self.assertEqual(data["runs"]["skill:flow"][0]["task"], EVIL)

    def test_every_page_has_a_nav_link(self):
        for page in ("skills", "runs", "compare", "diagnostics", "health", "method"):
            self.assertIn(f'data-page="{page}"', self.page)


ROUTES = ["#/", "#/?tab=cost", "#/?tab=outcome", "#/?tab=measures", "#/?kind=roles", "#/?kind=groups", "#/?skills=flow&v=flow:v2&split=1",
          "#/unit/skill%3Aflow", "#/unit/skill%3Aflow?tab=drivers", "#/unit/skill%3Aflow?tab=runs", "#/unit/agent%3AExplore%7Cscan",
          "#/compare", "#/compare?a=skill%3Aflow&av=v1&b=skill%3Aonce_only&bv=v1",
          "#/runs", "#/runs?cal=runs", "#/run/s1v1aaaa", "#/run/s6v2aaaa?layout=packed", "#/health",
          "#/diagnostics", "#/diagnostics?tab=tools", "#/diagnostics?tab=models", "#/diagnostics?tab=models&sub=effort&me=calls",
          "#/diagnostics?tab=models&sub=tokens", "#/diagnostics?tab=models&sub=time", "#/diagnostics?tab=agents", "#/diagnostics?tab=flow",
          "#/method", "#/method?tab=example", "#/no/such/page",
          "#/?range=7d", "#/runs?repo=other&model=claude-opus-5-5", "#/?from=2026-09-22&to=2026-09-24&minn=1",
          "#/?base=prev&ci=80&w=cost:0", "#/?cols=1", "#/runs?cols=1&range=30d", "#/unit/skill%3Aflow?base=ver%3Av1&wu=flow%3Acost%3A3", "#/diagnostics?pop=all&effort=high"]


@unittest.skipUnless(find_browser(), "no headless Chromium (Chrome or Edge) found; set RUNLENS_BROWSER")
class Renders(unittest.TestCase):
    """Open the page in a real browser at each route: it must draw an article and record no script error."""

    def check(self, m, routes):
        path = TMP / f"page-{len(routes)}.html"
        path.write_text(dashboard.render(m), encoding="utf-8")
        for route in routes:
            with self.subTest(route=route):
                dom = dump(path, route)
                self.assertTrue('class="page"' in dom, f"no page rendered at {route}")
                errors = re.search(r'<html[^>]*\bdata-errors="(\d+)"[^>]*>', dom)
                last = re.search(r'data-last-error="([^"]*)"', dom)
                self.assertIsNone(errors, f"script error at {route}: {last.group(1) if last else ''}")
                self.assertFalse("<b>x</b>" in dom, "data reached the page as markup")

    def test_every_route_renders(self):
        self.check(model(), ROUTES)

    def test_empty_history_renders(self):
        self.check(empty_model(), ["#/", "#/runs", "#/compare", "#/diagnostics", "#/health", "#/method"])

    def test_charts_are_drawn_at_their_real_width(self):
        path = TMP / "width.html"
        path.write_text(dashboard.render(copy.deepcopy(model())), encoding="utf-8")
        drawn = r'<svg[^>]*class="[^"]*\bchart\b[^"]*"[^>]*>'
        dom = dump(path, "#/?tab=cost", until=drawn)
        self.assertTrue(re.findall(drawn, dom), "no chart was drawn")
        self.assertIsNone(re.search(r'<svg[^>]*viewBox="0 0 640 ', dom), "a chart still uses the old fixed 640-wide viewBox")

    def test_text_does_not_rank_skills_or_mislabel_outcomes(self):
        path = TMP / "wording.html"
        path.write_text(dashboard.render(wording_model()), encoding="utf-8")
        dom = dump(path, "#/?tab=cost")
        text = visible(dom)
        self.assertNotIn("On the Pareto frontier", text)
        self.assertNotIn("nothing is both cheaper and better", text)
        # two outcome definitions: one chart each, never one axis mixing a PR opened with a check passing
        self.assertIn("PR-opened rate against cost per invocation (PR opened)", text)
        self.assertIn("First-pass rate against cost per invocation (step_check first-pass rate)", text)
        dom = dump(path, "#/?tab=outcome")
        text = visible(dom)
        self.assertNotIn("most often", text)
        self.assertNotIn("passes first time", text)
        dom = dump(path, "#/unit/skill%3Aflow?tab=outcome")
        text = visible(dom)
        self.assertIn("opened a PR over", text)
        self.assertNotIn("passed first time", text)
        self.assertNotIn("first-pass rate", text.lower())

    def test_diagnostics_does_not_name_a_worst_skill_or_deny_error_streaks(self):
        path = TMP / "diag.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        text = visible(dump(path, "#/diagnostics"))
        self.assertNotIn("hits the most", text)
        self.assertNotIn("without a tool failing", text)

    def test_measures_heatmap_is_alphabetical_and_ratios_are_not_percentages(self):
        path = TMP / "heat.html"
        path.write_text(dashboard.render(wording_model()), encoding="utf-8")
        dom = dump(path, "#/?tab=measures", until=r'class="rowlabel"')  # the heatmap is drawn on a frame
        rows = re.findall(r'class="rowlabel"[^>]*>([^<]+)<', dom)
        self.assertTrue(rows, "the heatmap was not drawn")
        self.assertEqual(rows, sorted(rows, key=str.lower), "rows are not ordered by score")
        text = visible(dom)
        self.assertRegex(text, r"60 ?% vs 90 ?%")  # a rate shows its value against the reference
        self.assertNotRegex(text, r"[+−]\d+%")  # no signed percentage of a ratio
        self.assertIn("×", text)

    def test_confounded_version_is_not_called_clearly_above(self):
        path = TMP / "conf.html"
        path.write_text(dashboard.render(wording_model()), encoding="utf-8")
        for route in ("#/?kind=groups", "#/"):
            text = visible(dump(path, route))
            self.assertNotRegex(text, r"release-flow is clearly above", route)
        text = visible(dump(path, "#/?kind=groups"))
        self.assertIn("1 confounded", text)

    def test_filter_bar_counts_the_runs_left(self):
        path = TMP / "filters.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        dom = dump(path, "#/runs?repo=other")
        self.assertRegex(dom, r"<strong>2 of 5 runs</strong>")  # 5 finished runs, 2 of them in the repo "other"
        self.assertIn("Reset filters", dom)
        dom = dump(path, "#/runs?repo=other&pop=all")
        self.assertRegex(dom, r"<strong>3 of 6 runs</strong>")  # the open run counts once open runs are included

    def test_filter_bar_starts_collapsed_with_chips(self):
        path = TMP / "fbar.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        dom = dump(path, "#/")
        self.assertRegex(dom, r'<button[^>]*class="ftrigger"[^>]*aria-expanded="false"[^>]*aria-controls="filterpanel"')
        self.assertRegex(dom, r'<div class="frow" id="filterpanel" hidden="">')  # every control is still there, behind the button
        self.assertIn('data-dim="repo"', dom)
        self.assertNotIn('class="fchip"', dom)
        dom = dump(path, "#/runs?repo=other&range=7d")
        self.assertRegex(dom, r'class="ftrigger on"[^>]*>.*?<span class="fbadge"[^>]*>2</span>')  # two active filters
        self.assertEqual(len(re.findall(r'<button[^>]*class="fchip"[^>]*aria-label="Remove the filter', dom)), 2)

    def test_chart_cards_have_one_menu_and_a_closed_how_to_read(self):
        path = TMP / "cards.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        for route in ("#/", "#/?tab=cost", "#/diagnostics", "#/run/s1v1aaaa", "#/compare"):
            with self.subTest(route=route):
                dom = dump(path, route)
                cards = dom.count('class="card chart-card')
                self.assertGreater(cards, 0)
                self.assertEqual(dom.count('<details class="menu cardmenu">'), cards, "one ⋯ menu per chart card")
                self.assertGreaterEqual(dom.count('data-act="svg"'), cards)
                self.assertGreaterEqual(dom.count('<details class="howto-read">'), cards, "each card explains itself, closed")
                self.assertNotIn('<details class="howto-read" open', dom)
                self.assertIsNone(re.search(r'class="tool"[^>]*>(SVG|PNG)</button>', dom), "no loose export buttons left on a card")
                self.assertIn('class="card-takeaway"', dom)

    def test_pages_answer_first(self):
        path = TMP / "answer.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        for route in ("#/", "#/runs", "#/run/s1v1aaaa", "#/diagnostics", "#/diagnostics?tab=tools", "#/diagnostics?tab=agents"):
            with self.subTest(route=route):
                dom = dump(path, route)
                answer = dom.find('class="answer')
                self.assertGreater(answer, 0, f"no answer at {route}")
                first_chart = dom.find('class="card chart-card')
                self.assertTrue(first_chart < 0 or answer < first_chart, "the answer comes before the first chart")
                first_card = dom.find('class="card')
                self.assertLessEqual(len(re.findall(r'<div class="kpi[ "]', dom[:first_card if first_card > 0 else None])), 4, "at most four headline numbers")
        dom = dump(path, "#/")
        self.assertIn('class="term"', dom)  # jargon explained in place
        unit = dump(path, "#/unit/skill%3Aflow")
        self.assertIn('class="profile"', unit)
        self.assertIn('data-score="', unit)

    def test_wide_tables_keep_rare_columns_behind_a_toggle(self):
        path = TMP / "cols.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        dom = dump(path, "#/runs")
        self.assertRegex(dom, r'class="tool morecols"[^>]*aria-pressed="false"[^>]*>More columns \(\d+\)')
        self.assertNotIn(">Claude Code <", re.search(r"<thead>.*?</thead>", dom.split('aria-label="Runs"')[1], re.S).group(0))
        dom = dump(path, "#/runs?cols=1")
        self.assertRegex(dom, r'class="tool morecols"[^>]*aria-pressed="true"[^>]*>Fewer columns')
        self.assertIn(">Claude Code <", re.search(r"<thead>.*?</thead>", dom.split('aria-label="Runs"')[1], re.S).group(0))

    def test_health_badge_and_custom_score_are_marked(self):
        path = TMP / "marks.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        dom = dump(path, "#/?w=cost:0")
        self.assertRegex(dom, r'id="healthbadge"[^>]*>⚠ 3 data issues')  # a failed ingest, a model without a price, hook errors
        self.assertIn('class="ghost custom"', dom)  # the Score menu says the settings are not the defaults
        self.assertIn('class="settingsnote"', dom)
        plain = dump(path, "#/")
        self.assertNotIn('class="ghost custom"', plain)
        self.assertNotIn('class="settingsnote"', plain)

    # ---- issue #30: controls that never appeared, lost state or ignored the settings ----

    def test_runs_calendar_offers_its_colour_select(self):
        path = TMP / "cal.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        dom = dump(path, "#/runs?cal=runs")
        sel = re.search(r'<select aria-label="Colour the days by">(.*?)</select>', dom, re.S)
        self.assertIsNotNone(sel, "the calendar's colour select is not on the page")
        self.assertRegex(sel.group(1), r'<option value="runs" selected="">Runs</option>')

    def test_per_unit_weights_keep_their_decimals(self):
        path = TMP / "wu.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        dom = dump(path, "#/unit/skill%3Aflow?wu=flow%3Acost%3A1.5.seconds%3A0")
        self.assertRegex(dom, r'data-key="w-cost"[^>]*><output class="sp-val">×1[.,]5</output>')  # not ×1
        self.assertRegex(dom, r'data-key="w-seconds"[^>]*><output class="sp-val">×0</output>')

    def test_unknown_baseline_version_is_the_default(self):
        path = TMP / "base.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        self.assertNotIn('class="ghost custom"', dump(path, "#/?base=ver%3Av99"))
        self.assertIn('class="ghost custom"', dump(path, "#/?base=ver%3Av1"))

    def test_how_it_works_follows_the_score_settings_and_filters(self):
        path = TMP / "method.html"
        path.write_text(dashboard.render(model()), encoding="utf-8")
        text = visible(dump(path, "#/method?ci=80").split('<article class="page"')[1])  # the page, not the Score menu's choices
        self.assertIn("80%", text)
        self.assertNotIn("95%", text)
        unit = dump(path, "#/unit/skill%3Aflow?w=cost%3A5")
        score = float(re.search(r'class="summary[^"]*"[^>]*data-score="([\d.]+)"', unit).group(1))
        text = visible(dump(path, "#/method?tab=example&w=cost%3A5"))
        self.assertIn("Worked out with your weights", text)
        self.assertEqual(int(re.search(r"So the score is (\d+)", text).group(1)), round(score))  # the score the unit page shows
        text = visible(dump(path, "#/method?tab=example&repo=nowhere"))
        self.assertIn("nothing to walk through", text)
        self.assertNotIn("So the score is", text)


def build_demo():
    """The demo history and its model, built in child processes with their own RUNLENS_HOME."""
    home = TMP / "demo-home"
    if not (home / "model.json").exists():
        env = {**os.environ, "RUNLENS_HOME": str(home), "PYTHONIOENCODING": "utf-8"}
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo.py"), str(home)], check=True, env=env, cwd=ROOT, capture_output=True)
        code = ("import json; from runlens import config, dashboard, store; cfg = config.load(); con = store.connect(read_only=True); "
                f"m = dashboard.model_of(con, cfg); open(r'{home / 'model.json'}', 'w', encoding='utf-8').write(dashboard.embed(m))")
        subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=ROOT, capture_output=True)
    return json.loads((home / "model.json").read_text(encoding="utf-8"))


@unittest.skipUnless(find_browser(), "no headless Chromium (Chrome or Edge) found; set RUNLENS_BROWSER")
class Recompute(unittest.TestCase):
    """The page's own score (core/scoring.js) against bench.py's, on the demo history."""

    @classmethod
    def setUpClass(cls):
        cls.model = build_demo()
        cls.path = TMP / "demo.html"
        cls.path.write_text(dashboard.render(cls.model), encoding="utf-8")

    def score_at(self, route):
        dom = dump(self.path, route, budget=12000)
        m = re.search(r'class="summary[^"]*"[^>]*data-score="([\d.]+)"', dom)
        self.assertIsNotNone(m, f"no score at {route}")
        self.assertIsNone(re.search(r'<html[^>]*\bdata-errors=', dom), f"script error at {route}")
        return float(m.group(1)), dom

    def test_recomputed_score_matches_the_model(self):
        # Setting a weight to its own default makes the page work everything out again, with the same result.
        for name in ("review-pr", "write-tests"):
            u = next(x for x in self.model["units"] if x["id"] == f"skill:{name}")
            w = int(u["weights"]["cost"])
            score, _ = self.score_at(f"#/unit/skill%3A{name}?w=cost:{w}")
            self.assertAlmostEqual(score, u["score"], places=2, msg=name)

    def test_weights_change_the_score(self):
        u = next(x for x in self.model["units"] if x["id"] == "skill:review-pr")
        cost_only, _ = self.score_at("#/unit/skill%3Areview-pr?w=cost:1,seconds:0,error_rate:0,incidents:0,interventions:0,idle_rate:0,"
                                     "api_error_rate:0,bad_markers:0,outcome:0")
        v = self.model["versions"]["skill:review-pr"][-1]
        self.assertAlmostEqual(cost_only, 100 * v["metrics"]["cost"]["ratio"], places=1)  # with cost alone, the score is its ratio
        self.assertNotAlmostEqual(cost_only, u["score"], places=1)

    def test_a_version_against_itself_scores_100_under_a_custom_baseline(self):
        # base=ver:<label> reads the page's own current version against itself; both sides must be counted the same way.
        for name in ("review-pr", "write-tests"):
            u = next(x for x in self.model["units"] if x["id"] == f"skill:{name}")
            label = next(v["label"] for v in self.model["versions"][u["id"]] if v["key"] == u["current"] or v["label"] == u["current"])
            score, _ = self.score_at(f"#/unit/skill%3A{name}?base=ver:{label}")
            self.assertAlmostEqual(score, 100.0, places=1, msg=name)

    def test_runs_kpis_match_sql(self):
        # The visible Runs KPIs against the database itself, including pull requests (a run keeps only 5 links).
        code = ("import json; from runlens import store; con = store.connect(read_only=True); "
                "print(json.dumps(con.execute(\"SELECT count(*), coalesce(sum(len(pr_urls)), 0), coalesce(sum(cost_usd), 0) FROM runs "
                "WHERE status = 'complete' AND NOT coalesce(is_stub, false)\").fetchone()))")
        env = {**os.environ, "RUNLENS_HOME": str(TMP / "demo-home"), "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=ROOT, capture_output=True, text=True).stdout
        runs, prs, spend = json.loads(out)
        dom = dump(self.path, "#/runs")
        big = re.finditer(r'<div class="kl">([^<]+)</div><div class="kv">(.*?)</div>', dom)  # the first four figures
        small = re.finditer(r"<dt>([^<]+)</dt><dd><strong>(.*?)</strong>", dom)  # the rest, on one line
        kpis = {m.group(1): re.sub(r"<[^>]+>", "", m.group(2)) for m in [*big, *small]}
        self.assertEqual(int(kpis["Runs"].replace(",", "")), runs)
        self.assertEqual(int(kpis["Pull requests"].replace(",", "")), prs)
        self.assertEqual(re.sub(r"\D", "", kpis["Spend"]), f"{round(spend * 100)}")  # digits only: the separators follow the browser's locale

    def test_filters_recompute_and_keep_a_verdict(self):
        score, dom = self.score_at("#/unit/skill%3Awrite-tests?repo=acme-shop&ci=80")
        self.assertGreater(score, 0)
        self.assertRegex(dom, r'data-verdict="(better|worse|no clear change|not enough runs|confounded)"')


if __name__ == "__main__":
    unittest.main()
