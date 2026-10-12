"""The benchmark maths and the version, group and attribution rules, on plain rows (no database).

Run: python -m unittest discover -s tests -v
"""
import unittest
from datetime import datetime, timedelta, timezone

from runlens import bench

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
REF = {"cost": 1.0, "seconds": 10.0, "error_rate": 0.1, "incidents": 1.0, "interventions": 2.0,
       "idle_rate": 0.2, "api_error_rate": 0.01, "bad_markers": 0.5}


def at(sec):
    return T0 + timedelta(seconds=sec)


def values(**over):
    return {**REF, **over}


def data(**kw):
    base = {"runs": [], "agents": [], "api": [], "tools": [], "incidents": [], "markers": [],
            "prompts": [], "loads": [], "texts": []}
    base.update(kw)
    return base


def run(sid, sec):
    return {"session_id": sid, "started": at(sec), "title": f"title {sid}", "repo": "C:\\work\\repo"}


def turn(sid, agent, sec, skill, cost=0.1, err=False):
    return {"session_id": sid, "agent_id": agent, "ts": at(sec), "skill": skill, "cost_usd": cost, "api_error": err}


def load(sid, sec, skill, digest, args=None, agent="main"):
    return {"session_id": sid, "agent_id": agent, "ts": at(sec), "skill": skill, "content_hash": digest, "args": args}


class ScoreMath(unittest.TestCase):
    def test_average_run_scores_100(self):
        s = bench.unit_score([values()] * 10, REF, "skill")
        self.assertAlmostEqual(s["score"], 100.0, places=6)

    def test_cheaper_runs_score_above_100(self):
        s = bench.unit_score([values(cost=0.5)] * 20, REF, "skill")
        self.assertGreater(s["score"], 100)
        self.assertGreater(s["metrics"]["cost"]["ratio"], 1.0)

    def test_few_runs_are_pulled_toward_the_average(self):
        one = bench.unit_score([values(cost=0.01)], REF, "skill")["score"]
        fifty = bench.unit_score([values(cost=0.01)] * 50, REF, "skill")["score"]
        self.assertLess(abs(one - 100), abs(fifty - 100))

    def test_each_ratio_is_clipped_to_a_factor_of_two(self):
        s = bench.unit_score([values(cost=1000.0)] * 50, REF, "skill")
        self.assertAlmostEqual(s["metrics"]["cost"]["ratio"], 0.5, places=6)

    def test_metric_without_reference_is_skipped(self):
        ref = {**REF, "bad_markers": 0.0}
        s = bench.unit_score([values(bad_markers=3)] * 4, ref, "skill")
        self.assertNotIn("bad_markers", s["metrics"])

    def test_agent_roles_are_not_scored_on_prompts(self):
        s = bench.unit_score([values(interventions=None)] * 4, REF, "agent")
        self.assertNotIn("interventions", s["metrics"])

    def test_interval_brackets_the_score(self):
        runs = [{"values": values(cost=0.2 + i / 20)} for i in range(30)]
        res = bench.scored(runs, REF, "skill", "seed", resamples=100)
        self.assertLessEqual(res["ci"][0], res["score"])
        self.assertGreaterEqual(res["ci"][1], res["score"])

    def test_a_single_run_has_no_interval(self):
        self.assertIsNone(bench.scored([{"values": values()}], REF, "skill", "seed", resamples=10)["ci"])

    def test_intervals_overlap_rule(self):
        self.assertFalse(bench.overlaps([1, 2], [3, 4]))
        self.assertTrue(bench.overlaps([1, 3], [2, 4]))
        self.assertIsNone(bench.overlaps(None, [1, 2]))

    def test_groups_are_validated(self):
        with self.assertRaises(ValueError):
            bench.parse_groups([{"name": "x", "members": ["m-plan"]}])
        with self.assertRaises(ValueError):
            bench.parse_groups([{"name": "x", "members": ["skill:a"]}, {"name": "x", "members": ["skill:b"]}])
        self.assertEqual(bench.parse_groups([{"name": "x", "members": ["skill:a", "agent:Explore"]}])[0]["members"],
                         ["skill:a", "agent:Explore"])


