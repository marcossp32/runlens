"""Paths and config. Everything flow-specific comes from config.toml, never from code."""
import os
import re
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

HOME = Path(os.environ.get("RUNLENS_HOME", Path.home() / ".runlens"))
# Claude Code keeps settings, skills and transcripts under CLAUDE_CONFIG_DIR when it is set (code.claude.com/docs/en/env-vars)
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS", CLAUDE_DIR / "projects"))
ARCHIVE = HOME / "archive"
BLOBS = ARCHIVE / "_blobs"      # evidence files, stored once by content hash
PENDING = HOME / "pending"      # sessions the hook queued for archive + ingest
DB = HOME / "runlens.duckdb"
PACKAGE = Path(__file__).parent

# Defaults for the generic analysis. Any key can be overridden under [analysis].
ANALYSIS = {
    # A Bash/PowerShell command made only of these parts does no work: it waits or prints.
    "idle_parts": [r"sleep\s+[\d.]+[smh]?", r"Start-Sleep(\s+-\w+)?\s+[\d.]+", r"echo(\s+.*)?", r"Write-(Host|Output)(\s+.*)?",
                   r"true", r":", r"timeout(\s+/t)?\s+\d+", r"wait"],
    # Paths that hold tests, for "a build edited the tests" signals.
    "test_path": r"(^|[\\/])(tests?|__tests__|specs?|e2e)[\\/]|\.(test|spec)\.[A-Za-z0-9]+$|(^|[\\/])test_[^\\/]+\.py$|_test\.(py|go|rb)$",
    "repeat_min": 3,        # identical tool calls in one agent before it counts as a repeat
    "repeat_window_s": 600,  # identical calls must fall within this many seconds to count as a repeat
    "idle_min": 3,          # idle calls in one agent before it counts as an idle loop
    "error_streak_min": 2,  # consecutive failing tool calls before it counts as a streak
    "context_steps": 8,     # steps of timeline kept before each incident
}

# When a run counts as finished, and when it is too small to say anything. Override under [runs].
RUNS = {
    "idle_hours": 12,       # a run with no cost-state at its end is taken as ended after this long without new records
    "stub_api_calls": 3,    # fewer model turns than this, in every agent together, is a stub
    "stub_cost_usd": 0.02,  # or cheaper than this
}

# Applied to every [[evidence]] rule unless the rule overrides them.
EVIDENCE = {
    "scope": "run",         # "run": only files modified while the run was going; "all": every match
    "slack_minutes": 10,    # how far outside [started, ended] a file's mtime may fall and still belong to the run
    "max_mb": 200,          # per run and rule; files beyond it are listed in the manifest as skipped
    "exclude": [],          # extra glob patterns (matched against the path relative to the rule's root)
}

# Never archived: browser profiles (cookies, saved passwords), databases, dependency and VCS internals.
EVIDENCE_EXCLUDE = [
    "**/Cookies", "**/Cookies-journal", "**/Login Data", "**/Login Data-journal", "**/Login Data For Account*",
    "**/Web Data", "**/Web Data-journal", "**/History", "**/History-journal", "**/Network Persistent State",
    "**/Local Storage/**", "**/Session Storage/**", "**/IndexedDB/**", "**/Service Worker/**",
    "**/*Cache/**", "**/blob_storage/**", "**/Local State", "**/Preferences", "**/Secure Preferences", "**/Sessions/**",
    "**/Crashpad/**", "**/*ShaderCache/**", "**/GraphiteDawnCache/**", "**/component_crx_cache/**", "**/*OptimizationGuide*/**",
    "**/Safe Browsing/**", "**/WidevineCdm/**", "**/Extension State/**", "**/Trust Tokens*", "**/Favicons*", "**/Top Sites*",
    "**/Shortcuts*", "**/Visited Links", "**/Web Data*", "**/Account Web Data*", "**/*.sqlite", "**/*.sqlite-*", "**/*.sqlite3", "**/*.db", "**/*.db-*",
    "**/*.ldb", "**/node_modules/**", "**/.git/objects/**", "**/__pycache__/**", "**/.venv/**",
]

PRIVACY = {
    "redact": False,        # mask secrets, tokens and e-mail addresses in stored text before they reach DuckDB
    "patterns": [],         # extra regexes to mask
}


def load(path=None):
    p = Path(path) if path else HOME / "config.toml"
    try:
        cfg = tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{p}: {e}") from None
    cfg["analysis"] = {**ANALYSIS, **cfg.get("analysis", {})}
    cfg["runs"] = {**RUNS, **cfg.get("runs", {})}
    cfg["privacy"] = {**PRIVACY, **cfg.get("privacy", {})}
    validate(cfg, p)
    return cfg


class ConfigError(Exception):
    """A config.toml that cannot work. Raised before any run is touched, with the key at fault."""


