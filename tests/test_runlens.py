"""End-to-end tests on a synthetic run that exercises every tricky part of the transcript format.

Run: python -m unittest discover -s tests -v
"""
import csv
import importlib
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="runlens-test-"))
os.environ["RUNLENS_HOME"] = str(TMP / "home")
os.environ["CLAUDE_PROJECTS"] = str(TMP / "projects")
os.environ["CLAUDE_SETTINGS"] = str(TMP / "settings.json")

from runlens import config  # noqa: E402

importlib.reload(config)
from runlens import archive, bench, check, classify, dashboard, hooks, report, store, transcripts  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"
USAGE = {"input_tokens": 10, "cache_read_input_tokens": 1000, "output_tokens": 100,
         "cache_creation_input_tokens": 200, "cache_creation": {"ephemeral_1h_input_tokens": 200, "ephemeral_5m_input_tokens": 0}}
CFG_TOML = """
[[marker]]
name = "step_check"
source = "tool_result"
pattern = '^STEP CHECK: (PASS|FAIL)\\b'
bad = ["FAIL"]

[[group]]
name = "pipeline"
members = ["skill:flow", "skill:build", "agent:general-purpose"]
"""


class Writer:
    def __init__(self, path, agent=None):
        self.path, self.agent, self.n, self.rows = path, agent, 0, []

    def rec(self, **r):
        self.n += 1
        r.setdefault("uuid", f"{self.path.stem}-{self.n}")
        r.setdefault("timestamp", f"2026-10-01T10:{self.n // 60:02d}:{self.n % 60:02d}.000Z")
        r.setdefault("sessionId", SID)
        r.setdefault("cwd", "C:\\work\\repo")
        if self.agent:
            r.setdefault("agentId", self.agent)
            r.setdefault("isSidechain", True)
        self.rows.append(r)
        return r

    def assistant(self, mid, blocks, model="claude-opus-5-5", attr=None, split=False):
        extra = {"attributionSkill": attr} if attr else {}
        parts = [[b] for b in blocks] if split else [blocks]
        for i, p in enumerate(parts):
            # Claude Code writes one record per content block while the message streams: the usage on the
            # earlier records is partial (output_tokens still growing) and only the last one has stop_reason.
            last = i == len(parts) - 1
            usage = USAGE if last else {**USAGE, "output_tokens": 4}
            self.rec(type="assistant", requestId=f"req-{mid}", message={"id": mid, "model": model, "role": "assistant",
                     "content": p, "usage": usage, "stop_reason": "tool_use" if last else None}, **extra)

    def result(self, tid, text, error=False, tur=None):
        self.rec(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                                                     "content": text, "is_error": error}]},
                 toolUseResult=tur if tur is not None else {"stdout": text, "interrupted": False})

    def skill_load(self, path, body):
        self.rec(type="user", isMeta=True, message={"role": "user", "content": [
            {"type": "text", "text": f"Base directory for this skill: {path}\n\n{body}"}]})

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(json.dumps(r) for r in self.rows), encoding="utf-8")


def bash(tid, cmd):
    return {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd, "description": "x"}}


