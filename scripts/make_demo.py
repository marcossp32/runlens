"""Build a made-up runlens history, so screenshots and demos show no real work.

Every skill, project, task and number here is invented. Run it into an empty folder,
then point runlens at that folder:

    python scripts/make_demo.py demo-home
    RUNLENS_HOME=demo-home runlens dashboard --out demo.html

The random seed is fixed, so the same history comes out every time. The history covers
what the dashboard can show: skill versions with an outcome marker, two repos, a Claude
Code update, cache writes, stop reasons, API limits, nested subagents, context
compactions, Claude Code's own token totals, an open run, a stub and one failed ingest.
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

rng = random.Random(2)  # a seed whose history shows a clear "better" and a "confounded" verdict
extra = random.Random(11)  # for fields added later, so they do not shift the rest of the history
ctx = random.Random(13)  # context growth and compactions, on their own stream for the same reason
START = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
DAYS = 40

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
VERSIONS = {  # edits are spread out, so some verdicts are clean and others are confounded by a nearby edit
    "triage-bug": [(0, 1.15), (1, 0.95)],
    "plan-feature": [(0, 1.2), (3, 1.0), (37, 0.8)],
    "write-tests": [(0, 1.0), (28, 1.8)],
    "review-pr": [(0, 1.15), (10, 0.7)],
    "refactor-module": [(0, 1.0)],
    "docs-writer": [(0, 0.9), (36, 0.85)],
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
CC_UPDATE = 38  # the day Claude Code moved from 2.1 to 2.2


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
    for i, _version in enumerate(vs):
        lines = lines if i == 0 else EDITS[(i - 1) % len(EDITS)](lines)
        body = f"# {skill}\n\n" + "\n".join(f"- {x}" for x in lines)
        texts[(skill, i)] = (body, hashlib.sha1(body.encode()).hexdigest()[:12])


def version_at(skill, day):
    return max(i for i, (d, _) in enumerate(VERSIONS[skill]) if d <= day)


TABLES = ("runs", "agents", "api_calls", "tool_calls", "events", "markers", "skill_loads", "incidents", "compactions", "model_usage")
rows = {t: [] for t in TABLES}
usage = {}  # (session, model) -> Claude Code's own totals for that run


def count_usage(sid, model, call):
    u = usage.setdefault((sid, model), {"input": 0, "output": 0, "thinking": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0})
    u["input"] += call["input_tokens"]
    # the transcript holds only part of the output Claude Code counts (see the data contract): scale it up
    u["output"] += int(call["output_tokens"] * extra.uniform(4.5, 7.0))
    u["thinking"] += call.get("thinking_tokens") or 0
    u["cache_read"] += call["cache_read_tokens"]
    u["cache_write"] += call["cache_write_5m"] + call["cache_write_1h"]
    u["cost"] += call["cost_usd"]


def api_call(sid, agent, mid, t, model, effort, skill, cost, out_lo, out_hi, cache_lo, cache_hi, think=0, think_ms=None, error_rate=0.0):
    first = extra.random() < 0.12  # a turn that writes a fresh cache prefix
    call = {"session_id": sid, "agent_id": agent, "msg_id": mid, "ts": t, "model": model, "effort": effort, "skill": skill,
            "cache_write_5m": extra.randint(2000, 9000) if first else extra.randint(0, 400),
            "cache_write_1h": extra.randint(4000, 15000) if first and extra.random() < 0.4 else 0,
            "input_tokens": rng.randint(50, 900) * 10 if agent == "main" else 300, "cache_read_tokens": rng.randint(cache_lo, cache_hi),
            "output_tokens": rng.randint(out_lo, out_hi), "thinking_tokens": think, "thinking_ms": think_ms, "cost_usd": cost,
            "stop_reason": extra.choice(["tool_use"] * 6 + ["end_turn"] * 2 + [None] * 6 + (["max_tokens"] if extra.random() < 0.05 else [])),
            "api_error": rng.random() < error_rate}
    if call["api_error"]:
        call["api_error_kind"], call["api_error_status"] = extra.choice([("overloaded", 529), ("server", 500)])
    elif extra.random() < 0.006:
        call.update(api_limit=True, api_error_kind="rate_limit", api_error_status=429)
    rows["api_calls"].append(call)
    count_usage(sid, model, call)
    return call


n_runs = 0
for day in range(DAYS):
    for _ in range(rng.choice([0, 1, 1, 2, 2, 3])):
        sid = uid()
        n_runs += 1
        t = START + timedelta(days=day, hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
        flow, task = rng.choice(FLOWS), rng.choice(TASKS)
        docs = flow == ["docs-writer"]
        repo = "docs-site" if docs else "acme-shop"
        run = {"session_id": sid, "project": repo, "cwd": f"/work/{repo}", "git_branch": "main" if docs else f"feature/{task.split()[0].lower()}-{day}",
               "cc_version": f"2.1.{280 + day}" if day < CC_UPDATE else f"2.2.{day - CC_UPDATE}", "title": task, "skills": flow, "started": t,
               "cost_estimated": False, "lines_added": 0, "lines_removed": 0, "status": "complete", "ended_by": "session_end", "is_stub": False,
               "entrypoint": "cli", "parser_version": 2, "bad_lines": 0, "unpriced_models": []}
        main_cost = sub_cost = active = 0.0
        n_agents = prompts = seq = n_calls = 0
        rows["events"].append({"session_id": sid, "agent_id": "main", "ts": t, "kind": "human_prompt", "detail": task, "source": "typed"})
        prompts += 1
        t += timedelta(seconds=10)
        main_ctx = 20000
        for skill in flow:
            vi = version_at(skill, day)
            q = VERSIONS[skill][vi][1] * rng.uniform(0.85, 1.15)
            body, digest = texts[(skill, vi)]
            rows["skill_loads"].append({"session_id": sid, "agent_id": "main", "ts": t, "seq": seq, "skill": skill, "skill_dir": f"/skills/{skill}",
                                        "content_hash": digest, "content_len": len(body), "args": task})
            turns = rng.randint(10, 32)
            for _turn in range(turns):
                t += timedelta(seconds=rng.randint(15, 110))
                active += 60
                model, per, _ = pick([((m, p, w), w) for m, p, w in MODELS])
                cost = per * rng.uniform(0.6, 1.5) * q * WEIGHT[skill]
                main_cost += cost
                n_calls += 1
                mid = uid("m")
                effort = pick([("medium", 0.9), ("high", 0.07), ("low", 0.03)])
                think = rng.randint(0, 600)
                api_call(sid, "main", mid, t, model, effort, skill, cost, 200, 1800, 8000, 60000, think=think,
                         think_ms=int(think * extra.uniform(8, 14)), error_rate=0.004 * q)
                main_ctx += ctx.randint(700, 3000)
                if main_ctx > 170000:  # the main session fills its context and Claude Code compacts it
                    rows["compactions"].append({"session_id": sid, "agent_id": "main", "ts": t, "trigger": "auto", "pre_tokens": main_ctx,
                                                "post_tokens": ctx.randint(18000, 30000), "duration_ms": ctx.randint(20000, 60000)})
                    rows["events"].append({"session_id": sid, "agent_id": "main", "ts": t, "kind": "compaction", "value": main_ctx, "source": "auto"})
                    main_ctx = 25000
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
                    api_call(sid, aid, amid, t, "claude-sonnet-5-5", "medium", skill, c, 150, 900, 5000, 40000)
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
                if a_ctx > 140000:
                    rows["compactions"].append({"session_id": sid, "agent_id": aid, "ts": t, "trigger": "auto", "pre_tokens": a_ctx,
                                                "post_tokens": extra.randint(15000, 25000), "duration_ms": extra.randint(15000, 40000)})
                if extra.random() < 0.15:  # a subagent that starts one of its own
                    cid = uid("a")[:17]
                    c_start, c_cost = t, 0.0
                    for _ in range(extra.randint(2, 5)):
                        t += timedelta(seconds=extra.randint(5, 30))
                        cc = 0.006 * extra.uniform(0.5, 1.5) * WEIGHT[skill]
                        c_cost += cc
                        api_call(sid, cid, uid("m"), t, "claude-haiku-5-5", "medium", skill, cc, 100, 500, 3000, 20000)
                    sub_cost += c_cost
                    n_agents += 1
                    rows["agents"].append({"session_id": sid, "agent_id": cid, "parent_agent_id": aid, "agent_type": "Explore",
                                           "description": "Explore a detail", "role": "Explore detail #", "model": "haiku", "spawn_depth": 2,
                                           "background": False, "status": "completed", "started": c_start, "ended": t, "skills": [skill],
                                           "api_calls": 3, "tool_calls": 3, "tool_errors": 0, "compactions": 0, "peak_context": 30000, "cost_usd": c_cost})
                rows["agents"].append({"session_id": sid, "agent_id": aid, "parent_agent_id": "main", "agent_type": atype,
                                       "description": f"{atype} step {rng.randint(1, 9)}", "role": f"{atype} step #", "model": "sonnet",
                                       "spawn_depth": 1, "background": rng.random() < 0.3, "status": "completed" if rng.random() < 0.97 else "failed",
                                       "started": a_start, "ended": t, "skills": [skill], "api_calls": a_calls, "tool_calls": a_calls,
                                       "tool_errors": a_err, "compactions": int(a_ctx > 140000), "peak_context": a_ctx, "cost_usd": a_cost})
            if rng.random() < 0.18 * q:
                rows["events"].append({"session_id": sid, "agent_id": "main", "ts": t, "kind": "human_prompt", "detail": "a correction", "source": "typed"})
                prompts += 1
            if extra.random() < 0.04:
                rows["events"].append({"session_id": sid, "agent_id": "main", "ts": t, "kind": "interrupt", "source": "typed"})
            for _ in range(rng.choice([0, 0, 1, 2]) if q > 0.95 else rng.choice([0, 0, 0, 1])):
                kind = rng.choice(INCIDENTS)
                rows["incidents"].append({"incident_id": uid("i")[:12], "session_id": sid, "agent_id": "main", "role": "main", "agent_type": "main",
                                          "ts": t, "type": kind, "key": "Bash", "n": rng.randint(2, 6), "skill": skill, "seq": seq,
                                          "anchor": "t", "context": f"a made-up {kind} in {skill}"})
            # the outcome check: a FAIL is followed by a retry later in the same invocation
            passed = rng.random() > 0.12 * q
            rows["markers"].append({"session_id": sid, "agent_id": "main", "ts": t, "marker": "tests", "value": "PASS" if passed else "FAIL",
                                    "bad": False, "source": "tool_result", "skill": skill})
            if not passed:
                t += timedelta(seconds=extra.randint(60, 240))
                rows["markers"].append({"session_id": sid, "agent_id": "main", "ts": t, "marker": "tests",
                                        "value": "PASS" if extra.random() < 0.8 else "FAIL", "bad": False, "source": "tool_result", "skill": skill})
            t += timedelta(seconds=30)
        prs = [f"https://example.com/acme/{repo}/pull/{100 + n_runs}"] if "review-pr" in flow and extra.random() < 0.7 else []
        run.update({"ended": t, "active_ms": int(active * 1000), "human_prompts": prompts, "n_agents": n_agents,
                    "cost_usd": main_cost + sub_cost, "lines_added": rng.randint(80, 900), "lines_removed": rng.randint(10, 300),
                    "api_ms": int(active * 600), "tool_ms": int(active * 250), "archived_at": t, "n_api_calls": n_calls, "pr_urls": prs})
        rows["runs"].append(run)
        rows["agents"].append({"session_id": sid, "agent_id": "main", "agent_type": "main", "role": "main", "started": run["started"], "ended": t,
                               "skills": flow, "cost_usd": main_cost})
for r in rows["markers"]:
    r["bad"] = r["value"] == "FAIL"

# The newest run is still going (open: left out of scores), and one run barely did anything (a stub).
rows["runs"][-1].update(status="open", ended_by=None, cost_estimated=True)
stub = rows["runs"][len(rows["runs"]) // 2]
stub_sid = "5" + uid()[1:]
rows["runs"].append({**stub, "session_id": stub_sid, "title": "Quick look at the logs", "skills": ["triage-bug"], "is_stub": True,
                     "cost_usd": 0.01, "n_api_calls": 1, "lines_added": 0, "lines_removed": 0, "pr_urls": [], "human_prompts": 1, "n_agents": 0,
                     "started": stub["started"] + timedelta(hours=3), "ended": stub["started"] + timedelta(hours=3, minutes=1)})

for (sid, model), u in usage.items():
    rows["model_usage"].append({"session_id": sid, "model": model, "input_tokens": u["input"], "output_tokens": u["output"],
                                "thinking_tokens": u["thinking"], "cache_read_tokens": u["cache_read"], "cache_write_tokens": u["cache_write"],
                                "web_search_requests": 0, "cost_usd": u["cost"]})

HOME.mkdir(parents=True, exist_ok=True)
(HOME / "config.toml").write_text('''[[marker]]
name = "tests"
source = "tool_result"
pattern = '^TESTS (PASS|FAIL)'
bad = ["FAIL"]

[outcome]
marker = "tests"
success = ["PASS"]

[[group]]
name = "release-flow"
members = ["skill:plan-feature", "skill:write-tests", "skill:review-pr"]

[weights.docs-writer]
interventions = 0

[[dashboard.view]]
name = "Last 7 days, opus only"
hash = "#/?range=7d&model=claude-opus-5-5"

[[dashboard.view]]
name = "Cost only, release flow"
hash = "#/?skills=plan-feature,write-tests,review-pr&w=cost:1,seconds:0,error_rate:0,incidents:0,interventions:0,idle_rate:0,api_error_rate:0,bad_markers:0,outcome:0&tab=cost"
''', encoding="utf-8")
con = store.connect()
for table, items in rows.items():
    names = [c for c, _ in store.SCHEMA[table]]
    con.executemany(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", [[r.get(n) for n in names] for r in items])
for (skill, _), (body, digest) in texts.items():
    con.execute("INSERT INTO skill_texts VALUES (?, ?, ?) ON CONFLICT DO NOTHING", [skill, digest, body])
# What `runlens classify` would say about most problems: a failure category per incident.
CATEGORIES = [("tool_misuse", "skill_instructions"), ("environment", "environment"), ("expected_behavior", "none"),
              ("missing_context", "skill_instructions"), ("flaky_test", "environment")]
for i in rows["incidents"]:
    if extra.random() < 0.7:
        category, fault = extra.choice(CATEGORIES)
        con.execute("INSERT INTO labels (incident_id, source, category, fault, confidence, model) VALUES (?, 'llm', ?, ?, ?, 'claude-haiku-5-5')",
                    [i["incident_id"], category, fault, extra.choice(["high", "medium", "low"])])
end = max(r["ended"] for r in rows["runs"])
con.execute("INSERT INTO ingest_errors VALUES (?, ?, ?, ?, ?, ?)",
            ["9f0c1d2e-0000-4000-8000-000000000000", "/archive/acme-shop/9f0c1d2e.jsonl", "parse", "JSONDecodeError: Unterminated string",
             "line 4121, column 88", end])
store.set_meta(con, parser_version=2, last_ingest=datetime.now(timezone.utc).isoformat())  # a fresh refresh: the demo is never stale
con.close()
print(f"made-up history in {HOME}: {len(rows['runs'])} runs, {len(rows['api_calls'])} model calls, {len(texts)} skill versions")