# The sections and keys config.toml may hold, with the kind of value each takes. Anything else is a typo and is refused.
# Kinds: str, int (whole number), num, bool, strs (list of strings), since (date text), any (checked where it is used).
SCHEMA = {
    "select": {"since": "since", "skills": "strs", "projects": "strs"},
    "runs": {"idle_hours": "num", "stub_api_calls": "int", "stub_cost_usd": "num"},
    "privacy": {"redact": "bool", "patterns": "strs"},
    "analysis": {"idle_parts": "strs", "test_path": "str", "repeat_min": "int", "repeat_window_s": "num", "idle_min": "int", "error_streak_min": "int",
                 "context_steps": "int"},
    "classify": {"model": "str", "before": "int", "after": "int", "skill_chars": "int", "timeline_chars": "int"},
    "evidence": {"name": "str", "glob": "str", "scope": "str", "slack_minutes": "num", "max_mb": "num", "exclude": "strs"},
    "marker": {"name": "str", "source": "str", "pattern": "str", "bad": "any"},
    "outcome": {"name": "str", "marker": "str", "success": "strs", "failure": "strs", "skills": "strs", "pr": "str"},
    "method": {"min_runs": "int", "resamples": "int", "confidence": "num", "cc_version": "str", "auto_groups": "bool"},
    "group": {"name": "str", "members": "strs"},
    "dashboard": {"auto": "bool", "view": "any"},
    "weights": None,    # measure names and per-unit tables: checked against the measures in bench.parse_weights
    "prices": None,     # model names: checked in validate
}
TABLE_LISTS = ("marker", "evidence", "outcome", "group")   # written as [[name]]; [outcome] may also be a single table
KIND_TEXT = {"str": "text", "int": "a whole number", "num": "a number", "bool": "true or false", "strs": "a list of text values",
             "since": "an ISO date like 2026-09-28"}


def _kind_ok(kind, v):
    if kind == "any":
        return True
    if kind == "str":
        return isinstance(v, str)
    if kind == "since":
        return isinstance(v, (str, date))
    if kind == "bool":
        return isinstance(v, bool)
    if kind == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "num":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def check_schema(cfg, bad):
    """Unknown sections and keys, and values of the wrong type, each named in a one-line error."""
    for section in cfg:
        if section not in SCHEMA:
            bad(f"[{section}]: unknown section (known: {', '.join(SCHEMA)})")
    for section, keys in SCHEMA.items():
        value = cfg.get(section)
        if keys is None or value is None:
            continue
        ref = f"[[{section}]]" if section in TABLE_LISTS else f"[{section}]"
        tables = value if isinstance(value, list) else [value]
        if not all(isinstance(t, dict) for t in tables):
            bad(f"{ref}: must be a table")
        if isinstance(value, list) and section not in TABLE_LISTS:
            bad(f"[{section}]: must be a single table, not [[{section}]]")
        for i, t in enumerate(tables):
            where = f"{ref} #{i + 1}" if isinstance(value, list) else ref
            for key, v in t.items():
                if key not in keys:
                    bad(f"{where} {key}: unknown key (known: {', '.join(keys)})")
                if not _kind_ok(keys[key], v):
                    bad(f"{where} {key}: must be {KIND_TEXT[keys[key]]}, got {v!r}")
    views = (cfg.get("dashboard") or {}).get("view") or []
    if not isinstance(views, list):
        bad("[dashboard] view: must be a list of [[dashboard.view]] tables")
    for i, v in enumerate(views):
        if not isinstance(v, dict) or not set(v) <= {"name", "hash"} or not all(isinstance(x, str) for x in v.values()):
            bad(f"[[dashboard.view]] #{i + 1}: a table with text values name and hash")


def validate(cfg, path="config.toml"):
    def bad(msg):
        raise ConfigError(f"{path}: {msg}")

    check_schema(cfg, bad)
    for i, m in enumerate(cfg.get("marker", [])):
        if not m.get("name") or not m.get("pattern"):
            bad(f"[[marker]] #{i + 1} needs a name and a pattern")
        try:
            re.compile(m["pattern"])
        except re.error as e:
            bad(f"[[marker]] {m['name']}: invalid pattern ({e})")
        if not isinstance(m.get("bad", []), list) and m.get("bad") != "*":
            bad(f"[[marker]] {m['name']}: bad must be a list of values or \"*\"")
    for i, ev in enumerate(cfg.get("evidence", [])):
        if not ev.get("glob"):
            bad(f"[[evidence]] #{i + 1} needs a glob")
        if ev.get("scope", "run") not in ("run", "all"):
            bad(f"[[evidence]] {ev.get('name', i + 1)}: scope must be \"run\" or \"all\"")
    for name, v in (cfg.get("prices") or {}).items():
        ok = (isinstance(v, (list, tuple)) and len(v) >= 3) or (isinstance(v, dict) and {"input", "output", "cache_read"} <= set(v))
        if not ok:
            bad(f"[prices] {name}: give [input, output, cache_read] or {{input, output, cache_read}} in USD per million tokens")
    for rx in cfg["privacy"].get("patterns", []):
        try:
            re.compile(rx)
        except re.error as e:
            bad(f"[privacy] patterns: {rx!r} is not a valid regex ({e})")
    for key in ("idle_parts",):
        for rx in cfg["analysis"].get(key, []):
            try:
                re.compile(rx)
            except re.error as e:
                bad(f"[analysis] {key}: {rx!r} is not a valid regex ({e})")
    try:
        re.compile(cfg["analysis"]["test_path"])
    except re.error as e:
        bad(f"[analysis] test_path: invalid regex ({e})")
    since = (cfg.get("select") or {}).get("since")
    if since:
        try:
            since_utc(since)
        except ValueError:
            bad(f"[select] since: {since!r} is not an ISO date like 2026-09-28")


def since_utc(value):
    """A `since` filter as an aware UTC datetime.

    A bare date means midnight where the user is, which is what someone typing
    2026-09-28 has in mind; transcript timestamps are UTC, so both sides are
    compared as instants rather than as strings.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = local time
    return dt.astimezone(timezone.utc)


def parse_ts(value):
    """An ISO timestamp from a transcript or a manifest as an aware UTC datetime, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
