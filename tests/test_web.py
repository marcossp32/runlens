"""Tests for the dashboard page: how its script is assembled, what it may contain, and that every page renders.

The rendering test opens the generated file in a headless Chromium (Chrome, Chromium or Edge) and is skipped
when none is installed; RUNLENS_BROWSER can point at one. The syntax test needs node and is skipped without it.

Run: python -m unittest tests.test_web -v
"""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="runlens-web-"))
os.environ.setdefault("RUNLENS_HOME", str(TMP / "home"))

from runlens import dashboard  # noqa: E402

WEB = dashboard.WEB
METRICS = [
    {"key": "cost", "label": "Cost per run", "unit": "usd", "weight": 3, "kinds": ["skill", "agent", "group"], "what": "Model spend."},
    {"key": "seconds", "label": "Time per run", "unit": "s", "weight": 2, "kinds": ["skill", "agent", "group"], "what": "Time."},
    {"key": "error_rate", "label": "Tool error rate", "unit": "rate", "weight": 2, "kinds": ["skill", "agent", "group"], "what": "Errors."},
    {"key": "interventions", "label": "Human prompts per run", "unit": "count", "weight": 2, "kinds": ["skill", "group"], "what": "Prompts."},
]


def metrics(ratio, n):
    return {m["key"]: {"value": 1.0 / ratio, "counted": 1.0 / ratio, "n": n, "ref": 1.0, "ratio": ratio, "weight": m["weight"]}
            for m in METRICS if "skill" in m["kinds"]}


def run(day, version, cost, task="</script><b>x</b>"):
    return {"started": f"2026-10-0{day}T10:00:00+02:00", "session": f"s{day}{version}", "task": task, "version": version, "repo": "r",
            "cost": cost, "seconds": 600.0, "calls": 10, "call_errors": 1, "idle": 0, "turns": 5, "api_errors": 0,
            "incidents": 1, "interventions": 0, "bad": 0}


def version(label, key, day0, day1, score, ci, n, delta=None, overlap=None, uid="skill:flow"):
    return {"id": uid, "label": label, "key": key, "parts": [{"skill": "flow", "hash": key}], "recorded": True,
            "first_seen": f"2026-10-0{day0}T10:00:00+02:00", "last_seen": f"2026-10-0{day1}T10:00:00+02:00",
            "runs": n, "low_sample": n < 5, "score": score, "ci": ci, "metrics": metrics(score / 100, n),
            "changes": [], "delta": delta, "overlap": overlap}


