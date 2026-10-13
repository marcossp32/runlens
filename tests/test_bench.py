"""The benchmark method on plain rows (no database): attribution, the score, the verdicts and their calibration.

The null simulations at the end are the method's acceptance test: when two versions do not really differ,
"better" or "worse" must come out at about the nominal rate (5% for a 95% interval), not the 25-64% the
first method gave against a cross-skill average.

Run: python -m unittest tests.test_bench -v
"""
import math
import random
import unittest
from datetime import datetime, timedelta, timezone

import duckdb

from runlens import bench

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def at(sec):
    return T0 + timedelta(seconds=sec)


def data(**kw):
    base = {"runs": [], "agents": [], "api": [], "tools": [], "incidents": [], "markers": [],
            "prompts": [], "loads": [], "texts": []}
    base.update(kw)
    return base


def run(sid, sec, **kw):
    return {"session_id": sid, "started": at(sec), "title": f"title {sid}", "repo": "C:\\work\\repo", "cc_version": "2.1.290",
            "status": "complete", "is_stub": False, "pr_urls": [], **kw}


def turn(sid, agent, sec, skill, cost=0.1, err=False, model="claude-opus-5-5", effort="medium"):
    return {"session_id": sid, "agent_id": agent, "ts": at(sec), "skill": skill, "cost_usd": cost, "api_error": err,
            "model": model, "effort": effort}


def tool(sid, agent, sec, skill, err=False, denied=None, idle=False, added=0):
    return {"session_id": sid, "agent_id": agent, "ts": at(sec), "skill": skill, "is_error": err, "denied": denied,
            "idle": idle, "patch_added": added, "patch_removed": 0}


def load(sid, sec, skill, digest, args=None, agent="main"):
    return {"session_id": sid, "agent_id": agent, "ts": at(sec), "skill": skill, "content_hash": digest, "args": args}


def incident(sid, sec, skill, type_="repeated_call", policy=False, label=None, agent="main"):
    return {"session_id": sid, "agent_id": agent, "ts": at(sec), "skill": skill, "type": type_, "policy": policy, "label": label}


def history(versions, skill="flow", other=None, cost=lambda v, i: 1.0, start=0, cc=lambda v, i: "2.1.290",
            model=lambda v, i: "claude-opus-5-5"):
    """Runs of one skill: `versions` is [(hash, n_runs), ...] in time order. `other` adds a second skill whose
    hash per run is other(v, i), to make it change (or not) at the same time."""
    d = data()
    t = start
    for v, (digest, n) in enumerate(versions):
        for i in range(n):
            sid = f"{skill}-{v}-{i}"
            t += 1000
            d["runs"].append(run(sid, t, cc_version=cc(v, i)))
            d["loads"].append(load(sid, t + 1, skill, digest))
            d["api"].append(turn(sid, "main", t + 2, skill, cost=cost(v, i), model=model(v, i)))
            d["api"].append(turn(sid, "main", t + 30, skill, cost=cost(v, i), model=model(v, i)))
            d["tools"].append(tool(sid, "main", t + 3, skill))
            if other:
                d["loads"].append(load(sid, t + 40, "helper", other(v, i)))
                d["api"].append(turn(sid, "main", t + 41, "helper", cost=0.2))
    return d


