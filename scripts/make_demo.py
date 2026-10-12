"""Build a made-up runlens history, so screenshots and demos show no real work.

Every skill, project, task and number here is invented. Run it into an empty folder,
then point runlens at that folder:

    python scripts/make_demo.py demo-home
    RUNLENS_HOME=demo-home runlens dashboard --out demo.html

The random seed is fixed, so the same history comes out every time.
"""
import hashlib
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(sys.argv[1] if len(sys.argv) > 1 else "demo-home").resolve()
os.environ["RUNLENS_HOME"] = str(HOME)  # before runlens is imported: it reads this once

from runlens import store  # noqa: E402

rng = random.Random(7)
extra = random.Random(11)  # for fields added later, so they do not shift the rest of the history
START = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
DAYS = 24

# name: [(first day, quality factor: lower costs less and fails less, text lines)]
BASE = {
    "triage-bug": ["Reproduce the bug before touching code.", "List the files that could be involved.", "Write a failing test.", "Report the likely cause."],
    "plan-feature": ["Read the request and the nearby code.", "List the steps, smallest first.", "Name what could go wrong.", "Ask before any breaking change."],
    "write-tests": ["Find the public behaviour to cover.", "Write one test per behaviour.", "Run the suite.", "Fix flaky tests, never skip them."],
    "review-pr": ["Read the diff top to bottom.", "Check tests for each change.", "Flag anything unclear.", "Summarise in three bullets."],
    "refactor-module": ["Run the tests first.", "Change one thing at a time.", "Keep the public API.", "Run the tests after every step."],
    "docs-writer": ["Read the code, then the old docs.", "Write for a new teammate.", "Add one runnable example.", "Link related pages."],
}
EDITS = [
    lambda L: L + ["State what you did not check."],
    lambda L: [x for x in L if "Ask before" not in x and "Flag anything" not in x] + ["Stop and ask when the task is ambiguous."],
    lambda L: L[:2] + ["Keep a short log of each decision."] + L[2:],
]
VERSIONS = {
    "triage-bug": [(0, 1.15), (9, 0.95)],
    "plan-feature": [(0, 1.2), (8, 1.0), (16, 0.8)],
    "write-tests": [(0, 1.0), (11, 1.25)],
    "review-pr": [(0, 1.1), (6, 0.95), (15, 0.9)],
    "refactor-module": [(0, 1.0)],
    "docs-writer": [(0, 0.9), (12, 0.85)],
}
# how expensive each skill's turns are, so the skills spread out on the cost charts
WEIGHT = {"triage-bug": 0.45, "plan-feature": 1.0, "write-tests": 2.2, "review-pr": 0.7, "refactor-module": 3.2, "docs-writer": 0.3}
FLOWS = [["triage-bug", "plan-feature", "write-tests", "review-pr"], ["plan-feature", "write-tests", "review-pr"],
         ["refactor-module", "write-tests", "review-pr"], ["docs-writer"], ["triage-bug", "refactor-module"],
         ["plan-feature", "write-tests", "review-pr", "docs-writer"]]
TASKS = ["Add coupon codes to checkout", "Fix the cart total rounding", "Split the order service", "Document the search API",
         "Speed up product listing", "Handle expired sessions", "Add an export button", "Retry failed webhooks"]
MODELS = [("claude-opus-5-5", 0.07, 0.62), ("claude-sonnet-5-5", 0.02, 0.30), ("claude-haiku-5-5", 0.004, 0.08)]
TOOLS = [("Bash", 0.5), ("Read", 0.2), ("Edit", 0.15), ("Grep", 0.1), ("Write", 0.05)]
ERRORS = ["nonzero_exit", "syntax", "not_found", "permission_denied", "test_failure", "harness_blocked"]
INCIDENTS = ["error_streak", "repeated_call", "idle_loop", "permission_denied", "test_edit_after_failure"]
AGENT_TYPES = [("Explore", 0.5), ("general-purpose", 0.35), ("Plan", 0.15)]


def pick(pairs):
    r, acc = rng.random() * sum(w for _, w in pairs), 0
    for item, w in pairs:
        acc += w
        if r <= acc:
            return item
    return pairs[-1][0]


def uid(prefix=""):
    return prefix + "%032x" % rng.getrandbits(128)


