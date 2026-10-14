"""Benchmarks of skills, agent roles and groups, computed from the database alone.

The question it answers: did a change to a skill make its runs better or worse? So every
comparison stays inside one skill (or one group). A version is compared with the skill's
previous version, and its score is read against the skill's own typical run. Different
skills do different work (research is cheaper than building), so their numbers are shown
side by side but never ranked against each other. Agent roles have no versions: they are
described, not scored.

Population. Only finished runs count (`runs.status = 'complete'`), and stubs (a skill
loaded and barely used) are left out (`NOT runs.is_stub`).

Measures. Every measure is a ratio of sums over runs, Σnum / Σden, so a big run weighs as
much as its size and no run's rate is averaged with another's:
- "log" measures (cost, time) are geometric means per invocation: num = Σ ln(x + offset)
  over the run's invocations, den = invocations. Costs are heavy-tailed (a tenth of the
  runs carry most of the spend), so an arithmetic mean would be the cost of the odd giant run.
- "rate" measures are events over opportunities (failed tool calls over tool calls).
- "count" measures are events per invocation (human prompts, failed checks).
An invocation is a skill load (skill_loads), an agent spawn, or a group's run. A version's
value is pulled toward its own skill's value by SHRINK pseudo-runs, never toward other skills.

Score. For each measure, l = ln(reference / value), with a floor on rates so a zero stays
finite, clipped to ±ln MAX_RATIO; positive is better. score = 100 x exp(Σ w·l / Σ w).
100 is the skill's typical run; for a comparison, the earlier version.

Verdicts. Version B against version A comes from a bootstrap of the DIFFERENCE: the runs of
each version are resampled by session (a session's invocations stay together), the
weighted difference is recomputed each time, and its central interval decides: entirely
above 0 is "better", below 0 "worse", otherwise "no clear change". Fewer than MIN_RUNS
runs on either side is "not enough runs". When something else changed between the two
sides (another skill's text, the model or effort mix, the Claude Code version, the
project), the verdict is "confounded" and names what changed: a change can then not be
put down to the skill text.

Double counting is removed at the source: denied tool calls are not tool errors (they
reflect permission rules); policy denials, failed-check incidents (already a measure), idle
loops and error streaks (already in the idle and error rates) and incidents a label calls
expected behaviour are not problems.
"""
import bisect
import difflib
import math
import os
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import NormalDist

KINDS = ("skill", "agent", "group")
VERSIONED = ("skill", "group")
MEASURES = [
    {"key": "outcome", "label": "Outcome", "unit": "rate", "type": "rate", "better": "higher", "num": "os", "den": "on",
     "weight": 3, "kinds": VERSIONED,
     "what": "The result the flow is meant to reach, as configured under [outcome]: a check that passes first time, or a PR opened."},
    {"key": "cost", "label": "Cost per invocation", "unit": "usd", "type": "log", "better": "lower", "num": "lc", "den": "inv",
     "weight": 2, "kinds": KINDS, "offset": 0.01,
     "what": "Model spend per invocation (skill load, subagent spawn or group run), as a geometric mean."},
    {"key": "seconds", "label": "Time per invocation", "unit": "s", "type": "log", "better": "lower", "num": "ls", "den": "inv",
     "weight": 1, "kinds": KINDS, "offset": 1.0,
     "what": "Working time per invocation, from each model turn to the same agent's next, capped per turn; a geometric mean."},
    {"key": "error_rate", "label": "Tool error rate", "unit": "rate", "type": "rate", "better": "lower", "num": "call_errors",
     "den": "calls", "weight": 2, "kinds": KINDS,
     "what": "Failing tool calls over all tool calls. Calls a permission rule denied are not errors of the skill."},
    {"key": "incidents", "label": "Problems per 100 tool calls", "unit": "count", "type": "rate", "better": "lower",
     "num": "incidents", "den": "calls", "scale": 100, "weight": 2, "kinds": KINDS,
     "what": "Repeated calls, interrupts, failed subagents, test edits after a failure and similar. Not counted: policy "
             "denials, failed checks, idle loops and error streaks (other measures already count them), and incidents "
             "labelled expected behaviour."},
    {"key": "interventions", "label": "Human prompts per invocation", "unit": "count", "type": "count", "better": "lower",
     "num": "interventions", "den": "inv", "weight": 1, "kinds": VERSIONED,
     "what": "Human prompts sent while it was the active skill. Give it weight 0 for skills that are meant to ask."},
    {"key": "idle_rate", "label": "Idle call rate", "unit": "rate", "type": "rate", "better": "lower", "num": "idle",
     "den": "calls", "weight": 1, "kinds": KINDS, "what": "Tool calls that only wait or print, over all tool calls."},
    {"key": "api_error_rate", "label": "API error rate", "unit": "rate", "type": "rate", "better": "lower",
     "num": "api_errors", "den": "turns", "weight": 1, "kinds": KINDS,
     "what": "Model turns that hit an API error, over all model turns. Quota and rate limits are not errors."},
    {"key": "bad_markers", "label": "Failed checks per invocation", "unit": "count", "type": "count", "better": "lower",
     "num": "bad", "den": "inv", "weight": 1, "kinds": KINDS,
     "what": "Config markers whose value is declared bad. A marker used as the outcome is counted there instead."},
]
MEASURE = {m["key"]: m for m in MEASURES}
SHRINK = 2          # pseudo-runs at the skill's own value that every version starts with
MAX_RATIO = 2.0     # one measure counts for at most this factor either way
FLOOR = 0.5         # fraction of the skill's own rate added to both sides of a rate ratio, so zeros stay finite
TURN_CAP = 600.0    # seconds: the gap between two model turns counts for at most this long
RESAMPLES = 4000    # bootstrap resamples per interval: the expanded tails at n = 5 are 0.1% each, so many are needed
MIN_RUNS = 5        # runs needed on each side before a verdict is given
CONFIDENCE = 0.95   # central interval of the bootstrap difference
MIX_SHIFT = 0.3     # smallest total variation distance between two sides' mixes that counts as a confounder
MIX_NOISE = 1.5     # ... and at least MIX_NOISE / sqrt(runs on the smaller side): two samples of one mix differ by chance
ALL_PAIRS = 6       # with at most this many versions every pair is compared, else consecutive ones only
DIFF_LINES = 800    # longest diff kept per changed skill
CLIP = math.log(MAX_RATIO)
ONCE = "roles seen in one run"
SKIP_INCIDENTS = {"bad_marker", "idle_loop", "error_streak"}
NEVER = datetime.min.replace(tzinfo=timezone.utc)
FAR = datetime.max.replace(tzinfo=timezone.utc)
VERDICTS = ("better", "worse", "no clear change", "not enough runs", "confounded")


# ---- settings from config.toml ---------------------------------------------------------