class Settings(unittest.TestCase):
    def test_groups_are_validated(self):
        with self.assertRaises(ValueError):
            bench.parse_groups([{"name": "x", "members": ["m-plan"]}])
        with self.assertRaises(ValueError):
            bench.parse_groups([{"name": "x", "members": ["skill:a"]}, {"name": "x", "members": ["skill:b"]}])
        self.assertEqual(bench.parse_groups([{"name": "x", "members": ["skill:a", "agent:Explore"]}])[0]["members"],
                         ["skill:a", "agent:Explore"])

    def test_outcome_and_weights_are_validated(self):
        markers = [{"name": "check", "pattern": "x", "bad": ["FAIL"]}]
        o = bench.parse_outcomes({"marker": "check", "success": ["PASS"]}, markers)[0]
        self.assertEqual((o["failure"], o["name"]), ({"FAIL"}, "check first-pass rate"))
        for bad in ({"marker": "nope", "success": ["PASS"]}, {"marker": "check"}, {"pr": "merged"}, {"skills": ["a"]}):
            with self.assertRaises(ValueError, msg=bad):
                bench.parse_outcomes(bad, markers)
        w = bench.parse_weights({"cost": 1, "m-grilling": {"interventions": 0}})
        self.assertEqual(w, {"default": {"cost": 1.0}, "units": {"m-grilling": {"interventions": 0.0}}})
        for bad in ({"speed": 1}, {"cost": -1}, {"x": {"cost": "high"}}):
            with self.assertRaises(ValueError, msg=bad):
                bench.parse_weights(bad)
        with self.assertRaises(ValueError):
            bench.settings({"method": {"min_runs": 1}})

    def test_t_quantile_and_the_expanded_tail(self):
        for df, ref in ((1, 12.706), (2, 4.303), (4, 2.776), (10, 2.228), (30, 2.042)):
            self.assertAlmostEqual(bench.t_quantile(0.975, df), ref, delta=0.01)
        self.assertLess(bench.tail(0.95, 5), 0.0015)        # n = 5: far wider than the plain 2.5%
        self.assertAlmostEqual(bench.tail(0.95, 2000), 0.025, delta=0.001)


