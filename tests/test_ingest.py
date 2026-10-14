"""The data layer: archive, ingest, hook queue, evidence, long paths, check, install, privacy and prune.

Each test builds its own home and projects folder under a temp dir and points runlens at them.
Run: python -m unittest tests.test_ingest -v
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from runlens import archive, check, cli, config, hooks, incidents, report, store, transcripts
from runlens.fs import fs_path, makedirs, plain, read_json, write_atomic

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


class Run:
    """A minimal transcript writer: one session, optional subagents, timestamps one second apart from `start`."""

    def __init__(self, projects, sid, project="C--work-repo", start=T0, cwd="C:\\work\\repo"):
        self.path = fs_path(Path(projects) / project / f"{sid}.jsonl")
        self.sid, self.t, self.cwd, self.rows, self.n = sid, start, cwd, [], 0

    def rec(self, **r):
        self.n += 1
        r.setdefault("uuid", f"{self.sid}-{self.n}")
        r.setdefault("timestamp", iso(self.t + timedelta(seconds=self.n)))
        r.setdefault("sessionId", self.sid)
        r.setdefault("cwd", self.cwd)
        self.rows.append(r)
        return r

    def turn(self, mid, tid, cmd="ls", result="ok", error=False, attr="flow", tur=None, **extra):
        self.rec(type="assistant", attributionSkill=attr, message={
            "id": mid, "model": "claude-sonnet-5-5", "role": "assistant", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}],
            "usage": {"input_tokens": 10, "output_tokens": 50, "cache_read_input_tokens": 100}})
        self.rec(type="user", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": error}]},
            toolUseResult=tur if tur is not None else {"stdout": result}, **extra)

    def end(self, cost=0.5):
        self.rec(type="cost-state", totalCostUSD=cost, modelUsage={"claude-sonnet-5-5": {"costUSD": cost, "outputTokens": 100}})

    def write(self, extra_lines=()):
        makedirs(self.path.parent)
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("\n".join([json.dumps(r) for r in self.rows] + list(extra_lines)) + "\n")
        return self


def simple_run(projects, sid, n=3, cost=0.5, **kw):
    r = Run(projects, sid, **kw)
    r.rec(type="user", message={"role": "user", "content": "do it"}, promptSource="typed")
    for i in range(n):
        r.turn(f"{sid[:4]}m{i}", f"{sid[:4]}t{i}", cmd=f"echo {i} && make")
    r.end(cost)
    return r.write()


class Sandbox(unittest.TestCase):
    """A fresh RUNLENS_HOME and projects folder per test."""
    home_name = "home"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runlens-ingest-"))
        self.home = self.tmp / self.home_name
        self.projects = self.tmp / "projects"
        makedirs(self.home)
        self.projects.mkdir()
        self.patch = mock.patch.multiple(config, HOME=self.home, DB=self.home / "runlens.duckdb",
                                         ARCHIVE=self.home / "archive", BLOBS=self.home / "archive" / "_blobs",
                                         PENDING=self.home / "pending", PROJECTS=self.projects)
        self.patch.start()
        self.cfg = config.load(self.tmp / "none.toml")

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(fs_path(self.tmp), ignore_errors=True)

    def quiet(self, fn, *a, **kw):
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            res = fn(*a, **kw)
        self.out = out.getvalue()
        return res

    def refresh(self, **kw):
        self.quiet(archive.archive, self.cfg, **kw)
        return self.quiet(store.ingest, self.cfg)

    def q(self, sql, *args):
        con = store.connect(read_only=True)
        try:
            return con.execute(sql, list(args)).fetchall()
        finally:
            con.close()


class LongPaths(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "the \\\\?\\ prefix is Windows only")
    def test_prefix_folds_dots_and_handles_unc(self):
        self.assertEqual(str(fs_path("C:\\a\\b\\..\\c\\f.txt")), "\\\\?\\C:\\a\\c\\f.txt")
        self.assertEqual(str(fs_path("\\\\server\\share\\x.txt")), "\\\\?\\UNC\\server\\share\\x.txt")
        self.assertEqual(str(fs_path(fs_path("C:\\a"))), "\\\\?\\C:\\a")  # idempotent
        self.assertEqual(str(plain(fs_path("\\\\server\\share\\x"))), "\\\\server\\share\\x")
        self.assertEqual(str(plain(fs_path("C:\\a\\b"))), "C:\\a\\b")

    def test_dots_resolve_to_an_existing_file(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "b").mkdir()
            (tmp / "b" / "f.txt").write_text("x")
            self.assertTrue(fs_path(tmp / "a" / ".." / "b" / "f.txt").exists())
        finally:
            shutil.rmtree(tmp)


class DeepHome(Sandbox):
    """RUNLENS_HOME so deep that every archive path is over 260 characters."""
    home_name = "h" + "/very-long-folder-name-for-runlens-home" * 4

    def test_archive_ingest_check_report_with_paths_over_260(self):
        self.assertLess(len(str(self.home)), 240)  # the database itself stays reachable; the archive goes deeper
        r = simple_run(self.projects, "aaaaaaaa-1111-2222-3333-444444444444")
        sub = Run(self.projects, "agent-x1", project=f"C--work-repo/{r.sid}/subagents")
        sub.turn("s1", "st1", attr=None)
        sub.write()
        (sub.path.parent / "agent-x1.meta.json").write_text(json.dumps({"agentType": "Explore", "toolUseId": "aaaat0"}))
        self.assertEqual(self.refresh(), 1)
        self.assertEqual(self.q("SELECT count(*) FROM agents")[0][0], 2)
        archived = fs_path(self.home / "archive" / "C--work-repo" / r.sid / "subagents" / "agent-x1.jsonl")
        self.assertGreater(len(str(plain(archived))), 260)
        self.assertTrue(archived.exists())
        self.assertEqual(self.quiet(check.check, cfg=self.cfg), 0, self.out)
        self.assertTrue(fs_path(self.quiet(report.write_report, self.cfg, str(self.tmp / "r.html"))).exists())


class Ingest(Sandbox):
    def test_malformed_records_do_not_stop_the_run_or_the_others(self):
        good = simple_run(self.projects, "bbbbbbbb-0000-0000-0000-000000000001")
        bad = Run(self.projects, "bbbbbbbb-0000-0000-0000-000000000002")
        bad.rec(type="user", message={"role": "user", "content": "go"}, origin={"kind": "human"})
        bad.rec(type="assistant", message={"id": "x", "model": "claude-sonnet-5-5", "content": [{"type": "text", "text": None}]})
        bad.rec(type="assistant", message="plain")
        bad.rec(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": None}]})
        bad.rec(type="system", subtype="turn_duration", durationMs="12", timestamp="2026-10-01T10:00:02")  # no zone
        bad.turn("y", "ty")
        bad.write(extra_lines=["[]", "null", "42", '{"type": "assistant", "message": {"id": "trunc'])
        self.assertEqual(self.refresh(), 2, self.out)
        self.assertEqual(self.q("SELECT bad_lines FROM runs WHERE session_id = ?", bad.sid)[0][0], 4)
        self.assertEqual(self.q("SELECT count(*) FROM runs")[0][0], 2)
        del good

    def test_active_time_counts_overlapping_turns_once(self):
        r = Run(self.projects, "abababab-0000-0000-0000-000000000009")
        r.rec(type="user", message={"role": "user", "content": "go"}, origin={"kind": "human"})
        # Two turns of 10 s ending at :10 and :20, then a last turn of 30 s that spans both.
        r.rec(type="system", subtype="turn_duration", durationMs=10000, timestamp="2026-10-01T10:00:10.000Z")
        r.rec(type="system", subtype="turn_duration", durationMs=10000, timestamp="2026-10-01T10:00:20.000Z")
        r.rec(type="system", subtype="turn_duration", durationMs=30000, timestamp="2026-10-01T10:00:30.000Z")
        # A separate turn after a gap adds its own length.
        r.rec(type="system", subtype="turn_duration", durationMs=5000, timestamp="2026-10-01T10:01:00.000Z")
        r.turn("y", "ty")
        r.write()
        self.assertEqual(self.refresh(), 1, self.out)
        self.assertEqual(self.q("SELECT active_ms FROM runs WHERE session_id = ?", r.sid)[0][0], 35000)

    def test_main_session_work_after_a_skill_goes_back_to_the_outermost(self):
        r = Run(self.projects, "abababab-0000-0000-0000-000000000001")
        r.rec(type="user", message={"role": "user", "content": "/flow"}, promptSource="typed")
        n = 0

        def turn(attr, load=None):
            nonlocal n
            n += 1
            if load:
                r.rec(type="user", isMeta=True, message={"role": "user", "content":
                      f"Base directory for this skill: C:\\skills\\{load}\n\n# {load}"})
            r.turn(f"m{n}", f"t{n}", cmd=f"echo {n}", attr=attr)

        # the attribution sequence of a real /m-feature run (issue #1)
        turn("flow", load="flow")
        turn(None)
        turn("grill", load="grill")
        turn("research", load="research")
        turn(None)
        turn("plan", load="plan")
        turn(None)
        turn("review", load="review")
        turn(None)
        r.end()
        r.write()
        self.assertEqual(self.refresh(), 1, self.out)
        got = [s for s, in self.q("SELECT skill FROM tool_calls WHERE session_id = ? ORDER BY seq", r.sid)]
        self.assertEqual(got, ["flow", "flow", "grill", "research", "flow", "plan", "flow", "review", "flow"])

    def test_a_run_that_fails_to_parse_is_recorded_and_the_rest_ingest(self):
        simple_run(self.projects, "cccccccc-0000-0000-0000-000000000001")
        broken = simple_run(self.projects, "cccccccc-0000-0000-0000-000000000002")
        self.quiet(archive.archive, self.cfg)
        real = transcripts.parse_run

        def parse(main, info, cfg, now=None):
            if info["session_id"] == broken.sid:
                raise RuntimeError("format changed")
            return real(main, info, cfg, now)

        with mock.patch.object(store, "parse_run", parse):
            self.assertEqual(self.quiet(store.ingest, self.cfg), 1)
        self.assertEqual(self.q("SELECT session_id, stage FROM ingest_errors"), [(broken.sid, "parse")])
        self.assertEqual(self.quiet(check.check, cfg=self.cfg, sources=False), 1)
        self.assertIn("ingest parse failed: RuntimeError: format changed", self.out)
        self.assertEqual(self.quiet(store.ingest, self.cfg), 1)  # fixed: it ingests and the error is cleared
        self.assertEqual(self.q("SELECT count(*) FROM ingest_errors")[0][0], 0)

    def test_incremental_parser_version_and_config(self):
        r = simple_run(self.projects, "dddddddd-0000-0000-0000-000000000001")
        simple_run(self.projects, "dddddddd-0000-0000-0000-000000000002")
        self.assertEqual(self.refresh(), 2)
        self.assertEqual(self.refresh(), 0)  # nothing changed
        r.turn("late", "tlate")
        r.end(0.9)
        r.write()
        self.assertEqual(self.refresh(), 1)  # the grown session is copied again and re-ingested
        self.assertEqual(self.q("SELECT cost_usd FROM runs WHERE session_id = ?", r.sid)[0][0], 0.9)
        with mock.patch.object(store, "PARSER_VERSION", transcripts.PARSER_VERSION + 1):
            self.assertEqual(self.quiet(store.ingest, self.cfg), 2)  # a parser change re-ingests everything
        self.cfg["marker"] = [{"name": "m", "pattern": "make", "source": "tool_input"}]
        self.assertEqual(self.quiet(store.ingest, self.cfg), 2)  # so does a config change that shapes rows
        self.assertEqual(self.quiet(store.ingest, self.cfg, force=True), 2)

    def test_bulk_ingest_is_fast(self):
        r = Run(self.projects, "eeeeeeee-0000-0000-0000-000000000001")
        for i in range(6000):
            r.turn(f"m{i}", f"t{i}", cmd=f"pytest -k case{i}", result="Exit code 1\n1 failed", error=i % 3 == 0)
        r.end()
        r.write()
        self.quiet(archive.archive, self.cfg)
        start = time.monotonic()
        self.assertEqual(self.quiet(store.ingest, self.cfg), 1)
        elapsed = time.monotonic() - start
        self.assertEqual(self.q("SELECT count(*) FROM tool_calls")[0][0], 6000)
        self.assertLess(elapsed, 30, f"ingest of 6000 calls took {elapsed:.1f}s")  # row-by-row inserts took ~6 minutes

    def test_run_status_open_complete_and_stub(self):
        now = datetime.now(timezone.utc)
        live = Run(self.projects, "ffffffff-0000-0000-0000-000000000001", start=now - timedelta(minutes=5))
        for i in range(4):
            live.turn(f"l{i}", f"lt{i}")
        live.write()  # no cost-state yet: the session may still be going
        idle = Run(self.projects, "ffffffff-0000-0000-0000-000000000002", start=now - timedelta(days=2))
        for i in range(4):
            idle.turn(f"i{i}", f"it{i}")
        idle.write()
        stub = simple_run(self.projects, "ffffffff-0000-0000-0000-000000000003", n=1, start=now - timedelta(days=1))
        self.refresh()
        got = {s: (st, by, sb) for s, st, by, sb in self.q("SELECT session_id, status, ended_by, is_stub FROM runs")}
        self.assertEqual(got[live.sid][:2], ("open", None))
        self.assertEqual(got[idle.sid][:2], ("complete", "idle"))
        self.assertEqual(got[stub.sid], ("complete", "session_end", True))
        self.quiet(check.check, cfg=self.cfg, sources=False)
        self.assertIn("open: the session may still be running", self.out)

    def test_since_is_compared_as_an_instant(self):
        self.assertEqual(config.since_utc("2026-10-01T02:00:00+02:00"), datetime(2026, 10, 1, tzinfo=timezone.utc))
        local_midnight = datetime(2026, 10, 1).astimezone()
        self.assertEqual(config.since_utc("2026-10-01"), local_midnight.astimezone(timezone.utc))
        simple_run(self.projects, "abababab-0000-0000-0000-000000000001", start=datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc))
        self.quiet(archive.archive, self.cfg, since="2026-10-01T00:00:00+00:00")
        self.assertEqual(list(fs_path(self.home / "archive").glob("*/*.runlens.json")), [])
        self.quiet(archive.archive, self.cfg, since="2026-09-30T23:00:00Z")
        self.assertEqual(len(list(fs_path(self.home / "archive").glob("*/*.runlens.json"))), 1)

    def test_structured_results_permissions_prompts_mentions(self):
        r = Run(self.projects, "acacacac-0000-0000-0000-000000000001")
        r.rec(type="user", message={"role": "user", "content": "<command-name>/flow</command-name>"})  # old CC: no origin
        r.rec(type="user", message={"role": "user", "content": "<task-notification>x</task-notification>"}, promptSource="sdk")
        r.rec(type="attachment", attachment={"type": "skill_mention", "skillName": "flow"})
        r.rec(type="attachment", attachment={"type": "skill_mention", "skillName": "other"})
        r.turn("m1", "t1", cmd="npm test", result="Exit code 2\nboom", error=True,
               tur={"stdout": "", "timedOutAfterMs": 120000, "returnCodeInterpretation": "failed"},
               permissionDecision={"decision": "accept", "source": "config", "reasonType": "rule"})
        r.rec(type="assistant", message={"id": "m2", "model": "claude-sonnet-5-5", "content": [
            {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "a.py"}},
            {"type": "tool_use", "id": "t3", "name": "Skill", "input": {"skill": "flow"}}]})
        r.rec(type="user", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]},
              toolUseResult={"structuredPatch": [{"lines": [" a", "-b", "+c", "+d"]}]})
        r.rec(type="user", message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t3", "content": "[Request interrupted by user] quoted in a file"}]})
        r.turn("m3", "t4", cmd="git push", result="denied", error=True, toolDenialKind="permission-rule",
               permissionDecision={"decision": "reject", "source": "config", "reasonType": "rule"})
        r.rec(type="assistant", isApiErrorMessage=True, apiErrorStatus=529,
              message={"id": "e1", "model": "<synthetic>", "content": [{"type": "text", "text": "API Error: 529 Overloaded"}]})
        r.end()
        r.write()
        self.refresh()
        self.assertEqual(self.q("SELECT human_prompts FROM runs")[0][0], 1)
        self.assertEqual(self.q("SELECT exit_code, timed_out_ms, return_code_info, permission, permission_source FROM tool_calls WHERE tool_use_id = 't1'"),
                         [(2, 120000, "failed", "accept", "config:rule")])
        self.assertEqual(self.q("SELECT patch_added, patch_removed FROM tool_calls WHERE tool_use_id = 't2'"), [(2, 1)])
        self.assertEqual(self.q("SELECT count(*) FROM events WHERE kind = 'interrupt'")[0][0], 0)
        self.assertEqual(sorted(self.q("SELECT skill, invoked FROM skill_mentions")), [("flow", True), ("other", False)])
        self.assertEqual(self.q("SELECT api_error, api_limit, api_error_kind FROM api_calls WHERE msg_id = 'e1'"), [(True, False, "overloaded")])
        self.assertEqual(self.q("SELECT type, policy, detail FROM incidents WHERE type = 'permission_denied'"),
                         [("permission_denied", True, "permission-rule")])
        self.assertEqual(self.q("SELECT count(*) FROM incidents WHERE type = 'api_error'")[0][0], 1)

    def test_unknown_model_is_flagged_not_guessed(self):
        r = Run(self.projects, "adadadad-0000-0000-0000-000000000001")
        r.rec(type="assistant", message={"id": "u1", "model": "claude-future-9", "content": [],
                                         "usage": {"input_tokens": 1000, "output_tokens": 100}})
        r.write()
        self.refresh()
        self.assertEqual(self.q("SELECT unpriced_models, cost_estimated FROM runs"), [(["claude-future-9"], True)])
        self.assertIsNone(self.q("SELECT cost_usd FROM api_calls")[0][0])
        self.quiet(check.check, cfg=self.cfg, sources=False)
        self.assertIn("no price for claude-future-9", self.out)

    def test_redaction(self):
        self.cfg["privacy"]["redact"] = True
        r = Run(self.projects, "aeaeaeae-0000-0000-0000-000000000001")
        r.turn("m1", "t1", cmd="curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' https://x", result="mail me@example.com")
        r.end()
        r.write()
        self.refresh()
        inp, head, digest = self.q("SELECT input_json, result_head, input_hash FROM tool_calls")[0]
        self.assertNotIn("abcdefghijklmnop", inp)
        self.assertNotIn("me@example.com", head)
        raw = json.dumps({"command": "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' https://x"}, sort_keys=True)
        self.assertEqual(digest, transcripts.hashlib.sha1(raw.encode()).hexdigest()[:16])  # hashes come from the original

    def test_prune(self):
        old = simple_run(self.projects, "afafafaf-0000-0000-0000-000000000001", start=datetime(2026, 1, 1, tzinfo=timezone.utc))
        simple_run(self.projects, "afafafaf-0000-0000-0000-000000000002")
        self.refresh()
        self.quiet(store.prune, before="2026-06-01")
        self.assertEqual(self.q("SELECT count(*) FROM runs")[0][0], 2)  # a dry run deletes nothing
        self.quiet(store.prune, before="2026-06-01", yes=True)
        self.assertEqual([r[0] for r in self.q("SELECT session_id FROM runs")], ["afafafaf-0000-0000-0000-000000000002"])
        self.assertFalse(fs_path(self.home / "archive" / "C--work-repo" / f"{old.sid}.jsonl").exists())


class Sources(Sandbox):
    def test_check_finds_stale_and_unarchived_runs(self):
        r = simple_run(self.projects, "babababa-0000-0000-0000-000000000001")
        self.refresh()
        self.assertEqual(self.quiet(check.check, cfg=self.cfg), 0, self.out)
        r.turn("late", "tl")
        r.write()
        simple_run(self.projects, "babababa-0000-0000-0000-000000000002")
        self.assertEqual(self.quiet(check.check, cfg=self.cfg), 2, self.out)
        self.assertIn("source changed since it was archived", self.out)
        self.assertIn("selected by [select] but never archived", self.out)
        self.refresh()
        self.assertEqual(self.quiet(check.check, cfg=self.cfg), 0, self.out)

    def test_scan_cache_skips_unchanged_sessions(self):
        simple_run(self.projects, "bcbcbcbc-0000-0000-0000-000000000001")
        self.quiet(archive.archive, self.cfg)
        with mock.patch.object(archive, "scan_session", side_effect=AssertionError("scanned again")):
            self.assertEqual(self.quiet(archive.archive, self.cfg), 1)


class Evidence(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        self.start = datetime.now(timezone.utc) - timedelta(hours=1)

    def ev_file(self, rel, text, when):
        p = fs_path(self.repo / "ev" / rel)
        makedirs(p.parent)
        p.write_text(text, encoding="utf-8")
        os.utime(p, (when.timestamp(), when.timestamp()))
        return p

    def run_in_repo(self, sid, start):
        r = Run(self.projects, sid, cwd=str(self.repo), start=start)
        for i in range(3):
            r.turn(f"{sid[:3]}{i}", f"{sid[:3]}t{i}")
        r.end()
        return r.write()

    def test_scope_excludes_dedup_and_limits(self):
        self.cfg["evidence"] = [{"name": "ev", "glob": "{cwd}/ev/**/*", "max_mb": 1}]
        inside = self.start + timedelta(seconds=2)
        self.ev_file("report.md", "same content", inside)
        self.ev_file("profile/Default/Cookies", "secret", inside)
        self.ev_file("old.md", "from another feature", self.start - timedelta(days=3))
        self.ev_file("big.bin", "x" * (2 * 1024 * 1024), inside)
        deep = "/".join(["nested-folder-with-a-long-name"] * 8) + "/deep.txt"
        self.ev_file(deep, "deep", inside)
        a = self.run_in_repo("cacacaca-0000-0000-0000-000000000001", self.start)
        b = self.run_in_repo("cacacaca-0000-0000-0000-000000000002", self.start)
        self.refresh()
        man = read_json(self.home / "archive" / "C--work-repo" / f"{a.sid}.evidence.json")
        paths = sorted(e["path"] for e in man["files"])
        self.assertEqual(paths, sorted(["report.md", deep]))  # cookies excluded, old file out of the run window
        self.assertEqual([s["path"] for s in man["skipped"]], ["big.bin"])  # over max_mb
        blobs = [f for f in fs_path(self.home / "archive" / "_blobs").glob("*/*")]
        self.assertEqual(len(blobs), 2)  # both runs reference the same two contents
        got = archive.evidence_file("C--work-repo", b.sid, "ev", "report.md")
        self.assertEqual(fs_path(got).read_text(encoding="utf-8"), "same content")
        self.assertEqual(self.quiet(check.check, cfg=self.cfg), 0, self.out)

    def test_migration_of_legacy_folders(self):
        a = self.run_in_repo("cbcbcbcb-0000-0000-0000-000000000001", self.start)
        b = self.run_in_repo("cbcbcbcb-0000-0000-0000-000000000002", self.start)
        self.refresh()
        deep = "/".join(["legacy-folder-with-quite-a-long-name"] * 7)
        when = (self.start - timedelta(days=5)).timestamp()
        for r in (a, b):  # 0.1 copied the same tree into every run
            base = self.home / "archive" / "C--work-repo" / r.sid / "evidence" / "mstack"
            for rel, text in ((f"{deep}/notes.md", "notes"), ("prove/profile/Cookies", "secret"), ("ledger.md", "ledger")):
                p = fs_path(base / rel)
                makedirs(p.parent)
                p.write_text(text, encoding="utf-8")
                os.utime(p, (when, when))
        self.assertGreater(len(str(self.home / "archive" / "C--work-repo" / a.sid / "evidence" / "mstack" / deep)), 260)
        dry = archive.migrate_evidence(dry_run=True, quiet=True)
        self.assertEqual((dry["files"], dry["excluded_files"], dry["blobs_new"], dry["folders_deleted"]), (6, 2, 2, 0))
        self.assertTrue(fs_path(self.home / "archive" / "C--work-repo" / a.sid / "evidence").exists())
        done = archive.migrate_evidence(dry_run=False, quiet=True)
        self.assertEqual((done["blobs_new"], done["folders_deleted"]), (2, 2))
        self.assertFalse(fs_path(self.home / "archive" / "C--work-repo" / a.sid / "evidence").exists())
        self.assertEqual(len(list(fs_path(self.home / "archive" / "_blobs").glob("*/*"))), 2)
        self.assertEqual(fs_path(archive.evidence_file("C--work-repo", b.sid, "mstack", f"{deep}/notes.md")).read_text(), "notes")
        self.refresh()  # re-archiving keeps the migrated entries
        self.assertEqual(len(read_json(self.home / "archive" / "C--work-repo" / f"{a.sid}.evidence.json")["files"]), 2)
        self.assertEqual(self.quiet(check.check, cfg=self.cfg), 0, self.out)


class HookQueue(Sandbox):
    def payload(self, sid):
        return json.dumps({"hook_event_name": "SessionEnd", "session_id": sid, "reason": "other"})

    def test_hook_only_queues_and_spawns(self):
        r = simple_run(self.projects, "dadadada-0000-0000-0000-000000000001")
        with mock.patch.object(hooks, "spawn_drain") as spawn:
            self.assertEqual(hooks.handle(self.cfg, self.payload(r.sid)), 0)
        spawn.assert_called_once()
        self.assertEqual([p.name for p in hooks.pending()], [r.sid])
        self.assertFalse(fs_path(self.home / "archive").exists())  # nothing slow ran inside the hook
        self.assertIn(f"queued {r.sid}", (self.home / "hooks.log").read_text(encoding="utf-8"))
        self.quiet(cli.main, ["--config", str(self.tmp / "none.toml"), "refresh", "--quiet"])  # refresh drains the queue
        self.assertEqual(hooks.pending(), [])
        self.assertEqual(self.q("SELECT count(*) FROM runs")[0][0], 1)

    def test_a_second_drain_leaves_while_one_runs(self):
        r = simple_run(self.projects, "dbdbdbdb-0000-0000-0000-000000000001")
        hooks.enqueue(r.sid)
        held = hooks.DrainLock()
        self.assertTrue(held.acquire())
        try:
            self.assertEqual(hooks.drain(self.cfg), 0)
            self.assertEqual(len(hooks.pending()), 1)
        finally:
            held.release()
        self.assertEqual(hooks.drain(self.cfg), 1)
        self.assertEqual(hooks.pending(), [])

    def test_unselected_session_is_dropped_from_the_queue(self):
        r = simple_run(self.projects, "dcdcdcdc-0000-0000-0000-000000000001")
        self.cfg["select"] = {"skills": ["something-else"]}
        hooks.enqueue(r.sid)
        self.assertEqual(hooks.drain(self.cfg), 0)
        self.assertEqual(hooks.pending(), [])
        self.assertIn("skipped", (self.home / "hooks.log").read_text(encoding="utf-8"))

    def test_lock_errors_are_recognised_and_waited_for(self):
        store.connect().close()
        code = ("import duckdb, sys, time; c = duckdb.connect(sys.argv[1]); print('ready', flush=True); time.sleep(3); c.close()")
        holder = subprocess.Popen([sys.executable, "-c", code, str(config.DB)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ready")
            with self.assertRaises(Exception) as ctx:
                store.open_db(wait=0.3)
            self.assertTrue(store.is_locked(ctx.exception), ctx.exception)
            start = time.monotonic()
            store.connect(wait=30).close()  # waits for the other writer instead of failing
            self.assertGreater(time.monotonic() - start, 0.5)
        finally:
            holder.wait(10)
            holder.stdout.close()


class Install(Sandbox):
    def setUp(self):
        super().setUp()
        self.settings = self.tmp / "settings.json"
        self.p2 = mock.patch.object(hooks, "SETTINGS", self.settings)
        self.p2.start()

    def tearDown(self):
        self.p2.stop()
        super().tearDown()

    def test_exact_match_atomic_and_unicode(self):
        mine = {"hooks": [{"type": "command", "command": "bash ~/scripts/backup-runlens-db.sh"}]}
        old = {"hooks": [{"type": "command", "command": "C:/py/python.exe", "args": ["-m", "runlens", "hook"], "async": True, "timeout": 600}]}
        self.settings.write_text(json.dumps({"statusLine": "año ñ", "hooks": {"SessionEnd": [mine, old]}}, ensure_ascii=False), encoding="utf-8")
        self.quiet(hooks.install, skill=False)
        text = self.settings.read_text(encoding="utf-8")
        self.assertIn("año ñ", text)  # not rewritten as \\u00f1
        s = json.loads(text)
        self.assertEqual(s["hooks"]["SessionEnd"][0], mine)  # the user's own hook that mentions runlens stays
        self.assertEqual(len(s["hooks"]["SessionEnd"]), 2)
        ours = s["hooks"]["SessionEnd"][1]["hooks"][0]
        self.assertEqual(ours["args"], ["-m", "runlens", "hook"])
        self.assertNotIn("async", ours)
        self.assertLessEqual(ours["timeout"], 60)
        self.quiet(hooks.install, skill=False)
        self.assertEqual(len(json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["SessionEnd"]), 2)
        self.quiet(hooks.uninstall)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["SessionEnd"], [mine])
        self.assertEqual([p.name for p in self.tmp.glob(".settings.json.*")], [])  # no temp files left
        self.assertLessEqual(len(list(self.tmp.glob("settings.json.runlens-backup-*"))), 1)

    def test_invalid_settings_give_a_message(self):
        self.settings.write_text("{not json", encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            self.quiet(hooks.install, skill=False)
        self.assertIn("is not valid JSON", str(ctx.exception))
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{not json")


class Cli(Sandbox):
    def run_cli(self, *args):
        env = {**os.environ, "RUNLENS_HOME": str(self.home), "CLAUDE_PROJECTS": str(self.projects)}
        return subprocess.run([sys.executable, "-m", "runlens", *args], capture_output=True, text=True, env=env, cwd=ROOT,
                              encoding="utf-8")

    def test_sql_errors_are_one_line_and_output_formats(self):
        simple_run(self.projects, "eaeaeaea-0000-0000-0000-000000000001")
        self.refresh()
        bad = self.run_cli("sql", "selec 1")
        self.assertEqual(bad.returncode, 1)
        self.assertNotIn("Traceback", bad.stderr)
        self.assertIn("runlens: Parser error", bad.stderr)
        ok = self.run_cli("sql", "SELECT session_id, cost_usd FROM runs", "--json")
        self.assertEqual(json.loads(ok.stdout)[0]["cost_usd"], 0.5)
        csv_out = self.run_cli("incidents", "--csv", "--all")
        self.assertTrue(csv_out.stdout.startswith("incident_id,run,type"), csv_out.stdout + csv_out.stderr)

    def test_report_with_a_quote_in_the_path(self):
        odd = self.tmp / "o'brien"
        odd.mkdir()
        with mock.patch.multiple(config, HOME=odd, DB=odd / "runlens.duckdb", ARCHIVE=self.home / "archive"):
            simple_run(self.projects, "ebebebeb-0000-0000-0000-000000000001")
            self.refresh()
            path = self.quiet(report.write_report, self.cfg, str(odd / "r.html"), ["ebebebeb"])
            self.assertIn("ebebebeb", Path(path).read_text(encoding="utf-8"))

    def test_bad_config_is_reported_before_work(self):
        cfgfile = self.tmp / "bad.toml"
        cfgfile.write_text('[[marker]]\nname = "x"\npattern = "(unclosed"\n', encoding="utf-8")
        res = self.run_cli("--config", str(cfgfile), "ingest")
        self.assertEqual(res.returncode, 1)
        self.assertIn("config error", res.stderr)
        self.assertNotIn("Traceback", res.stderr)


class Units(unittest.TestCase):
    def test_incident_ids_survive_a_growing_streak(self):
        def rows(n):
            calls = [{"agent_id": "main", "seq": i, "tool_use_id": f"t{i}", "ts": None, "tool": "Bash", "skill": None,
                      "is_error": True, "error_class": "other", "input_hash": f"h{i}", "input_summary": "x", "idle": False,
                      "touches_test": False, "denied": None, "result_head": ""} for i in range(n)]
            return {"runs": [{"session_id": "s"}], "agents": [], "tool_calls": calls, "texts": [], "markers": [], "events": []}
        cfg = {"analysis": config.ANALYSIS}
        first = incidents.build(rows(2), cfg)[0]["incident_id"]
        self.assertEqual(incidents.build(rows(4), cfg)[0]["incident_id"], first)

    def test_shipped_configs_are_valid(self):
        for p in (config.PACKAGE / "config.example.toml", ROOT / "examples" / "m-feature.toml"):
            cfg = config.load(p)
            self.assertIn("runs", cfg)

    def test_default_excludes_cover_browser_profiles(self):
        ex = archive.excluder(config.EVIDENCE_EXCLUDE)
        for rel in ("prove/x/q1/prof/Default/Network/Cookies", "a/Login Data", "p/Default/Local Storage/leveldb/1.ldb",
                    "web/node_modules/x/index.js", "repo/.git/objects/ab/cd", "p/Local State", "a.sqlite-wal"):
            self.assertTrue(ex(rel), rel)
        for rel in ("prove/x/q1/r12-bands.txt", "review/notes.md", "History.md"):
            self.assertFalse(ex(rel), rel)

    def test_write_atomic_replaces_whole_file(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            write_atomic(tmp / "a" / "f.txt", "one")
            write_atomic(tmp / "a" / "f.txt", "two")
            self.assertEqual((tmp / "a" / "f.txt").read_text(), "two")
            self.assertEqual(len(list((tmp / "a").iterdir())), 1)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