def parse_groups(groups):
    """Validate the [[group]] tables. A member is "skill:<name>" or "agent:<type>"."""
    out, seen = [], set()
    for g in groups or []:
        name = str(g.get("name") or "").strip()
        members = g.get("members") or []
        if not name or not members:
            raise ValueError("every [[group]] needs a name and at least one member")
        if name in seen:
            raise ValueError(f"group {name!r} is defined twice")
        seen.add(name)
        skills, types, listed = set(), set(), []
        for m in members:
            kind, _, value = str(m).partition(":")
            value = value.strip()
            if kind == "skill" and value:
                skills.add(value)
                listed.append(f"skill:{value}")
            elif kind == "agent" and value:
                types.add(value)
                listed.append(f"agent:{value}")
            else:
                raise ValueError(f"group {name!r}: member {m!r} must be 'skill:<name>' or 'agent:<type>'")
        out.append({"id": f"group:{name}", "name": name, "skills": skills, "types": types, "members": listed})
    return out


def parse_outcomes(raw, markers=()):
    """[outcome] (one table) or [[outcome]] (several): what a successful run of a skill looks like.

    marker = "<[[marker]] name>"   success = [values]   failure = [values] (default: the marker's bad values)
    or pr = "opened"               (Claude Code records the PR a session opened; whether it was merged is not recorded)
    skills = [names]               the skills (and groups containing them) it judges; [] = every skill and group.
    With `skills` set, every such marker in a session counts for the skill, whoever printed it."""
    entries = [raw] if isinstance(raw, dict) else list(raw or [])
    known = {m.get("name"): m for m in markers or []}
    out = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise ValueError(f"[outcome] #{i + 1} must be a table")
        skills = [str(s) for s in e.get("skills") or []]
        if e.get("pr") is not None:
            if e["pr"] != "opened":
                raise ValueError("[outcome] pr: only \"opened\" is recorded (Claude Code's pr-link); merge state is not")
            out.append({"kind": "pr", "name": e.get("name") or "PR opened", "skills": skills, "marker": None,
                        "success": set(), "failure": set()})
            continue
        marker = e.get("marker")
        if not marker:
            raise ValueError(f"[outcome] #{i + 1} needs marker = \"<name>\" or pr = \"opened\"")
        if known and marker not in known:
            raise ValueError(f"[outcome] marker {marker!r} is not a [[marker]] in config.toml")
        success = {str(v) for v in e.get("success") or []}
        if not success:
            raise ValueError(f"[outcome] {marker}: list the values that mean success, e.g. success = [\"PASS\"]")
        bad = (known.get(marker) or {}).get("bad")
        failure = {str(v) for v in (e.get("failure") or (bad if isinstance(bad, list) else []))}
        out.append({"kind": "marker", "name": e.get("name") or f"{marker} first-pass rate", "skills": skills,
                    "marker": marker, "success": success, "failure": failure})
    return out


def parse_weights(raw):
    """[weights]: measure = weight sets the default; [weights.<skill or group name>] overrides it for one unit."""
    default, units = {}, {}
    for key, value in (raw or {}).items():
        if isinstance(value, dict):
            units[key] = {k: _weight(k, v, key) for k, v in value.items()}
        else:
            default[key] = _weight(key, value)
    return {"default": default, "units": units}


def _weight(key, value, unit=None):
    where = f"[weights.{unit}]" if unit else "[weights]"
    if key not in MEASURE:
        raise ValueError(f"{where} {key}: unknown measure (known: {', '.join(MEASURE)})")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{where} {key}: a weight is a number >= 0")
    return float(value)


def settings(cfg=None, groups=None):
    """Everything config.toml can change about the method, validated."""
    cfg = cfg or {}
    method = cfg.get("method") or {}
    s = {
        "groups": parse_groups(cfg.get("group", []) if groups is None else groups),
        "outcomes": parse_outcomes(cfg.get("outcome"), cfg.get("marker", [])),
        "weights": parse_weights(cfg.get("weights")),
        "min_runs": int(method.get("min_runs", MIN_RUNS)),
        "resamples": int(method.get("resamples", RESAMPLES)),
        "confidence": float(method.get("confidence", CONFIDENCE)),
        "cc_version": method.get("cc_version", "patch"),
        "auto_groups": bool(method.get("auto_groups", True)),
    }
    if s["min_runs"] < 2:
        raise ValueError("[method] min_runs must be at least 2")
    if s["resamples"] < 100:
        raise ValueError("[method] resamples must be at least 100")
    if not 0.5 <= s["confidence"] < 1:
        raise ValueError("[method] confidence must be between 0.5 and 1, e.g. 0.95")
    if s["cc_version"] not in ("minor", "patch"):
        raise ValueError("[method] cc_version must be \"minor\" or \"patch\"")
    return s


# ---- estimates, the score and the bootstrap -------------------------------------------

def internal(m, sums):
    """A measure's estimate on its own scale (mean log for log measures), from (Σnum, Σden), or None."""
    num, den = sums
    return num / den if den > 0 else None


def display(m, x):
    """An internal estimate in the measure's unit: dollars, seconds, a share or a count."""
    if x is None:
        return None
    if m["type"] == "log":
        return max(0.0, math.exp(x) - m["offset"])
    return x * m.get("scale", 1)


def shrunk(sums, base, pseudo):
    """(Σnum + K·b) / (Σden + K) with K = SHRINK pseudo-runs of `pseudo` denominator each at the skill's value b."""
    num, den = sums
    if den <= 0:
        return None
    k = SHRINK * pseudo
    return (num + k * base) / (den + k)


def ell(m, ref, val, base):
    """ln(ref / val) on the measure's scale, clipped; positive means `val` is better. None when it cannot be told."""
    if ref is None or val is None or base is None:
        return None
    if m["type"] == "log":
        x = ref - val
    else:
        if m["better"] == "higher":
            ref, val, base = 1 - ref, 1 - val, 1 - base
        if base <= 0:
            return None  # the event never happened in this skill: no information either way
        f = FLOOR * base
        x = math.log((ref + f) / (val + f))
    return max(-CLIP, min(CLIP, x))


def composite(ref_est, val_est, base, weights):
    """Σ w·l / Σ w over the measures known on both sides, and each l."""
    acc = wsum = 0.0
    parts = {}
    for key, w in weights.items():
        lx = ell(MEASURE[key], ref_est.get(key), val_est.get(key), base.get(key))
        if lx is None:
            continue
        parts[key] = lx
        if w > 0:
            acc += w * lx
            wsum += w
    return (acc / wsum if wsum else None), parts


def quantile(xs, q):
    """Linear interpolation between the sorted values xs."""
    i = q * (len(xs) - 1)
    lo = math.floor(i)
    return xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (i - lo)


def t_quantile(p, df):
    """Student's t quantile without scipy: exact for 1 and 2 degrees of freedom, else the Cornish-Fisher
    expansion of Abramowitz & Stegun 26.7.5 (within 0.2% of the table from 3 degrees of freedom up)."""
    if df == 1:
        return math.tan(math.pi * (p - 0.5))
    if df == 2:
        return (2 * p - 1) / math.sqrt(2 * p * (1 - p))
    z = NormalDist().inv_cdf(p)
    v = float(df)
    return (z + (z ** 3 + z) / (4 * v) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * v ** 2)
            + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * v ** 3)
            + (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / (92160 * v ** 4))


