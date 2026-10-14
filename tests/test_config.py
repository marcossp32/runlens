"""The shipped config files must load, and every option they document must be one the code reads.

config.example.toml is the reference for every option, most of them commented out. The test uncomments
every commented `key = value` line and table header, so a renamed key or a changed default in the code
fails here instead of leaving the docs silently wrong.

Run: python -m unittest tests.test_config -v
"""
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("RUNLENS_HOME", tempfile.mkdtemp(prefix="runlens-config-"))

from runlens import bench, classify, config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "runlens" / "config.example.toml"
MFEATURE = ROOT / "examples" / "m-feature.toml"

# The keys each section may hold: the contract the docs are checked against.
KEYS = {
    "select": {"since", "skills", "projects"},
    "runs": set(config.RUNS),
    "privacy": set(config.PRIVACY),
    "analysis": set(config.ANALYSIS),
    "classify": set(classify.DEFAULTS),
    "evidence": {"name", "glob"} | set(config.EVIDENCE),
    "marker": {"name", "source", "pattern", "bad"},
    "outcome": {"name", "marker", "success", "failure", "skills", "pr"},
    "method": {"min_runs", "resamples", "confidence", "cc_version", "auto_groups"},
    "group": {"name", "members"},
    "dashboard": {"auto", "view"},
}
DEFAULTS = {
    "runs": config.RUNS, "analysis": config.ANALYSIS, "classify": classify.DEFAULTS, "evidence": config.EVIDENCE,
    "method": {"min_runs": bench.MIN_RUNS, "resamples": bench.RESAMPLES, "confidence": bench.CONFIDENCE, "cc_version": "patch", "auto_groups": True},
}
ASSIGNMENT = re.compile(r"^# ((?:\[\[?[\w.\-]+\]\]?(?:\s+#.*)?|[\w\"\-]+ = \S.*))$")


def uncommented(text):
    """The example with every commented option switched on; prose comments stay comments."""
    return "\n".join(ASSIGNMENT.sub(r"\1", line) for line in text.splitlines())


def load(text):
    path = Path(tempfile.mkdtemp(prefix="runlens-config-")) / "config.toml"
    path.write_text(text, encoding="utf-8")
    return config.load(path)


def tables(cfg, section):
    value = cfg.get(section)
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


