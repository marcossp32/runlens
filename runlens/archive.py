"""Select runs from ~/.claude/projects and copy them into the archive.

Layout of the archive (every path goes through fs.fs_path, so depth is never a problem on Windows):
  <project>/<sid>.jsonl              the main transcript
  <project>/<sid>/...                its subagents and tool results, as Claude Code wrote them
  <project>/<sid>.runlens.json       what was selected and the size and mtime of each source file when copied
  <project>/<sid>.evidence.json      the run's [[evidence]] files: path, size, mtime and content hash
  _blobs/<2 hex>/<sha256>            each evidence file's content, stored once however many runs reference it
"""
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config
from .fs import fs_path, makedirs, plain, read_json, signature, write_json
from .transcripts import iter_records, run_files

SCAN_CACHE = "scan-cache.json"


def scan_session(main):
    """Cheap pass over a run: time span, cwd and every skill seen in it."""
    first = last = cwd = None
    skills = set()
    for f in run_files(main):
        for r in iter_records(f):
            t = r.get("timestamp")
            if isinstance(t, str) and t:
                first = min(first or t, t)
                last = max(last or t, t)
            if not cwd and isinstance(r.get("cwd"), str):
                cwd = r["cwd"]
            if isinstance(r.get("attributionSkill"), str):
                skills.add(r["attributionSkill"])
            if r.get("type") == "assistant":
                content = (r.get("message") or {}).get("content") if isinstance(r.get("message"), dict) else None
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
                        s = (b.get("input") or {}).get("skill") if isinstance(b.get("input"), dict) else None
                        if isinstance(s, str) and s:
                            skills.add(s)
    return {"session_id": plain(main).stem, "project": plain(main).parent.name, "cwd": cwd,
            "started": first, "ended": last, "skills": sorted(skills)}


def source_files(main):
    """Every file of a session in ~/.claude/projects, relative to the project folder: the main transcript and its folder."""
    main = fs_path(main)
    out = {main.name: main}
    side = main.with_suffix("")
    if side.is_dir():
        for f in side.rglob("*"):
            if f.is_file():
                out[f.relative_to(main.parent).as_posix()] = f
    return out


def source_signature(main):
    """{relative path: [size, mtime_ns]} of a session's source files. It changes whenever the session does."""
    sig = {}
    for rel, f in source_files(main).items():
        try:
            sig[rel] = signature(f)
        except OSError:
            pass
    return sig


def select(cfg, since=None, skills=None, projects=None, sessions=None, cache=None, transcripts=None):
    """Sessions that count as runs, with their scan. Unchanged sessions reuse the cached scan instead of being read."""
    sel = cfg.get("select", {})
    since_dt = config.since_utc(since or sel.get("since"))
    want_skills = set(skills or sel.get("skills", []))
    want_projects = [p.lower() for p in (projects or sel.get("projects", []))]
    cache = {} if cache is None else cache
    gone = pruned()
    found = {p.as_posix(): p for p in config.PROJECTS.glob("*/*.jsonl")}
    for extra in transcripts or []:  # a transcript_path the hook was given, wherever Claude Code keeps its projects
        extra = Path(extra)
        if extra.suffix == ".jsonl" and extra.is_file():
            found.setdefault(extra.as_posix(), extra)
    for main in sorted(found.values()):
        if (sessions and main.stem not in sessions) or main.stem in gone:
            continue
        try:
            sig = source_signature(main)
            hit = cache.get(main.as_posix())
            if hit and hit.get("sig") == sig:
                info = dict(hit["info"])
            else:
                info = scan_session(main)
                cache[main.as_posix()] = {"sig": sig, "info": info}
        except OSError as e:
            print(f"error  {main.stem[:8]}  cannot read: {e}", file=sys.stderr)
            continue
        started = config.parse_ts(info["started"])
        if not started or (since_dt and started < since_dt):
            continue
        if want_skills and not want_skills & set(info["skills"]):
            continue
        if want_projects and not any(p in (info["cwd"] or "").lower() for p in want_projects):
            continue
        info["source"] = sig
        yield main, info


PRUNED = "pruned.json"


def pruned():
    """{session id: what was recorded} for every run `prune` deleted. archive, ingest and check leave these out,
    so a pruned run is not copied, loaded or asked for again while its source is still in ~/.claude/projects."""
    try:
        data = read_json(config.HOME / PRUNED)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_pruned(entries):
    if entries:
        write_json(config.HOME / PRUNED, {**pruned(), **{e["session_id"]: e for e in entries}})