def tail(confidence, n):
    """The probability each end of a percentile interval cuts off, expanded for a small sample.

    A plain percentile bootstrap is too narrow with a handful of runs: on real runs split at random into two
    pseudo-versions of 5 or more runs each, a 95% interval called a change 13% of the time, and 16% when 5-7
    runs faced a larger side. The expanded percentile interval (Hesterberg 2015, "What teachers should know
    about the bootstrap", The American Statistician 69(4)) uses sqrt(n / (n - 1)) x t(n - 1) in place of z,
    with n the smaller side; on the same splits it calls a change 4-5.5% of the time, about the nominal 5%."""
    if n < 2:
        return (1 - confidence) / 2
    z = math.sqrt(n / (n - 1)) * t_quantile(1 - (1 - confidence) / 2, n - 1)
    return 1 - NormalDist().cdf(z)


class Arm:
    """The runs of one side of a comparison, as per-run (num, den) vectors so a resample is a few C-level sums."""

    def __init__(self, rows, keys):
        self.keys = keys
        self.rows = [tuple(float(r.get(MEASURE[k]["num"]) or 0.0) if j == 0 else float(r.get(MEASURE[k]["den"]) or 0.0)
                           for k in keys for j in (0, 1)) for r in rows]
        self.n = len(self.rows)

    def sums(self, rows=None):
        cols = list(zip(*(rows if rows is not None else self.rows)))
        return [sum(c) for c in cols] if cols else [0.0] * (2 * len(self.keys))

    def estimates(self, sums, base, pseudo, shrink=True):
        out = {}
        for i, k in enumerate(self.keys):
            s = (sums[2 * i], sums[2 * i + 1])
            out[k] = shrunk(s, base[k], pseudo[k]) if shrink else internal(MEASURE[k], s)
        return {k: v for k, v in out.items() if v is not None}

    def draw(self, rng):
        return self.sums(rng.choices(self.rows, k=self.n))


def compare(rows_a, rows_b, base, pseudo, weights, seed, resamples=RESAMPLES, confidence=CONFIDENCE, interval=True):
    """B against A: the weighted difference D (positive: B is better), its bootstrap interval, and per measure
    A, B, the effect exp(l) and its interval. Runs are resampled within each side, so a run's invocations stay together.

    The difference is taken between the two sides' own estimates, not shrunk ones: shrinking both toward the
    skill's value with different run counts would make two sides with no events look different."""
    keys = [k for k in weights if k in base]
    a, b = Arm(rows_a, keys), Arm(rows_b, keys)
    raw_a, raw_b = a.estimates(a.sums(), base, pseudo, shrink=False), b.estimates(b.sums(), base, pseudo, shrink=False)
    d, parts = composite(raw_a, raw_b, base, weights)
    out = {"d": d, "ci": None, "measures": {}, "outcome": None}
    draws, mdraws, odraws = [], defaultdict(list), []
    if interval and a.n and b.n and d is not None:
        rng = random.Random(seed)
        for _ in range(resamples):
            ea, eb = a.estimates(a.draw(rng), base, pseudo, False), b.estimates(b.draw(rng), base, pseudo, False)
            dd, pp = composite(ea, eb, base, weights)
            if dd is not None:
                draws.append(dd)
            for k, v in pp.items():
                mdraws[k].append(v)
            if ea.get("outcome") is not None and eb.get("outcome") is not None:
                odraws.append(eb["outcome"] - ea["outcome"])
    lo_q = tail(confidence, min(n_runs(rows_a), n_runs(rows_b)))
    hi_q = 1 - lo_q
    ci = lambda xs: [quantile(xs, lo_q), quantile(xs, hi_q)] if len(xs) >= 20 else None
    if draws:
        out["ci"] = ci(sorted(draws))
    for k in keys:
        m = MEASURE[k]
        if k not in parts:
            continue
        mci = ci(sorted(mdraws[k])) if mdraws.get(k) else None
        out["measures"][k] = {"a": display(m, raw_a.get(k)), "b": display(m, raw_b.get(k)), "effect": math.exp(parts[k]),
                              "ci": [math.exp(mci[0]), math.exp(mci[1])] if mci else None, "weight": weights[k]}
    if raw_a.get("outcome") is not None and raw_b.get("outcome") is not None:
        out["outcome"] = {"a": raw_a["outcome"], "b": raw_b["outcome"], "value": raw_b["outcome"] - raw_a["outcome"],
                          "ci": ci(sorted(odraws)) if odraws else None}
    return out


def n_runs(rows):
    """Distinct sessions among run rows (a session that used two versions has a row in each)."""
    return len({r.get("sid") or r.get("session") or i for i, r in enumerate(rows)})


def verdict_of(d_ci, n_a, n_b, confounders, min_runs=MIN_RUNS):
    """(verdict, direction): direction is what the interval alone says; verdict adds the run count and confounders."""
    if n_a < min_runs or n_b < min_runs:
        return "not enough runs", None
    if not d_ci:
        return "not enough runs", None
    direction = "better" if d_ci[0] > 0 else "worse" if d_ci[1] < 0 else "no clear change"
    return ("confounded" if confounders else direction), direction


# ---- versions and diffs ----------------------------------------------------------------

def short(digest):
    """A version's display name: its hash, or 'unversioned' when Claude Code never recorded the skill text."""
    return "unversioned" if digest is None else digest[:8]


def version_key(vmap):
    """A run's version: the version of each skill it belongs to, as one string."""
    if not vmap:
        return "-"
    return "|".join(f"{s}={h or 'unversioned'}" for s, h in sorted(vmap.items()))


def diff_entry(skill, old, new, texts):
    """What changed for one skill between two versions: counts and the diff lines."""
    entry = {"skill": skill, "from": short(old), "to": short(new),
             "added": 0, "removed": 0, "lines": None, "truncated": False, "note": None}
    old_text = texts.get((skill, old)) if old else None
    new_text = texts.get((skill, new)) if new else None
    if not old or not new:
        entry["note"] = "There is no earlier version of this skill in your history, so there is nothing to diff against."
    elif old_text is None or new_text is None:
        entry["note"] = "The text of this version is not recorded yet. Run `runlens refresh` to record it."
    else:
        raw = list(difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), n=2, lineterm=""))[2:]
        lines = []
        for line in raw:
            if line.startswith("@@"):
                lines.append(["@", line])
            elif line.startswith("+"):
                lines.append(["+", line[1:]])
                entry["added"] += 1
            elif line.startswith("-"):
                lines.append(["-", line[1:]])
                entry["removed"] += 1
            else:
                lines.append([" ", line[1:]])
        entry["truncated"] = len(lines) > DIFF_LINES
        entry["lines"] = lines[:DIFF_LINES]
    return entry


def changes(prev, cur, texts):
    """The skills whose version differs between two version maps."""
    return [diff_entry(s, prev.get(s), cur.get(s), texts)
            for s in sorted(set(prev) | set(cur)) if prev.get(s) != cur.get(s)]


# ---- confounders -----------------------------------------------------------------------

def shift(a, b):
    """Total variation distance between two weighted mixes (Counters): 0 = the same mix, 1 = nothing in common."""
    ta, tb = sum(a.values()), sum(b.values())
    if not ta or not tb:
        return 0.0
    return 0.5 * sum(abs(a[k] / ta - b[k] / tb) for k in set(a) | set(b))


def _top_change(a, b):
    """The member of a mix whose share moved most, as 'name x% → y%'. On a tie, the one that grew."""
    ta, tb = sum(a.values()) or 1, sum(b.values()) or 1
    moved = lambda x: b[x] / tb - a[x] / ta
    k = max(sorted(set(a) | set(b)), key=lambda x: (round(abs(moved(x)), 9), moved(x) > 0))
    return f"{k} {a[k] / ta:.0%} → {b[k] / tb:.0%}"


