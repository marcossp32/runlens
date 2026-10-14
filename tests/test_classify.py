"""The judge's prompt and invocation, the sampling, the agreement maths and export-eval, on a small hand-built database.

Run: python -m unittest discover -s tests -v
"""
import csv
import io
import json
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from runlens import classify, cli, config, evals, privacy, store

S = "aaaaaaaa-1111-2222-3333-444444444444"
T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
SKILL_V1 = "# Build\nRun the tests.\nIf a test fails, update the test so it passes.\nReport STEP CHECK: PASS or FAIL.\n"
MARKER = '^STEP CHECK: (PASS|FAIL)\\b'
CFG_TOML = f"""
[[marker]]
name = "step_check"
source = "tool_result"
pattern = '{MARKER}'
bad = ["FAIL"]
"""


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def insert(con, table, **row):
    con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def call(con, agent, seq, tid, tool, inp, err=False, head="ok", minute=None):
    insert(con, "tool_calls", session_id=S, agent_id=agent, tool_use_id=tid, seq=seq, ts=at(minute if minute is not None else seq),
           tool=tool, skill="build" if agent == "ab1" else "flow", input_summary=inp.get("command") or inp.get("file_path"),
           input_json=json.dumps(inp, sort_keys=True), is_error=err, result_head=head)


def incident(con, iid, kind, agent="main", seq=None, skill="flow", key="k", anchor=None, minute=0, context=""):
    insert(con, "incidents", incident_id=iid, session_id=S, agent_id=agent, role="Build step #" if agent != "main" else None,
           agent_type="general-purpose", ts=at(minute), type=kind, key=key, n=1, skill=skill, seq=seq, anchor=anchor, context=context)


def build_db(tmp):
    con = store.connect()
    insert(con, "runs", session_id=S, cwd="C:\\work\\repo", git_branch="main", started=at(0))
    insert(con, "agents", session_id=S, agent_id="main")
    insert(con, "agents", session_id=S, agent_id="ab1", role="Build step #", agent_type="general-purpose",
           prompt="Build step 3: make the failing tests in tests/ pass.")
    insert(con, "agents", session_id=S, agent_id="ab2", role="Review", agent_type="general-purpose", prompt="Review it.")
    insert(con, "events", session_id=S, agent_id="main", ts=at(0), kind="human_prompt",
           detail="<command-name>/flow</command-name>\n<command-args>issue 7</command-args>")
    skill_dir = tmp / "skills" / "build"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: build\n---\n" + SKILL_V1, encoding="utf-8")
    (tmp / "skills" / "flow").mkdir()
    (tmp / "skills" / "flow" / "SKILL.md").write_text("---\nname: flow\n---\nDo the flow.\n", encoding="utf-8")
    for agent, minute, seq, h, skill, args in (("main", 0, 0, "f1", "flow", "issue 7"), ("main", 1, 0, "h0", "build", None),
                                               ("ab1", 2, 0, "h1", "build", None), ("main", 90, 50, "h2", "build", None)):
        insert(con, "skill_loads", session_id=S, agent_id=agent, ts=at(minute), seq=seq, skill=skill,
               skill_dir=str(tmp / "skills" / skill), content_hash=h, args=args)
    for skill, h, text in (("build", "h0", "Old build text."), ("build", "h1", SKILL_V1), ("build", "h2", "Newest text."),
                           ("flow", "f1", "Do the flow.")):
        insert(con, "skill_texts", skill=skill, content_hash=h, text=text)
    # the subagent: two failing test runs, an edit to a test, then it claims success
    call(con, "ab1", 1, "u1", "Read", {"file_path": "src/a.py"}, minute=3)
    call(con, "ab1", 2, "u2", "Bash", {"command": "pytest"}, err=True, head="1 failed", minute=4)
    insert(con, "texts", session_id=S, agent_id="ab1", seq=3, ts=at(5), skill="build", text="The test expects the old value.")
    call(con, "ab1", 4, "u4", "Bash", {"command": "pytest -x"}, err=True, head="1 failed", minute=6)
    call(con, "ab1", 5, "u5", "Edit", {"file_path": "tests/test_x.py", "old_string": "1", "new_string": "2"}, minute=7)
    call(con, "ab1", 6, "u6", "Bash", {"command": "pytest"}, head="1 passed", minute=8)
    insert(con, "texts", session_id=S, agent_id="ab1", seq=7, ts=at(9), skill="build", text="AFTER-STEP all tests pass now.")
    call(con, "ab1", 20, "u20", "Bash", {"command": "echo far-future-step"}, minute=30)
    # main session calls behind a bad marker and a repeated call
    call(con, "main", 1, "r1", "Bash", {"command": "ls \"missing dir\""}, err=True, head="No such file", minute=10)
    call(con, "main", 2, "t6", "Bash", {"command": "python check.py"}, head="STEP CHECK: FAIL", minute=11)
    call(con, "main", 3, "p1", "Bash", {"command": "rm -rf .git/x"}, err=True, head="denied", minute=12)
    incident(con, "inc-tamper", "test_edit_after_failure", "ab1", 5, "build", "Edit: tests/test_x.py", "u5", 7,
             "after failing call: [Bash] pytest -x\n   4 [Bash] pytest -x -> ERROR: 1 failed\n   5 [Edit] tests/test_x.py -> ok:")
    incident(con, "inc-review", "error_streak", "ab2", None, "build", "Bash: other", None, 40, "")
    incident(con, "inc-marker", "bad_marker", "main", 2, "flow", "step_check=FAIL", "t6", 11)
    incident(con, "inc-repeat", "repeated_call", "main", 1, "flow", "Bash: ls", "r1", 10)
    incident(con, "inc-denied", "permission_denied", "main", 3, "flow", "Bash: rm -rf .git/x", "p1", 12)
    incident(con, "inc-api", "api_error", "main", None, "flow", "429 rate limit", None, 13)
    for n in range(5):
        incident(con, f"inc-streak{n}", "error_streak", "main", None, None, "Bash: other", None, 20 + n)
    for n in range(2):
        incident(con, f"inc-idle{n}", "idle_loop", "main", None, None, "3 idle calls", None, 30 + n)
    con.close()


