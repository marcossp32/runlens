"""Optional masking of secrets in the text runlens stores, and `runlens prune`.

With `[privacy] redact = true`, every text column that comes from a transcript
(tool inputs and outputs, the agent's text, prompts, incident timelines) is
passed through `redact` before it reaches DuckDB. Hashes used for versions and
repeated calls are taken from the original text, so redaction changes no count.
The archived transcripts themselves stay verbatim: they are the source of truth
and can be re-ingested.
"""
import re

PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"\bsk-ant-[A-Za-z0-9_\-]{10,}",                    # Anthropic
    r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}",              # OpenAI-style
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",      # GitHub tokens
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bglpat-[A-Za-z0-9_\-]{20,}",                     # GitLab
    r"\bxox[abposr]-[A-Za-z0-9\-]{10,}",                # Slack
    r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",                   # AWS access key id
    r"\bAIza[0-9A-Za-z_\-]{35}\b",                      # Google API key
    r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}",   # Stripe
    r"\bnpm_[A-Za-z0-9]{30,}",
    r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",  # JWT
    r"\b(?i:bearer|basic)\s+[A-Za-z0-9._~+/\-]{16,}=*",
    r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)",              # user:password@ in URLs
    r"""\b(?i:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|auth)\b["']?\s*[:=]\s*["']?[^\s"',;]{6,}""",
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",  # e-mail
]
MASK = "[redacted]"

# Text columns that can carry secrets, per table.
TEXT_COLUMNS = {
    "agents": ("description", "prompt"),
    "tool_calls": ("input_summary", "input_json", "result_head"),
    "texts": ("text",),
    "events": ("detail",),
    "markers": ("value",),
    "skill_loads": ("args",),
    "runs": ("title",),
}


def redactor(cfg):
    """A function that masks secrets in a string, or None when redaction is off."""
    opts = (cfg or {}).get("privacy") or {}
    if not opts.get("redact"):
        return None
    rx = re.compile("|".join(f"(?:{p})" for p in PATTERNS + list(opts.get("patterns") or [])))
    return lambda s: rx.sub(MASK, s) if isinstance(s, str) and s else s


def redact_rows(rows, cfg):
    """Mask secrets in place in the parsed rows of one run. Incidents built afterwards inherit the masking."""
    fn = redactor(cfg)
    if fn is None:
        return rows
    for table, cols in TEXT_COLUMNS.items():
        for r in rows.get(table, []):
            for c in cols:
                if r.get(c):
                    r[c] = fn(r[c])
    return rows