def _mode(c):
    """The most common member of a mix; on a tie, the first by name."""
    return max(sorted(c), key=lambda k: c[k])


def model_id(model):
    """The full model id: haiku-4-5 and haiku-5-5 are different models."""
    return model or "unknown"


def cc_level(version, level):
    if not version:
        return "unknown"
    return version if level == "patch" else ".".join(version.split(".")[:2])


def mix_threshold(n):
    """Total variation distance two mixes must reach to count as shifted: it grows as there are fewer runs."""
    return max(MIX_SHIFT, MIX_NOISE / math.sqrt(max(n, 1)))


def confounders_of(side_a, side_b, own_skills, ctx):
    """What else differed between two sets of runs. `side_*` are run rows with their context."""
    out = []
    sids_a = sorted({r["sid"] for r in side_a})
    sids_b = sorted({r["sid"] for r in side_b})
    limit = mix_threshold(min(len(sids_a), len(sids_b)))
    versions = ctx["session_versions"]
    others = set()
    for sid in sids_a + sids_b:
        others |= set(versions.get(sid, {}))
    for s in sorted(others - set(own_skills)):
        ha = Counter(short(versions[sid][s]) for sid in sids_a if s in versions.get(sid, {}))
        hb = Counter(short(versions[sid][s]) for sid in sids_b if s in versions.get(sid, {}))
        if ha and hb and shift(ha, hb) >= mix_threshold(min(sum(ha.values()), sum(hb.values()))):
            out.append(f"{s} also changed ({_top_change(ha, hb)})")
    mix = lambda rows, field: sum((r[field] for r in sorted(rows, key=lambda r: r["sid"])), Counter())
    for field, what in (("models", "model mix (share of main-agent cost)"), ("efforts", "effort mix (share of turns)")):
        a, b = mix(side_a, field), mix(side_b, field)
        if shift(a, b) >= limit:
            out.append(f"{what}: {_top_change(a, b)}")
    runs = ctx["sessions"]
    for field, what in (("cc", "Claude Code version"), ("repo", "project mix")):
        a = Counter(ctx["run_attr"](runs.get(sid), field) for sid in sids_a)
        b = Counter(ctx["run_attr"](runs.get(sid), field) for sid in sids_b)
        if shift(a, b) >= limit:
            top_a, top_b = _mode(a), _mode(b)
            if field == "cc" and top_a != top_b:
                out.append(f"Claude Code {top_a} → {top_b}")
            else:  # the most common value is the same on both sides: name the one whose share moved
                out.append(f"{what}: {_top_change(a, b)}")
    return out


# ---- skill sets found in the history ----------------------------------------------------

SET_OVERLAP = 0.8  # share of the rarer skill's runs that must also use the other skill