class Attribution(unittest.TestCase):
    def test_versions_follow_the_skill_text(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000), run("s3", 2000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1001, "flow"), turn("s3", "main", 2001, "flow")],
            loads=[load("s1", 1, "flow", "aaa"), load("s2", 1001, "flow", "bbb"), load("s3", 2001, "flow", "bbb")],
            texts=[{"skill": "flow", "content_hash": "aaa", "text": "step one\nstep two\n"},
                   {"skill": "flow", "content_hash": "bbb", "text": "step one\nstep 2 changed\nstep three\n"}],
        ), resamples=100)
        vs = model["versions"]["skill:flow"]
        self.assertEqual([v["label"] for v in vs], ["v1", "v2"])
        self.assertEqual([v["runs"] for v in vs], [1, 2])
        self.assertEqual([v["vid"] for v in vs], ["skill:flow@aaa", "skill:flow@bbb"])
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
        ), resamples=100)
        change = model["versions"]["skill:flow"][1]["changes"][0]
        self.assertIsNone(change["lines"])
        self.assertIn("runlens refresh", change["note"])

    def test_a_run_without_a_load_uses_the_version_current_at_its_start(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1005, "flow")],
            loads=[load("s1", 1, "flow", "aaa")],
        ), resamples=100)
        vs = model["versions"]["skill:flow"]
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0]["runs"], 2)

    def test_unrecorded_skill_text_is_not_a_version(self):
        model = bench.compute(data(runs=[run("s1", 0)], api=[turn("s1", "main", 1, "tool")]), resamples=100)
        v = model["versions"]["skill:tool"][0]
        self.assertFalse(v["recorded"])
        self.assertEqual(v["parts"], [{"skill": "tool", "hash": "unversioned"}])

    def test_open_and_stub_runs_are_left_out(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000, status="open"), run("s3", 2000, is_stub=True)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1001, "flow"), turn("s3", "main", 2001, "flow")],
        ), resamples=100)
        self.assertEqual(model["units"][0]["runs"], 1)
        self.assertEqual(model["population"], {"runs": 1, "open": 1, "stub": 1, "rule": "status = 'complete' AND NOT is_stub"})

    def test_work_belongs_to_its_invocation(self):
        # Three loads in one run (main and two subagents): three invocations, each with its own cost.
        model = bench.compute(data(
            runs=[run("s1", 0)],
            agents=[{"session_id": "s1", "agent_id": a, "agent_type": "general-purpose", "role": "Build", "description": "b"} for a in ("a1", "a2")],
            loads=[load("s1", 1, "build", "h1"), load("s1", 10, "build", "h1", agent="a1"), load("s1", 20, "build", "h1", agent="a2")],
            api=[turn("s1", "main", 2, "build", cost=1.0), turn("s1", "a1", 11, "build", cost=4.0), turn("s1", "a2", 21, "build", cost=16.0)],
        ), resamples=100)
        u = next(x for x in model["units"] if x["id"] == "skill:build")
        self.assertEqual(u["invocations"], 3)
        self.assertAlmostEqual(u["kpi"]["cost"], 4.0, delta=0.05)  # geometric mean of 1, 4 and 16
        self.assertEqual(model["runs"]["skill:build"][0]["inv"], 3)

    def test_no_double_counting(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            api=[turn("s1", "main", 1, "flow")],
            tools=[tool("s1", "main", 2, "flow", err=True), tool("s1", "main", 3, "flow", err=True, denied="user_rejected"), tool("s1", "main", 4, "flow")],
            incidents=[incident("s1", 5, "flow"), incident("s1", 5, "flow", "permission_denied", policy=True),
                       incident("s1", 5, "flow", "bad_marker"), incident("s1", 5, "flow", "idle_loop"),
                       incident("s1", 5, "flow", "error_streak"), incident("s1", 5, "flow", "repeated_call", label="expected_behavior")],
        ), resamples=100)
        r = model["runs"]["skill:flow"][0]
        self.assertEqual((r["call_errors"], r["calls"]), (1, 3))  # the denied call is not an error
        self.assertEqual(r["incidents"], 1)

    def test_runs_carry_each_measures_sums(self):
        model = bench.compute(data(runs=[run("s1", 0)], api=[turn("s1", "main", 1, "flow")]), resamples=100)
        r = model["runs"]["skill:flow"][0]
        for m in bench.MEASURES:
            if m["key"] != "outcome":
                self.assertIn(m["num"], r)
                self.assertIn(m["den"], r)

    def test_group_counts_shared_work_once(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            agents=[{"session_id": "s1", "agent_id": "sub1", "agent_type": "general-purpose", "role": "Build", "description": "Build step 3"}],
            api=[turn("s1", "main", 1, "flow", cost=1.0), turn("s1", "sub1", 2, "flow", cost=0.5)],
        ), groups=[{"name": "pipe", "members": ["skill:flow", "agent:general-purpose"]}], resamples=100)
        by_id = {u["id"]: u for u in model["units"]}
        self.assertAlmostEqual(model["runs"]["group:pipe"][0]["cost"], 1.5)
        self.assertAlmostEqual(model["runs"]["skill:flow"][0]["cost"], 1.5)
        self.assertAlmostEqual(model["runs"]["agent:general-purpose|Build"][0]["cost"], 0.5)
        self.assertEqual(by_id["group:pipe"]["members"], ["skill:flow", "agent:general-purpose"])
        self.assertEqual(model["runs"]["agent:general-purpose|Build"][0]["task"], "Build step 3")

    def test_roles_seen_in_one_run_are_folded_per_type(self):
        agents = [{"session_id": "s1", "agent_id": "a", "agent_type": "Explore", "role": "Scan once", "description": "x"},
                  {"session_id": "s1", "agent_id": "b", "agent_type": "Explore", "role": "Scan", "description": "y"},
                  {"session_id": "s2", "agent_id": "c", "agent_type": "Explore", "role": "Scan", "description": "y"}]
        model = bench.compute(data(runs=[run("s1", 0), run("s2", 1000)], agents=agents,
                                   api=[turn("s1", "a", 1, None), turn("s1", "b", 2, None), turn("s2", "c", 1002, None)]), resamples=100)
        ids = {u["id"] for u in model["units"]}
        self.assertEqual(ids, {"agent:Explore|Scan", f"agent:Explore|{bench.ONCE}"})
        role = next(u for u in model["units"] if u["id"] == "agent:Explore|Scan")
        self.assertIsNone(role["score"])  # roles have no versions: described, not scored

    def test_group_version_changes_only_when_a_member_changes(self):
        model = bench.compute(data(
            runs=[run("s1", 0), run("s2", 1000)],
            api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1005, "flow")],
            loads=[load("s1", 1, "flow", "aaa")],
        ), groups=[{"name": "pipe", "members": ["skill:flow"]}], resamples=100)
        vs = model["versions"]["group:pipe"]
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0]["key"], "flow=aaa")

    def test_prompts_count_against_the_skill_running_when_they_arrived(self):
        model = bench.compute(data(
            runs=[run("s1", 0)],
            api=[turn("s1", "main", 1, "flow"), turn("s1", "main", 100, "build")],
            prompts=[{"session_id": "s1", "ts": at(0.5)}, {"session_id": "s1", "ts": at(50)}, {"session_id": "s1", "ts": at(150)}],
        ), resamples=100)
        self.assertEqual(model["runs"]["skill:flow"][0]["interventions"], 1)
        self.assertEqual(model["runs"]["skill:build"][0]["interventions"], 1)

    def test_time_between_turns_is_capped(self):
        model = bench.compute(data(runs=[run("s1", 0)], api=[turn("s1", "main", 0, "flow"), turn("s1", "main", 2000, "flow")]),
                              resamples=100)
        self.assertEqual(model["runs"]["skill:flow"][0]["seconds"], bench.TURN_CAP)