def model():
    """A small model in the shape bench.build returns, with a hostile task text to prove nothing runs as markup."""
    units = [
        {"id": "skill:flow", "kind": "skill", "name": "flow", "members": [], "runs": 6, "versions": 2, "current": "v2",
         "score": 112.0, "ci": [101.0, 125.0], "low_sample": False, "delta": 9.0, "overlap": True,
         "kpi": {"cost": 1.2, "seconds": 600.0, "error_rate": 0.1, "interventions": 0.0}, "first_seen": "2026-10-01T10:00:00+02:00",
         "last_seen": "2026-10-06T10:00:00+02:00"},
        {"id": "skill:once_only", "kind": "skill", "name": "once_only", "members": [], "runs": 1, "versions": 1, "current": "v1",
         "score": 90.0, "ci": None, "low_sample": True, "delta": None, "overlap": None,
         "kpi": {"cost": 3.0, "seconds": 900.0, "error_rate": None, "interventions": 1.0}, "first_seen": "2026-10-02T10:00:00+02:00",
         "last_seen": "2026-10-02T10:00:00+02:00"},
        {"id": "agent:Explore · scan", "kind": "agent", "name": "Explore · scan", "members": [], "runs": 2, "versions": 0, "current": None,
         "score": 100.0, "ci": None, "low_sample": True, "delta": None, "overlap": None,
         "kpi": {"cost": 0.5, "seconds": 60.0, "error_rate": 0.0, "interventions": None}, "first_seen": "2026-10-03T10:00:00+02:00",
         "last_seen": "2026-10-04T10:00:00+02:00"},
    ]
    versions = {
        "skill:flow": [version("v1", "a1", 1, 3, 103.0, [92.0, 115.0], 3), version("v2", "b2", 4, 6, 112.0, [101.0, 125.0], 3, 9.0, True)],
        "skill:once_only": [version("v1", "c3", 2, 2, 90.0, None, 1, uid="skill:once_only")],
    }
    runs = {"skill:flow": [run(d, "v1" if d <= 3 else "v2", 1.0 + d / 10) for d in range(1, 7)],
            "skill:once_only": [run(2, "v1", 3.0)], "agent:Explore · scan": [run(3, "v1", 0.4), run(4, "v1", 0.6)]}
    diag = {
        "runs": [{"run": f"r{d}", "started": f"2026-10-0{d}T10:00:00+02:00", "repo": "r", "branch": "main", "cc_version": "2.1",
                  "title": "<img src=x onerror=alert(1)>", "cost": 2.0 * d, "estimated": d == 6, "active_ms": 3.6e6, "prompts": 1,
                  "agents": d, "lines_added": 10, "lines_removed": 2, "incidents": 1, "tool_calls": 20, "tool_errors": 2} for d in range(1, 7)],
        "incidents": [{"type": "idle_loop", "skill": "flow", "incidents": 2, "occurrences": 4}],
        "incident_roles": [{"role": "main", "incidents": 2}],
        "tool_errors": [{"class": "not_found", "tool": "Read", "errors": 2}],
        "tools": [{"tool": "Read", "calls": 40, "errors": 2, "median_ms": 30.0, "p95_ms": 900.0, "total_ms": 5000.0}],
        "idle": [{"skill": "flow", "idle_calls": 1, "calls": 40}],
        "models": [{"model": "claude-opus-5-5", "calls": 30, "cost": 7.2, "output": 1000, "thinking": 50, "fresh_input": 3000, "cache_read": 90000}],
        "efforts": [{"effort": "high", "calls": 30, "cost": 7.2}],
        "agent_types": [{"agent_type": "Explore", "agents": 2, "cost": 1.0, "tool_calls": 10, "tool_errors": 1, "peak_context": 50000,
                         "compactions": 0, "not_completed": 0}],
        "agent_status": [{"status": "completed", "agents": 2}],
        "flow": [{"source": "flow", "target": "once_only", "transitions": 1}],
        "markers": [{"marker": "step_check", "value": "PASS", "bad": False, "skill": "flow", "n": 3}],
        "events": [{"kind": "away_summary", "n": 1}], "labels": [],
        "model_effort": [{"model": "claude-opus-5-5", "effort": "high", "calls": 30, "cost": 7.2, "avg_output": 30.0, "avg_thinking": 2.0, "avg_thinking_ms": 900.0}],
        "model_skill": [{"model": "claude-opus-5-5", "skill": "flow", "calls": 30, "cost": 7.2}],
        "model_day": [{"day": "2026-10-01", "model": "claude-opus-5-5", "cost": 3.0, "calls": 10}, {"day": "2026-10-04", "model": "claude-opus-5-5", "cost": 4.2, "calls": 20}],
        "api_errors": [{"model": "claude-opus-5-5", "errors": 0, "calls": 30}],
        "agents_by_run": [{"run": "r3", "agent_type": "Explore", "n": 2, "cost": 1.0}],
        "agents_by_skill": [{"skill": "flow", "agent_type": "Explore", "n": 2, "cost": 1.0}],
        "agent_shape": [{"depth": 1, "background": False, "n": 2}],
        "agent_models": [{"agent_type": "Explore", "model": "sonnet", "n": 2, "cost": 1.0}],
        "agent_roles": [{"agent_type": "Explore", "role": "scan", "agents": 2, "cost": 1.0, "avg_seconds": 30.0, "avg_tools": 5.0, "peak_context": 50000}],
        "agent_time": [{"agent_type": "Explore", "avg_s": 30.0, "median_s": 28.0, "p95_s": 40.0}],
        "agent_skills": [], "agent_day": [{"day": "2026-10-03", "n": 2, "cost": 1.0}],
    }
    return {
        "generated": "2026-10-07T09:00+02:00",
        "window": {"first": "2026-10-01T10:00:00+02:00", "last": "2026-10-06T10:00:00+02:00", "runs": 6},
        "texts": True,
        "method": {"metrics": METRICS, "shrink": 2, "max_ratio": 2.0, "floor": 0.01, "turn_cap": 600, "resamples": 2000, "min_runs": 5},
        "reference": {"skill": {"cost": 1.0, "seconds": 1.0, "error_rate": 1.0, "interventions": 1.0}, "agent": {"cost": 1.0}},
        "units": units, "versions": versions, "runs": runs, "diag": diag,
    }