def skill_sets(session_versions, sessions, taken=(), min_runs=MIN_RUNS):
    """Sets of skills used and edited together, to score as one unit next to each skill on its own.

    Two skills are linked when at least `min_runs` runs use both, at least SET_OVERLAP of the rarer one's runs
    also use the other, and a new version of each (not its first) appeared in the same run: they were edited together.
    A set is a group of linked skills (single linkage) with two or more members; a set with the same skills as a
    [[group]] in config.toml (`taken`) is left out. Returns [[group]]-shaped dicts marked auto."""
    order = sorted(sessions, key=lambda sid: (sessions[sid].get("started") or NEVER, sid))
    runs, first = defaultdict(set), {}
    for sid in order:
        for skill, h in session_versions.get(sid, {}).items():
            runs[skill].add(sid)
            if h:
                first.setdefault((skill, h), sid)
    # run -> skills with a new version first seen in it. A skill's first version is not an edit: when the history
    # starts, every skill shows up at once.
    pos = {sid: i for i, sid in enumerate(order)}
    opening = {}
    for (skill, _h), sid in first.items():
        if skill not in opening or pos[sid] < pos[opening[skill]]:
            opening[skill] = sid
    born = defaultdict(set)
    for (skill, _h), sid in first.items():
        if sid != opening[skill]:
            born[sid].add(skill)
    edited = defaultdict(set)
    for skills in born.values():
        for a in skills:
            edited[a] |= skills - {a}
    parent = {}

    def root(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for a in sorted(runs):
        for b in sorted(edited[a]):
            if b <= a or b not in runs:
                continue
            both = len(runs[a] & runs[b])
            if both >= min_runs and both >= SET_OVERLAP * min(len(runs[a]), len(runs[b])):
                parent[root(b)] = root(a)
    members = defaultdict(set)
    for skill in set(parent) | set(parent.values()):
        members[root(skill)].add(skill)
    out = []
    for skills in sorted(members.values(), key=lambda m: sorted(m)):
        if len(skills) < 2 or frozenset(skills) in taken:
            continue
        names = sorted(skills)
        prefix = os.path.commonprefix(names)
        stem = prefix.rstrip("-_:. ")
        name = f"{prefix}* set" if len(stem) >= 2 or (stem and prefix != stem) else f"{names[0]} + {len(names) - 1} more"
        out.append({"id": f"group:{name}", "name": name, "skills": set(skills), "types": set(),
                    "members": [f"skill:{n}" for n in names], "auto": True})
    return out


# ---- the computation -------------------------------------------------------------------

def compute(data, groups=None, resamples=None, cfg=None):
    """`data` holds the rows read by `load`; `cfg` is config.toml (outcome, weights, groups, method).
    Returns the model the dashboard renders and the CLI prints."""
    st = settings(cfg, groups if groups else None)
    if resamples is not None:
        st["resamples"] = resamples
    groups = st["groups"]
    group_of = {g["id"]: g for g in groups}
    texts = {(t["skill"], t["content_hash"]): t["text"] for t in data.get("texts", [])}

    # Population: finished runs that are not stubs.
    sessions, excluded = {}, Counter()
    for r in data["runs"]:
        if (r.get("status") or "complete") != "complete":
            excluded["open"] += 1
        elif r.get("is_stub"):
            excluded["stub"] += 1
        else:
            sessions[r["session_id"]] = r
    kept = lambda rows: [x for x in rows if x["session_id"] in sessions]

    # Agent roles; a role seen in a single run joins its type's "roles seen in one run".
    role_runs = defaultdict(set)
    for a in kept(data["agents"]):
        if a["agent_id"] != "main":
            role_runs[(a["agent_type"] or "?", a["role"] or "-")].add(a["session_id"])
    agent_of, agent_desc, spawns = {}, {}, defaultdict(set)
    for a in kept(data["agents"]):
        if a["agent_id"] == "main":
            continue
        t, role = a["agent_type"] or "?", a["role"] or "-"
        # With a single run in the history every role is "seen once"; folding them would only hide them.
        ident = (t, role if len(role_runs[(t, role)]) >= 2 or len(sessions) < 2 else ONCE)
        agent_of[(a["session_id"], a["agent_id"])] = ident
        agent_desc.setdefault((a["session_id"], *ident), a.get("description"))
        spawns[(f"agent:{ident[0]}|{ident[1]}", a["session_id"])].add(a["agent_id"])

    # Skill versions and invocations. Each piece of work belongs to the invocation (skill load) it ran under:
    # the latest load of that skill by the same agent, else the latest in the session. Work under a skill the
    # session never loaded (a subagent inherits it) uses the version that was current when the run started.
    timeline = defaultdict(list)
    for r in sorted((x for x in data["loads"] if x["ts"]), key=lambda x: x["ts"]):
        timeline[r["skill"]].append((r["ts"], r["content_hash"]))
    load_ts = {s: [t for t, _ in v] for s, v in timeline.items()}

    def version_before(skill, ts):
        if ts is None or skill not in timeline:
            return None
        i = bisect.bisect_right(load_ts[skill], ts)
        return timeline[skill][i - 1][1] if i else None

    loads = defaultdict(list)
    session_versions = defaultdict(dict)
    first_args = {}
    for r in sorted(kept(data["loads"]), key=lambda x: (x["ts"] or NEVER)):
        k = (r["session_id"], r["skill"])
        loads[k].append((r["ts"], r["agent_id"], r["content_hash"], len(loads[k])))
        session_versions[r["session_id"]][r["skill"]] = r["content_hash"]
        if r.get("args"):
            first_args.setdefault(k, r["args"])

    # Skills used and edited together are also scored as one set, unless a [[group]] already covers them.
    if st["auto_groups"]:
        names = {g["name"] for g in groups}
        found = skill_sets(session_versions, sessions, {frozenset(g["skills"]) for g in groups if not g["types"]}, st["min_runs"])
        groups = groups + [g for g in found if g["name"] not in names]
        group_of = {g["id"]: g for g in groups}

    def invocation(sid, agent, ts, skill):
        """(invocation key, version hash) of a piece of work done under `skill`."""
        lst = loads.get((sid, skill))
        if not lst:
            return (sid, skill, "-"), version_before(skill, sessions[sid].get("started"))
        same = other = None
        for t, ag, h, i in lst:
            if ts is not None and t is not None and t > ts:
                break
            if ag == agent:
                same = (t, ag, h, i)
            other = (t, ag, h, i)
        hit = same or other or lst[0]
        return (sid, skill, hit[3]), hit[2]

    def group_vmap(gid, sid):
        g = group_of[gid]
        return {s: session_versions[sid].get(s) or version_before(s, sessions[sid].get("started")) for s in sorted(g["skills"])}

    def place(sid, agent, ts, skill):
        """Every (unit, version key, invocation key) a piece of work belongs to; it is counted once per unit."""
        out = []
        if skill:
            inv, h = invocation(sid, agent, ts, skill)
            out.append((f"skill:{skill}", version_key({skill: h}), inv))
        ident = agent_of.get((sid, agent))
        if ident:
            out.append((f"agent:{ident[0]}|{ident[1]}", "-", (sid, agent)))
        for g in groups:
            if (skill and skill in g["skills"]) or (ident and ident[0] in g["types"]):
                out.append((g["id"], version_key(group_vmap(g["id"], sid)), sid))
        return out

    # Human prompts count against the skill the main agent was running when they arrived.
    turns = defaultdict(list)
    for a in sorted((x for x in kept(data["api"]) if x["agent_id"] == "main" and x["ts"]), key=lambda x: x["ts"]):
        turns[a["session_id"]].append((a["ts"], a["skill"]))
    turn_ts = {s: [t for t, _ in v] for s, v in turns.items()}

    def active_skill(sid, ts):
        i = bisect.bisect_right(turn_ts.get(sid, []), ts)
        return turns[sid][i - 1][1] if i else None

    # Time: the gap from each model turn to the same agent's next turn, capped.
    api = kept(data["api"])
    seconds = [0.0] * len(api)
    chains = defaultdict(list)
    for i, a in enumerate(api):
        if a["ts"]:
            chains[(a["session_id"], a["agent_id"])].append((a["ts"], i))
    for chain in chains.values():
        chain.sort()
        for (t, i), (t_next, _) in zip(chain, chain[1:]):
            seconds[i] = min(TURN_CAP, max(0.0, (t_next - t).total_seconds()))

    acc = {}

    def cell(uid, sid, vkey):
        k = (uid, sid, vkey)
        if k not in acc:
            acc[k] = {"cost": 0.0, "seconds": 0.0, "turns": 0, "api_errors": 0, "calls": 0, "call_errors": 0, "idle": 0,
                      "incidents": 0, "bad": 0, "prompts": 0, "lines": 0, "inv": defaultdict(lambda: [0.0, 0.0]),
                      "loads": set(), "marks": [], "models": Counter(), "efforts": Counter()}
        return acc[k]

    for i, a in enumerate(api):
        for uid, vkey, inv in place(a["session_id"], a["agent_id"], a["ts"], a["skill"]):
            c = cell(uid, a["session_id"], vkey)
            cost = a["cost_usd"] or 0.0
            c["turns"] += 1
            c["cost"] += cost
            c["seconds"] += seconds[i]
            c["api_errors"] += bool(a["api_error"])
            c["inv"][inv][0] += cost
            c["inv"][inv][1] += seconds[i]
            if a["agent_id"] == "main":  # the skill's own subagents are part of its effect, not a confounder
                c["models"][model_id(a.get("model"))] += cost
            c["efforts"][a.get("effort") or "default"] += 1
    for t in kept(data["tools"]):
        for uid, vkey, _ in place(t["session_id"], t["agent_id"], t.get("ts"), t["skill"]):
            c = cell(uid, t["session_id"], vkey)
            c["calls"] += 1
            c["call_errors"] += bool(t["is_error"]) and not t.get("denied")
            c["idle"] += bool(t["idle"])
            c["lines"] += (t.get("patch_added") or 0) + (t.get("patch_removed") or 0)
    for x in kept(data["incidents"]):
        if x.get("type") in SKIP_INCIDENTS or x.get("policy") or x.get("label") == "expected_behavior":
            continue
        for uid, vkey, _ in place(x["session_id"], x["agent_id"], x.get("ts"), x["skill"]):
            cell(uid, x["session_id"], vkey)["incidents"] += 1
    for p in kept(data["prompts"]):
        skill = active_skill(p["session_id"], p["ts"]) if p["ts"] else None
        if skill:
            for uid, vkey, _ in place(p["session_id"], "main", p["ts"], skill):
                if not uid.startswith("agent:"):
                    cell(uid, p["session_id"], vkey)["prompts"] += 1

    # Invocations as loaded (what "n invocations" counts), separate from the ones that did attributed work.
    for (sid, skill), lst in loads.items():
        for _t, _ag, h, i in lst:
            cell(f"skill:{skill}", sid, version_key({skill: h}))["loads"].add(i)

    # Outcomes.
    outcomes = st["outcomes"]

    def outcome_for(uid):
        kind, _, rest = uid.partition(":")
        if kind == "agent":
            return None
        own = {rest} if kind == "skill" else group_of[uid]["skills"]
        for o in outcomes:
            if o["skills"] and own & set(o["skills"]):
                return o
        return next((o for o in outcomes if not o["skills"]), None)

    outcome_markers = {o["marker"] for o in outcomes if o["kind"] == "marker"}
    for x in kept(data["markers"]):
        if x.get("bad") and x.get("marker") not in outcome_markers:
            for uid, vkey, _ in place(x["session_id"], x["agent_id"], x.get("ts"), x["skill"]):
                cell(uid, x["session_id"], vkey)["bad"] += 1
        if x.get("marker") not in outcome_markers:
            continue
        targets = place(x["session_id"], x["agent_id"], x.get("ts"), x["skill"])
        for o in outcomes:
            if o["marker"] == x["marker"] and o["skills"]:
                for s in o["skills"]:
                    if (x["session_id"], s) in loads:
                        targets += place(x["session_id"], x["agent_id"], x.get("ts"), s)
        done = set()
        for uid, vkey, _ in targets:
            o = outcome_for(uid)
            if o and o["marker"] == x["marker"] and (uid, vkey) not in done:
                done.add((uid, vkey))
                cell(uid, x["session_id"], vkey)["marks"].append((x.get("ts") or NEVER, str(x.get("value"))))

    def outcome_counts(uid, sid, c):
        """(first-pass successes, eventual successes, attempts). A chain of checks ends at a success."""
        o = outcome_for(uid)
        if not o:
            return None, None, None
        if o["kind"] == "pr":
            ok = int(bool(sessions[sid].get("pr_urls")))
            return ok, ok, 1
        first = eventual = n = 0
        length = 0
        for _, value in sorted(c["marks"], key=lambda m: m[0]):
            good = value in o["success"]
            if not good and o["failure"] and value not in o["failure"]:
                continue  # a value that is neither (e.g. "not comparable")
            length += 1
            if good:
                n += 1
                eventual += 1
                first += length == 1
                length = 0
        if length:
            n += 1  # a chain that never passed
        return first, eventual, n

    def repo_of(sid):
        cwd = (sessions.get(sid, {}).get("repo") or "").rstrip("\\/")
        return re.split(r"[\\/]", cwd)[-1] or None

    def run_attr(run, field):
        if run is None:
            return "unknown"
        if field == "cc":
            return cc_level(run.get("cc_version"), st["cc_version"])
        return repo_of(run["session_id"]) or "unknown"

    # One row per (unit, session, version).
    unit_rows = defaultdict(list)
    for (uid, sid, vkey), c in acc.items():
        kind = uid.split(":", 1)[0]
        inv = c["inv"].values()
        os_, oe, on = outcome_counts(uid, sid, c)
        if kind == "skill":
            n_inv = len(c["loads"]) or (1 if c["inv"] else 0)
        elif kind == "agent":
            n_inv = len(spawns.get((uid, sid), ())) or len(c["inv"])
        else:
            n_inv = 1
        if not c["inv"] and not c["calls"] and not c["marks"] and kind != "skill":
            continue
        if kind == "skill" and not c["inv"] and not c["calls"] and not c["marks"] and not c["prompts"]:
            continue  # a load whose work Claude Code attributed to another skill: nothing to measure here
        vmap = {}
        if kind == "skill":
            vmap = {uid.split(":", 1)[1]: (None if vkey.endswith("=unversioned") else vkey.split("=", 1)[1])}
        elif kind == "group":
            vmap = group_vmap(uid, sid)
        unit_rows[uid].append({
            "sid": sid, "vkey": vkey, "vmap": vmap, "started": sessions[sid].get("started"),
            "inv": len(inv), "invocations": n_inv,
            "lc": sum(math.log(x[0] + MEASURE["cost"]["offset"]) for x in inv),
            "ls": sum(math.log(x[1] + MEASURE["seconds"]["offset"]) for x in inv),
            "cost": c["cost"], "seconds": c["seconds"], "turns": c["turns"], "api_errors": c["api_errors"],
            "calls": c["calls"], "call_errors": c["call_errors"], "idle": c["idle"], "incidents": c["incidents"],
            "interventions": c["prompts"] if kind != "agent" else None, "bad": c["bad"], "lines": c["lines"],
            "os": os_, "oe": oe, "on": on, "models": c["models"], "efforts": c["efforts"],
        })

    ctx = {"session_versions": session_versions, "sessions": sessions, "run_attr": run_attr}

    def name_of(uid):
        kind, _, rest = uid.partition(":")
        if kind == "agent":
            t, _, role = rest.partition("|")
            return f"{t} · {role}"
        return group_of[uid]["name"] if kind == "group" else rest

    def task_of(uid, kind, sid):
        if kind == "agent":
            t, _, role = uid.split(":", 1)[1].partition("|")
            text = agent_desc.get((sid, t, role)) if role != ONCE else None
        elif kind == "skill":
            text = first_args.get((sid, uid.split(":", 1)[1]))
        else:
            text = next((first_args[(sid, s)] for s in sorted(group_of[uid]["skills"]) if (sid, s) in first_args), None)
        return text or sessions.get(sid, {}).get("title")

    units, versions_out, runs_out, pairs_out = [], {}, {}, {}
    for uid in sorted(set(unit_rows) | {g["id"] for g in groups}):
        kind, _, rest = uid.partition(":")
        rows = unit_rows.get(uid, [])
        o = outcome_for(uid)
        keys = [m["key"] for m in MEASURES if kind in m["kinds"] and (m["key"] != "outcome" or o)]
        base, pseudo = {}, {}
        for k in keys:
            m = MEASURE[k]
            num = sum(r[m["num"]] or 0 for r in rows)
            den = sum(r[m["den"]] or 0 for r in rows)
            runs_with = sum(1 for r in rows if r[m["den"]])
            if den > 0:
                base[k] = num / den
                pseudo[k] = den / runs_with
        weights = unit_weights(st["weights"], uid, name_of(uid), keys)
        weights = {k: w for k, w in weights.items() if k in base}
        own_skills = {rest} if kind == "skill" else (group_of[uid]["skills"] if kind == "group" else set())
        units_entry, vlist = describe_unit(uid, kind, name_of(uid), rows, base, pseudo, weights, o, group_of, st["min_runs"])

        if kind in VERSIONED:
            by_version = defaultdict(list)
            for r in rows:
                by_version[r["vkey"]].append(r)
            ordered = sorted(by_version.items(), key=lambda kv: min((r["started"] or FAR) for r in kv[1]))
            prev_vmap = None
            for i, (vkey, xs) in enumerate(ordered):
                vmap = xs[0]["vmap"]
                vlist.append(version_entry(uid, i, vkey, vmap, xs, base, pseudo, weights, o, st,
                                           changes(prev_vmap, vmap, texts) if prev_vmap is not None else []))
                prev_vmap = vmap
            pairs = []
            idx = [(i - 1, i) for i in range(1, len(ordered))]
            if len(ordered) <= ALL_PAIRS:
                idx = [(i, j) for j in range(len(ordered)) for i in range(j)]
            for i, j in idx:
                pairs.append(pair_entry(uid, vlist[i], vlist[j], ordered[i][1], ordered[j][1], base, pseudo, weights,
                                        own_skills, ctx, st))
            for p in pairs:
                if p["vs_previous"]:
                    v = next(x for x in vlist if x["label"] == p["b"])
                    v.update(verdict=p["verdict"], direction=p["direction"], vs=p["a"], difference=p["difference"],
                             confounders=p["confounders"])
                    v["delta"] = (v["score"] - vlist[vlist.index(v) - 1]["score"]
                                  if v["score"] is not None and vlist[vlist.index(v) - 1]["score"] is not None else None)
            pairs_out[uid] = pairs
            last = vlist[-1] if vlist else None
            if last:
                units_entry.update(current=last["label"], score=last["score"], ci=last["ci"], verdict=last["verdict"],
                                   vs=last["vs"], delta=last["delta"], difference=last["difference"],
                                   confounders=last["confounders"], direction=last["direction"])
        units_entry["versions"] = len(vlist)
        units.append(units_entry)
        versions_out[uid] = vlist
        label_of = {v["key"]: v["label"] for v in vlist}
        runs_out[uid] = sorted(
            (run_row(r, label_of.get(r["vkey"], "all"), task_of(uid, kind, r["sid"]), repo_of(r["sid"]), kind) for r in rows),
            key=lambda r: r["started"] or NEVER, reverse=True)

    starts = [r["started"] for r in sessions.values() if r.get("started")]
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="minutes"),
        "window": {"first": min(starts, default=None), "last": max(starts, default=None), "runs": len(sessions),
                   "excluded": dict(excluded)},
        "population": {"runs": len(sessions), "open": excluded["open"], "stub": excluded["stub"],
                       "rule": "status = 'complete' AND NOT is_stub"},
        "texts": bool(texts),
        "method": {"metrics": [{**{k: v for k, v in m.items() if k != "kinds"}, "kinds": list(m["kinds"])} for m in MEASURES],
                   "shrink": SHRINK, "max_ratio": MAX_RATIO, "floor": FLOOR, "turn_cap": TURN_CAP,
                   "resamples": st["resamples"], "min_runs": st["min_runs"], "confidence": st["confidence"],
                   "mix_shift": MIX_SHIFT, "cc_version": st["cc_version"],
                   "outcomes": [{"name": o["name"], "kind": o["kind"], "marker": o["marker"], "skills": o["skills"],
                                 "success": sorted(o["success"]), "failure": sorted(o["failure"])} for o in outcomes],
                   "verdicts": list(VERDICTS)},
        "units": units,
        "versions": versions_out,
        "pairs": pairs_out,
        "runs": runs_out,
    }


