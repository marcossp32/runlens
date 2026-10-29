"""Compare two versions of /runlens-retro on its eval scenarios, and keep the numbers.

Each scenario in runlens/skill/runlens-retro/evals/evals.json replays canned runlens output, so a run needs no
database. This runs every scenario several times with each skill text through `claude -p`, has a judge grade each
report against the scenario's assertions without knowing which version wrote it, and writes benchmark.json and
benchmark.md: pass rate per scenario and version, with tokens, time and cost.

    python scripts/eval_retro.py                         # the working copy against main, 3 runs each
    python scripts/eval_retro.py --base HEAD~1 --runs 1 --evals 8 9

Isolation: runs use only project settings from an empty folder (so no user hook, such as runlens's own SessionEnd
hook, archives them), are not saved as sessions, and may only read files, so no real `runlens` command runs.
Every call is a model call on your account.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "runlens" / "skill" / "runlens-retro"
GRADE_SCHEMA = {
    "type": "object", "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "required": ["assertion", "passed", "evidence"],
        "properties": {"assertion": {"type": "string"}, "passed": {"type": "boolean"}, "evidence": {"type": "string"}}}}},
}
JUDGE = """You grade one report written by an agent that ran a retrospective skill on canned data.

Expected outcome, for context:
{expected}

For each assertion, decide whether the report meets it. Require concrete evidence in the report for a pass: quote
the words that meet it. When the report is silent or ambiguous, the assertion fails. Judge only the report below.

Assertions:
{assertions}

<report>
{report}
</report>"""


def claude_exe():
    """The claude binary; on Windows the npm `claude.cmd` shim would send arguments through cmd.exe, which mangles JSON."""
    found = shutil.which("claude")
    if not found:
        raise SystemExit("claude is not on PATH")
    exe = Path(found).with_name("node_modules") / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
    return str(exe) if Path(found).suffix.lower() == ".cmd" and exe.exists() else found


def claude(prompt, cwd, model, tools, schema=None, timeout=1200):
    cmd = [claude_exe(), "-p", "--model", model, "--output-format", "json", "--setting-sources", "project",
           "--no-session-persistence", "--allowedTools", *tools, "--disallowedTools", "Bash", "PowerShell", "Write", "Edit",
           "NotebookEdit", "WebFetch", "WebSearch", "Agent"]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    t0 = time.time()
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=timeout)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"claude -p failed ({r.returncode}): {r.stderr[-500:] or r.stdout[-500:]}") from err
    out["wall_s"] = round(time.time() - t0, 1)
    return out


def skill_prompt(skill_text, ev):
    """What Claude Code would hand the model when a person types the eval's /runlens-retro line."""
    first, _, rest = ev["prompt"].partition("\n")
    args = first.removeprefix("/runlens-retro").strip()
    body = skill_text.split("---", 2)[2] if skill_text.startswith("---") else skill_text
    return (f"The person ran `/runlens-retro {args}`. The skill's instructions follow.\n\n<skill name=\"runlens-retro\">\n"
            f"{body.replace('$ARGUMENTS', args).strip()}\n</skill>\n\n{rest.strip()}")


def one(job, texts, work, out_dir, model, judge):
    ev, arm, n = job
    run_dir = out_dir / ev["name"] / arm / f"run-{n}"
    if (run_dir / "grading.json").exists():  # resume
        return json.loads((run_dir / "grading.json").read_text(encoding="utf-8"))
    run_dir.mkdir(parents=True, exist_ok=True)
    res = claude(skill_prompt(texts[arm], ev), work, model, ["Read", "Glob", "Grep"])
    report = res.get("result") or ""
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    g = claude(JUDGE.format(expected=ev["expected_output"], report=report,
                            assertions="\n".join(f"{i + 1}. {a}" for i, a in enumerate(ev["assertions"]))),
               work, judge, ["Read"], schema=GRADE_SCHEMA)
    results = (g.get("structured_output") or {}).get("results") or []
    if len(results) != len(ev["assertions"]):
        raise RuntimeError(f"{ev['name']}/{arm}/{n}: judge returned {len(results)} of {len(ev['assertions'])} results")
    for r, a in zip(results, ev["assertions"]):
        r["assertion"] = a
    usage = res.get("usage") or {}
    grading = {"eval": ev["name"], "arm": arm, "run": n, "passed": sum(r["passed"] for r in results), "total": len(results),
               "results": results, "cost_usd": res.get("total_cost_usd"), "wall_s": res["wall_s"], "turns": res.get("num_turns"),
               "tokens": sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                         "cache_read_input_tokens", "output_tokens"))}
    (run_dir / "grading.json").write_text(json.dumps(grading, indent=2), encoding="utf-8")
    print(f"{ev['name']:<44} {arm:<4} run {n}: {grading['passed']}/{grading['total']}", flush=True)
    return grading