def write_transcript(tmp):
    """The archived main transcript: a human prompt, one call, then the message that made the failing call (t6)."""
    recs = [
        {"type": "user", "uuid": "1", "origin": {"kind": "human"},
         "message": {"role": "user", "content": "<command-name>/flow</command-name>\n<command-args>issue 7</command-args>"}},
        {"type": "assistant", "uuid": "2", "message": {"id": "m1", "content": [{"type": "tool_use", "id": "r1", "name": "Bash", "input": {}}]}},
        {"type": "user", "uuid": "3", "message": {"content": [{"type": "tool_result", "tool_use_id": "r1", "content": "x"}]}},
        {"type": "assistant", "uuid": "4", "message": {"id": "m2", "content": [{"type": "text", "text": "Running the check."}]}},
        {"type": "assistant", "uuid": "5", "message": {"id": "m2", "content": [{"type": "tool_use", "id": "t6", "name": "Bash", "input": {}}]}},
        {"type": "user", "uuid": "6", "message": {"content": [{"type": "tool_result", "tool_use_id": "t6", "content": "STEP CHECK: FAIL"}]}},
    ]
    d = config.ARCHIVE / "C--work-repo"
    d.mkdir(parents=True)
    (d / f"{S}.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")


def parse_frontmatter(text):
    """Our frontmatter writes every value as JSON (valid YAML 1.2 flow): parse it back strictly."""
    assert text.startswith("---\n"), text[:40]
    head, _, body = text[4:].partition("\n---\n")
    fields = {}
    for line in head.splitlines():
        key, sep, value = line.partition(": ")
        assert sep and re.fullmatch(r"[a-z_]+", key), line
        fields[key] = json.loads(value)
    return fields, body


class ClassifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="runlens-classify-"))
        home = cls.tmp / "home"
        cls.patch = mock.patch.multiple(config, HOME=home, DB=home / "runlens.duckdb", ARCHIVE=home / "archive")
        cls.patch.start()
        home.mkdir(parents=True)
        (home / "config.toml").write_text(CFG_TOML, encoding="utf-8")
        cls.cfg = config.load()
        build_db(cls.tmp)
        write_transcript(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.con = store.connect(read_only=True)

    def tearDown(self):
        self.con.close()

    def inc(self, iid):
        return classify.load_incidents(self.con, [iid])[0]

    def judge_prompt(self, iid):
        return classify.build_prompt(self.con, self.inc(iid), classify.taxonomy(), classify.settings(self.cfg))

    # ------------------------------------------------------------ what the judge sees

    def test_prompt_has_skill_text_task_and_timeline_both_sides(self):
        text, skill = self.judge_prompt("inc-tamper")
        self.assertEqual(skill["hash"], "h1")
        self.assertIn("If a test fails, update the test so it passes.", text)  # the active version's instructions
        self.assertIn('version="h1"', text)
        self.assertNotIn("Old build text.", text)
        self.assertIn("Build step 3: make the failing tests", text)  # the spawn prompt
        self.assertIn("The test expects the old value.", text)  # before
        self.assertIn(">>   5 [Edit] tests/test_x.py", text)  # the marked step
        self.assertIn("AFTER-STEP all tests pass now.", text)  # after: did it recover?
        self.assertNotIn("far-future-step", text)  # beyond the after window

    def test_incident_type_comes_after_the_timeline(self):
        text, _ = self.judge_prompt("inc-tamper")
        timeline_at = text.index("<timeline>")
        self.assertGreater(text.index("<detector>"), text.index("</timeline>"))
        self.assertNotIn("test_edit_after_failure", text[:timeline_at])
        self.assertIn("after failing call: [Bash] pytest -x", text[text.index("<detector>"):])  # detector notes kept there

    def test_unknown_outcome_and_instruction_field(self):
        sch = classify.schema(classify.taxonomy())
        self.assertIn("unknown", sch["properties"]["category"]["enum"])
        self.assertIn("unknown", sch["properties"]["fault"]["enum"])
        self.assertIn("skill_instructions", sch["properties"]["fault"]["enum"])
        self.assertIn("instruction", sch["required"])
        text, _ = self.judge_prompt("inc-tamper")
        self.assertIn("- unknown:", text)
        self.assertIn("copy the instruction verbatim from <skill>", text)

    def test_no_skill_and_unrecorded_skill_say_so(self):
        text, skill = self.judge_prompt("inc-streak0")
        self.assertIsNone(skill)
        self.assertIn("No skill was active at this step", text)
        inc = {**self.inc("inc-tamper"), "skill": "ghost"}
        self.assertIn("was not recorded", classify.prompt(inc, "task", classify.taxonomy(), classify.active_skill(self.con, inc)))

    def test_active_skill_version(self):
        self.assertEqual(classify.active_skill(self.con, self.inc("inc-tamper"))["hash"], "h1")  # loaded in its own agent
        inherited = classify.active_skill(self.con, self.inc("inc-review"))  # ab2 never loaded it: latest load before the incident
        self.assertEqual(inherited["hash"], "h1")
        self.assertEqual(classify.active_skill(self.con, self.inc("inc-marker"))["args"], "issue 7")

    def test_long_skill_text_is_clipped_head_and_tail(self):
        text = "\n".join(f"line {n}" for n in range(5000))
        out = classify.clip(text, 2000)
        self.assertLess(len(out), 2100)
        self.assertTrue(out.startswith("line 0\n"))
        self.assertTrue(out.endswith("line 4999"))
        self.assertIn("characters omitted", out)
        self.assertEqual(classify.clip("short", 2000), "short")

    def test_quote_must_be_in_the_skill(self):
        skill = {"text": SKILL_V1}
        ok = {"fault": "skill_instructions", "instruction": "If a test fails,  update the test so it passes."}
        self.assertEqual(classify.checked_instruction(ok, skill), ok["instruction"])
        bad = {"fault": "skill_instructions", "instruction": "Always delete failing tests."}
        self.assertTrue(classify.checked_instruction(bad, skill).startswith("[quote not found"))
        missing = {"fault": "skill_instructions", "instruction": "missing: never edit tests after a failure"}
        self.assertEqual(classify.checked_instruction(missing, skill), missing["instruction"])

    # ------------------------------------------------------------ the judge call

    def test_judge_is_toolless_and_takes_the_prompt_on_stdin(self):
        done = mock.Mock(stdout=json.dumps({"structured_output": {"category": "unknown"}, "total_cost_usd": 0.01}),
                         stderr="", returncode=0)
        with mock.patch.object(classify.subprocess, "run", return_value=done) as run:
            label, cost = classify.judge("SECRET PROMPT", {"type": "object"}, "sonnet")
        args, kw = run.call_args
        cmd = args[0]
        self.assertEqual(label, {"category": "unknown"})
        self.assertEqual(cost, 0.01)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        for flag in ("-p", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--json-schema"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--disallowedTools") + 1], "mcp__*")
        self.assertNotIn("SECRET PROMPT", " ".join(cmd))
        self.assertEqual(kw["input"], "SECRET PROMPT")
        self.assertNotIn("shell", kw)

    def test_judge_reports_non_json_output(self):
        bad = mock.Mock(stdout="not json", stderr="error: unknown option", returncode=1)
        with mock.patch.object(classify.subprocess, "run", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "unknown option"):
                classify.judge("p", {}, "sonnet")

    def test_classify_stores_fault_instruction_and_version(self):
        self.con.close()
        answer = {"category": "test_tampering", "new_category": "", "fault": "skill_instructions",
                  "instruction": "If a test fails, update the test so it passes.", "note": "edited the test",
                  "evidence": "[Edit] tests/test_x.py", "confidence": "high"}
        with mock.patch.object(classify, "judge", return_value=(answer, 0.02)), redirect_stdout(io.StringIO()) as o:
            classify.classify(self.cfg, types=["test_edit_after_failure"], limit=5, workers=1)
        self.assertIn("labeled 1/1", o.getvalue())
        self.con = store.connect(read_only=True)
        row = self.con.execute("SELECT category, fault, instruction, skill_hash FROM labels WHERE incident_id = 'inc-tamper'").fetchone()
        self.assertEqual(row, ("test_tampering", "skill_instructions", answer["instruction"], "h1"))
        self.con.close()
        con = store.connect()
        con.execute("DELETE FROM labels")
        con.close()
        self.con = store.connect(read_only=True)

    def test_dry_run_calls_no_model(self):
        with mock.patch.object(classify, "judge", side_effect=AssertionError("no model call")), \
                redirect_stdout(io.StringIO()) as o:
            picked = classify.classify(self.cfg, limit=3, dry_run=True, seed=1)
        self.assertEqual(len(picked), 3)
        self.assertIn("--- judge prompt for", o.getvalue())

    # ------------------------------------------------------------ sampling and SQL safety

    def test_stratified_sample_takes_every_type_in_turn(self):
        cands = classify.candidates(self.con)
        types = {c[1] for c in cands}
        picked = classify.sample(cands, len(types), "stratified", seed=3)
        self.assertEqual({c[1] for c in picked}, types)  # one per type before any type gets a second
        self.assertEqual(picked, classify.sample(cands, len(types), "stratified", seed=3))  # reproducible
        many = classify.sample(cands, 100, "stratified", seed=3)
        self.assertEqual(len(many), len(cands))
        self.assertEqual(len({c[0] for c in many}), len(cands))
        draws = {tuple(c[0] for c in classify.sample(cands, len(types), "stratified", seed=s)) for s in range(20)}
        self.assertGreater(len(draws), 1)  # random within type, not a fixed order

    def test_priority_sample_keeps_the_old_order(self):
        picked = classify.sample(classify.candidates(self.con), 3, "priority")
        self.assertEqual(picked[0][1], "bad_marker")

    def test_type_and_skill_filters_are_parameters(self):
        evil = "x' OR '1'='1"
        self.assertEqual(classify.candidates(self.con, types=[evil]), [])
        self.assertEqual(classify.candidates(self.con, skills=[evil]), [])
        self.assertEqual({c[0] for c in classify.candidates(self.con, types=["idle_loop"])}, {"inc-idle0", "inc-idle1"})
        with redirect_stdout(io.StringIO()) as o:
            cli.main(["classify", "--type", "x') OR 1=1 --", "--dry-run"])
        self.assertIn("nothing to label", o.getvalue())

    # ------------------------------------------------------------ agreement

    def test_kappa_and_rates_by_hand(self):
        rows = [("a", "a", None, None)] * 4 + [("b", "b", None, None)] * 4 + [("a", "b", None, None), ("b", "a", None, None)]
        rep = classify.agreement_report(rows)
        self.assertAlmostEqual(rep["agreement"], 0.8)
        self.assertAlmostEqual(rep["kappa"], 0.6)  # po 0.8, pe 0.5
        lo, hi = rep["kappa_ci95"]
        self.assertLessEqual(lo, 0.6)
        self.assertGreaterEqual(hi, 0.6)
        a = next(c for c in rep["categories"] if c["category"] == "a")
        self.assertEqual((a["tp"], a["fn"], a["fp"], a["tn"]), (4, 1, 1, 4))
        self.assertAlmostEqual(a["tpr"], 0.8)
        self.assertAlmostEqual(a["tnr"], 0.8)
        self.assertTrue(a["verified"])  # 5 human positives, both rates at 80%
        self.assertFalse(rep["enough"])

    def test_agreement_normalises_other_and_retired_ids(self):
        rep = classify.agreement_report([("other:foo", "other:bar", None, None), ("role_disobeyed", "spec_disobeyed", None, None)])
        self.assertEqual(rep["agreement"], 1.0)
        self.assertIsNone(classify.kappa([("a", "a"), ("a", "a")]))  # one category: kappa undefined, not 1

    def test_fault_agreement(self):
        rep = classify.agreement_report([("x", "x", "agent_judgment", "agent_judgment"), ("x", "x", "none", "skill_instructions"),
                                         ("x", "x", "none", None)])
        self.assertEqual(rep["fault"]["pairs"], 2)
        self.assertAlmostEqual(rep["fault"]["agreement"], 0.5)

    def test_agreement_without_human_labels_says_so(self):
        with redirect_stdout(io.StringIO()) as o:
            rep = classify.agreement()
        self.assertEqual(rep["pairs"], 0)
        self.assertIn("Not enough human labels", o.getvalue())
        self.assertIn("labels export sample.csv --limit", o.getvalue())

    def test_label_sample_roundtrip(self):
        self.con.close()
        con = store.connect()
        for iid, cat in (("inc-tamper", "test_tampering"), ("inc-repeat", "stuck_retrying"), ("inc-idle0", "busy_waiting")):
            con.execute("INSERT INTO labels (incident_id, source, category, fault) VALUES (?, 'llm', ?, 'agent_judgment')", [iid, cat])
        con.close()
        path = self.tmp / "sample.csv"
        with redirect_stdout(io.StringIO()):
            classify.export_labels(path, limit=2, seed=5, blind=True)
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 2)
        self.assertFalse(any(k.startswith("llm_") for k in rows[0]))  # blind: the LLM answer cannot anchor the reviewer
        self.assertTrue({r["incident_id"] for r in rows} <= {"inc-tamper", "inc-repeat", "inc-idle0"})
        for r in rows:
            r["human_category"], r["human_fault"] = "busy_waiting", "agent_judgment"
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        with redirect_stdout(io.StringIO()) as o:
            classify.import_labels(path)
            rep = classify.agreement(as_json=True)
        self.assertEqual(rep["pairs"], 2)
        self.assertEqual(rep["fault"]["pairs"], 2)
        self.assertIn('"pairs": 2', o.getvalue())
        con = store.connect()
        con.execute("DELETE FROM labels")
        con.close()
        self.con = store.connect(read_only=True)

    # ------------------------------------------------------------ export-eval

    def test_export_eval_writes_runnable_cases(self):
        out = self.tmp / "evals-out"
        with redirect_stdout(io.StringIO()):
            res = evals.export(self.cfg, ids=["inc-tamper", "inc-marker", "inc-repeat", "inc-denied", "inc-api"], out=out,
                               use_history=True)
        self.assertEqual(res, out)
        plugin = out / "plugin-eval" / evals.PLUGIN
        self.assertEqual(json.loads((plugin / ".claude-plugin" / "plugin.json").read_text())["name"], evals.PLUGIN)
        self.assertTrue((plugin / "skills" / "build" / "SKILL.md").exists())  # the skill under test ships in the plugin
        cases = sorted(p.name for p in (plugin / "evals").iterdir())
        self.assertEqual(len(cases), 4)
        self.assertFalse(any("api" in c for c in cases))  # api errors have no task-level assertion
        valid = {"regex", "tool_used", "tool_order", "file_exists", "llm", "baseline"}
        allowed = {"type", "weight", "arm", "pattern", "flags", "match", "target", "tool", "input_match", "min", "max",
                   "before", "after", "path", "exists", "criteria", "focus", "baseline_file"}
        for case in cases:
            fields, body = parse_frontmatter((plugin / "evals" / case / "prompt.md").read_text(encoding="utf-8"))
            self.assertTrue(body.strip())
            self.assertLessEqual(set(fields), {"schema_version", "name", "description", "tags", "plugins", "runs",
                                               "expected_outcome", "model", "max_turns", "timeout_seconds", "allowed_tools",
                                               "append_system_prompt", "env"})
            graders = list((plugin / "evals" / case / "graders").glob("*.md"))
            self.assertTrue(graders)
            for g in graders:
                gf, gbody = parse_frontmatter(g.read_text(encoding="utf-8"))
                self.assertIn(gf["type"], valid)
                self.assertLessEqual(set(gf), allowed)
                for key in ("pattern", "input_match"):
                    if key in gf:
                        re.compile(gf[key])
                if gf["type"] == "llm":
                    self.assertIn("FAIL if", gbody)
        tamper = plugin / "evals" / "test-edit-after-failure-inc-tamper"
        fields, body = parse_frontmatter((tamper / "prompt.md").read_text(encoding="utf-8"))
        self.assertEqual(body.strip(), "Build step 3: make the failing tests in tests/ pass.")  # the spawn prompt, verbatim
        self.assertIn("Edit", fields["allowed_tools"])
        self.assertIn("not reconstructed", (tamper / "context.md").read_text(encoding="utf-8"))

    def test_export_eval_redacts_what_it_copies(self):
        fn = privacy.redactor({"privacy": {"redact": True}})
        rec = {"message": {"content": [{"type": "text", "text": "key sk-ant-FAKEFAKEFAKEFAKE1234"}]}, "n": 1}
        self.assertNotIn("FAKEFAKE", json.dumps(evals.redacted(rec, fn)))
        self.assertEqual(evals.redacted(rec, fn)["n"], 1)

    def test_export_eval_graders_match_the_failure(self):
        out = self.tmp / "evals-graders"
        with redirect_stdout(io.StringIO()):
            evals.export(self.cfg, ids=["inc-marker", "inc-repeat"], out=out, use_history=True)
        root = out / "plugin-eval" / evals.PLUGIN / "evals"
        marker, _ = parse_frontmatter((root / "bad-marker-inc-marker" / "graders" / "no-bad-marker.md").read_text(encoding="utf-8"))
        self.assertEqual(marker["match"], "not_contains")
        self.assertIsNotNone(re.search(marker["pattern"], json.dumps("STEP CHECK: FAIL\n2 broke")))
        self.assertIsNone(re.search(marker["pattern"], "STEP CHECK: PASS"))
        repeat, _ = parse_frontmatter((root / "repeated-call-inc-repeat" / "graders" / "no-repeated-call.md").read_text(encoding="utf-8"))
        encoded = json.dumps({"command": 'ls "missing dir"'}, separators=(",", ":"))
        self.assertIsNotNone(re.search(repeat["input_match"], encoded))  # matches the same call as Claude Code encodes it
        self.assertEqual((repeat["min"], repeat["max"], repeat["arm"]), (0, 2, "both"))
        # main-session case: resumed from the transcript cut before the message that made the failing call
        case = root / "bad-marker-inc-marker"
        hist = [json.loads(line) for line in (case / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["uuid"] for r in hist], ["1", "2", "3"])
        self.assertIn('history_file: "history.jsonl"', (case / "case.yaml").read_text(encoding="utf-8"))
        self.assertIn('schema_version: "1.1"', (case / "case.yaml").read_text(encoding="utf-8"))

    def test_export_eval_skips_cases_without_a_checking_grader(self):
        for typ in ("repeated_call", "permission_denied"):
            g, a = evals.checks(self.cfg, {"type": typ, "skill": "flow", "key": "x"}, None)  # failing call missing
            self.assertEqual((g, a), ([], []))  # no bare skill-fired, no tool_used without input_match
        g, _ = evals.checks(self.cfg, {"type": "idle_loop", "skill": "flow"}, None)
        self.assertTrue(all(x.get("input_match") for x in g if x["type"] == "tool_used" and "max" in x))

    def test_export_eval_prompt_from_skill_args_without_history(self):
        out = self.tmp / "evals-args"
        with redirect_stdout(io.StringIO()):
            evals.export(self.cfg, ids=["inc-marker"], out=out, fmt="plugin-eval")
        _, body = parse_frontmatter((out / "plugin-eval" / evals.PLUGIN / "evals" / "bad-marker-inc-marker" / "prompt.md")
                                    .read_text(encoding="utf-8"))
        self.assertEqual(body.strip(), f"/{evals.PLUGIN}:flow issue 7")
        self.assertFalse((out / "skill-creator").exists())

    def test_export_eval_skill_creator_format(self):
        out = self.tmp / "evals-sc"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["export-eval", "--incident", "inc-tamper", "--incident", "inc-marker",
                                       "--format", "skill-creator", "--out", str(out)]), 0)
        self.assertFalse((out / "plugin-eval").exists())
        for skill in ("build", "flow"):
            doc = json.loads((out / "skill-creator" / skill / "evals" / "evals.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["skill_name"], skill)
            for e in doc["evals"]:
                self.assertIsInstance(e["id"], int)
                self.assertTrue(e["prompt"] and e["expected_output"])
                self.assertEqual(e["files"], [])
                self.assertTrue(e["assertions"])
                self.assertEqual(e["assertions"], e["expectations"])
                self.assertNotIn("name", e)
        flow = json.loads((out / "skill-creator" / "flow" / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(flow["evals"][0]["prompt"], "issue 7")
        build = json.loads((out / "skill-creator" / "build" / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertIn("Must not edit tests", build["evals"][0]["assertions"][0])
        readme = (out / "README.md").read_text(encoding="utf-8")
        self.assertIn("The repository is not reconstructed", readme)

    def test_export_eval_by_label_skips_expected_behavior(self):
        self.con.close()
        con = store.connect()
        con.execute("INSERT INTO labels (incident_id, source, category) VALUES ('inc-repeat', 'llm', 'expected_behavior')")
        con.execute("INSERT INTO labels (incident_id, source, category) VALUES ('inc-denied', 'human', 'permission_blocked')")
        con.close()
        self.con = store.connect(read_only=True)
        flow = [i["incident_id"] for i in evals.select(self.con, skills=["flow"], limit=50)]
        self.assertNotIn("inc-repeat", flow)
        self.assertEqual([i["incident_id"] for i in evals.select(self.con, labels=["permission_blocked"])], ["inc-denied"])
        self.assertEqual(evals.select(self.con, skills=["x' OR '1'='1"]), [])
        self.con.close()
        con = store.connect()
        con.execute("DELETE FROM labels")
        con.close()
        self.con = store.connect(read_only=True)


class RetroSkillTest(unittest.TestCase):
    """The /runlens-retro skill: authoring limits, commands that exist, and its own eval scenarios."""
    ROOT = config.PACKAGE / "skill" / "runlens-retro"
    CONTRACT = {"score", "versions", "proposals", "verify"}  # implemented by the method wave (PLAN.md CLI JSON contract)

    def test_frontmatter_and_size(self):
        text = (self.ROOT / "SKILL.md").read_text(encoding="utf-8")
        head, _, body = text.removeprefix("---\n").partition("\n---\n")
        fields = {}
        for line in head.splitlines():  # hand-written YAML: plain scalars, or JSON-style quoted strings and booleans
            key, _, value = line.partition(": ")
            try:
                fields[key] = json.loads(value)
            except json.JSONDecodeError:
                fields[key] = value
        self.assertEqual(fields["name"], "runlens-retro")
        self.assertLessEqual(len(fields["description"]), 1024)
        self.assertIn("Run it yourself", fields["description"])  # it is user-invoked only, so the text must not promise automatic use
        self.assertNotIn("Use after", fields["description"])
        self.assertTrue(fields.get("argument-hint"))
        self.assertIs(fields["disable-model-invocation"], True)
        self.assertLess(len(body.splitlines()), 500)
        self.assertIn("- [ ]", body)  # a copyable checklist

    def test_every_command_it_runs_exists(self):
        with redirect_stdout(io.StringIO()) as o, self.assertRaises(SystemExit):
            cli.main(["--help"])
        known = set(re.search(r"\{([a-z,-]+)\}", o.getvalue()).group(1).split(",")) | self.CONTRACT
        used = set(re.findall(r"`runlens ([a-z-]+)", (self.ROOT / "SKILL.md").read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertLessEqual(used, known)

    def test_eval_scenarios(self):
        doc = json.loads((self.ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["skill_name"], "runlens-retro")
        self.assertGreaterEqual(len(doc["evals"]), 3)
        self.assertEqual(len({e["id"] for e in doc["evals"]}), len(doc["evals"]))
        for e in doc["evals"]:
            self.assertTrue(e["prompt"].startswith("/runlens-retro"))
            self.assertTrue(e["assertions"])
            self.assertEqual(e["assertions"], e["expectations"])
            for f in e["files"]:
                self.assertTrue((self.ROOT / f).exists(), f)
        self.assertEqual(list(self.ROOT.rglob("evals/**/SKILL.md")), [])  # fixtures must not be discovered as skills


if __name__ == "__main__":
    unittest.main()
