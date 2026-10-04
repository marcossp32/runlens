"""Claude Code integration: a SessionEnd hook that archives and ingests the run that just ended.

The hook runs async, applies the same [select] filters as `runlens archive`, and
never fails the session: errors go to ~/.runlens/hooks.log.
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config

SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS", Path.home() / ".claude" / "settings.json"))
SKILLS = Path.home() / ".claude" / "skills"


def log(line):
    config.HOME.mkdir(parents=True, exist_ok=True)
    with open(config.HOME / "hooks.log", "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")


def handle(cfg, payload):
    if os.environ.get("RUNLENS_JUDGE"):
        return 0
    try:
        data = json.loads(payload or "{}")
        if data.get("hook_event_name") != "SessionEnd" or not data.get("session_id"):
            return 0
        sid = data["session_id"]
        from .archive import archive
        from .store import ingest
        if not archive(cfg, quiet=True, sessions=[sid]):
            log(f"skipped {sid}: not selected by [select] in config.toml")
            return 0
        for attempt in range(6):  # DuckDB allows one writer: another hook or an open session may hold the lock
            try:
                ingest(cfg, sessions=[sid], quiet=True)
                log(f"archived and ingested {sid} ({data.get('reason')})")
                return 0
            except Exception as e:
                if "lock" not in str(e).lower() or attempt == 5:
                    raise
                time.sleep(10 * (attempt + 1))
    except Exception as e:  # a hook must never break the session
        log(f"error: {type(e).__name__}: {e}")
    return 0


def is_ours(group):
    return any("runlens" in " ".join([h.get("command", "")] + h.get("args", [])) for h in group.get("hooks", []))


def install(skill=True):
    settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.runlens-backup-{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(SETTINGS, backup)
        print(f"backup  {backup}")
    groups = settings.setdefault("hooks", {}).setdefault("SessionEnd", [])
    groups[:] = [g for g in groups if not is_ours(g)]
    groups.append({"hooks": [{"type": "command", "command": Path(sys.executable).as_posix(),
                              "args": ["-m", "runlens", "hook"], "async": True, "timeout": 600}]})
    SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"hook    SessionEnd -> {Path(sys.executable).as_posix()} -m runlens hook (async)")
    cfg = config.HOME / "config.toml"
    if not cfg.exists():
        config.HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.PACKAGE / "config.example.toml", cfg)
        print(f"config  {cfg} (edit [select], [[evidence]] and [[marker]] for your flow)")
    if skill:
        src = config.PACKAGE / "skill" / "runlens-retro"
        dst = SKILLS / "runlens-retro"
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"skill   {dst} (/runlens-retro)")


def uninstall():
    if not SETTINGS.exists():
        return
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    groups = settings.get("hooks", {}).get("SessionEnd", [])
    kept = [g for g in groups if not is_ours(g)]
    if len(kept) == len(groups):
        print("no runlens hook installed")
        return
    shutil.copy2(SETTINGS, SETTINGS.with_name(f"settings.json.runlens-backup-{datetime.now():%Y%m%d%H%M%S}"))
    if kept:
        settings["hooks"]["SessionEnd"] = kept
    else:
        settings["hooks"].pop("SessionEnd")
        if not settings["hooks"]:
            settings.pop("hooks")
    SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print("removed the runlens SessionEnd hook")
