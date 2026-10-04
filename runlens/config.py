"""Paths and config. Everything flow-specific comes from config.toml, never from code."""
import os
import tomllib
from pathlib import Path

HOME = Path(os.environ.get("RUNLENS_HOME", Path.home() / ".runlens"))
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS", Path.home() / ".claude" / "projects"))
ARCHIVE = HOME / "archive"
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
    "idle_min": 3,          # idle calls in one agent before it counts as an idle loop
    "error_streak_min": 2,  # consecutive failing tool calls before it counts as a streak
    "context_steps": 8,     # steps of timeline kept before each incident
}


def load(path=None):
    p = Path(path) if path else HOME / "config.toml"
    cfg = tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg["analysis"] = {**ANALYSIS, **cfg.get("analysis", {})}
    return cfg