class Outcome(unittest.TestCase):
    def test_first_pass_rate_of_a_marker_attributed_to_a_named_skill(self):
        # The check is printed by the main agent after the build subagent: with skills = ["build"] it is build's.
        markers = [{"session_id": "s1", "agent_id": "main", "ts": at(s), "skill": "flow", "marker": "check", "value": v, "bad": v == "FAIL"}
                   for s, v in ((30, "PASS"), (60, "FAIL"), (70, "PASS"), (90, "FAIL"))]
        cfg = {"marker": [{"name": "check", "pattern": "x", "bad": ["FAIL"]}],
               "outcome": {"marker": "check", "success": ["PASS"], "skills": ["build"]}}
        model = bench.compute(data(
            runs=[run("s1", 0)],
            agents=[{"session_id": "s1", "agent_id": "a1", "agent_type": "general-purpose", "role": "Build", "description": "b"}],
            loads=[load("s1", 1, "flow", "f1"), load("s1", 10, "build", "b1", agent="a1")],
            api=[turn("s1", "main", 2, "flow", cost=1.0), turn("s1", "a1", 11, "build", cost=2.0)],
            markers=markers,
        ), cfg=cfg, resamples=100)
        r = model["runs"]["skill:build"][0]
        self.assertEqual((r["os"], r["oe"], r["on"]), (1, 2, 3))  # PASS | FAIL PASS | FAIL (never passed)
        self.assertEqual(r["bad"], 0)  # the outcome marker is not also a failed check
        u = next(x for x in model["units"] if x["id"] == "skill:build")
        self.assertAlmostEqual(u["outcome"]["value"], 1 / 3)
        self.assertAlmostEqual(u["kpi"]["cost_per_success"], 1.0)
        self.assertIsNone(next(x for x in model["units"] if x["id"] == "skill:flow")["outcome"])

    def test_pr_opened(self):
        cfg = {"outcome": {"pr": "opened"}}
        model = bench.compute(data(runs=[run("s1", 0, pr_urls=["https://x/pull/1"]), run("s2", 1000)],
                                   api=[turn("s1", "main", 1, "flow"), turn("s2", "main", 1001, "flow")]), cfg=cfg, resamples=100)
        self.assertEqual(model["units"][0]["outcome"], {"measure": "PR opened", "value": 0.5, "n": 2})

    def test_weights_per_skill(self):
        d = history([("aaa", 5), ("bbb", 5)])
        for r in d["runs"][5:]:
            d["prompts"].append({"session_id": r["session_id"], "ts": r["started"] + timedelta(seconds=10)})
        plain = bench.compute(d, resamples=200)
        quiet = bench.compute(d, cfg={"weights": {"flow": {"interventions": 0}}}, resamples=200)
        v2 = lambda m: m["versions"]["skill:flow"][1]
        self.assertLess(v2(plain)["score"], 100)
        self.assertAlmostEqual(v2(quiet)["score"], 100, delta=0.01)
        self.assertEqual(next(u for u in quiet["units"] if u["id"] == "skill:flow")["weights"]["interventions"], 0)