# the text of every version: each new version edits the one before
texts = {}
for skill, vs in VERSIONS.items():
    lines = BASE[skill]
    for i, (day, q) in enumerate(vs):
        lines = lines if i == 0 else EDITS[(i - 1) % len(EDITS)](lines)
        body = f"# {skill}\n\n" + "\n".join(f"- {x}" for x in lines)
        texts[(skill, i)] = (body, hashlib.sha1(body.encode()).hexdigest()[:12])


def version_at(skill, day):
    return max(i for i, (d, _) in enumerate(VERSIONS[skill]) if d <= day)


rows = {t: [] for t in ("runs", "agents", "api_calls", "tool_calls", "events", "markers", "skill_loads", "incidents")}
for day in range(DAYS):
    for _ in range(rng.choice([0, 1, 1, 2, 2, 3])):
        sid = uid()
        t = START + timedelta(days=day, hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
        flow, task = rng.choice(FLOWS), rng.choice(TASKS)
        run = {"session_id": sid, "project": "acme-shop", "cwd": "/work/acme-shop", "git_branch": f"feature/{task.split()[0].lower()}-{day}",
               "cc_version": "2.1.0", "title": task, "skills": flow, "started": t, "cost_estimated": False, "lines_added": 0, "lines_removed": 0}
        main_cost = sub_cost = active = 0.0
        n_agents = prompts = seq = 0
        rows["events"].append({"session_id": sid, "agent_id": "main", "ts": t, "kind": "human_prompt", "detail": task})
        prompts += 1
        t += timedelta(seconds=10)
        for skill in flow:
            vi = version_at(skill, day)
            q = VERSIONS[skill][vi][1] * rng.uniform(0.85, 1.15)
            body, digest = texts[(skill, vi)]
            rows["skill_loads"].append({"session_id": sid, "agent_id": "main", "ts": t, "seq": seq, "skill": skill, "skill_dir": f"/skills/{skill}",
                                        "content_hash": digest, "content_len": len(body), "args": task})
            turns = rng.randint(10, 32)
            for i in range(turns):
                t += timedelta(seconds=rng.randint(15, 110))
                active += 60
                model, per, _ = pick([((m, p, w), w) for m, p, w in MODELS])
                cost = per * rng.uniform(0.6, 1.5) * q * WEIGHT[skill]
                main_cost += cost
                mid = uid("m")
                rows["api_calls"].append({"session_id": sid, "agent_id": "main", "msg_id": mid, "ts": t, "model": model,
                                          "effort": pick([("medium", 0.9), ("high", 0.07), ("low", 0.03)]), "skill": skill,
                                          "cache_write_5m": 0, "cache_write_1h": 0, "input_tokens": rng.randint(50, 900) * 10, "cache_read_tokens": rng.randint(8000, 60000),
                                          "output_tokens": rng.randint(200, 1800), "thinking_tokens": (think := rng.randint(0, 600)),
                                          "thinking_ms": int(think * extra.uniform(8, 14)), "cost_usd": cost,
                                          "api_error": rng.random() < 0.004 * q})
                for _ in range(rng.choice([1, 1, 2])):
                    seq += 1
                    failed = rng.random() < 0.05 * q
                    rows["tool_calls"].append({"session_id": sid, "agent_id": "main", "tool_use_id": uid("t"), "msg_id": mid, "seq": seq, "ts": t,
                                               "duration_ms": int(rng.expovariate(1 / 1800)), "tool": pick(TOOLS), "skill": skill,
                                               "is_error": failed, "error_class": rng.choice(ERRORS) if failed else None,
                                               "idle": rng.random() < 0.02 * q})
            for _ in range(rng.randint(0, 3)):  # subagents started by this skill
                aid, atype = uid("a")[:17], pick(AGENT_TYPES)
                n_agents += 1
                a_cost, a_calls, a_err, a_ctx = 0.0, rng.randint(3, 12), 0, rng.randint(20000, 160000)
                a_start = t
                for _ in range(a_calls):
                    t += timedelta(seconds=rng.randint(5, 40))
                    c = 0.015 * rng.uniform(0.5, 1.6) * q * WEIGHT[skill]
                    a_cost += c
                    amid = uid("m")
                    rows["api_calls"].append({"session_id": sid, "agent_id": aid, "msg_id": amid, "ts": t, "model": "claude-sonnet-5-5", "effort": "medium",
                                              "skill": skill, "cache_write_5m": 0, "cache_write_1h": 0, "input_tokens": 300, "cache_read_tokens": rng.randint(5000, 40000),
                                              "output_tokens": rng.randint(150, 900), "cost_usd": c})
                    seq += 1
                    err = rng.random() < 0.04 * q
                    a_err += err
                    rows["tool_calls"].append({"session_id": sid, "agent_id": aid, "tool_use_id": uid("t"), "msg_id": amid, "seq": seq, "ts": t,
                                               "duration_ms": int(rng.expovariate(1 / 1200)), "tool": pick(TOOLS), "skill": skill, "is_error": err,
                                               "error_class": rng.choice(ERRORS) if err else None, "idle": False})
                sub_cost += a_cost
                if extra.random() < 0.2:  # a skill the subagent loads for itself
                    rows["skill_loads"].append({"session_id": sid, "agent_id": aid, "ts": a_start, "seq": seq, "skill": extra.choice(["lint-fix", "dep-audit"]),
                                                "skill_dir": "/skills/side", "content_hash": "0" * 12, "content_len": 400, "args": ""})
                rows["agents"].append({"session_id": sid, "agent_id": aid, "parent_agent_id": "main", "agent_type": atype,
                                       "description": f"{atype} step {rng.randint(1, 9)}", "role": f"{atype} step #", "model": "sonnet",
                                       "spawn_depth": 1, "background": rng.random() < 0.3, "status": "completed" if rng.random() < 0.97 else "failed",
                                       "started": a_start, "ended": t, "skills": [skill], "api_calls": a_calls, "tool_calls": a_calls,
                                       "tool_errors": a_err, "compactions": int(a_ctx > 140000), "peak_context": a_ctx, "cost_usd": a_cost})
            if rng.random() < 0.18 * q:
                rows["events"].append({"session_id": sid, "agent_id": "main", "ts": t, "kind": "human_prompt", "detail": "a correction"})
                prompts += 1
            for _ in range(rng.choice([0, 0, 1, 2]) if q > 0.95 else rng.choice([0, 0, 0, 1])):
                kind = rng.choice(INCIDENTS)
                rows["incidents"].append({"incident_id": uid("i")[:12], "session_id": sid, "agent_id": "main", "role": "main", "agent_type": "main",
                                          "ts": t, "type": kind, "key": "Bash", "n": rng.randint(2, 6), "skill": skill, "seq": seq,
                                          "anchor": "t", "context": f"a made-up {kind} in {skill}"})
            rows["markers"].append({"session_id": sid, "agent_id": "main", "ts": t, "marker": "tests", "value": "PASS" if rng.random() > 0.12 * q else "FAIL",
                                    "bad": False, "source": "tool_result", "skill": skill})
            t += timedelta(seconds=30)
        run.update({"ended": t, "active_ms": int(active * 1000), "human_prompts": prompts, "n_agents": n_agents,
                    "cost_usd": main_cost + sub_cost, "lines_added": rng.randint(80, 900), "lines_removed": rng.randint(10, 300),
                    "api_ms": int(active * 600), "tool_ms": int(active * 250), "archived_at": t})
        rows["runs"].append(run)
        rows["agents"].append({"session_id": sid, "agent_id": "main", "agent_type": "main", "role": "main", "started": run["started"], "ended": t,
                               "skills": flow, "cost_usd": main_cost})
for r in rows["markers"]:
    r["bad"] = r["value"] == "FAIL"

HOME.mkdir(parents=True, exist_ok=True)
(HOME / "config.toml").write_text('[[group]]\nname = "release-flow"\nmembers = ["skill:plan-feature", "skill:write-tests", "skill:review-pr"]\n', encoding="utf-8")
con = store.connect()
for table, items in rows.items():
    names = [c for c, _ in store.SCHEMA[table]]
    con.executemany(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", [[r.get(n) for n in names] for r in items])
for (skill, _), (body, digest) in texts.items():
    con.execute("INSERT INTO skill_texts VALUES (?, ?, ?) ON CONFLICT DO NOTHING", [skill, digest, body])
con.close()
print(f"made-up history in {HOME}: {len(rows['runs'])} runs, {len(rows['api_calls'])} model calls, {len(texts)} skill versions")