def summarise(gradings, evals, meta):
    rows = []
    for ev in evals:
        row = {"eval": ev["name"]}
        for arm in ("new", "base"):
            g = [x for x in gradings if x["eval"] == ev["name"] and x["arm"] == arm]
            rates = [x["passed"] / x["total"] for x in g]
            row[arm] = {"pass_rate": statistics.mean(rates), "stdev": statistics.pstdev(rates), "runs": len(g),
                        "all_pass_runs": sum(x["passed"] == x["total"] for x in g),
                        "tokens": statistics.mean(x["tokens"] for x in g), "wall_s": statistics.mean(x["wall_s"] for x in g),
                        "cost_usd": sum(x["cost_usd"] or 0 for x in g)}
            row[arm]["failed"] = sorted({r["assertion"] for x in g for r in x["results"] if not r["passed"]})
        rows.append(row)
    both = [ev["name"] + ": " + a for ev in evals for a in ev["assertions"]
            if all(r["passed"] for x in gradings if x["eval"] == ev["name"] for r in x["results"] if r["assertion"] == a)]
    return {**meta, "evals": rows, "always_pass_in_both": both}


def markdown(b):
    pct = lambda x: f"{x:.0%}"
    lines = [f"# /runlens-retro benchmark, {b['date']}", "",
             f"New: {b['new']} · Base: {b['base']} · {b['runs']} runs each · runs on {b['model']}, graded by {b['judge']}", "",
             "| Scenario | New pass | New all-pass runs | Base pass | Base all-pass runs | New tokens | Base tokens |",
             "|---|---|---|---|---|---|---|"]
    for r in b["evals"]:
        n, o = r["new"], r["base"]
        lines.append(f"| {r['eval']} | {pct(n['pass_rate'])} ± {pct(n['stdev'])} | {n['all_pass_runs']}/{n['runs']} | "
                     f"{pct(o['pass_rate'])} ± {pct(o['stdev'])} | {o['all_pass_runs']}/{o['runs']} | {n['tokens']:,.0f} | {o['tokens']:,.0f} |")
    for arm in ("new", "base"):
        tot = [r[arm] for r in b["evals"]]
        lines.append(f"\n**{arm}**: mean pass rate {pct(statistics.mean(x['pass_rate'] for x in tot))}, "
                     f"mean tokens {statistics.mean(x['tokens'] for x in tot):,.0f}, mean time {statistics.mean(x['wall_s'] for x in tot):.0f} s, "
                     f"cost ${sum(x['cost_usd'] for x in tot):.2f}")
    lines += ["", "## Failed assertions", ""]
    for r in b["evals"]:
        for arm in ("new", "base"):
            for a in r[arm]["failed"]:
                lines.append(f"- {r['eval']} ({arm}): {a}")
    lines += ["", "## Assertions that passed in every run of both versions", ""] + [f"- {a}" for a in b["always_pass_in_both"]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="main", help="git ref of the baseline skill text (default main)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--evals", type=int, nargs="*", help="only these eval ids")
    ap.add_argument("--model", default="sonnet", help="model the skill runs on")
    ap.add_argument("--judge", default="sonnet", help="model that grades the reports")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", help="output folder (default ~/.runlens/retro-benchmarks/<date>, outside the repo)")
    a = ap.parse_args(argv)
    evals = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    evals = [e for e in evals if not a.evals or e["id"] in a.evals]
    base_text = subprocess.run(["git", "show", f"{a.base}:runlens/skill/runlens-retro/SKILL.md"], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", check=True).stdout
    texts = {"new": (SKILL / "SKILL.md").read_text(encoding="utf-8"), "base": base_text}
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    home = Path(os.environ.get("RUNLENS_HOME") or Path.home() / ".runlens")
    out_dir = Path(a.out) if a.out else home / "retro-benchmarks" / date
    work = Path(tempfile.mkdtemp(prefix="retro-eval-"))
    shutil.copytree(SKILL / "evals", work / "evals")  # fixtures only, no skill text
    jobs = [(e, arm, n) for e in evals for arm in ("new", "base") for n in range(1, a.runs + 1)]
    try:
        with ThreadPoolExecutor(a.workers) as pool:
            gradings = list(pool.map(lambda j: one(j, texts, work, out_dir, a.model, a.judge), jobs))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    meta = {"date": date, "new": "working copy", "base": a.base, "runs": a.runs, "model": a.model, "judge": a.judge}
    bench = summarise(gradings, evals, meta)
    (out_dir / "benchmark.json").write_text(json.dumps(bench, indent=2), encoding="utf-8")
    (out_dir / "benchmark.md").write_text(markdown(bench), encoding="utf-8")
    print(f"\n{out_dir / 'benchmark.md'}")


if __name__ == "__main__":
    main()