class Verdicts(unittest.TestCase):
    def test_a_single_version_scores_100_and_has_no_verdict(self):
        model = bench.compute(history([("aaa", 6)], cost=lambda v, i: 0.5 + i), resamples=200)
        u = next(x for x in model["units"] if x["id"] == "skill:flow")
        self.assertAlmostEqual(u["score"], 100, places=6)
        self.assertIsNone(u["verdict"])

    def test_scores_never_depend_on_other_skills(self):
        alone = bench.compute(history([("aaa", 5), ("bbb", 5)], cost=lambda v, i: 1 + v), resamples=200)
        d = history([("aaa", 5), ("bbb", 5)], cost=lambda v, i: 1 + v)
        cheap = history([("zzz", 6)], skill="research", cost=lambda v, i: 0.01, start=10 ** 6)
        for k in d:
            d[k] += cheap[k]
        both = bench.compute(d, resamples=200)
        score = lambda m: [v["score"] for v in m["versions"]["skill:flow"]]
        for a, b in zip(score(alone), score(both)):
            self.assertAlmostEqual(a, b, places=9)

    def test_too_few_runs_is_not_a_verdict(self):
        model = bench.compute(history([("aaa", 4), ("bbb", 9)], cost=lambda v, i: 1 if v == 0 else 10), resamples=200)
        v2 = model["versions"]["skill:flow"][1]
        self.assertEqual((v2["verdict"], v2["vs"]), ("not enough runs", "v1"))
        self.assertIsNone(v2["difference"]["ci"])

    def test_the_m_plan_inversion_is_gone(self):
        # The audit's case: v1 has 2 cheap runs, v2 has 4 runs 3.4x dearer. The old method called v2 "clearly better"
        # because shrinkage toward a cross-skill average depended on n. Now v2 scores lower and gets no verdict.
        model = bench.compute(history([("aaa", 2), ("bbb", 4)], cost=lambda v, i: 0.94 if v == 0 else 3.18), resamples=200)
        v1, v2 = model["versions"]["skill:flow"]
        self.assertGreater(v1["score"], v2["score"])
        self.assertEqual(v2["verdict"], "not enough runs")
        self.assertLess(v2["difference"]["score"], 100)

    def test_a_clear_change_is_called(self):
        rng = random.Random(3)
        cost = lambda v, i: (1.0 if v == 0 else 3.0) * math.exp(rng.gauss(0, 0.2))
        model = bench.compute(history([("aaa", 8), ("bbb", 8)], cost=cost), resamples=1000)
        v2 = model["versions"]["skill:flow"][1]
        self.assertEqual(v2["verdict"], "worse")
        self.assertLess(v2["difference"]["ci"][1], 100)
        self.assertEqual(model["pairs"]["skill:flow"][0]["verdict"], "worse")

    def test_another_skill_changing_at_the_same_time_confounds(self):
        rng = random.Random(4)
        cost = lambda v, i: (1.0 if v == 0 else 3.0) * math.exp(rng.gauss(0, 0.2))
        model = bench.compute(history([("aaa", 6), ("bbb", 6)], cost=cost, other=lambda v, i: f"h{v}"), resamples=1000)
        v2 = model["versions"]["skill:flow"][1]
        self.assertEqual((v2["verdict"], v2["direction"]), ("confounded", "worse"))
        self.assertTrue(any(c.startswith("helper also changed") for c in v2["confounders"]), v2["confounders"])

    def test_model_mix_and_claude_code_version_confound(self):
        model = bench.compute(history([("aaa", 6), ("bbb", 6)], cost=lambda v, i: 1 + i / 10,
                                      model=lambda v, i: "claude-opus-5-5" if v == 0 else "claude-sonnet-5-5",
                                      cc=lambda v, i: "2.1.290" if v == 0 else "2.2.1"), resamples=200)
        conf = model["versions"]["skill:flow"][1]["confounders"]
        self.assertTrue(any(c.startswith("model mix") for c in conf), conf)
        self.assertIn("Claude Code 2.1 → 2.2", conf)
        # Patch releases alone are not a confounder unless asked for.
        model = bench.compute(history([("aaa", 6), ("bbb", 6)], cc=lambda v, i: f"2.1.{290 + v}"), resamples=200)
        self.assertEqual(model["versions"]["skill:flow"][1]["confounders"], [])
        model = bench.compute(history([("aaa", 6), ("bbb", 6)], cc=lambda v, i: f"2.1.{290 + v}"),
                              cfg={"method": {"cc_version": "patch"}}, resamples=200)
        self.assertEqual(model["versions"]["skill:flow"][1]["confounders"], ["Claude Code 2.1.290 → 2.1.291"])

    def test_cli_summaries_follow_the_contract(self):
        model = bench.compute(history([("aaa", 5), ("bbb", 5)], cost=lambda v, i: 1 + i), resamples=200)
        s = bench.score_summary(model, "skill")["units"][0]
        for key in ("unit", "runs", "invocations", "verdict", "vs", "confounders", "outcome", "difference"):
            self.assertIn(key, s)
        self.assertIn("ci95", s["difference"])
        vs = bench.versions_summary(model, "skill:flow")
        self.assertEqual([v["id"] for v in vs["versions"]], ["skill:flow@aaa", "skill:flow@bbb"])
        self.assertEqual(vs["versions"][1]["vs"], "v1")
        self.assertIsNone(bench.versions_summary(model, "skill:none"))


