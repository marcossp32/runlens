/* core/data.js: the embedded model, and the plain-English names the page uses for it.
   dashboard.py concatenates every module inside one function, in the order it lists, so a
   name declared here is visible to every later module and to nothing outside the page. */

const DATA = JSON.parse(document.getElementById("data").textContent);
const UNITS = new Map(DATA.units.map((u) => [u.id, u]));
const METRICS = DATA.method.metrics;
const MIN_RUNS = DATA.method.min_runs;
const LOG_CAP = Math.log(DATA.method.max_ratio);
const KIND = { skill: "Skill", agent: "Agent role", group: "Group" };
const DAY = 864e5;

// Each measure in words a reader knows: a label, a one-line help, and a short name for tight spaces.
const PLAIN = {
  outcome: ["Outcome", "The result your config counts as success, such as a check that passes first time or a PR opened.", "Outcome"],
  cost: ["Cost per invocation", "Model spend each time it was used (a typical value: the geometric mean).", "Cost"],
  seconds: ["Agent time per invocation", "Agent time each time it was used (a typical value); parallel agents add up, and waits for subagents or the user are included.", "Time"],
  error_rate: ["Tool errors", "Share of its tool calls that failed. Calls your permission rules denied do not count.", "Tool errors"],
  incidents: ["Scored problems per 100 tool calls", "Repeated calls, interrupts, failed subagents and similar.", "Problems"],
  interventions: ["Your messages per invocation", "Messages you sent while it was the active skill.", "Your messages"],
  idle_rate: ["Waiting calls", "Share of its tool calls that only wait or print.", "Waiting"],
  api_error_rate: ["API errors", "Share of its model turns that hit an API error (limits are not errors).", "API errors"],
  bad_markers: ["Failed checks per invocation", "Checks that your config marks as failed.", "Failed checks"],
};
const metricLabel = (m) => (PLAIN[m.key] ? PLAIN[m.key][0] : m.label);
const metricHelp = (m) => (PLAIN[m.key] ? PLAIN[m.key][1] : m.what);
const metricShort = (m) => (PLAIN[m.key] ? PLAIN[m.key][2] : m.label);
const metricByKey = new Map(METRICS.map((m) => [m.key, m]));

// Internal names (incident types, error classes, event kinds, statuses) as words. Unknown names are
// still readable: underscores become spaces and the first letter is capitalised.
const WORDS = {
  "(none)": "No skill", "(default)": "Default", "?": "Unknown",
  idle_loop: "Idle loop", error_streak: "Error streak", repeated_call: "Repeated call", nonzero_exit: "Non-zero exit",
  test_edit_after_failure: "Test edited after a failure", bad_marker: "Failed check", api_error: "API error",
  agent_failed: "Subagent failed", interrupt: "Interrupted", interrupted: "Interrupted", compaction: "Context compaction",
  not_found: "Not found", timeout: "Timed out", permission: "Permission denied", denied: "Permission denied",
  async_launched: "Launched in the background", completed: "Completed", killed: "Killed", failed: "Failed",
  expected_behavior: "Expected behaviour", busy_waiting: "Busy waiting", away_summary: "Away summary",
  agents_killed: "Subagents killed", pr_opened: "PR opened", step_check: "Step check",
};
function human(name) {
  if (name === null || name === undefined || name === "") return "—";
  const s = String(name);
  if (Object.prototype.hasOwnProperty.call(WORDS, s)) return WORDS[s];
  if (!/^[a-z0-9]+(_[a-z0-9]+)+$/.test(s) && !/^[a-z]+$/.test(s)) return s; // names with dashes or capitals are names, not codes
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

// A version without a recorded skill text is named by what is known, not by a number.
const nameOf = (v) => (v.recorded ? v.label : "unrecorded");
const findVersion = (s) => (DATA.versions[s.id] || []).find((v) => v.key === s.key) || null;
const sumOf = (rows, f) => rows.reduce((n, r) => n + (f(r) || 0), 0);
const groupSum = (rows, key, val) => {
  const m = new Map();
  for (const r of rows) m.set(r[key], (m.get(r[key]) || 0) + (r[val] || 0));
  return [...m].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
};
const median = (xs) => {
  const s = xs.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!s.length) return null;
  const k = (s.length - 1) / 2;
  return (s[Math.floor(k)] + s[Math.ceil(k)]) / 2;
};
const timeOf = (iso) => (iso ? Date.parse(iso) : NaN);
const dayMs = (key) => Date.parse(`${key}T00:00:00Z`);

// ---- per-run facts (explorer.py): what the filters slice and the run pages explore ----
// Tables arrive as {c: columns, r: rows, d: {column: values}}; a coded column holds a position in d.
function decodeTable(t) {
  if (!t || !t.c) return [];
  const d = t.d || {};
  return t.r.map((row) => {
    const o = {};
    t.c.forEach((c, i) => { o[c] = d[c] ? d[c][row[i]] : row[i]; });
    return o;
  });
}
const EX = (() => {
  const raw = DATA.explore || {};
  const out = {};
  for (const [k, v] of Object.entries(raw)) out[k] = v && v.c ? decodeTable(v) : v;
  for (const k of ["runs", "calls", "days", "tools", "durations", "errors", "agents", "incidents", "markers", "events", "stops", "apierr",
    "compactions", "segments", "flow", "toolerr", "tokens"]) out[k] = out[k] || [];
  out.curves = out.curves || {};
  out.health = out.health || null;
  out.duration_edges = out.duration_edges || [];
  for (const r of out.runs) {
    r.t0 = r.started * 1000;
    r.t1 = r.ended != null ? r.t0 + r.ended * 1000 : r.t0;
    r.pop = r.status === "complete" && !r.stub;
    r.models = r.models || [];
    r.efforts = r.efforts || [];
    r.skills = r.skills || [];
  }
  return out;
})();
const RUN = new Map(EX.runs.map((r) => [r.run, r]));
// A time inside a run (seconds from its start) as epoch milliseconds.
const atRun = (run, t) => {
  const r = RUN.get(run);
  return r && t !== null && t !== undefined ? r.t0 + t * 1000 : NaN;
};
// A local calendar day as "YYYY-MM-DD": the reader's day, which is how dates are picked in the filter bar.
function localDay(ms) {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const localMidnight = (key) => {
  const [y, m, d] = key.split("-").map(Number);
  return new Date(y, m - 1, d).getTime();
};
// "claude-opus-5-5" reads as "opus-5-5" where space is tight; the full name stays in tooltips and tables.
const shortModel = (m) => String(m || "?").replace(/^claude-/, "");