def build_fixture():
    proj = config.PROJECTS / "C--work-repo"
    main = Writer(proj / f"{SID}.jsonl")
    main.rec(type="user", message={"role": "user", "content": "<command-name>/flow</command-name>"},
             origin={"kind": "human"}, version="2.1.289", gitBranch="main")
    main.skill_load("C:\\skills\\flow", "Do the flow.\n\n\nARGUMENTS: issue 7")
    main.assistant("m1", [{"type": "text", "text": "Starting."}, bash("t1", "ls missing"),
                          {"type": "tool_use", "id": "t2", "name": "Agent",
                           "input": {"description": "Build step 3", "subagent_type": "general-purpose", "prompt": "Build it"}}],
                   attr="flow", split=True)
    main.result("t1", "Exit code 2\nls: cannot access 'missing': No such file or directory", error=True)
    main.result("t2", "launched", tur={"isAsync": True, "status": "async_launched", "agentId": "ab1"})
    for i, mid in enumerate(["m2", "m3", "m4"]):
        main.assistant(mid, [bash(f"t3{i}", "sleep 5; echo waiting")])
        main.result(f"t3{i}", "waiting")
    main.rec(type="queue-operation", operation="enqueue",
             content="<task-notification><task-id>ab1</task-id><status>failed</status></task-notification>")
    main.assistant("m5", [bash("t6", "python check.py")])
    main.result("t6", "STEP CHECK: FAIL\n2 tests broke")
    # One real compaction: Claude Code writes both a compact_boundary and an isCompactSummary record for it.
    main.rec(type="system", subtype="compact_boundary", content="Conversation compacted",
             compactMetadata={"trigger": "auto", "preTokens": 180000, "postTokens": 9000, "durationMs": 30000})
    main.rec(type="user", isCompactSummary=True, message={"role": "user", "content": "This session is being continued..."})
    # A session limit is an API "error" that is the account's quota, not a failure of the work.
    main.rec(type="assistant", isApiErrorMessage=True, error="rate_limit", apiErrorStatus=429,
             quotaLimits={"status": "rejected", "rateLimitType": "five_hour"},
             message={"id": "lim1", "model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
                      "content": [{"type": "text", "text": "You've hit your session limit"}], "usage": {"input_tokens": 0, "output_tokens": 0}})
    main.rec(type="pr-link", prNumber=7, prUrl="https://github.com/o/r/pull/7", prRepository="o/r")
    main.rec(type="system", subtype="turn_duration", durationMs=5000)
    main.rec(type="cost-state", totalCostUSD=1.0, totalAPIDuration=4000, totalToolDuration=900,
             modelUsage={"claude-opus-5-5[1m]": {"costUSD": 0.8}, "claude-sonnet-5": {"costUSD": 0.2}})
    main.write()

    sub = proj / SID / "subagents"
    ab1 = Writer(sub / "agent-ab1.jsonl", agent="ab1")
    ab1.rec(type="user", message={"role": "user", "content": "Build it"})
    ab1.assistant("s1", [{"type": "tool_use", "id": "u1", "name": "Skill", "input": {"skill": "build"}}], model="claude-sonnet-5")
    ab1.skill_load("C:\\skills\\build", "Build carefully.")
    ab1.assistant("s2", [bash("u2", "pytest")], model="claude-sonnet-5")
    ab1.result("u2", "Exit code 1\n1 failed", error=True)
    ab1.assistant("s3", [bash("u3", "pytest -x")], model="claude-sonnet-5")
    ab1.result("u3", "Exit code 1\n1 failed", error=True)
    ab1.assistant("s4", [{"type": "tool_use", "id": "u4", "name": "Edit",
                          "input": {"file_path": "C:/work/repo/tests/test_x.py", "old_string": "a", "new_string": "b"}}],
                  model="claude-sonnet-5")
    ab1.result("u4", "ok")
    ab1.assistant("s5", [{"type": "tool_use", "id": "u5", "name": "Agent",
                          "input": {"description": "Fork lines", "subagent_type": "fork", "prompt": "do part"}}],
                  model="claude-sonnet-5")
    ab1.write()
    (sub / "agent-ab1.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": "Build step 3",
                                                         "toolUseId": "t2", "spawnDepth": 1, "requestShape": "background",
                                                         "model": "sonnet"}))
    fk = Writer(sub / "agent-fk1.jsonl", agent="fk1")
    for r in ab1.rows:  # a fork starts with a copy of its parent's history, same uuids
        fk.rows.append({**r, "agentId": "fk1"})
    fk.rec(type="assistant", uuid="copied-again", message={**ab1.rows[-1]["message"]})  # the spawning message, new uuid
    fk.assistant("f1", [{"type": "tool_use", "id": "v1", "name": "Read", "input": {"file_path": "C:/work/repo/a.py"}}],
                 model="claude-sonnet-5")
    fk.result("v1", "content")
    fk.write()
    (sub / "agent-fk1.meta.json").write_text(json.dumps({"agentType": "fork", "isFork": True, "parentAgentId": "ab1",
                                                         "description": "Fork lines", "toolUseId": "u5", "spawnDepth": 2}))


class RunlensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_fixture()
        config.HOME.mkdir(parents=True, exist_ok=True)
        (config.HOME / "config.toml").write_text(CFG_TOML, encoding="utf-8")
        cls.cfg = config.load()
        with redirect_stdout(io.StringIO()):
            archive.archive(cls.cfg, skills=["flow"])
            store.ingest(cls.cfg)
        cls.con = store.connect(read_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def one(self, sql, *args):
        return self.con.execute(sql, list(args)).fetchone()

    def test_api_calls_deduplicated_by_message(self):
        self.assertEqual(self.one("SELECT count(*) FROM api_calls WHERE agent_id = 'main' AND model <> '<synthetic>'")[0], 5)
        self.assertEqual(self.one("SELECT input_tokens, cache_write_1h FROM api_calls WHERE msg_id = 'm1'"), (10, 200))

    def test_usage_comes_from_the_last_streamed_record(self):
        # m1 streamed in three records; the first two carry output_tokens=4 and no stop_reason
        self.assertEqual(self.one("SELECT output_tokens, stop_reason FROM api_calls WHERE msg_id = 'm1'"), (100, "tool_use"))
        self.assertEqual(self.one("SELECT last_stop_reason FROM agents WHERE agent_id = 'main'")[0], "stop_sequence")

    def test_one_compaction_per_real_compaction(self):
        self.assertEqual(self.one("SELECT count(*) FROM events WHERE kind = 'compaction'")[0], 1)
        self.assertEqual(self.one("SELECT trigger, pre_tokens, post_tokens FROM compactions"), ("auto", 180000, 9000))
        self.assertEqual(self.one("SELECT compactions FROM agents WHERE agent_id = 'main'")[0], 1)
        self.assertEqual(self.one("SELECT count(*) FROM incidents WHERE type = 'compaction'")[0], 1)

    def test_api_limits_are_events_not_errors_or_incidents(self):
        self.assertEqual(self.one("SELECT api_error, api_limit, api_error_kind, api_error_status FROM api_calls WHERE msg_id = 'lim1'"),
                         (False, True, "quota", 429))
        self.assertEqual(self.one("SELECT count(*) FROM events WHERE kind = 'api_limit'")[0], 1)
        self.assertEqual(self.one("SELECT count(*) FROM incidents WHERE type LIKE 'api%'")[0], 0)

    def test_run_status_and_outcome_fields(self):
        status, ended_by, stub, prs = self.one("SELECT status, ended_by, is_stub, pr_urls FROM runs")
        self.assertEqual((status, ended_by, stub), ("complete", "session_end", False))
        self.assertEqual(prs, ["https://github.com/o/r/pull/7"])
        self.assertEqual(self.one("SELECT parser_version FROM runs")[0], transcripts.PARSER_VERSION)
        self.assertEqual(self.one("SELECT count(*) FROM model_usage")[0], 2)

    def test_fork_copied_history_is_skipped(self):
        self.assertEqual(self.one("SELECT count(*) FROM api_calls WHERE agent_id = 'fk1'")[0], 1)
        self.assertEqual(self.one("SELECT count(*) FROM tool_calls WHERE agent_id = 'fk1'")[0], 1)
        self.assertEqual(self.one("SELECT count(*), count(DISTINCT tool_use_id) FROM tool_calls"), (12, 12))

    def test_agent_tree_status_and_roles(self):
        self.assertEqual(self.one("SELECT parent_agent_id, status, role FROM agents WHERE agent_id = 'ab1'"),
                         ("main", "failed", "Build step #"))
        self.assertEqual(self.one("SELECT parent_agent_id FROM agents WHERE agent_id = 'fk1'")[0], "ab1")

    def test_skill_attribution(self):
        self.assertEqual(self.one("SELECT skill FROM tool_calls WHERE tool_use_id = 't1'")[0], "flow")
        self.assertEqual(self.one("SELECT skill FROM tool_calls WHERE tool_use_id = 'u1'")[0], "flow")  # inherited at spawn
        self.assertEqual(self.one("SELECT skill FROM tool_calls WHERE tool_use_id = 'u2'")[0], "build")
        self.assertEqual(self.one("SELECT count(*) FROM api_calls WHERE skill IS NULL")[0], 0)

    def test_skill_versions(self):
        rows = self.con.execute("SELECT skill, content_hash FROM skill_loads ORDER BY skill").fetchall()
        self.assertEqual([r[0] for r in rows], ["build", "flow"])
        self.assertTrue(all(len(r[1]) == 12 for r in rows))
        self.assertEqual(self.one("SELECT args FROM skill_loads WHERE skill = 'flow'")[0], "issue 7")
        same = transcripts.hashlib.sha1("Do the flow.".encode()).hexdigest()[:12]
        self.assertEqual(self.one("SELECT content_hash FROM skill_loads WHERE skill = 'flow'")[0], same)

    def test_cost_matches_cost_state(self):
        total, opus = self.one("SELECT sum(cost_usd), sum(cost_usd) FILTER (WHERE model = 'claude-opus-5-5') FROM api_calls")
        self.assertAlmostEqual(total, 1.0, places=6)
        self.assertAlmostEqual(opus, 0.8, places=6)

    def test_tool_errors_classified(self):
        self.assertEqual(self.one("SELECT error_class FROM tool_calls WHERE tool_use_id = 't1'")[0], "not_found")
        self.assertEqual(self.one("SELECT error_class FROM tool_calls WHERE tool_use_id = 'u2'")[0], "test_failure")
        self.assertEqual(self.one("SELECT count(*) FROM tool_calls WHERE idle")[0], 3)

    def test_markers(self):
        self.assertEqual(self.one("SELECT marker, value, bad FROM markers"), ("step_check", "FAIL", True))

    def test_incidents(self):
        types = {r[0] for r in self.con.execute("SELECT type FROM incidents").fetchall()}
        self.assertTrue({"bad_marker", "idle_loop", "error_streak", "test_edit_after_failure", "agent_failed"} <= types, types)
        ctx = self.one("SELECT context FROM incidents WHERE type = 'error_streak'")[0]
        self.assertIn("pytest", ctx)

    def test_check_passes(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(check.check(), 0)
        self.assertIn("ok", out.getvalue())

    def test_ingest_is_idempotent(self):
        before = self.one("SELECT count(*) FROM tool_calls")[0]
        self.con.close()
        with redirect_stdout(io.StringIO()):
            store.ingest(self.cfg)
        type(self).con = store.connect(read_only=True)
        self.assertEqual(self.one("SELECT count(*) FROM tool_calls")[0], before)

    def test_report(self):
        path = report.write_report(self.cfg, str(TMP / "r.html"))
        page = Path(path).read_text(encoding="utf-8")
        self.assertIn("Run Diagnosis", page)
        self.assertIn("step_check", page)

    def test_bench_scores_every_skill_role_and_group(self):
        model = bench.build(self.con, self.cfg.get("group", []), resamples=20)
        ids = {u["id"] for u in model["units"]}
        self.assertTrue({"skill:flow", "skill:build", "agent:general-purpose|Build step #", "group:pipeline"} <= ids, ids)
        flow = next(u for u in model["units"] if u["id"] == "skill:flow")
        self.assertEqual(flow["runs"], 1)
        self.assertIsNotNone(flow["score"])
        self.assertEqual(model["runs"]["skill:flow"][0]["task"], "issue 7")
        self.assertEqual([v["label"] for v in model["versions"]["skill:flow"]], ["v1"])
        self.assertTrue(model["texts"])

    def test_dashboard_is_self_contained_and_parses(self):
        path = dashboard.write_dashboard(self.cfg, str(TMP / "dash.html"))
        page = Path(path).read_text(encoding="utf-8")
        blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
        model = json.loads(blob)
        self.assertIn("pipeline", {u["name"] for u in model["units"]})
        diag = model["diag"]
        for key in ("runs", "incidents", "tool_errors", "tools", "models", "agent_types", "flow", "markers", "events"):
            self.assertIn(key, diag)
        self.assertIn("agent_skills", diag)
        self.assertEqual(len(diag["runs"]), 1)
        self.assertTrue(any(t["tool"] == "Bash" for t in diag["tools"]))
        self.assertNotIn("{{", page)
        self.assertEqual(page.count("</script>"), 2)
        self.assertIsNone(re.search(r'(src|href)="https?://', page))

    def test_embedded_data_cannot_close_its_script(self):
        evil = "</script><img src=x onerror=alert(1)>& "
        text = dashboard.embed({"args": evil})
        self.assertNotIn("<", text)
        self.assertNotIn(">", text)
        self.assertEqual(json.loads(text)["args"], evil)

    def test_web_assets_ship_with_the_package(self):
        for name in ("template.html", "app.css", *(f"js/{m}" for m in dashboard.MODULES)):
            self.assertTrue((config.PACKAGE / "web" / name).exists(), name)

    def test_labels_roundtrip_and_agreement(self):
        self.con.close()
        con = store.connect()
        iid = con.execute("SELECT incident_id FROM incidents WHERE type = 'bad_marker'").fetchone()[0]
        con.execute("INSERT INTO labels (incident_id, source, category, fault) VALUES (?, 'llm', 'expected_behavior', 'none')", [iid])
        con.close()
        csv_path = TMP / "labels.csv"
        with redirect_stdout(io.StringIO()):
            classify.export_labels(csv_path)
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        for r in rows:
            if r["incident_id"] == iid:
                r["human_category"] = "expected_behavior"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with redirect_stdout(io.StringIO()) as o:
            classify.import_labels(csv_path)
            classify.agreement()
        self.assertIn("imported 1 human labels", o.getvalue())
        self.assertIn("agreement 100%", o.getvalue())
        type(self).con = store.connect(read_only=True)

    def test_judge_prompt_and_schema(self):
        cats = classify.taxonomy()
        sch = classify.schema(cats)
        self.assertIn("expected_behavior", sch["properties"]["category"]["enum"])
        inc = {"type": "error_streak", "key": "Bash", "n": 2, "agent_type": "general-purpose", "role": "Build step #",
               "skill": "build", "context": "1 [Bash] pytest -> ERROR"}
        self.assertIn("pytest", classify.prompt(inc, "Build it", cats))

    def test_hook_archives_matching_session(self):
        shutil.rmtree(config.ARCHIVE)
        payload = json.dumps({"hook_event_name": "SessionEnd", "session_id": SID, "reason": "other"})
        self.con.close()
        os.environ["RUNLENS_HOOK_INLINE"] = "1"  # drain in this process instead of a detached one
        try:
            self.assertEqual(hooks.handle(self.cfg, payload), 0)
        finally:
            os.environ.pop("RUNLENS_HOOK_INLINE")
        self.assertTrue(any(config.ARCHIVE.glob(f"*/{SID}.jsonl")))
        log = (config.HOME / "hooks.log").read_text(encoding="utf-8")
        self.assertIn(f"queued {SID}", log)  # logged before any work
        self.assertIn("archived and ingested", log)
        self.assertEqual(hooks.pending(), [])
        self.assertTrue((config.HOME / "dashboard.html").exists())  # rebuilt after each ingested run
        self.assertEqual(hooks.handle(self.cfg, "not json"), 0)  # never raises
        type(self).con = store.connect(read_only=True)

    def test_install_and_uninstall_hook(self):
        hooks.SETTINGS = TMP / "settings.json"
        hooks.SETTINGS.write_text(json.dumps({"model": "x", "hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
        with redirect_stdout(io.StringIO()):
            hooks.install(skill=False)
            hooks.install(skill=False)  # idempotent
        s = json.loads(hooks.SETTINGS.read_text())
        self.assertEqual(len(s["hooks"]["SessionEnd"]), 2)
        self.assertEqual(s["model"], "x")
        with redirect_stdout(io.StringIO()):
            hooks.uninstall()
        s = json.loads(hooks.SETTINGS.read_text())
        self.assertEqual(s["hooks"]["SessionEnd"], [{"hooks": [{"type": "command", "command": "other"}]}])

    def test_skill_stack(self):
        st = transcripts.SkillStack()
        st.push("outer")
        self.assertEqual(st.on_attribution("outer"), "outer")
        st.push("inner")
        self.assertEqual(st.on_attribution("inner"), "inner")
        self.assertEqual(st.on_attribution(None), "outer")   # nested skill ended
        self.assertEqual(st.on_attribution(None), "outer")
        self.assertEqual(st.on_attribution("outer"), "outer")
        self.assertEqual(st.on_attribution(None), "outer")   # the outermost skill is never popped

    def test_idle_detection(self):
        parts = config.ANALYSIS["idle_parts"]
        self.assertTrue(transcripts.is_idle("sleep 60; echo tick", parts))
        self.assertTrue(transcripts.is_idle("echo standing by", parts))
        self.assertFalse(transcripts.is_idle("sleep 5 && npm test", parts))
        self.assertFalse(transcripts.is_idle("echo $(date) > log", parts))
        self.assertTrue(transcripts.is_idle('until grep -q done "$Q/log"; do sleep 30; done; tail -3 "$Q/log"', parts))
        self.assertFalse(transcripts.is_idle("while read l; do echo $l; done < f", parts))
        self.assertTrue(transcripts.is_idle('S="C:/a b/c"; until grep -q "^exit" $S/r.txt; do sleep 20; done; grep -v x $S/r.txt', parts))

    def test_prices(self):
        # https://platform.claude.com/docs/en/about-claude/pricing (2026-10-13)
        self.assertEqual(transcripts.price_of("claude-opus-5-5[1m]")[:3], (4.0, 20.0, 0.20))
        self.assertEqual(transcripts.price_of("claude-haiku-4-5-20251001")[:3], (1.0, 5.0, 0.10))
        self.assertEqual(transcripts.price_of("claude-sonnet-5-5")[:3], (2.0, 10.0, 0.10))
        self.assertEqual(transcripts.price_of("claude-fable-5")[:3], (10.0, 50.0, 1.0))
        self.assertEqual(transcripts.price_of("claude-fable-5-1")[:3], (10.0, 50.0, 0.25))
        self.assertEqual(transcripts.price_of("claude-opus-4-5")[:3], (5.0, 25.0, 0.50))
        self.assertEqual(transcripts.price_of("claude-sonnet-4-5")[:3], (3.0, 15.0, 0.30))
        self.assertEqual(transcripts.price_of("claude-haiku-5-5")[:3], (0.10, 0.50, 0.01))
        self.assertEqual(transcripts.price_of("claude-haiku-5-5", prompt_tokens=150_000)[:3], (0.50, 2.50, 0.05))
        self.assertEqual(transcripts.price_of("claude-opus-5-5", speed="fast")[:2], (8.0, 40.0))
        self.assertAlmostEqual(transcripts.price_of("claude-opus-5-5", geo="us")[0], 4.4)
        self.assertEqual(transcripts.price_of("claude-opus-5-5")[3:], (5.0, 8.0))  # cache writes 1.25x and 2x
        self.assertIsNone(transcripts.price_of("claude-unknown-9"))  # flagged, never priced with a guess
        self.assertEqual(transcripts.price_of("claude-unknown-9", {"claude-unknown-9": [1, 2, 0.1]})[:3], (1, 2, 0.1))


if __name__ == "__main__":
    unittest.main()