def unit_weights(cfg_weights, uid, name, keys):
    w = {k: float(MEASURE[k]["weight"]) for k in keys}
    w.update({k: v for k, v in cfg_weights["default"].items() if k in w})
    for alias in (name, uid, uid.split(":", 1)[-1]):
        w.update({k: v for k, v in cfg_weights["units"].get(alias, {}).items() if k in w})
    return w


def sums_of(rows, key):
    m = MEASURE[key]
    return sum(r[m["num"]] or 0 for r in rows), sum(r[m["den"]] or 0 for r in rows)


def extras(rows):
    """Shown, never scored: spend, cost per success and cost per 1,000 changed lines."""
    cost = sum(r["cost"] for r in rows)
    lines = sum(r["lines"] for r in rows)
    wins = sum(r["oe"] or 0 for r in rows) if any(r["on"] is not None for r in rows) else None
    return {"spend": cost, "cost_per_success": cost / wins if wins else None,
            "cost_per_kloc": cost / lines * 1000 if lines else None, "lines": lines,
            "invocations": sum(r["invocations"] for r in rows)}


def outcome_summary(o, rows):
    if not o:
        return None
    s, n = sums_of(rows, "outcome")
    return {"measure": o["name"], "value": s / n if n else None, "n": int(n)}


def describe_unit(uid, kind, name, rows, base, pseudo, weights, o, group_of, min_runs):
    """The unit's descriptive figures (never a verdict across units) and an empty version list to fill."""
    kpi = {m["key"]: display(m, internal(m, sums_of(rows, m["key"]))) for m in MEASURES if m["key"] in base}
    starts = [r["started"] for r in rows if r["started"]]
    entry = {
        "id": uid, "kind": kind, "name": name, "members": group_of[uid]["members"] if kind == "group" else [],
        "auto": bool(group_of[uid].get("auto")) if kind == "group" else False,
        "runs": len({r["sid"] for r in rows}), "invocations": sum(r["invocations"] for r in rows),
        "versions": 0, "current": None, "score": None, "ci": None, "verdict": None, "direction": None, "vs": None,
        "delta": None, "difference": None, "confounders": [], "low_sample": len({r["sid"] for r in rows}) < min_runs,
        "kpi": {**kpi, **extras(rows)}, "outcome": outcome_summary(o, rows),
        "baseline": base, "pseudo": pseudo, "weights": weights,
        "first_seen": min(starts, default=None), "last_seen": max(starts, default=None),
    }
    return entry, []


