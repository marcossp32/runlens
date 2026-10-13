/* core/filters.js: the global filter bar's state, and the slice of the data it keeps.

   One set of filters scopes every page (dataviz rule: filters in one row above everything they scope).
   They live in the URL hash, so a link reproduces the slice:
     range=7d|30d|90d       a window ending on the day the page was generated (or from/to=YYYY-MM-DD)
     repo, branch, model, effort, cc, skills = comma-separated values (absent: all)
     minn=1                 hide skills, roles and versions with fewer runs than a verdict needs
     pop=all                also count runs still open and stub runs (the scores never do)
   A run is kept when it passes every filter; a model, effort or skill filter also trims the rows inside a
   run (a run that used two models keeps only the chosen model's calls). */

const FILTER_DIMS = [
  { key: "repo", label: "Repo", plural: "repos", of: (r) => [r.repo] },
  { key: "branch", label: "Branch", plural: "branches", of: (r) => [r.branch] },
  { key: "model", label: "Model", plural: "models", of: (r) => r.models, show: shortModel },
  { key: "effort", label: "Effort", plural: "effort levels", of: (r) => r.efforts, show: (e) => human(e) },
  { key: "skills", label: "Skills", plural: "skills", of: (r) => r.skills },
  { key: "cc", label: "Claude Code", plural: "versions", of: (r) => [r.cc] },
];
const RANGES = { "7d": 7, "30d": 30, "90d": 90 };
const GENERATED_DAY = localDay(Date.parse(DATA.generated) || Date.now());

// The values each filter can take, most used first (effort and Claude Code in their natural order).
const FILTER_OPTIONS = (() => {
  const out = {};
  for (const d of FILTER_DIMS) {
    const n = new Map();
    for (const r of EX.runs) for (const v of d.of(r) || []) if (v !== null && v !== undefined && v !== "") n.set(v, (n.get(v) || 0) + 1);
    let vals = [...n.keys()];
    if (d.key === "effort") vals.sort((a, b) => effortOrder(a) - effortOrder(b));
    else if (d.key === "cc") vals.sort((a, b) => String(b).localeCompare(String(a), undefined, { numeric: true }));
    else vals.sort((a, b) => n.get(b) - n.get(a) || String(a).localeCompare(String(b)));
    out[d.key] = vals.map((v) => ({ value: v, runs: n.get(v) }));
  }
  // A skill with units but no run rows still belongs in the list.
  for (const u of DATA.units) if (u.kind === "skill" && !out.skills.some((o) => o.value === u.name)) out.skills.push({ value: u.name, runs: 0 });
  return out;
})();
function effortOrder(e) {
  const order = ["(default)", "none", "minimal", "low", "medium", "high", "xhigh", "max"];
  const i = order.indexOf(String(e).toLowerCase());
  return i < 0 ? order.length : i;
}

const F = { from: null, to: null, range: null, sets: {}, minn: false, popAll: false };
let RUNSET = new Set();

// Read the filters from the URL and work out which runs they keep. Called on every route.
function applyFilters() {
  F.range = RANGES[param("range")] ? param("range") : null;
  const day = (v) => (/^\d{4}-\d{2}-\d{2}$/.test(v || "") ? v : null);
  if (F.range) {
    F.to = GENERATED_DAY;
    F.from = localDay(localMidnight(GENERATED_DAY) - (RANGES[F.range] - 1) * DAY + 3 * 36e5);
  } else {
    F.from = day(param("from"));
    F.to = day(param("to"));
  }
  F.sets = {};
  for (const d of FILTER_DIMS) {
    const raw = param(d.key);
    if (raw) F.sets[d.key] = new Set(raw.split(",").filter(Boolean));
  }
  F.minn = param("minn") === "1";
  F.popAll = param("pop") === "all";
  RUNSET = new Set(EX.runs.filter(runPasses).map((r) => r.run));
  // Runs the model scored but the facts do not know (an older database) still count when nothing filters.
  if (!EX.runs.length) for (const rows of Object.values(DATA.runs)) for (const r of rows) RUNSET.add(r.session);
}

function runPasses(r, ignore) {
  if (!F.popAll && !r.pop) return false;
  if (ignore !== "date") {
    if (F.from && r.t0 < localMidnight(F.from)) return false;
    if (F.to && r.t0 >= localMidnight(F.to) + DAY) return false;
  }
  for (const d of FILTER_DIMS) {
    const s = F.sets[d.key];
    if (s && d.key !== ignore && !(d.of(r) || []).some((v) => s.has(v))) return false;
  }
  return true;
}

// Does anything narrow the runs? (minn and pop do not change which runs a score uses.)
const slicing = () => Boolean(F.from || F.to || Object.keys(F.sets).length);
const filtered = () => slicing() || F.popAll;
const keptRuns = () => EX.runs.filter((r) => RUNSET.has(r.run));
const populationRuns = () => EX.runs.filter((r) => r.pop);

// Fact rows inside the kept runs, trimmed to the chosen models, efforts and skills where a row has them.
function slice(rows) {
  const sm = F.sets.model, se = F.sets.effort, sk = F.sets.skills;
  return rows.filter((x) => RUNSET.has(x.run) && (!sm || x.model === undefined || sm.has(x.model))
    && (!se || x.effort === undefined || se.has(x.effort)) && (!sk || x.skill === undefined || sk.has(x.skill)));
}

// A unit's run rows (bench model) inside the kept runs.
function unitRunsOf(uid) {
  const rows = DATA.runs[uid] || [];
  return slicing() ? rows.filter((r) => RUNSET.has(r.session)) : rows;
}
// Whether a skill passes the skills filter (other units always do).
const skillShown = (name) => !F.sets.skills || F.sets.skills.has(name);
const enoughRuns = (n) => !F.minn || n >= MIN_RUNS;