def synthetic_runs(rng, n, scale=1.0):
    """Runs with heavy-tailed cost (lognormal, sigma 1.2: the top tenth carries about half the spend) and
    rare events, the shape the audit found in real runs."""
    rows = []
    for _ in range(n):
        inv = rng.randint(1, 8)
        costs = [scale * math.exp(rng.gauss(0, 1.2)) for _ in range(inv)]
        secs = [60 * math.exp(rng.gauss(0, 1.0)) for _ in range(inv)]
        calls = rng.randint(20, 400)
        rows.append({"inv": inv, "invocations": inv, "lc": sum(math.log(c + 0.01) for c in costs), "ls": sum(math.log(s + 1) for s in secs),
                     "calls": calls, "call_errors": sum(rng.random() < 0.06 for _ in range(calls)), "idle": sum(rng.random() < 0.02 for _ in range(calls)),
                     "incidents": sum(rng.random() < 0.01 for _ in range(calls)), "turns": calls, "api_errors": int(rng.random() < 0.1),
                     "interventions": int(rng.random() < 0.2), "bad": int(rng.random() < 0.1)})
    return rows


class NullSimulation(unittest.TestCase):
    """No real difference: false "better"/"worse" must stay near the nominal 5%. A real 3x cost difference must be found."""

    def setUp(self):
        self.keys = [m["key"] for m in bench.MEASURES if m["key"] != "outcome"]
        self.weights = {k: float(bench.MEASURE[k]["weight"]) for k in self.keys}

    def verdicts(self, trials, sizes, scale_b=1.0, seed=1, measure=None):
        rng = random.Random(seed)
        out = []
        for t in range(trials):
            na, nb = rng.choice(sizes), rng.choice(sizes)
            a, b = synthetic_runs(rng, na), synthetic_runs(rng, nb, scale_b)
            pool = a + b
            base, pseudo = {}, {}
            for k in self.keys:
                m = bench.MEASURE[k]
                num, den = sum(r[m["num"]] for r in pool), sum(r[m["den"]] for r in pool)
                base[k], pseudo[k] = num / den, den / len(pool)
            res = bench.compare(a, b, base, pseudo, self.weights, f"null{t}", resamples=1000)
            if measure:
                ci = res["measures"][measure]["ci"]
                out.append("better" if ci[0] > 1 else "worse" if ci[1] < 1 else "no clear change")
            else:
                out.append(bench.verdict_of(res["ci"], na, nb, [])[0])
        return out

    def test_no_difference_rarely_reads_as_one(self):
        v = self.verdicts(160, [5, 6, 8, 12])
        rate = sum(x in ("better", "worse") for x in v) / len(v)
        self.assertLessEqual(rate, 0.10, f"false clear-change rate {rate:.1%} (nominal 5%)")

    def test_unbalanced_sides_stay_calibrated(self):
        rng = random.Random(9)
        out = []
        for t in range(120):
            a, b = synthetic_runs(rng, 5), synthetic_runs(rng, 15)
            pool = a + b
            base = {k: sum(r[bench.MEASURE[k]["num"]] for r in pool) / sum(r[bench.MEASURE[k]["den"]] for r in pool) for k in self.keys}
            pseudo = {k: sum(r[bench.MEASURE[k]["den"]] for r in pool) / len(pool) for k in self.keys}
            res = bench.compare(a, b, base, pseudo, self.weights, f"u{t}", resamples=1000)
            out.append(bench.verdict_of(res["ci"], 5, 15, [])[0])
        rate = sum(x in ("better", "worse") for x in out) / len(out)
        self.assertLessEqual(rate, 0.10, f"false clear-change rate {rate:.1%} with 5 runs against 15")

    def test_a_real_difference_is_found(self):
        # A version 4x cheaper per invocation: its cost interval sees it almost always, and the combined score,
        # where cost is 2 of 11 weight units and capped at x2, far more often than the 5% of the null.
        self.assertGreaterEqual(self.verdicts(40, [10, 12], scale_b=1 / 4, seed=2, measure="cost").count("better") / 40, 0.85)
        self.assertGreaterEqual(self.verdicts(40, [10, 12], scale_b=1 / 4, seed=2).count("better") / 40, 0.25)


