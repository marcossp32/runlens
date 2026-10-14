"""Proposals and their verification, and the CLI JSON the retro skill reads (score, versions, proposals, verify).

Run: python -m unittest tests.test_proposals -v
"""
import io
import json
import math
import random
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from unittest import mock

import duckdb

from runlens import bench, cli, config, proposals, store
from tests.test_bench import T0, history

BEFORE_EDIT = T0 + timedelta(seconds=6500)  # between the 6th and 7th run of history()


def model_of(cost, versions=(("aaa", 6), ("bbb", 6)), other=None):
    rng = random.Random(5)
    return bench.compute(history(list(versions), cost=lambda v, i: cost(v) * math.exp(rng.gauss(0, 0.15)), other=other), resamples=1000)


class Proposals(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()

    def tearDown(self):
        self.con.close()

    def test_add_numbers_ids_and_defaults_to_the_current_version(self):
        m = model_of(lambda v: 1.0)
        p1 = proposals.add(self.con, m, "flow", "fewer retries", "cost", "lower", ["i1", "i2"])
        p2 = proposals.add(self.con, m, "flow", "first", "error_rate", "lower", base_version="aaa")
        self.assertEqual((p1["id"], p1["base_version"], p1["evidence"]), ("p-0001", "bbb", ["i1", "i2"]))
        self.assertEqual((p2["id"], p2["base_version"]), ("p-0002", "aaa"))
        self.assertEqual([p["id"] for p in proposals.listing(self.con)], ["p-0001", "p-0002"])

    def test_bad_input_is_refused(self):
        m = model_of(lambda v: 1.0)
        for kw in ({"measure": "speed"}, {"direction": "up"}, {"hypothesis": " "}):
            args = {"skill": "flow", "hypothesis": "h", "measure": "cost", "direction": "lower", **kw}
            with self.assertRaises(ValueError, msg=kw):
                proposals.add(self.con, m, **args)
        with self.assertRaises(ValueError):
            proposals.add(self.con, m, "unknown-skill", "h", "cost", "lower")

    def test_no_newer_version_is_not_enough_runs(self):
        m = model_of(lambda v: 1.0)
        p = proposals.add(self.con, m, "flow", "h", "cost", "lower")
        r = proposals.verify(self.con, m)[0]
        self.assertEqual((r["verdict"], r["runs_after"]), ("not enough runs", 0))
        self.assertEqual(proposals.listing(self.con)[0]["verdict"], "not enough runs")
        self.assertEqual(proposals.listing(self.con)[0]["result"]["id"], p["id"])

    def test_confirmed_and_refuted(self):
        cheaper = model_of(lambda v: 1.0 if v == 0 else 0.3)
        proposals.add(self.con, cheaper, "flow", "cheaper", "cost", "lower", base_version="aaa", now=BEFORE_EDIT)
        proposals.add(self.con, cheaper, "flow", "dearer", "cost", "higher", base_version="aaa", now=BEFORE_EDIT)
        proposals.add(self.con, cheaper, "flow", "better overall", "score", "higher", base_version="aaa", now=BEFORE_EDIT)
        got = {r["hypothesis"]: r for r in proposals.verify(self.con, cheaper)}
        self.assertEqual(got["cheaper"]["verdict"], "confirmed")
        self.assertEqual((got["dearer"]["verdict"], got["dearer"]["observed"]), ("refuted", "better"))
        self.assertEqual(got["better overall"]["verdict"], "confirmed")
        self.assertEqual((got["cheaper"]["runs_before"], got["cheaper"]["runs_after"]), (6, 6))
        self.assertGreater(got["cheaper"]["difference"]["effect"], 1)

    def test_no_clear_change_is_inconclusive_not_refuted(self):
        same = model_of(lambda v: 1.0)
        proposals.add(self.con, same, "flow", "cheaper", "cost", "lower", base_version="aaa", now=BEFORE_EDIT)
        r = proposals.verify(self.con, same)[0]
        self.assertEqual((r["verdict"], r["observed"]), ("inconclusive", "no clear change"))

    def test_a_proposal_made_after_the_new_version_appeared_waits_for_a_newer_one(self):
        cheaper = model_of(lambda v: 1.0 if v == 0 else 0.3)
        proposals.add(self.con, cheaper, "flow", "late", "cost", "lower", base_version="aaa", now=T0 + timedelta(days=30))
        self.assertEqual(proposals.verify(self.con, cheaper)[0]["verdict"], "not enough runs")

    def test_confounded(self):
        m = model_of(lambda v: 1.0 if v == 0 else 0.3, other=lambda v, i: f"h{v}")
        proposals.add(self.con, m, "flow", "cheaper", "cost", "lower", base_version="aaa", now=BEFORE_EDIT)
        r = proposals.verify(self.con, m, "p-0001")[0]
        self.assertEqual((r["verdict"], r["observed"]), ("confounded", "better"))
        self.assertTrue(r["confounders"])
        with self.assertRaises(ValueError):
            proposals.verify(self.con, m, "p-9999")


class CommandLine(unittest.TestCase):
    """The commands end to end on a small database, checking the JSON fields the retro skill relies on."""

    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp(prefix="runlens-cli-"))
        cls.patch = mock.patch.multiple(config, HOME=cls.home, DB=cls.home / "runlens.duckdb", ARCHIVE=cls.home / "archive")
        cls.patch.start()
        d = history([("aaa", 6), ("bbb", 6)], cost=lambda v, i: (1.0 if v == 0 else 3.0) * (1 + i / 50))
        con = store.connect()
        for r in d["runs"]:
            con.execute("INSERT INTO runs (session_id, started, title, cwd, cc_version, status, is_stub, pr_urls) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [r["session_id"], r["started"], r["title"], r["repo"], r["cc_version"], r["status"], r["is_stub"], r["pr_urls"]])
        for a in d["api"]:
            con.execute("INSERT INTO api_calls (session_id, agent_id, ts, skill, cost_usd, api_error, model, effort) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [a["session_id"], a["agent_id"], a["ts"], a["skill"], a["cost_usd"], a["api_error"], a["model"], a["effort"]])
        for t in d["tools"]:
            con.execute("INSERT INTO tool_calls (session_id, agent_id, ts, skill, is_error, idle) VALUES (?, ?, ?, ?, ?, ?)",
                        [t["session_id"], t["agent_id"], t["ts"], t["skill"], t["is_error"], t["idle"]])
        for x in d["loads"]:
            con.execute("INSERT INTO skill_loads (session_id, agent_id, ts, skill, content_hash) VALUES (?, ?, ?, ?, ?)",
                        [x["session_id"], x["agent_id"], x["ts"], x["skill"], x["content_hash"]])
        con.close()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        shutil.rmtree(cls.home, ignore_errors=True)

    def run_cli(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            code = cli.main(["--config", str(self.home / "none.toml"), *argv])
        return code, out.getvalue()

    def test_score_json(self):
        code, out = self.run_cli("score", "--kind", "skill", "--json")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(doc["kind"], "skill")
        u = doc["units"][0]
        self.assertEqual((u["unit"], u["runs"], u["invocations"], u["current"], u["vs"], u["verdict"]), ("skill:flow", 12, 12, "v2", "v1", "worse"))
        for key in ("confounders", "outcome", "difference"):
            self.assertIn(key, u)
        self.assertLess(u["difference"]["ci95"][1], 100)

    def test_versions_json_and_text(self):
        _, out = self.run_cli("versions", "flow", "--json")
        doc = json.loads(out)
        self.assertEqual([v["label"] for v in doc["versions"]], ["v1", "v2"])
        v2 = doc["versions"][1]
        for key in ("id", "hash", "runs", "invocations", "verdict", "vs", "confounders", "difference", "outcome", "diff"):
            self.assertIn(key, v2)
        self.assertEqual(v2["id"], "skill:flow@bbb")
        _, out = self.run_cli("versions", "flow")
        self.assertIn("worse", out)
        with self.assertRaises(ValueError):
            self.run_cli("versions", "nothing")

    def test_proposals_and_verify(self):
        _, out = self.run_cli("proposals", "add", "--skill", "flow", "--hypothesis", "h", "--measure", "cost", "--direction", "lower",
                                 "--evidence", "x1", "x2")
        self.assertRegex(out.strip(), r"^p-\d{4} recorded: flow bbb$")
        _, out = self.run_cli("proposals", "list", "--json")
        self.assertEqual(json.loads(out)["proposals"][-1]["evidence"], ["x1", "x2"])
        _, out = self.run_cli("verify", "--json")
        r = json.loads(out)["proposals"][-1]
        self.assertEqual(r["verdict"], "not enough runs")
        for key in ("id", "skill", "base", "measure", "direction", "verdict", "runs_before", "runs_after", "confounders", "difference"):
            self.assertIn(key, r)

    def test_help_hides_the_internal_command(self):
        with redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            cli.main(["--help"])
        self.assertNotIn("SUPPRESS", out.getvalue())
        self.assertNotIn("drain", out.getvalue())


if __name__ == "__main__":
    unittest.main()