def empty_model():
    m = model()
    m.update(units=[], versions={}, runs={}, diag=None, window={"first": None, "last": None, "runs": 0})
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
        rank = {"core": 0, "charts": 1, "pages": 2, "app": 3}
        self.assertEqual(kinds, sorted(kinds, key=rank.get), "core, then charts, then pages, then app")
        for a, b in (("core/data.js", "core/colour.js"), ("core/prefs.js", "core/format.js"), ("charts/frame.js", "charts/kit.js")):
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
        self.assertEqual(data["runs"]["skill:flow"][0]["task"], "</script><b>x</b>")

    def test_every_page_has_a_nav_link(self):
        for page in ("skills", "compare", "diagnostics", "method"):
            self.assertIn(f'data-page="{page}"', self.page)


ROUTES = ["#/", "#/?tab=cost", "#/?tab=measures", "#/?kind=roles", "#/?kind=groups", "#/?skills=flow&v=flow:v2&split=1",
          "#/unit/skill%3Aflow", "#/unit/skill%3Aflow?tab=drivers", "#/unit/skill%3Aflow?tab=runs", "#/unit/agent%3AExplore%20%C2%B7%20scan",
          "#/compare", "#/compare?a=skill%3Aflow&av=v1&b=skill%3Aonce_only&bv=v1",
          "#/diagnostics", "#/diagnostics?tab=problems", "#/diagnostics?tab=tools", "#/diagnostics?tab=models&sub=effort",
          "#/diagnostics?tab=models&sub=time", "#/diagnostics?tab=agents&sub=generated", "#/diagnostics?tab=flow",
          "#/method", "#/method?tab=example", "#/no/such/page"]


@unittest.skipUnless(find_browser(), "no headless Chromium (Chrome or Edge) found; set RUNLENS_BROWSER")
class Renders(unittest.TestCase):
    """Open the page in a real browser at each route: it must draw an article and record no script error."""

    def dom(self, path, route):
        prof = tempfile.mkdtemp(prefix="runlens-browser-", dir=TMP)
        cmd = [find_browser(), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={prof}",
               "--virtual-time-budget=4000", "--window-size=1280,900", "--dump-dom", path.as_uri() + route]
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        return out.stdout

    def check(self, m, routes):
        path = TMP / f"page-{len(routes)}.html"
        path.write_text(dashboard.render(m), encoding="utf-8")
        for route in routes:
            with self.subTest(route=route):
                dom = self.dom(path, route)
                self.assertTrue('class="page"' in dom, f"no page rendered at {route}")
                errors = re.search(r'<html[^>]*\bdata-errors="(\d+)"[^>]*>', dom)
                last = re.search(r'data-last-error="([^"]*)"', dom)
                self.assertIsNone(errors, f"script error at {route}: {last.group(1) if last else ''}")
                self.assertFalse("<b>x</b>" in dom, "data reached the page as markup")

    def test_every_route_renders(self):
        self.check(model(), ROUTES)

    def test_empty_history_renders(self):
        self.check(empty_model(), ["#/", "#/compare", "#/diagnostics", "#/method"])

    def test_charts_are_drawn_at_their_real_width(self):
        path = TMP / "width.html"
        path.write_text(dashboard.render(copy.deepcopy(model())), encoding="utf-8")
        dom = self.dom(path, "#/?tab=cost")
        widths = re.findall(r'<svg[^>]*class="[^"]*\bchart\b[^"]*"[^>]*>', dom) or re.findall(r'<svg[^>]*width="(\d+)"[^>]*class="[^"]*chart', dom)
        self.assertTrue(widths, "no chart was drawn")
        self.assertIsNone(re.search(r'<svg[^>]*viewBox="0 0 640 ', dom), "a chart still uses the old fixed 640-wide viewBox")


if __name__ == "__main__":
    unittest.main()
