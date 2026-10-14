"""Claude Code integration: a SessionEnd hook that queues the run that just ended.

The hook only writes ~/.runlens/pending/<session_id> and starts a detached
`runlens drain`, then returns: Claude Code gives SessionEnd hooks 1.5 seconds by
default and kills hooks still running when a `claude -p` session tears down, so
the slow part (archive, ingest, dashboard) must not run inside the hook.
https://code.claude.com/docs/en/hooks ("Run hooks in the background")
`runlens refresh` drains the queue too, so a run whose drain never ran is
picked up later. Nothing here ever fails the session: errors go to hooks.log.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import config
from .fs import write_atomic

SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS", config.CLAUDE_DIR / "settings.json"))
SKILLS = config.CLAUDE_DIR / "skills"
HOOK_ARGS = ["-m", "runlens", "hook"]
LOG_MAX = 1_000_000  # bytes; hooks.log is rotated to hooks.log.1 beyond this


def log(line):
    config.HOME.mkdir(parents=True, exist_ok=True)
    path = config.HOME / "hooks.log"
    try:
        if path.exists() and path.stat().st_size > LOG_MAX:
            os.replace(path, path.with_name("hooks.log.1"))
    except OSError:
        pass
    flat = " | ".join(s.strip() for s in str(line).splitlines() if s.strip())  # one event per line
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S%z}  {flat}\n")


def refresh_dashboard(cfg):
    """Rebuild the benchmark dashboard after runs are ingested. Its failure is logged, never raised."""
    if not cfg.get("dashboard", {}).get("auto", True):
        return
    try:
        from .dashboard import write_dashboard
        write_dashboard(cfg)
    except Exception as e:
        log(f"dashboard: {type(e).__name__}: {e}")


def enqueue(sid, payload=None):
    config.PENDING.mkdir(parents=True, exist_ok=True)
    write_atomic(config.PENDING / sid, json.dumps(payload or {"session_id": sid}, ensure_ascii=False))


def pending():
    if not config.PENDING.is_dir():
        return []
    return sorted(p for p in config.PENDING.iterdir() if p.is_file() and not p.name.startswith("."))


def queued_transcript(sid):
    """The transcript_path the hook was given for a queued session, if it is a plain string."""
    try:
        path = json.loads((config.PENDING / sid).read_text(encoding="utf-8")).get("transcript_path")
    except (OSError, ValueError, AttributeError):
        return None
    return path if isinstance(path, str) and path else None


def handle(cfg, payload):
    """The hook itself: queue the session and start a detached drain. Returns at once."""
    if os.environ.get("RUNLENS_JUDGE"):
        return 0
    try:
        data = json.loads(payload or "{}")
        if not isinstance(data, dict) or data.get("hook_event_name") != "SessionEnd" or not data.get("session_id"):
            return 0
        sid = str(data["session_id"])
        if not sid.replace("-", "").isalnum():
            return 0
        log(f"queued {sid} ({data.get('reason')})")
        enqueue(sid, {"session_id": sid, "reason": data.get("reason"), "transcript_path": data.get("transcript_path"), "queued_at": datetime.now().astimezone().isoformat()})
        if os.environ.get("RUNLENS_HOOK_INLINE"):
            drain(cfg)
        else:
            spawn_drain()
    except Exception as e:  # a hook must never break the session
        log(f"error: {type(e).__name__}: {e}")
    return 0


def spawn_drain():
    """Start `runlens drain` fully detached, so it outlives the hook and the session."""
    args = [sys.executable, "-m", "runlens", "drain"]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True,
          "cwd": str(config.HOME)}
    if os.name == "nt":
        base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:  # leave the job object Claude Code may put hooks in, when the job allows it
            subprocess.Popen(args, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
            return
        except OSError:
            subprocess.Popen(args, creationflags=base, **kw)
    else:
        subprocess.Popen(args, start_new_session=True, **kw)


class DrainLock:
    """An OS-level lock on ~/.runlens/drain.lock, released by the OS if the process dies."""

    def __init__(self):
        self.fh = None

    def acquire(self):
        config.HOME.mkdir(parents=True, exist_ok=True)
        fh = open(config.HOME / "drain.lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True

    def release(self):
        if not self.fh:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None


def drain(cfg, wait_lock=False):
    """Archive and ingest every queued session, then rebuild the dashboard once.

    Runs last ingested by an older parser are re-ingested too, so a parser bump never leaves old numbers behind.
    Only one drain runs at a time. A drain that finds another one running leaves: that one re-reads the queue
    after it releases the lock, so a session queued meanwhile is never stranded. Returns how many were ingested.
    """
    from .archive import archive
    from .store import failed_sessions, ingest, is_locked, outdated_sessions
    total, tried, upgraded = 0, set(), False
    while True:
        lock = DrainLock()
        got = lock.acquire()
        while not got and wait_lock:
            time.sleep(1)
            got = lock.acquire()
        if not got:
            return total
        idle = False
        try:
            sids = [p.name for p in pending() if p.name not in tried]  # a session that failed waits for the next drain
            stale = []
            if not upgraded:
                upgraded = True
                try:
                    stale = outdated_sessions()
                except Exception as e:
                    log(f"parser check: {type(e).__name__}: {e}")
            if not sids and not stale:
                idle = True
            else:
                tried.update(sids)
                log(f"drain start: {len(sids)} queued" + (f", {len(stale)} on an older parser" if stale else ""))
                selected = set()
                for sid in sids:
                    try:
                        if archive(cfg, quiet=True, sessions=[sid], transcripts=[t for t in [queued_transcript(sid)] if t]):
                            selected.add(sid)
                        else:
                            log(f"skipped {sid}: not selected by [select] in config.toml")
                            (config.PENDING / sid).unlink(missing_ok=True)
                    except Exception as e:
                        log(f"error archiving {sid}: {type(e).__name__}: {e}")
                if selected or stale:
                    for attempt in range(8):  # another writer (a CLI command, classify) may hold the database
                        try:
                            n = ingest(cfg, sessions=sorted(selected | set(stale)), quiet=True)
                            break
                        except Exception as e:
                            if not is_locked(e) or attempt == 7:
                                raise
                            time.sleep(min(5 * 2 ** attempt, 60))
                    failed = failed_sessions(selected) if selected else set()
                    for sid in selected:
                        (config.PENDING / sid).unlink(missing_ok=True)
                        log(f"archived, ingest failed (see `runlens check`) {sid}" if sid in failed else f"archived and ingested {sid}")
                    if stale:
                        log(f"re-ingested {len(stale)} run(s) for the current parser")
                    total += n
                    refresh_dashboard(cfg)
        except Exception as e:
            log(f"error: {type(e).__name__}: {e} @ {traceback.format_exc().splitlines()[-3].strip()}")
            return total
        finally:
            lock.release()
        # A session queued after the empty read above but before the release would wait for the next drain: look again.
        if idle and not any(p.name not in tried for p in pending()):
            return total


# --- install ------------------------------------------------------------------------------------------------

def our_hook():
    # Synchronous on purpose: it returns in well under a second, and an async hook can be killed at teardown
    # (observed before it had queued anything). The timeout only bounds a pathological case (a stuck disk).
    return {"type": "command", "command": Path(sys.executable).as_posix(), "args": list(HOOK_ARGS), "timeout": 10}


def is_ours(group):
    """Only the hook runlens itself installs: `<python> -m runlens hook`, nothing that merely mentions runlens."""
    hooks = group.get("hooks", []) if isinstance(group, dict) else []
    return bool(hooks) and all(isinstance(h, dict) and h.get("args") == HOOK_ARGS for h in hooks)


def read_settings():
    if not SETTINGS.exists():
        return {}
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{SETTINGS} is not valid JSON (line {e.lineno}, column {e.colno}): fix it, then run this again") from None
    if not isinstance(data, dict):
        raise SystemExit(f"{SETTINGS} does not hold a JSON object: fix it, then run this again")
    return data


def write_settings(settings):
    write_atomic(SETTINGS, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")


def backup_settings():
    """One backup per day at most, so repeated installs do not pile up copies."""
    backup = SETTINGS.with_name(f"settings.json.runlens-backup-{datetime.now():%Y%m%d}")
    if not backup.exists():
        shutil.copy2(SETTINGS, backup)
    return backup


def install(skill=True):
    settings = read_settings()
    if SETTINGS.exists():
        print(f"backup  {backup_settings()}")
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f"{SETTINGS}: \"hooks\" is not an object; fix it, then run this again")
    groups = hooks.setdefault("SessionEnd", [])
    groups[:] = [g for g in groups if not is_ours(g)]
    groups.append({"hooks": [our_hook()]})
    write_settings(settings)
    print(f"hook    SessionEnd -> {Path(sys.executable).as_posix()} -m runlens hook (queues the run; a detached drain ingests it)")
    cfg = config.HOME / "config.toml"
    if not cfg.exists():
        config.HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.PACKAGE / "config.example.toml", cfg)
        print(f"config  {cfg} (edit [select], [[evidence]] and [[marker]] for your flow)")
    if skill:
        src = config.PACKAGE / "skill" / "runlens-retro"
        dst = SKILLS / "runlens-retro"
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("evals"))  # eval fixtures stay in the package
        print(f"skill   {dst} (/runlens-retro)")


def uninstall():
    if not SETTINGS.exists():
        print("no runlens hook installed")
        return
    settings = read_settings()
    groups = (settings.get("hooks") or {}).get("SessionEnd", [])
    kept = [g for g in groups if not is_ours(g)]
    if len(kept) == len(groups):
        print("no runlens hook installed")
        return
    backup_settings()
    if kept:
        settings["hooks"]["SessionEnd"] = kept
    else:
        settings["hooks"].pop("SessionEnd")
        if not settings["hooks"]:
            settings.pop("hooks")
    write_settings(settings)
    print("removed the runlens SessionEnd hook")