class Diagnostics(unittest.TestCase):
    def test_a_missing_table_leaves_that_part_empty(self):
        con = duckdb.connect()
        con.execute("CREATE TABLE api_calls (model VARCHAR, cost_usd DOUBLE, output_tokens BIGINT, thinking_tokens BIGINT, input_tokens BIGINT,"
                    " cache_write_5m BIGINT, cache_write_1h BIGINT, cache_read_tokens BIGINT, effort VARCHAR, api_error BOOLEAN, api_limit BOOLEAN,"
                    " skill VARCHAR, ts TIMESTAMPTZ, thinking_ms BIGINT, agent_id VARCHAR, session_id VARCHAR)")
        con.execute("INSERT INTO api_calls VALUES ('claude-opus-5-5', 1.0, 10, 0, 5, 100, 300, 1000, 'high', false, false, 'flow', now(), 0, 'main', 's')")
        con.execute("CREATE TABLE model_usage (session_id VARCHAR, model VARCHAR, input_tokens BIGINT, output_tokens BIGINT, thinking_tokens BIGINT,"
                    " cache_read_tokens BIGINT, cache_write_tokens BIGINT, web_search_requests INTEGER, cost_usd DOUBLE)")
        con.execute("INSERT INTO model_usage VALUES ('s', 'claude-opus-5-5[1m]', 1000, 2000, 0, 50000, 4000, 0, 2.5)")
        d = bench.diagnostics(con)
        self.assertEqual(d["runs"], [])  # no runs table: empty, not an error
        self.assertEqual(d["models"][0]["cache_write_1h"], 300)
        parts = {r["type"]: r for r in d["token_cost"]}
        self.assertAlmostEqual(sum(r["cost"] for r in d["token_cost"]), 2.5)  # scaled to what Claude Code recorded
        self.assertEqual(round(parts["cache_write_1h"]["tokens"]), 3000)      # cache writes split 1:3 as in the transcript

    def test_other_errors_are_not_swallowed(self):
        con = duckdb.connect()
        con.close()
        with self.assertRaises(duckdb.Error):
            bench.diagnostics(con)


if __name__ == "__main__":
    unittest.main()
