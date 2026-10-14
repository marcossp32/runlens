"""Cost: list prices, and how cost-state is spread over calls whose transcript tokens are partial.

Run: python -m unittest tests.test_cost -v
"""
import math
import unittest
from datetime import datetime, timedelta, timezone

from runlens import bench
from runlens.transcripts import allocate_cost, covered, list_cost, merge_cost_states, model_key, price_of
from tests.test_bench import history

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
MODEL = "claude-sonnet-5-5"


def call(sec=0, out=8, inp=0, read=0, stop=None, size=0, model=MODEL, **kw):
    return {"ts": T0 + timedelta(seconds=sec), "model": model, "input_tokens": inp, "output_tokens": out,
            "cache_read_tokens": read, "cache_write_5m": 0, "cache_write_1h": 0, "stop_reason": stop, "api_error": False,
            "_len": size, "cost_usd": None, **kw}


def state(cost, out=None, inp=None, read=None, start=None, model=MODEL):
    use = {"costUSD": cost}
    for key, v in (("outputTokens", out), ("inputTokens", inp), ("cacheReadInputTokens", read)):
        if v is not None:
            use[key] = v
    return {"totalCostUSD": cost, "modelUsage": {model: use}, **({"startTime": start} if start else {})}


class Prices(unittest.TestCase):
    def test_cloud_model_ids_find_their_price(self):
        for name in ("anthropic.claude-sonnet-4-5-20250929-v1:0", "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                     "claude-sonnet-4-5@20250929", "claude-sonnet-4-5-20250929", "claude-sonnet-4-5"):
            self.assertEqual(model_key(name), "claude-sonnet-4-5", name)
        self.assertEqual(model_key("claude-opus-5[1m]"), "claude-opus-5")
        self.assertIsNotNone(price_of("anthropic.claude-sonnet-4-5-20250929-v1:0"))

    def test_us_geo_only_on_newer_models(self):
        self.assertAlmostEqual(price_of("claude-sonnet-5-5", geo="us")[0], 2.2)
        self.assertAlmostEqual(price_of("claude-opus-4-6", geo="us")[0], 5.5)
        self.assertEqual(price_of("claude-sonnet-4-5", geo="us")[0], 3.0)
        self.assertEqual(price_of("claude-opus-4-1", geo="us")[0], 15.0)

    def test_web_searches_cost_ten_dollars_per_thousand(self):
        a = call(out=0)
        a["web_searches"] = 3
        self.assertAlmostEqual(list_cost(a), 0.03)


class Allocation(unittest.TestCase):
    def rows(self, *calls):
        return {"api_calls": list(calls)}

    def test_output_gap_goes_to_calls_without_stop_reason(self):
        main = call(out=400, stop="end_turn", size=1600)
        sub1, sub2 = call(out=8, size=3000), call(out=8, size=1000)
        rows = self.rows(main, sub1, sub2)
        allocate_cost(rows, state(1.0, out=4016), None)
        # main keeps its 400 output tokens; the 3600 missing ones are split 3:1 over the subagent calls
        self.assertAlmostEqual(main["cost_usd"] + sub1["cost_usd"] + sub2["cost_usd"], 1.0)
        self.assertAlmostEqual(sub1["cost_usd"] / sub2["cost_usd"], (8 + 2700) / (8 + 900))
        self.assertAlmostEqual(main["cost_usd"], 1.0 * 400 / 4016)

    def test_each_category_has_its_own_gap(self):
        a, b = call(out=100, inp=1000, stop="end_turn"), call(out=100, inp=1000, stop="end_turn")
        allocate_cost(self.rows(a, b), state(1.0, out=200, inp=4000), None)
        self.assertAlmostEqual(a["cost_usd"], 0.5)
        self.assertAlmostEqual(b["cost_usd"], 0.5)
        # without the input count the cost-state input is unknown and stays as the transcript has it
        c = call(out=300, stop="end_turn")
        d = call(out=100, stop="end_turn")
        allocate_cost(self.rows(c, d), state(1.0, out=400), None)
        self.assertAlmostEqual(c["cost_usd"] / d["cost_usd"], 3)

    def test_no_stale_call_spreads_the_gap_over_all(self):
        a, b = call(out=100, stop="end_turn", size=100), call(out=100, stop="end_turn", size=300)
        allocate_cost(self.rows(a, b), state(1.0, out=1000), None)
        self.assertAlmostEqual(a["cost_usd"] + b["cost_usd"], 1.0)
        self.assertGreater(b["cost_usd"], a["cost_usd"])

    def test_resumed_session_keeps_list_price_before_cost_state_starts(self):
        start = int((T0 + timedelta(hours=20)).timestamp() * 1000)
        old, new = call(sec=0, out=1000, stop="end_turn"), call(sec=20 * 3600 + 5, out=1000, stop="end_turn")
        rows = self.rows(old, new)
        allocate_cost(rows, state(0.5, start=start), None)
        self.assertAlmostEqual(old["cost_usd"], list_cost(call(out=1000)))
        self.assertAlmostEqual(new["cost_usd"], 0.5)
        self.assertFalse(covered(state(0.5, start=start), old))
        self.assertTrue(covered(state(0.5, start=start), new))

    def test_one_cost_state_per_process_are_added(self):
        one, two = state(0.5, out=100, start=1000), state(0.25, out=50, start=5000)
        merged = merge_cost_states({1000: one, 5000: two})
        self.assertAlmostEqual(merged["totalCostUSD"], 0.75)
        self.assertEqual(merged["modelUsage"][MODEL]["outputTokens"], 150)
        self.assertEqual(merged["startTime"], 1000)
        self.assertIs(merge_cost_states({1000: one}), one)
        self.assertIsNone(merge_cost_states({}))


class Bench(unittest.TestCase):
    def test_runs_without_cost_state_are_left_out_of_the_cost_measure(self):
        d = history([("aaa", 6)], cost=lambda v, i: 1.0)
        for r in d["runs"][:3]:
            r["cost_estimated"] = True
        for a in d["api"]:
            if a["session_id"] in {r["session_id"] for r in d["runs"][:3]}:
                a["cost_usd"] = 0.01  # the partial-transcript list price
        model = bench.compute(d, resamples=50)
        cost = model["units"][0]["baseline"].get("cost")
        rows = model["runs"]["skill:flow"]
        self.assertEqual(sum(1 for r in rows if r.get("inv_cost")), 3)
        self.assertTrue(all(r["inv"] == 1 for r in rows))
        self.assertIsNotNone(cost)
        # mean log cost: two turns of 1.0 per invocation, not dragged down by the estimated runs
        self.assertAlmostEqual(math.exp(cost) - bench.MEASURE["cost"]["offset"], 2.0, places=3)

    def test_a_call_without_a_price_is_missing_not_free(self):
        d = history([("aaa", 6)], cost=lambda v, i: 1.0)
        d["api"][0]["cost_usd"] = None
        model = bench.compute(d, resamples=50)
        rows = {r["session"]: r for r in model["runs"]["skill:flow"]}
        self.assertEqual(rows["flow-0-0"[:8]]["inv_cost"], 0)
        self.assertEqual(rows["flow-0-1"[:8]]["inv_cost"], 1)

    def test_verdict_names_runs_left_out(self):
        d = history([("aaa", 6), ("bbb", 6)])
        for r in d["runs"][6:9]:
            r["cost_estimated"] = True
        model = bench.compute(d, resamples=50)
        pair = model["pairs"]["skill:flow"][0]
        self.assertEqual(len(pair["notes"]), 1)
        self.assertIn("3 of 6 runs of v2", pair["notes"][0])


if __name__ == "__main__":
    unittest.main()