def unprune(ids):
    """Take runs off the pruned list (by full id or 8-character prefix), so the next archive and ingest bring them
    back. Returns the session ids taken off."""
    have = pruned()
    gone = [sid for sid in have if any(sid == x or sid[:8] == x for x in ids or [])]
    if gone:
        write_json(config.HOME / PRUNED, {k: v for k, v in have.items() if k not in gone})
    return gone


def load_cache():
    try:
        return read_json(config.HOME / SCAN_CACHE)
    except (OSError, ValueError):
        return {}


def copy_if_changed(src, dst):
    src, dst = fs_path(src), fs_path(dst)
    s = src.stat()
    if dst.exists():
        d = dst.stat()
        if d.st_size == s.st_size and d.st_mtime_ns >= s.st_mtime_ns:
            return False
    makedirs(dst.parent)
    shutil.copy2(src, dst)
    return True


def git_dir(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# --- evidence ----------------------------------------------------------------------------------------------

def glob_rx(pattern):
    """A compiled regex for a glob over a relative posix path: ** spans folders, * and ? stay inside one."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z", re.I)


def excluder(patterns):
    rxs = [glob_rx(p) for p in patterns]
    return lambda rel: any(rx.match(rel) for rx in rxs)


def blob_path(digest):
    return config.BLOBS / digest[:2] / digest


def hash_file(path):
    h = hashlib.sha256()
    with open(fs_path(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_blob(src, digest):
    """Copy a file into the blob store unless that content is already there."""
    dst = fs_path(blob_path(digest))
    if dst.exists():
        return False
    makedirs(dst.parent)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copy2(fs_path(src), tmp)
    os.replace(tmp, dst)
    return True


def rule_matches(ev, places):
    """(root, [(relative path, file)]) for one [[evidence]] rule."""
    pattern = ev["glob"].format(**places).replace("\\", "/")
    prefix = pattern.split("*")[0]
    root = prefix.rstrip("/") if "*" in pattern and prefix.endswith("/") else os.path.dirname(prefix.rstrip("/"))
    rel_pattern = pattern[len(root):].lstrip("/") if root else pattern
    froot = fs_path(root or ".")
    if not froot.is_dir():
        return root, []
    # glob relative to the root: a \\?\ prefix in the pattern itself would be read as a wildcard
    names = glob.glob(rel_pattern, root_dir=froot, recursive=True, include_hidden=True)
    out = []
    for name in sorted(names):
        f = froot / name
        if f.is_file():
            out.append((Path(name).as_posix(), f))
    return root, out


def archive_evidence(cfg, info, project, sid, quiet=True):
    """Store the files a flow leaves outside the transcript ([[evidence]]) and write the run's evidence manifest.

    Only files modified while the run was going are kept by default (scope = "run"), browser profiles, databases
    and dependency folders are never kept, and each rule stops at max_mb per run. Contents are deduplicated."""
    rules = cfg.get("evidence") or []
    if not rules or not info.get("cwd"):
        return False
    mpath = config.ARCHIVE / project / f"{sid}.evidence.json"
    try:
        previous = {(e["rule"], e["path"]): e for e in read_json(mpath).get("files", [])}
    except (OSError, ValueError):
        previous = {}
    started, ended = config.parse_ts(info.get("started")), config.parse_ts(info.get("ended"))
    places = {"cwd": info["cwd"], "git_dir": None, "session_id": sid}
    files, skipped, changed = [], [], False
    for ev in rules:
        opts = {**config.EVIDENCE, **ev}
        name = ev.get("name", "files")
        if "{git_dir}" in ev["glob"]:
            places["git_dir"] = places["git_dir"] or git_dir(info["cwd"])
            if not places["git_dir"]:
                continue
        excluded = excluder(config.EVIDENCE_EXCLUDE + list(opts.get("exclude") or []))
        slack = timedelta(minutes=opts["slack_minutes"])
        budget = opts["max_mb"] * 1024 * 1024 if opts.get("max_mb") else None
        used = 0
        _, matches = rule_matches(ev, places)
        for rel, f in matches:
            if excluded(rel):
                continue
            st = f.stat()
            mtime = datetime.fromtimestamp(st.st_mtime, timezone.utc)
            if opts["scope"] == "run" and started and ended and not (started - slack <= mtime <= ended + slack):
                continue
            if budget is not None and used + st.st_size > budget:
                skipped.append({"rule": name, "path": rel, "size": st.st_size, "reason": f"over max_mb = {opts['max_mb']}"})
                continue
            used += st.st_size
            old = previous.get((name, rel))
            if old and old["size"] == st.st_size and old.get("mtime_ns") == st.st_mtime_ns:
                digest = old["sha256"]
            else:
                digest = hash_file(f)
                changed = True
            changed |= store_blob(f, digest)
            files.append({"rule": name, "path": rel, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                          "mtime": mtime.isoformat(), "sha256": digest})
    seen = {(e["rule"], e["path"]) for e in files}
    files += [e for k, e in previous.items() if e.get("legacy") and k not in seen]  # migrated from 0.1: kept as they were
    if skipped and not quiet:
        print(f"note   {sid[:8]}  {len(skipped)} evidence file(s) over max_mb were left out (listed in {plain(mpath).name})")
    if changed or set(previous) != {(e["rule"], e["path"]) for e in files} or not fs_path(mpath).exists():
        write_json(mpath, {"session_id": sid, "files": files, "skipped": skipped})
        changed = True
    return changed


def evidence_file(project, sid, rule, path):
    """The archived content of one evidence file, by the run, rule and path it was recorded under."""
    for e in read_json(config.ARCHIVE / project / f"{sid}.evidence.json").get("files", []):
        if e["rule"] == rule and e["path"] == path:
            return plain(fs_path(blob_path(e["sha256"])))
    return None


# --- archive -----------------------------------------------------------------------------------------------

def archive(cfg, quiet=False, **filters):
    """Copy selected runs into the archive. A run whose source changed since it was archived is copied again."""
    n, cache = 0, load_cache()
    for main, info in select(cfg, cache=cache, **filters):
        sid = main.stem
        new = not fs_path(config.ARCHIVE / info["project"] / f"{sid}.runlens.json").exists()
        try:
            changed = archive_run(cfg, main, info, quiet)
        except Exception as e:  # one unreadable run must not stop the others
            print(f"error  {sid[:8]}  {type(e).__name__}: {e}", file=sys.stderr)
            continue
        n += 1
        if not quiet:
            label = "new    " if new else "updated" if changed else "same   "
            print(f"{label}  {info['started'][:16]}  {sid}  {info['cwd']}")
    try:
        write_json(config.HOME / SCAN_CACHE, cache)
    except OSError:
        pass
    if not quiet:
        print(f"{n} run(s) in {config.ARCHIVE}")
    return n


def archive_run(cfg, main, info, quiet=True):
    sid, dest = main.stem, config.ARCHIVE / info["project"]
    mpath = dest / f"{sid}.runlens.json"
    try:
        old = read_json(mpath)
    except (OSError, ValueError):
        old = None
    changed = False
    for rel, f in source_files(main).items():
        changed |= copy_if_changed(f, dest / rel)
    if old is None or old.get("source") != info["source"] or changed:
        changed |= archive_evidence(cfg, info, info["project"], sid, quiet)
        info["archived_at"] = datetime.now(timezone.utc).isoformat()
        write_json(mpath, info)
        changed = True
    elif cfg.get("evidence") and not fs_path(dest / f"{sid}.evidence.json").exists():
        changed |= archive_evidence(cfg, info, info["project"], sid, quiet)
    return changed


def stale_runs():
    """Archived runs whose source in ~/.claude/projects changed after they were copied: (sid, project, reason)."""
    out, gone = [], pruned()
    for mf in sorted(fs_path(config.ARCHIVE).glob("*/*.runlens.json")):
        if mf.name.removesuffix(".runlens.json") in gone:
            continue  # pruned with --keep-archive: no longer tracked
        try:
            info = read_json(mf)
        except (OSError, ValueError):
            continue
        sid, project = info.get("session_id"), info.get("project")
        src = config.PROJECTS / project / f"{sid}.jsonl"
        if not fs_path(src).exists():
            continue  # Claude Code cleaned it up; the archive is now the only copy
        recorded = info.get("source")
        now = source_signature(src)
        if recorded is None:
            archived = source_signature(mf.with_name(f"{sid}.jsonl"))
            ok = all(now.get(k, [None])[0] == v[0] for k, v in archived.items()) and set(now) <= set(archived)
            if not ok:
                out.append((sid, project, f"source has {len(now)} file(s), archive {len(archived)}; sizes differ"))
        elif recorded != now:
            new = len(set(now) - set(recorded))
            grown = sum(1 for k in set(now) & set(recorded) if now[k] != recorded[k])
            out.append((sid, project, f"source changed since it was archived ({new} new file(s), {grown} changed)"))
    return out


def remove_run(project, sid):
    """Delete one run from the archive: transcripts, manifests, evidence manifest. Blobs go in collect_garbage."""
    base = config.ARCHIVE / project
    for f in (base / f"{sid}.jsonl", base / f"{sid}.runlens.json", base / f"{sid}.evidence.json"):
        try:
            os.unlink(fs_path(f))
        except FileNotFoundError:
            pass
    rmtree(base / sid)


def rmtree(path):
    """shutil.rmtree for archive folders: long paths, and read-only files (git objects) made writable first."""
    p = fs_path(path)
    if not p.exists():
        return

    def retry(func, target, _exc):
        os.chmod(target, 0o700)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=retry)
    else:
        shutil.rmtree(p, onerror=lambda f, t, e: retry(f, t, e))


def referenced_blobs():
    refs = set()
    for mf in fs_path(config.ARCHIVE).glob("*/*.evidence.json"):
        try:
            refs.update(e["sha256"] for e in read_json(mf).get("files", []))
        except (OSError, ValueError, KeyError):
            pass
    return refs


def collect_garbage():
    """Delete blobs no evidence manifest references any more. Returns (files, bytes) freed."""
    root = fs_path(config.BLOBS)
    if not root.is_dir():
        return 0, 0
    refs, files, size = referenced_blobs(), 0, 0
    for f in root.glob("*/*"):
        if f.is_file() and f.name not in refs:
            size += f.stat().st_size
            f.unlink()
            files += 1
    return files, size


# --- migration of evidence archived by runlens 0.1 ------------------------------------------------------

def migrate_evidence(dry_run=True, keep_excluded=False, quiet=False):
    """Turn the per-run evidence/ folders of runlens 0.1 into blobs plus manifests, then delete those folders.

    0.1 copied every match into <project>/<sid>/evidence/<rule>/<path>, the same tree again for every run.
    Each file is hashed once per (rule, path, size, mtime): identical copies in other runs reuse the hash.
    Files the default exclude list covers (browser profiles, databases, node_modules...) are dropped unless
    keep_excluded. Returns a summary dict.
    """
    excluded = excluder(config.EVIDENCE_EXCLUDE)
    known, stats = {}, {"runs": 0, "files": 0, "bytes": 0, "excluded_files": 0, "excluded_bytes": 0,
                         "blobs_new": 0, "blob_bytes_new": 0, "folders_deleted": 0}
    for folder in sorted(fs_path(config.ARCHIVE).glob("*/*/evidence")):
        if not folder.is_dir() or folder.parent.parent.name == "_blobs":
            continue
        sid, project = folder.parent.name, folder.parent.parent.name
        mpath = config.ARCHIVE / project / f"{sid}.evidence.json"
        try:
            entries = {(e["rule"], e["path"]): e for e in read_json(mpath).get("files", [])}
        except (OSError, ValueError):
            entries = {}
        stats["runs"] += 1
        for dirpath, _dirs, names in os.walk(folder):
            for name in names:
                f = Path(dirpath) / name
                parts = f.relative_to(folder).parts
                rule, rel = (parts[0], "/".join(parts[1:])) if len(parts) > 1 else ("files", parts[0])
                st = f.stat()
                stats["files"] += 1
                stats["bytes"] += st.st_size
                if not keep_excluded and excluded(rel):
                    stats["excluded_files"] += 1
                    stats["excluded_bytes"] += st.st_size
                    continue
                key = (rule, rel, st.st_size, st.st_mtime_ns)
                digest = known.get(key)
                if digest is None:
                    digest = known[key] = hash_file(f) if not dry_run else f"pending:{len(known)}"
                    is_new = dry_run or not fs_path(blob_path(digest)).exists()
                    if is_new:
                        stats["blobs_new"] += 1
                        stats["blob_bytes_new"] += st.st_size
                if not dry_run:
                    store_blob(f, digest)
                entries[(rule, rel)] = {"rule": rule, "path": rel, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                                        "sha256": digest, "legacy": True}
        if dry_run:
            continue
        write_json(mpath, {"session_id": sid, "files": sorted(entries.values(), key=lambda e: (e["rule"], e["path"])),
                           "skipped": [], "migrated_from": "evidence/"})
        missing = [e for e in entries.values() if not fs_path(blob_path(e["sha256"])).exists()]
        if missing:
            raise RuntimeError(f"{sid}: {len(missing)} blob(s) missing after migration; {plain(folder)} was kept")
        rmtree(folder)
        stats["folders_deleted"] += 1
        if not quiet:
            print(f"migrated  {sid[:8]}  {project}")
    return stats
