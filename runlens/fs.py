"""Filesystem helpers shared by everything that touches the archive.

Windows refuses paths longer than 260 characters unless long paths are enabled
machine-wide (LongPathsEnabled) or the path carries the \\\\?\\ prefix. The archive
nests deep (project folder, session, subagents, evidence), so every file
operation on it goes through `fs_path`. The prefix turns off Windows' own path
normalisation, so the path is made absolute and `..` is folded first, and UNC
shares need the \\\\?\\UNC\\ form.
https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation
"""
import json
import os
import tempfile
from pathlib import Path

LONG = "\\\\?\\"
LONG_UNC = "\\\\?\\UNC\\"


def fs_path(p):
    """An absolute path that every OS call accepts, whatever its length."""
    s = str(p)
    if os.name != "nt":
        return Path(os.path.abspath(s))
    if s.startswith(LONG):
        return Path(s)
    s = os.path.abspath(s)  # folds `..` and `.`, which the prefix would otherwise keep literally
    if s.startswith("\\\\"):
        return Path(LONG_UNC + s[2:])
    return Path(LONG + s)


def plain(p):
    """The same path without the long-path prefix, for messages and for storing."""
    s = str(p)
    if s.startswith(LONG_UNC):
        return Path("\\\\" + s[len(LONG_UNC):])
    if s.startswith(LONG):
        return Path(s[len(LONG):])
    return Path(s)


def makedirs(p):
    """mkdir -p that works on prefixed paths (os.makedirs walks up into the bare prefix and fails)."""
    p = fs_path(p)
    missing = []
    while not p.exists():
        missing.append(p)
        if p.parent == p:
            break
        p = p.parent
    for d in reversed(missing):
        try:
            os.mkdir(d)
        except FileExistsError:
            pass


def write_atomic(path, text):
    """Write a text file so readers see either the old or the new content, never half of it."""
    path = fs_path(path)
    makedirs(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data):
    write_atomic(path, json.dumps(data, indent=2, ensure_ascii=False, default=str))


def read_json(path):
    with open(fs_path(path), encoding="utf-8") as fh:
        return json.load(fh)


def signature(p):
    """(size, mtime in ns) of a file: what tells a changed file from an unchanged one without reading it."""
    st = os.stat(fs_path(p))
    return [st.st_size, st.st_mtime_ns]