class ShippedConfigs(unittest.TestCase):
    def check_keys(self, cfg, name):
        for section, allowed in KEYS.items():
            for table in tables(cfg, section):
                self.assertLessEqual(set(table), allowed, f"{name}: unknown key in [{section}]")
        for key, value in (cfg.get("weights") or {}).items():
            for measure in (value if isinstance(value, dict) else {key: value}):
                self.assertIn(measure, bench.MEASURE, f"{name}: [weights] {measure} is not a measure")
        known = set(KEYS) | {"weights", "prices"}
        self.assertLessEqual(set(cfg), known, f"{name}: unknown section")

    def test_example_loads_as_shipped(self):
        cfg = config.load(EXAMPLE)
        bench.settings(cfg)
        self.check_keys(cfg, "config.example.toml")

    def test_every_commented_option_is_real_and_shows_the_default(self):
        cfg = load(uncommented(EXAMPLE.read_text(encoding="utf-8")))
        s = bench.settings(cfg)  # outcomes, weights, groups and [method] parse
        self.check_keys(cfg, "config.example.toml (uncommented)")
        for section in ("runs", "analysis", "classify", "evidence", "method"):
            raw = tables(cfg, section)
            self.assertTrue(raw, f"[{section}] documents no option")
        # Each section's options are all documented...
        for section in ("runs", "privacy", "analysis", "classify", "method"):
            self.assertEqual(set(cfg[section]), KEYS[section], f"[{section}] does not document every option")
        self.assertEqual(set(cfg["evidence"][0]), KEYS["evidence"])
        self.assertEqual({k for o in cfg["outcome"] for k in o}, KEYS["outcome"] - {"name"})
        # ...with the value the code actually uses when the key is left out.
        for section, defaults in DEFAULTS.items():
            table = tables(cfg, section)[0]
            for key, value in table.items():
                if key in defaults and isinstance(defaults[key], (int, float)) and not isinstance(defaults[key], bool):
                    self.assertEqual(value, defaults[key], f"[{section}] {key}: the example says {value}, the code uses {defaults[key]}")
        self.assertEqual(cfg["evidence"][0]["scope"], config.EVIDENCE["scope"])
        self.assertEqual(cfg["method"]["cc_version"], "patch")
        self.assertEqual(cfg["classify"]["model"], classify.DEFAULTS["model"])
        self.assertEqual([o["kind"] for o in s["outcomes"]], ["marker", "pr"])
        self.assertEqual(s["weights"]["units"]["my-interview"], {"interventions": 0.0})
        self.assertIn("claude-new-model", cfg["prices"])
        self.assertEqual([set(v) for v in cfg["dashboard"]["view"]], [{"name", "hash"}])

    def test_documented_measure_weights_match_the_code(self):
        line = next(x for x in EXAMPLE.read_text(encoding="utf-8").splitlines() if x.startswith("# outcome 3"))
        documented = {k: float(v) for k, v in re.findall(r"(\w+) (\d+(?:\.\d+)?)", line)}
        self.assertEqual(documented, {m["key"]: float(m["weight"]) for m in bench.MEASURES})

    def test_m_feature_example(self):
        cfg = config.load(MFEATURE)
        s = bench.settings(cfg)
        self.check_keys(cfg, "m-feature.toml")
        self.assertEqual([e["scope"] for e in cfg["evidence"]], ["run"])
        outcomes = {o["name"]: o for o in s["outcomes"]}
        step = outcomes["step check first-pass rate"]
        self.assertEqual((step["kind"], step["marker"], step["success"], step["skills"]), ("marker", "step_check", {"PASS"}, ["m-build"]))
        self.assertEqual(outcomes["PR opened"]["kind"], "pr")
        self.assertEqual(s["weights"]["units"]["m-grilling"], {"interventions": 0.0})
        group = next(g for g in s["groups"] if g["name"] == "m-stack")
        self.assertIn("m-build", group["skills"])
        self.assertTrue(all(m.startswith("skill:m-") for m in group["members"]))
        self.assertEqual(bench.unit_weights(s["weights"], "skill:m-grilling", "m-grilling", ["interventions", "cost"]),
                         {"interventions": 0.0, "cost": 2.0})


class Rejected(unittest.TestCase):
    """A typo or a wrong type stops the command with an error that names the key."""

    def fails(self, text, *needles):
        with self.assertRaises(config.ConfigError) as ctx:
            load(text)
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def test_unknown_key(self):
        self.fails("[runs]\nidle_hourz = 3\n", "[runs] idle_hourz", "unknown key")
        self.fails('[[marker]]\nname = "a"\npattern = "x"\nbadd = ["y"]\n', "[[marker]] #1 badd")
        self.fails("[weights]\ncost = 1\n[method]\nmin_run = 5\n", "[method] min_run")

    def test_unknown_section(self):
        self.fails("[selectt]\nsince = ''\n", "[selectt]", "unknown section")

    def test_wrong_type_names_the_key(self):
        self.fails('[method]\nmin_runs = "x"\n', "[method] min_runs", "whole number", "'x'")
        self.fails("[method]\nresamples = 4000.5\n", "[method] resamples", "whole number")
        self.fails("[method]\nauto_groups = 1\n", "[method] auto_groups", "true or false")
        self.fails("[runs]\nidle_hours = true\n", "[runs] idle_hours", "a number")
        self.fails('[select]\nskills = "m-feature"\n', "[select] skills", "list")
        self.fails("[privacy]\nredact = 'yes'\n", "[privacy] redact")
        self.fails("[dashboard]\nauto = 'no'\n", "[dashboard] auto")

    def test_valid_values_still_load(self):
        cfg = load('[method]\nmin_runs = 5\nconfidence = 0.9\n[select]\nsince = 2026-09-28\nskills = ["a"]\n[runs]\nstub_cost_usd = 1\n')
        self.assertEqual(cfg["method"]["min_runs"], 5)


if __name__ == "__main__":
    unittest.main()
