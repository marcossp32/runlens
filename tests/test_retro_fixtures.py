"""The /runlens-retro eval fixtures against the real CLI.

Each evals/files/<case>/commands.md holds canned output of `runlens` commands, so the skill's branches can be
tested without a database. Canned output drifts when the CLI changes, so this builds the made-up demo history
(scripts/make_demo.py) in a child process with its own RUNLENS_HOME, runs the real commands, and checks that
every fixture uses the same line formats and JSON keys.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "runlens" / "skill" / "runlens-retro"
CASES = sorted((SKILL / "evals" / "files").glob("*/commands.md"))

CHECK_LINE = re.compile(r"^(ok  |FAIL|WARN)  \S+  \S")
CHECK_LAST = re.compile(r"^(\d+) problem\(s\)$|^all checks passed$")


def sections(path):
    """[(heading, text of its first fenced block)] of a commands.md."""
    out = []
    for m in re.finditer(r"^## (.+?)\n```(?:json)?\n(.*?)```", path.read_text(encoding="utf-8"), re.S | re.M):
        out.append((m.group(1).strip(), m.group(2)))
    return out


def keys_of(rows):
    return set().union(*(r.keys() for r in rows if isinstance(r, dict))) if rows else set()


def nested(rows, key):
    """The dicts found under `key` in every row."""
    return [r[key] for r in rows if isinstance(r.get(key), dict)]


class Real:
    """The real CLI on the demo history, run once."""
    home = None
    out = {}

    @classmethod
    def build(cls):
        cls.home = Path(tempfile.mkdtemp(prefix="runlens-retro-fixtures-"))
        cls.env = {**os.environ, "RUNLENS_HOME": str(cls.home), "PYTHONIOENCODING": "utf-8"}
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_demo.py"), str(cls.home)], check=True, env=cls.env, cwd=ROOT,
                       capture_output=True)
        score = cls.run("score", "--kind", "skill", "--json")
        cls.out["score"] = json.loads(score)
        cls.out["versions"] = [json.loads(cls.run("versions", u["name"], "--json")) for u in cls.out["score"]["units"]]
        first = next(v for v in cls.out["versions"] if len(v["versions"]) > 1)
        cls.run("proposals", "add", "--skill", first["skill"], "--hypothesis", "fixture check", "--measure", "cost",
                "--direction", "lower", "--evidence", "x", "--base-version", first["versions"][0]["hash"])
        cls.out["verify"] = json.loads(cls.run("verify", "--json"))
        cls.out["agreement"] = json.loads(cls.run("agreement", "--json"))
        cls.out["check"] = cls.run("check").splitlines()
        cls.out["incidents"] = cls.run("incidents", "--limit", "3").splitlines()
        cls.out["help"] = cls.run("--help")

    @classmethod
    def run(cls, *argv):
        r = subprocess.run([sys.executable, "-m", "runlens", *argv], capture_output=True, text=True, encoding="utf-8", env=cls.env, cwd=ROOT)
        return r.stdout

    @classmethod
    def drop(cls):
        shutil.rmtree(cls.home, ignore_errors=True)


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Real.build()

    @classmethod
    def tearDownClass(cls):
        Real.drop()

    def blocks(self, command):
        """(case, parsed or raw block) for every fixture section that is `runlens <command> ...`."""
        for path in CASES:
            for heading, body in sections(path):
                if heading.split()[:2] == ["runlens", command]:
                    yield path.parent.name, body

    def test_every_case_is_listed_and_every_file_exists(self):
        evals = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
        used = set()
        for e in evals:
            self.assertEqual(e["assertions"], e["expectations"], e["name"])
            for f in e["files"]:
                self.assertTrue((SKILL / f).is_file(), f"{e['name']}: {f}")
                used.add(f)
            for f in re.findall(r"evals/files/[\w./-]+", e["prompt"]):
                self.assertIn(f, used | {x for x in e["files"]}, f"{e['name']} prompt names {f} that is not in files")
        for path in CASES:
            self.assertIn(f"evals/files/{path.parent.name}/commands.md", used, f"{path.parent.name} is used by no eval")

    def test_commands_are_real_subcommands(self):
        for path in CASES:
            for heading, _ in sections(path):
                words = heading.split()
                if words[0] == "runlens":
                    self.assertRegex(Real.out["help"], rf"\b{re.escape(words[1])}\b", f"{path.parent.name}: {heading}")

    def test_check_format(self):
        """Per run `ok  /FAIL/WARN  <8-char id>  <details>`, then `N problem(s)` or `all checks passed`."""
        real = Real.out["check"]
        self.assertRegex(real[-1], CHECK_LAST)
        self.assertTrue(any(line.startswith("FAIL  ") for line in real), "the demo has a failed ingest, so check must print a FAIL line")
        seen = 0
        for case, body in self.blocks("check"):
            seen += 1
            lines = body.strip().splitlines()
            for line in lines[:-1]:
                self.assertRegex(line, CHECK_LINE, f"{case}: {line}")
            m = CHECK_LAST.match(lines[-1])
            self.assertTrue(m, f"{case}: last line is {lines[-1]!r}")
            problems = sum(not line.startswith("ok") for line in lines[:-1])
            if m.group(1):
                self.assertEqual(int(m.group(1)), problems, f"{case}: problem count")
            else:
                self.assertEqual(problems, 0, f"{case}: 'all checks passed' with problem lines")
            for line in lines[:-1]:
                if line.startswith("FAIL") and "raw" in line:
                    self.assertRegex(line, r"\w+: raw \d+ vs db \d+", case)
        self.assertGreaterEqual(seen, len(CASES))

    def test_score_keys(self):
        real = Real.out["score"]
        units = real["units"]
        for case, body in self.blocks("score"):
            doc = json.loads(body)
            self.assertLessEqual(set(doc), set(real), case)
            self.assertLessEqual(set(doc["population"]), set(real["population"]), case)
            self.assertLessEqual(keys_of(doc["units"]), keys_of(units), case)
            self.assertLessEqual(keys_of(nested(doc["units"], "difference")), keys_of(nested(units, "difference")), case)
            self.assertLessEqual(keys_of(nested(doc["units"], "outcome")), keys_of(nested(units, "outcome")), case)

    def test_versions_keys(self):
        real = [v for doc in Real.out["versions"] for v in doc["versions"]]
        for case, body in self.blocks("versions"):
            doc = json.loads(body)
            self.assertLessEqual(set(doc), set(Real.out["versions"][0]), case)
            self.assertLessEqual(keys_of(doc["versions"]), keys_of(real), case)
            diffs, real_diffs = nested(doc["versions"], "difference"), nested(real, "difference")
            self.assertLessEqual(keys_of(diffs), keys_of(real_diffs), case)
            self.assertLessEqual(keys_of(nested(diffs, "outcome")), keys_of(nested(real_diffs, "outcome")), case)
            measures = [m for d in diffs for m in d["measures"].values()]
            real_measures = [m for d in real_diffs for m in d["measures"].values()]
            self.assertLessEqual(keys_of(measures), keys_of(real_measures), case)

    def test_verify_keys(self):
        real = Real.out["verify"]["proposals"]
        self.assertTrue(real)
        for case, body in self.blocks("verify"):
            doc = json.loads(body)
            self.assertEqual(set(doc), {"proposals"}, case)
            self.assertLessEqual(keys_of(doc["proposals"]), keys_of(real), case)
            for p in doc["proposals"]:
                self.assertIn(p["verdict"], {"confirmed", "refuted", "not enough runs", "confounded"}, case)

    def test_agreement_keys(self):
        real = Real.out["agreement"]
        for case, body in self.blocks("agreement"):
            doc = json.loads(body)
            self.assertLessEqual(set(doc), set(real), case)

    def test_incidents_header(self):
        header = Real.out["incidents"][0].split()
        for case, body in self.blocks("incidents"):
            lines = body.strip().splitlines()
            if lines[0] != "(no incidents)":
                self.assertEqual(lines[0].split(), header, case)

    def test_verdict_words(self):
        """The verdicts the fixtures use are ones the skill's text and the CLI both know."""
        known = {"better", "worse", "no clear change", "not enough runs", "confounded", None}
        for case, body in [*self.blocks("score"), *self.blocks("versions")]:
            doc = json.loads(body)
            for row in doc.get("units") or doc["versions"]:
                self.assertIn(row.get("verdict"), known, case)


if __name__ == "__main__":
    unittest.main()