def version_entry(uid, i, vkey, vmap, xs, base, pseudo, weights, o, st, diffs):
    """One version: its score against the skill's typical run and the interval of that score."""
    keys = list(weights)
    arm = Arm(xs, keys)
    sums = arm.sums()
    est, raw = arm.estimates(sums, base, pseudo), arm.estimates(sums, base, pseudo, shrink=False)
    ref = {k: base[k] for k in keys}
    d, parts = composite(ref, est, base, weights)
    n = len({r["sid"] for r in xs})
    ci = None
    if d is not None and n >= st["min_runs"]:
        rng, draws = random.Random(f"{uid}|{vkey}"), []
        for _ in range(st["resamples"]):
            dd, _ = composite(ref, arm.estimates(arm.draw(rng), base, pseudo), base, weights)
            if dd is not None:
                draws.append(dd)
        draws.sort()
        lo_q = tail(st["confidence"], n)
        ci = [100 * math.exp(quantile(draws, lo_q)), 100 * math.exp(quantile(draws, 1 - lo_q))] if draws else None
    metrics = {}
    for k in keys:
        if k in parts:
            m = MEASURE[k]
            metrics[k] = {"value": display(m, raw.get(k)), "counted": display(m, est.get(k)), "ref": display(m, base[k]),
                          "n": sum(1 for r in xs if r[m["den"]]), "ratio": math.exp(parts[k]), "weight": weights[k]}
    hashes = "+".join(short(h) for _, h in sorted(vmap.items())) or "-"
    starts = [r["started"] for r in xs if r["started"]]
    return {
        "id": uid, "vid": f"{uid}@{hashes}", "label": f"v{i + 1}", "key": vkey,
        "parts": [{"skill": s, "hash": short(h)} for s, h in sorted(vmap.items())],
        "recorded": bool(vmap) and all(h is not None for h in vmap.values()),
        "first_seen": min(starts, default=None), "last_seen": max(starts, default=None),
        "runs": n, "invocations": sum(r["invocations"] for r in xs), "low_sample": n < st["min_runs"],
        "score": 100 * math.exp(d) if d is not None else None, "ci": ci, "metrics": metrics,
        "outcome": outcome_summary(o, xs), "kpi": extras(xs),
        "changes": diffs, "verdict": None, "direction": None, "vs": None, "difference": None, "confounders": [],
        "delta": None, "overlap": None,
    }