class Attribution(unittest.TestCase):
    def test_versions_follow_the_skill_text(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000), run("s3", 2000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1001, "flow"), turn("s3", "main", 2001, "flow")],
            loads=[load("s1", 1, "flow", "aaa"), load("s2", 1001, "flow", "bbb"), load("s3", 2001, "flow", "bbb")],
            texts=[{"skill": "flow", "content_hash": "aaa", "text": "step one\nstep two\n"},
                   {"skill": "flow", "content_hash": "bbb", "text": "step one\nstep 2 changed\nstep three\n"}],
        ), resamples=10)
        vs = model["versions"]["skill:flow"]
        self.assertEqual([v["label"] for v in vs], ["v1", "v2"])
        self.assertEqual([v["runs"] for v in vs], [1, 2])
        self.assertEqual(vs[0]["changes"], [])
        change = vs[1]["changes"][0]
        self.assertEqual((change["skill"], change["from"], change["to"]), ("flow", "aaa", "bbb"))
        self.assertEqual((change["added"], change["removed"]), (2, 1))
        self.assertIn(["-", "step two"], change["lines"])
        self.assertIn(["+", "step 2 changed"], change["lines"])

    def test_missing_text_is_reported_not_guessed(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1001, "flow")],
            loads=[load("s1", 1, "flow", "aaa"), load("s2", 1001, "flow", "bbb")],
        ), resamples=10)
        change = model["versions"]["skill:flow"][1]["changes"][0]
        self.assertIsNone(change["lines"])
        self.assertIn("runlens refresh", change["note"])

    def test_a_run_without_a_load_uses_the_version_current_at_its_start(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1005, "flow")],
            loads=[load("s1", 1, "flow", "aaa")],
        ), resamples=10)
        vs = model["versions"]["skill:flow"]
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0]["runs"], 2)

    def test_unrecorded_skill_text_is_not_a_version(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            api=[turn("s1", "main", 1, "tool")],
        ), resamples=10)
        v = model["versions"]["skill:tool"][0]
        self.assertFalse(v["recorded"])
        self.assertEqual(v["parts"], [{"skill": "tool", "hash": "unversioned"}])

    def test_recorded_version_is_flagged(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            api=[turn("s1", "main", 1, "flow")],
            loads=[load("s1", 1, "flow", "abcdef123456")],
        ), resamples=10)
        v = model["versions"]["skill:flow"][0]
        self.assertTrue(v["recorded"])
        self.assertEqual(v["parts"], [{"skill": "flow", "hash": "abcdef12"}])

    def test_group_counts_shared_work_once(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            agents=[{"session_id": "s1", "agent_id": "sub1", "agent_type": "general-purpose", "role": "Build", "description": "Build step 3"}],
            api=[turn("s1", "main", 1, "flow", cost=1.0), turn("s1", "sub1", 2, "flow", cost=0.5)],
        ), groups=[{"name": "pipe", "members": ["skill:flow", "agent:general-purpose"]}], resamples=10)
        by_id = {u["id"]: u for u in model["units"]}
        self.assertAlmostEqual(model["runs"]["group:pipe"][0]["cost"], 1.5)
        self.assertAlmostEqual(model["runs"]["skill:flow"][0]["cost"], 1.5)
        self.assertAlmostEqual(model["runs"]["agent:general-purpose|Build"][0]["cost"], 0.5)
        self.assertEqual(by_id["group:pipe"]["members"], ["skill:flow", "agent:general-purpose"])
        self.assertEqual(model["runs"]["agent:general-purpose|Build"][0]["task"], "Build step 3")

    def test_group_version_changes_only_when_a_member_changes(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1005, "flow")],
            loads=[load("s1", 1, "flow", "aaa")],
        ), groups=[{"name": "pipe", "members": ["skill:flow"]}], resamples=10)
        vs = model["versions"]["group:pipe"]
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0]["key"], "flow=aaa")

    def test_prompts_count_against_the_skill_running_when_they_arrived(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            api=[turn("s1", "main", 1, "flow"), turn("s1", "main", 100, "build")],
            prompts=[{"session_id": "s1", "ts": at(0.5)}, {"session_id": "s1", "ts": at(50)}, {"session_id": "s1", "ts": at(150)}],
        ), resamples=10)
        self.assertEqual(model["runs"]["skill:flow"][0]["interventions"], 1)
        self.assertEqual(model["runs"]["skill:build"][0]["interventions"], 1)

    def test_time_between_turns_is_capped(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            api=[turn("s1", "main", 0, "flow"), turn("s1", "main", 2000, "flow")],
        ), resamples=10)
        self.assertEqual(model["runs"]["skill:flow"][0]["seconds"], bench.TURN_CAP)


if __name__ == "__main__":
    unittest.main()
