"""Select runs from ~/.claude/projects and copy them into the archive."""
import glob
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .transcripts import iter_records, run_files


def scan_session(main):
    """Cheap pass over a run: time span, cwd and every skill seen in it."""
    first = last = cwd = None
    skills = set()
    for f in run_files(main):
        for r in iter_records(f):
            t = r.get("timestamp")
            if t:
                first = min(first or t, t)
                last = max(last or t, t)
            cwd = cwd or r.get("cwd")
            if r.get("attributionSkill"):
                skills.add(r["attributionSkill"])
            if r.get("type") == "assistant":
                for b in (r.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                        s = (b.get("input") or {}).get("skill")
                        if s:
                            skills.add(s)
    return {"session_id": main.stem, "project": main.parent.name, "cwd": cwd,
            "started": first, "ended": last, "skills": sorted(skills)}


def select(cfg, since=None, skills=None, projects=None, sessions=None):
    sel = cfg.get("select", {})
    since = since or sel.get("since")
    want_skills = set(skills or sel.get("skills", []))
    want_projects = [p.lower() for p in (projects or sel.get("projects", []))]
    for main in sorted(config.PROJECTS.glob("*/*.jsonl")):
        if sessions and main.stem not in sessions:
            continue
        info = scan_session(main)
        if not info["started"] or (since and info["started"] < since):
            continue
        if want_skills and not want_skills & set(info["skills"]):
            continue
        if want_projects and not any(p in (info["cwd"] or "").lower() for p in want_projects):
            continue
        yield main, info


def copy_if_changed(src, dst):
    if dst.exists() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def git_dir(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def archive_evidence(cfg, info, dest):
    """Copy files a flow leaves outside the transcript, from [[evidence]] globs."""
    changed = False
    if not cfg.get("evidence") or not info["cwd"]:
        return changed
    places = {"cwd": info["cwd"], "git_dir": None}
    for ev in cfg["evidence"]:
        if "{git_dir}" in ev["glob"]:
            places["git_dir"] = places["git_dir"] or git_dir(info["cwd"])
            if not places["git_dir"]:
                continue
        pattern = ev["glob"].format(**places).replace("\\", "/")
        prefix = pattern.split("*")[0]
        root = Path(prefix) if "*" in pattern and prefix.endswith("/") else Path(prefix).parent
        for name in glob.glob(pattern, recursive=True):
            f = Path(name)
            if f.is_file():
                changed |= copy_if_changed(f, dest / ev.get("name", "files") / f.relative_to(root))
    return changed


def archive(cfg, quiet=False, **filters):
    n = 0
    for main, info in select(cfg, **filters):
        dest = config.ARCHIVE / info["project"]
        changed = copy_if_changed(main, dest / main.name)
        side = main.with_suffix("")
        if side.is_dir():
            for f in side.rglob("*"):
                if f.is_file():
                    changed |= copy_if_changed(f, dest / main.stem / f.relative_to(side))
        changed |= archive_evidence(cfg, info, dest / main.stem / "evidence")
        info["archived_at"] = datetime.now(timezone.utc).isoformat()
        (dest / f"{main.stem}.runlens.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        n += 1
        if not quiet:
            print(f"{'updated' if changed else 'same   '}  {info['started'][:16]}  {main.stem}  {info['cwd']}")
    if not quiet:
        print(f"{n} run(s) in {config.ARCHIVE}")
    return n