def pair_entry(uid, va, vb, rows_a, rows_b, base, pseudo, weights, own_skills, ctx, st):
    """Version B against version A of the same unit: the bootstrap of the difference, confounders and the verdict."""
    n_a, n_b = va["runs"], vb["runs"]
    enough = n_a >= st["min_runs"] and n_b >= st["min_runs"]
    res = compare(rows_a, rows_b, base, pseudo, weights, f"{uid}|{va['key']}|{vb['key']}", st["resamples"],
                  st["confidence"], interval=enough)
    conf = confounders_of(rows_a, rows_b, own_skills, ctx)
    verdict, direction = verdict_of(res["ci"], n_a, n_b, conf, st["min_runs"])
    diff = {"score": 100 * math.exp(res["d"]) if res["d"] is not None else None,
            "ci": [100 * math.exp(x) for x in res["ci"]] if res["ci"] else None,
            "measures": res["measures"], "outcome": res["outcome"]}
    return {"a": va["label"], "b": vb["label"], "vs_previous": int(vb["label"][1:]) - int(va["label"][1:]) == 1,
            "runs_a": n_a, "runs_b": n_b, "invocations_a": va["invocations"], "invocations_b": vb["invocations"],
            "verdict": verdict, "direction": direction, "difference": diff, "confounders": conf}


def run_row(r, version, task, repo, kind):
    """What the page needs to show a run and to recompute any score from it: each measure's num and den."""
    row = {"started": r["started"], "session": r["sid"][:8], "task": _clip(task), "version": version, "repo": repo,
           "inv": r["inv"], "invocations": r["invocations"], "cost": r["cost"], "seconds": r["seconds"],
           "lc": round(r["lc"], 4), "ls": round(r["ls"], 4), "calls": r["calls"], "call_errors": r["call_errors"],
           "idle": r["idle"], "turns": r["turns"], "api_errors": r["api_errors"], "incidents": r["incidents"],
           "interventions": r["interventions"], "bad": r["bad"], "lines": r["lines"]}
    if r["on"] is not None:
        row.update(os=r["os"], oe=r["oe"], on=r["on"])
    return row


def _clip(text, n=300):
    return None if text is None else (text if len(text) <= n else text[: n - 1] + "…")


# ---- summaries for the CLI (the JSON contract the retro skill reads) --------------------

def unit_summary(model, u):
    return {"unit": u["id"], "name": u["name"], "kind": u["kind"], "runs": u["runs"], "invocations": u["invocations"],
            "versions": u["versions"], "current": u["current"], "verdict": u["verdict"], "direction": u["direction"],
            "vs": u["vs"], "confounders": u["confounders"], "outcome": u["outcome"], "difference": _diff_out(u["difference"]),
            "score": u["score"], "ci95": u["ci"],
            "typical": {k: v for k, v in u["kpi"].items() if k in MEASURE},
            "cost_per_success_usd": u["kpi"].get("cost_per_success"), "cost_per_kloc_usd": u["kpi"].get("cost_per_kloc"),
            "spend_usd": u["kpi"].get("spend")}


def _diff_out(diff):
    if not diff:
        return None
    out = {"score": diff["score"], "ci95": diff["ci"],
           "measures": {k: {"a": d["a"], "b": d["b"], "effect": d["effect"], "ci95": d["ci"]} for k, d in diff["measures"].items()}}
    if diff.get("outcome"):
        o = diff["outcome"]
        out["outcome"] = {"a": o["a"], "b": o["b"], "value": o["value"], "ci95": o["ci"]}
    return out


def score_summary(model, kind="skill"):
    units = [unit_summary(model, u) for u in model["units"] if u["kind"] == kind and u["runs"]]
    return {"kind": kind, "population": model["population"], "unit_of_analysis": "invocation",
            "note": "Verdicts compare each unit's current version with its previous one; units are never ranked against each other.",
            "units": units}


def versions_summary(model, uid):
    u = next((x for x in model["units"] if x["id"] == uid), None)
    if u is None:
        return None
    out = []
    for v in model["versions"].get(uid, []):
        mine = [c for c in v["changes"] if c["lines"]]
        diff = "\n".join(("" if op == "@" else op) + text for c in mine for op, text in c["lines"]) if mine else None
        out.append({
            "id": v["vid"], "label": v["label"], "hash": "+".join(p["hash"] for p in v["parts"]) or None,
            "recorded": v["recorded"], "first_seen": v["first_seen"], "last_seen": v["last_seen"],
            "runs": v["runs"], "invocations": v["invocations"], "score": v["score"], "ci95": v["ci"],
            "verdict": v["verdict"], "direction": v["direction"], "vs": v["vs"], "confounders": v["confounders"],
            "difference": _diff_out(v["difference"]), "outcome": v["outcome"],
            "measures": {k: d["value"] for k, d in v["metrics"].items()},
            "cost_per_success_usd": v["kpi"]["cost_per_success"], "cost_per_kloc_usd": v["kpi"]["cost_per_kloc"],
            "spend_usd": v["kpi"]["spend"], "diff": diff,
        })
    pairs = [{k: p[k] for k in ("a", "b", "runs_a", "runs_b", "verdict", "direction", "confounders")}
             | {"difference": _diff_out(p["difference"])} for p in model["pairs"].get(uid, []) if not p["vs_previous"]]
    return {"skill": u["name"], "unit": uid, "unit_of_analysis": "invocation", "population": model["population"],
            "baseline": {k: display(MEASURE[k], v) for k, v in u["baseline"].items()}, "weights": u["weights"],
            "versions": out, "other_pairs": pairs}


# ---- reading the database --------------------------------------------------------------

def load(con):
    """The rows `compute` needs, read from a DuckDB connection."""
    def rows(sql):
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def has(table):
        return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0]

    label = ("""(SELECT category FROM labels l WHERE l.incident_id = i.incident_id
                 ORDER BY (l.source = 'human') DESC, l.labeled_at DESC LIMIT 1)""" if has("labels") else "NULL")
    return {
        "runs": rows("""SELECT session_id, started, title, cwd AS repo, cc_version, status, is_stub, pr_urls,
                               lines_added, lines_removed FROM runs"""),
        "agents": rows("SELECT session_id, agent_id, agent_type, role, description FROM agents"),
        "api": rows("SELECT session_id, agent_id, ts, skill, cost_usd, api_error, model, effort FROM api_calls"),
        "tools": rows("""SELECT session_id, agent_id, ts, skill, is_error, denied, idle, patch_added, patch_removed
                         FROM tool_calls"""),
        "incidents": rows(f"SELECT session_id, agent_id, ts, skill, type, policy, {label} AS label FROM incidents i"),
        "markers": rows("SELECT session_id, agent_id, ts, skill, marker, value, bad FROM markers"),
        "prompts": rows("SELECT session_id, ts FROM events WHERE kind = 'human_prompt' AND agent_id = 'main'"),
        "loads": rows("SELECT session_id, agent_id, ts, skill, content_hash, args FROM skill_loads"),
        "texts": rows("SELECT skill, content_hash, text FROM skill_texts") if has("skill_texts") else [],
    }


def build(con, cfg=None, resamples=None):
    """The dashboard model: `compute` on the database (the page's per-run facts come from explorer.build).
    `cfg` is config.toml as loaded by config.load (a bare list of [[group]] tables is accepted too)."""
    if isinstance(cfg, (list, tuple)):
        cfg = {"group": list(cfg)}
    cfg = cfg or {}
    return compute(load(con), resamples=resamples, cfg=cfg)
