/* pages/skills.js: the home page. Every skill compared on one screen, plus agent roles and groups.

   Which skills are on is the global "skills" filter (core/filters.js). This page adds, in the URL hash:
     v=a:v1.v3;b:v2   per skill, the versions that are on (absent: all)
     split=1          each version drawn as its own item
   Scores, ranges and verdicts come from core/scoring.js: the model's own with the default settings, worked
   out again in the page when the filters or the score settings change. */

const SKILLS = DATA.units.filter((u) => u.kind === "skill");
const OUTCOME = METRICS.some((m) => m.key === "outcome") && (DATA.method.outcomes || []).length > 0;

function readSelection() {
  const pick = new Set(SKILLS.filter((u) => skillShown(u.name)).map((u) => u.id));
  const vers = new Map(SKILLS.map((u) => [u.id, new Set((DATA.versions[u.id] || []).map((v) => v.key))]));
  for (const part of (param("v") || "").split(";").filter(Boolean)) {
    const [name, labels] = part.split(":");
    const vs = DATA.versions[`skill:${name}`];
    if (!vs) continue;
    const want = new Set((labels || "").split(".").filter(Boolean));
    vers.set(`skill:${name}`, new Set(vs.filter((v) => want.has(v.label)).map((v) => v.key)));
  }
  return { pick, vers, split: param("split") === "1" };
}

function writeSelection(sel) {
  const allOn = sel.pick.size === SKILLS.length;
  const skills = allOn || !sel.pick.size ? null : SKILLS.filter((u) => sel.pick.has(u.id)).map((u) => u.name).join(",");
  const v = SKILLS.filter((u) => {
    const vs = DATA.versions[u.id] || [];
    return vs.length && sel.vers.get(u.id).size !== vs.length;
  }).map((u) => `${u.name}:${(DATA.versions[u.id] || []).filter((x) => sel.vers.get(u.id).has(x.key)).map((x) => x.label).join(".")}`).join(";");
  setParams({ skills, v: v || null, split: sel.split ? "1" : null });
}

// A skill as the page shows it. With every version on, the scored unit's figures. With some versions left
// out, the score, measures, spend and runs are those of the versions still on, and there is no range.
function viewOf(u, sel) {
  const sc = scoreUnit(u);
  const all = sc.versions;
  const keys = sel ? sel.vers.get(u.id) || new Set(all.map((v) => v.key)) : new Set(all.map((v) => v.key));
  const chosen = all.filter((v) => keys.has(v.key));
  const full = chosen.length === all.length;
  const keyOfLabel = new Map(all.map((v) => [v.label, v.key]));
  const runList = sc.rows.filter((r) => !all.length || keys.has(keyOfLabel.get(r.version)));
  let score = sc.score, ci = sc.ci, delta = sc.delta;
  let judged = { verdict: sc.verdict, vs: sc.vs, confounders: sc.confounders, difference: sc.difference, kind: u.kind };
  if (!full) {
    const p = pointScore(runList, u.kind, { ...u, baseline: sc.baseline, pseudo: sc.pseudo }, sc.weights);
    score = p ? p.score : null;
    ci = null;
    delta = null;
    judged = { verdict: null, vs: null, confounders: [], difference: null, kind: u.kind };
    if (chosen.length >= 2) {
      const a = chosen[chosen.length - 2], b = chosen[chosen.length - 1];
      const pair = pairIn(sc, a.label, b.label);
      if (pair) judged = { verdict: pair.verdict, vs: a.label, confounders: pair.confounders, difference: pair.difference, kind: u.kind };
      if (a.score != null && b.score != null) delta = b.score - a.score;
    }
  }
  const started = runList.map((r) => r.started).filter(Boolean).sort();
  return {
    ...u, unit: u, sc, score, ci, partial: !full,
    kpi: full ? sc.kpi : kpiOf(runList, u.kind),
    runs: new Set(runList.map((r) => r.session)).size, runList,
    spend: runList.reduce((n, r) => n + (r.cost || 0), 0),
    low_sample: new Set(runList.map((r) => r.session)).size < MIN_RUNS,
    last_seen: started.length ? started[started.length - 1] : null,
    current: chosen.length ? chosen[chosen.length - 1].label : sc.current,
    chosen, recordedCount: chosen.filter((v) => v.recorded).length,
    delta, overlap: null, ...judged,
  };
}

// One version of a skill as its own item, so every chart treats the versions as separate entries.
function versionView(u, v, sc) {
  const runList = sc.rows.filter((r) => r.version === v.label);
  const started = runList.map((r) => r.started).filter(Boolean).sort();
  return {
    ...u, unit: u, sc, name: `${u.name} ${nameOf(v)}`, score: v.score, ci: v.ci, partial: false,
    kpi: kpiOf(runList, u.kind), runs: runList.length, runList,
    spend: runList.reduce((n, r) => n + (r.cost || 0), 0), low_sample: v.low_sample,
    last_seen: started.length ? started[started.length - 1] : null,
    current: v.label, chosen: [v], recordedCount: v.recorded ? 1 : 0, delta: v.delta, overlap: null,
    verdict: v.verdict, vs: v.vs, confounders: v.confounders, difference: v.difference,
  };
}

// The skills on: in the skills filter, with runs in the slice, and (with "hide few") enough of them.
const skillsOn = (sel) => SKILLS.filter((u) => sel.pick.has(u.id) && unitRunsOf(u.id).length);

function viewsFor(sel) {
  return skillsOn(sel).flatMap((u) => {
    const base = viewOf(u, sel);
    return sel.split ? base.chosen.map((v) => versionView(u, v, base.sc)) : [base];
  }).filter((x) => enoughRuns(x.runs));
}

// ---- columns shared by the tables of units ----

const nameCol = (label) => ({ key: "name", label, value: (u) => u.name, cell: (u) => h("a", { href: hrefUnit(u.id) }, u.name) });
const scoreCol = { key: "score", label: "Score", num: true, value: (u) => u.score, cell: (u) => scoreCell(u.score, u.ci, u.low_sample, u), csv: (u) => u.score };
const rangeCol = { key: "ci", label: "Range", num: true, value: (u) => (u.ci ? u.ci[0] : null), cell: (u) => fmt.interval(u.ci), csv: (u) => (u.ci ? u.ci.join("–") : "") };
const changeCol = { key: "delta", label: "Latest change", value: (u) => u.delta, cell: (u) => changeCell(u), csv: (u) => change(u).text };
const runsCol = { key: "runs", label: "Runs", num: true, value: (u) => u.runs, cell: (u) => fmt.int(u.runs) };
const costCol = { key: "cost", label: "Cost per invocation", num: true, value: (u) => u.kpi.cost, cell: (u) => fmt.usd(u.kpi.cost) };
const timeCol = { key: "seconds", label: "Time per invocation", num: true, value: (u) => u.kpi.seconds, cell: (u) => fmt.secs(u.kpi.seconds) };
const errCol = { key: "error_rate", label: "Tool errors", num: true, value: (u) => u.kpi.error_rate, cell: (u) => fmt.pct(u.kpi.error_rate) };
const outcomeCol = { key: "outcome", label: "Outcome", num: true, value: (u) => u.kpi.outcome, cell: (u) => fmt.pct(u.kpi.outcome) };
const lastCol = { key: "last", label: "Last used", value: (u) => u.last_seen, cell: (u) => fmt.day(u.last_seen) };
const versionsCol = {
  key: "versions", label: "Versions", num: true, value: (u) => u.recordedCount,
  cell: (u) => (u.recordedCount ? `${u.recordedCount} · now ${u.current}` : h("span", { class: "muted" }, "not recorded")),
};

// ---- the page ----

function skillsPage() {
  const roles = DATA.units.filter((u) => u.kind === "agent");
  const groups = DATA.units.filter((u) => u.kind === "group");
  if (!DATA.units.length) {
    return h("article", { class: "page" }, h("h1", { tabindex: "-1" }, "Skills"),
      empty("No runs yet. Run `runlens refresh`, then `runlens dashboard`."));
  }
  const runsN = slicing() ? RUNSET.size : DATA.window.runs;
  const span = DATA.window.first ? ` (${fmt.span(DATA.window.first, DATA.window.last)})` : "";
  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("h1", { tabindex: "-1" }, "Skills"),
      h("p", { class: "lede" }, `How each skill did across ${fmt.runs(runsN)}${slicing() ? " in the filters" : span}. Each skill is compared only with its own history: 100 is ${baseWords()}, and each version is judged against the version before it. Different skills do different work, so they are never ranked against each other.`),
      scoreSettingsNote()),
    tabs("Kind of unit", [
      { id: "skills", label: `Skills · ${SKILLS.length}`, build: () => skillsPanel() },
      { id: "roles", label: `Agent roles · ${roles.length}`, build: () => rolesPanel(roles) },
      { id: "groups", label: `Groups · ${groups.length}`, build: () => groupsPanel(groups) },
    ], { param: "kind" }));
}

function skillsPanel() {
  if (!SKILLS.length) return empty("No skill has run yet.");
  const sel = readSelection();
  const holder = h("div", {});
  const draw = () => holder.replaceChildren(skillsView(sel));
  const picker = selectorCard(sel, () => {
    writeSelection(sel);
    applyFilters();
    renderFilterBar();
    draw();
  });
  draw();
  return h("div", {}, picker, holder);
}

function skillsView(sel) {
  const bases = skillsOn(sel).map((u) => viewOf(u, sel)).filter((x) => enoughRuns(x.runs));
  const shown = viewsFor(sel);
  if (!shown.length) {
    return h("div", { class: "emptybox" }, empty(F.minn ? `No skill has ${MIN_RUNS} runs or more in this slice.` : "No skill ran in this slice, so there is nothing to draw."),
      button("Reset filters", () => refreshAfter(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))));
  }
  const tones = shown.map((u) => verdict(u.score, u.ci, u).tone);
  const count = (t) => tones.filter((x) => x === t).length;
  const versions = bases.reduce((n, u) => n + u.recordedCount, 0);
  const sessions = new Set(shown.flatMap((u) => u.runList.map((r) => r.session))).size;
  const spend = shown.reduce((n, u) => n + u.spend, 0);
  const partial = shown.some((u) => u.partial);
  const unrecorded = shown.filter((u) => (DATA.versions[u.id] || []).length && !u.recordedCount).map((u) => u.name);
  const cols = [nameCol("Skill"), scoreCol, rangeCol, changeCol, versionsCol, runsCol, ...(OUTCOME ? [outcomeCol] : []), costCol, timeCol, errCol, lastCol];
  const pct = Math.round(S.ci * 100);
  const marks = changeMarks(["cc", "model"]);
  return h("div", {},
    h("div", { class: "kpis" },
      kpi(sel.split ? "Items" : "Skills", fmt.int(shown.length), sel.split ? `${bases.length} skills split into versions` : `of ${SKILLS.length} recorded`),
      kpi("Verdicts", h("span", { class: "verdicts" },
        toneTag("better", fmt.int(count("better"))), " ", toneTag("worse", fmt.int(count("worse"))), " ", toneTag("unclear", fmt.int(count("unclear") + count("few") + count("confounded") + count("first")))),
      "latest version against the one before · better · worse · other"),
      kpi("Versions", fmt.int(versions), "recorded, shown"),
      kpi("Runs", fmt.int(sessions), slicing() ? "in the filters" : DATA.window.first ? fmt.span(DATA.window.first, DATA.window.last) : ""),
      kpi("Model spend", fmt.usd(spend), "attributed to the skills shown")),
    tabs("Charts", [
      { id: "overview", label: "Overview", build: () => h("div", { class: "charts" },
        h("div", { class: "grid split-wide" },
          rangeChart({
            title: "Latest version against its own skill", question: "Is each skill's current version better or worse than usual?",
            sub: `100 = ${baseWords()} · bar = ${pct}% range`,
            rows: shown.map((u, i) => ({ label: u.name, name: u.unit.name, ns: "skill", score: u.score, ci: u.ci, href: hrefUnit(u.id),
              tone: tones[i], word: verdict(u.score, u.ci, u).word })),
            ref: 100, refLabel: S.base === "self" ? "typical run" : baseWords(), axisTitle: `Score (100 = ${baseWords()})`, labelTitle: "Skill",
            notes: partial ? "Skills with versions left out show a point score, with no range." : null,
          }),
          versionTimeline({
            title: "Score of each version over time", question: "How did each skill change, and what else changed around it?",
            sub: "one panel per skill · shared time and score axes · dotted lines: Claude Code updates and new models",
            facets: bases.filter((u) => u.chosen.some((v) => v.recorded && v.score != null)).map((u) => ({ label: u.name, ns: "skill", name: u.name, href: hrefUnit(u.id),
              versions: u.chosen.filter((v) => v.recorded && enoughRuns(v.runs)).map((v) => ({ label: v.label, t0: timeOf(v.first_seen), t1: timeOf(v.last_seen || v.first_seen),
                score: v.score, ci: v.ci, runs: v.runs, tone: change(v).tone, text: change(v).text })) })),
            ref: 100, vlines: marks, emptyText: "No recorded version is selected.",
            notes: "Each segment spans the dates a version was in use; the band is its likely range. Versions of different skills are only compared through time, never by their number.",
          })),
        sortTable({ caption: "Skills", cols, rows: shown, sort: { key: "runs", dir: -1 }, csvName: "skills" }).el,
        note(`Latest change compares the newest version shown with the one before it, from the difference between their runs; it needs ${MIN_RUNS} runs on each side, and is “confounded” when another skill, the model, the effort, Claude Code or the project changed at the same time.${unrecorded.length ? ` No skill text was recorded for ${unrecorded.join(", ")}, so their versions are unknown.` : ""} A skill that only ever ran inside a subagent has no version of its own yet.`),
        h("details", { class: "more" }, h("summary", {}, `${versions} recorded versions shown`), versionTable(bases))) },
      { id: "cost", label: "Cost", build: () => costPanel(shown) },
      { id: "outcome", label: "Outcome", build: () => outcomePanel(bases) },
      { id: "measures", label: "Measures", build: () => h("div", { class: "charts" }, measuresHeatmap(shown)) },
    ], { param: "tab" }));
}

function costPanel(shown) {
  const names = new Set(shown.map((u) => u.unit.name));
  const series = topSeries(shown.filter((u) => u.spend > 0).sort((a, b) => b.spend - a.spend), 7);
  const keyOf = new Map(series.flatMap((s) => s.items.map((u) => [u.unit.name, s.key])));
  const days = new Map();
  for (const d of slice(EX.days)) {
    if (!names.has(d.skill)) continue;
    const e = days.get(d.day) || { day: d.day, parts: {} };
    const k = keyOf.get(d.skill) || "(other)";
    e.parts[k] = (e.parts[k] || 0) + (d.cost || 0);
    days.set(d.day, e);
  }
  const maxRuns = Math.max(1, ...shown.map((u) => u.runs));
  const yOutcome = OUTCOME && shown.some((u) => valid(u.kpi.outcome));
  const pts = shown.filter((u) => u.kpi.cost > 0 && (yOutcome ? valid(u.kpi.outcome) : u.score != null));
  return h("div", { class: "charts" },
    scatterChart({
      title: yOutcome ? "Outcome against cost per invocation" : "Score against cost per invocation",
      question: yOutcome ? "Which skills reach their outcome for the least money?" : "Which items give the most for the least money?",
      sub: "each mark is one item · bigger marks have more runs · the line joins the items nothing else beats on both",
      points: pts.map((u) => ({
        x: u.kpi.cost, y: yOutcome ? u.kpi.outcome : u.score, label: u.name, ns: "skill", name: u.unit.name, r: 4 + 6 * Math.sqrt(u.runs / maxRuns), href: hrefUnit(u.id), hollow: u.low_sample,
        tip: { title: u.name, rows: [["Score", fmt.score(u.score)], ["Outcome", fmt.pct(u.kpi.outcome)], ["Cost per invocation", fmt.usd(u.kpi.cost)], ["Runs", fmt.int(u.runs)]] },
      })),
      x: { title: "Cost per invocation, US$ (log scale)", log: true, fmt: fmt.usdTick },
      y: yOutcome ? { title: "Outcome: success rate", fmt: (v) => fmt.pct(v, 0), fit: true } : { title: `Score (100 = ${baseWords()})`, fmt: fmt.score, fit: true, ref: 100, refLabel: "typical run" },
      frontier: { x: "low", y: "high" }, labels: true, labelTitle: "Skill",
      legendItems: [...names].map((n) => { const c = colourOf("skill", n); return { label: n, css: c.css, shape: c.shape }; }).concat([{ label: "Pareto frontier", css: "var(--text2)", kind: "line" }]),
      extraCols: [{ label: "Runs", num: true, value: (p) => p.r }],
      notes: yOutcome ? "The outcome is the success rate your config defines. Hollow marks have too few runs to trust." : "Each score is against its own skill, so marks of different skills are not ranked. Set an [outcome] in config.toml to put success on this axis instead. Hollow marks have too few runs to trust.",
    }),
    h("div", { class: "grid" },
      barChart({ title: "Where the spend goes", question: "Which skills cost the most in total?", sub: "model spend attributed to each item",
        items: shown.map((u) => ({ label: u.name, name: u.unit.name, value: u.spend, href: hrefUnit(u.id) })),
        ns: "skill", fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Skill" }),
      dayColumns({ title: "Spend per day, by skill", question: "Where does the money go over time?", sub: "model spend on the day each call was made",
        days: [...days.values()], series: series.map((s) => ({ key: s.key, label: s.label, css: s.css })), fmt: fmt.usd, tickFmt: fmt.usdTick, yTitle: "Spend, US$" })),
    tokenCostChart("skill", [...names]));
}

// Cost by token type for skills or models: Claude Code's own token totals, priced by type. A skill's share
// of a run's model cost follows its share of that model's spend in the run.
function tokenCostChart(by, only) {
  const types = [["input", "fresh input", "var(--c1)"], ["cache_write_5m", "cache write, 5 min", "var(--c4)"], ["cache_write_1h", "cache write, 1 hour", "var(--c2)"],
    ["cache_read", "cache read", "var(--c3)"], ["output", "output and thinking", "var(--c7)"]];
  const share = new Map();
  if (by === "skill") {
    const tot = new Map();
    for (const c of slice(EX.calls)) {
      const k = `${c.run}|${c.model}`;
      tot.set(k, (tot.get(k) || 0) + (c.cost || 0));
    }
    for (const c of slice(EX.calls)) {
      const k = `${c.run}|${c.model}`;
      if (!tot.get(k)) continue;
      (share.get(k) || share.set(k, new Map()).get(k)).set(c.skill, (share.get(k).get(c.skill) || 0) + (c.cost || 0) / tot.get(k));
    }
  }
  const rows = new Map();
  const add = (label, type, cost) => {
    const r = rows.get(label) || { label, parts: {} };
    r.parts[type] = (r.parts[type] || 0) + cost;
    rows.set(label, r);
  };
  for (const t of EX.tokens.filter((x) => RUNSET.has(x.run) && (!F.sets.model || F.sets.model.has(x.model)))) {
    if (!t.cost) continue;
    if (by === "model") add(t.model, t.type, t.cost);
    else {
      const m = share.get(`${t.run}|${t.model}`);
      if (!m) continue;
      for (const [skill, f] of m) if (!only || only.includes(skill)) add(skill, t.type, t.cost * f);
    }
  }
  const list = [...rows.values()].sort((a, b) => Object.values(b.parts).reduce((p, q) => p + q, 0) - Object.values(a.parts).reduce((p, q) => p + q, 0));
  const mode = param("tokmode") === "share" ? "share" : "abs";
  const sel = h("select", { "aria-label": "Show as" }, [["abs", "US$"], ["share", "Share"]].map(([v, t]) => h("option", { value: v, selected: v === mode ? true : null }, t)));
  sel.addEventListener("change", () => refreshAfter({ tokmode: sel.value === "abs" ? null : sel.value }));
  return stackChart({
    title: `Cost by token type, per ${by}`, question: "Am I paying for fresh input, for the cache, or for output?",
    sub: `Claude Code's own token counts priced by type${by === "skill" ? " · a run's model cost split by each skill's share of it" : ""}`,
    rows: list.map((r) => ({ label: by === "skill" ? human(r.label) : r.label, parts: r.parts })), series: types.map(([key, label, css]) => ({ key, label, css })),
    mode, fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Cost, US$", labelTitle: by === "skill" ? "Skill" : "Model", controls: sel,
    notes: "Cache writes cost more than fresh input (1.25× for five minutes, 2× for an hour) and cache reads a tenth of it. A large write share with a small read share means the cache is written and not reused.",
  });
}

// The outcome over time: per skill, the weekly first-pass rate with its interval, and when each version arrived.
function outcomePanel(bases) {
  if (!OUTCOME) {
    return h("div", { class: "howto" }, h("h2", {}, "No outcome is configured"),
      h("p", {}, "An outcome is what success means for a flow: a check that passes first time, or a PR opened. Add one to ~/.runlens/config.toml and run runlens dashboard again; it becomes a measure with the most weight, and this tab shows it over time."),
      h("pre", { class: "snippet" }, '[outcome]\nmarker = "step_check"   # a [[marker]] you defined\nsuccess = ["PASS"]\nskills = ["my-build"]\n\n# or: [outcome]\n# pr = "opened"'));
  }
  const facets = bases.map((u) => ({ label: u.name, ns: "skill", name: u.name,
    points: u.runList.filter((r) => r.on).map((r) => ({ t: timeOf(r.started), k: r.os || 0, n: r.on })),
    vlines: (DATA.versions[u.id] || []).slice(1).filter((v) => v.first_seen).map((v) => ({ t: timeOf(v.first_seen), label: v.label, kind: "skill" })) }));
  const o = DATA.method.outcomes[0];
  return h("div", { class: "charts" },
    rateFacets({ title: "First-pass rate over time", question: "Do the skills reach their outcome more often than before?",
      sub: `${o.kind === "pr" ? "runs that opened a PR" : `${human(o.marker)} passing on the first try`} · weekly, per skill · dotted lines: new versions`,
      facets, rateTitle: "First-pass rate",
      notes: `Each dot is a week; its size is the number of attempts, hollow under ${MIN_RUNS}. The band is the ${Math.round(S.ci * 100)}% Wilson interval of that week's rate.` }),
    sortTable({ caption: "Outcome by skill", csvName: "outcome-by-skill",
      cols: [nameCol("Skill"), { key: "o", label: "First-pass rate", num: true, value: (u) => u.kpi.outcome, cell: (u) => fmt.pct(u.kpi.outcome) },
        { key: "n", label: "Attempts", num: true, value: (u) => sumOf(u.runList, (r) => r.on) },
        { key: "e", label: "Eventual successes", num: true, value: (u) => sumOf(u.runList, (r) => r.oe) },
        { key: "cps", label: "Cost per success", num: true, value: (u) => (sumOf(u.runList, (r) => r.oe) ? u.spend / sumOf(u.runList, (r) => r.oe) : null),
          cell: (u) => fmt.usd(sumOf(u.runList, (r) => r.oe) ? u.spend / sumOf(u.runList, (r) => r.oe) : null) }],
      rows: bases.filter((u) => sumOf(u.runList, (r) => r.on)), sort: { key: "n", dir: -1 } }).el);
}

// Up to n named series in their own colour; the rest folded into one grey "Other".
function topSeries(views, n) {
  const head = views.slice(0, views.length > n + 1 ? n : views.length).map((u) => ({ key: u.unit.name, label: u.unit.name, css: colourOf("skill", u.unit.name).css, items: [u] }));
  const rest = views.slice(head.length);
  return rest.length ? head.concat({ key: "(other)", label: `Other (${rest.length})`, css: "var(--other)", items: rest }) : head;
}

function measuresHeatmap(shown) {
  const rows = shown.filter((u) => u.score != null).sort((a, b) => b.score - a.score);
  const cols = METRICS.filter((m) => m.kinds.includes("skill") && rows.some((u) => (u.chosen[u.chosen.length - 1] || {}).metrics && u.chosen[u.chosen.length - 1].metrics[m.key]));
  const cur = new Map(rows.map((u) => [u.id + u.name, u.chosen[u.chosen.length - 1]]));
  return heatmap({
    title: "Measures against the reference", question: "Where is each skill better or worse than usual?",
    sub: `the latest version shown of each item · ratio to ${baseWords()}, above ×1 is better`,
    rows: rows.map((u) => ({ key: u.id + u.name, label: u.name, href: hrefUnit(u.id), u })), rowTitle: "Skill",
    cols: cols.map((m) => ({ key: m.key, label: metricShort(m), sub: `weight ×${fmt.num((weightsOf(SKILLS[0] || { weights: {} })[m.key] ?? m.weight), 1)}`, m })),
    scale: "div",
    cell: (r, c) => {
      const v = cur.get(r.key);
      const d = v && v.metrics ? v.metrics[c.key] : null;
      if (!d) return null;
      return {
        t: Math.log(d.ratio) / LOG_CAP, raw: d.ratio, text: fmt.ratio(d.ratio), dim: d.n < MIN_RUNS,
        tip: [["Ratio to the reference", `${fmt.ratio(d.ratio)} (${d.ratio >= 1 ? "better" : "worse"})`], [metricLabel(c.m), fmt.metric(c.m, d.value)], ["Reference", fmt.metric(c.m, d.ref)],
          ["Runs", `${fmt.int(d.n)}${d.n < MIN_RUNS ? " (too few to trust)" : ""}`], ["Weight in the score", `×${d.weight}`], ["Version", v.label]],
      };
    },
    legendText: ["worse than the reference", "better", "corner mark = fewer than " + MIN_RUNS + " runs"],
    notes: "Blue is better than the reference, red is worse, grey is about the same. The colour saturates at ×" + DATA.method.max_ratio + " either way, where the score stops counting. The weights in the column heads are the defaults; a skill may override them.",
  });
}

// Every recorded version that is on, one row each.
function versionTable(views) {
  const rows = views.flatMap((u) => u.chosen.filter((v) => v.recorded).map((v) => ({
    id: u.id, name: u.name, label: v.label, hash: v.parts.map((p) => p.hash).join(" + "),
    first: v.first_seen, last: v.last_seen, runs: v.runs, score: v.score, ci: v.ci, change: change(v),
  })));
  const cols = [
    { key: "name", label: "Skill", value: (r) => r.name, cell: (r) => h("a", { href: hrefUnit(r.id) }, r.name) },
    { key: "label", label: "Version", value: (r) => r.label, cell: (r) => h("strong", {}, r.label) },
    { key: "hash", label: "Text", value: (r) => r.hash, cell: (r) => h("code", {}, r.hash) },
    { key: "first", label: "In use", value: (r) => r.first, cell: (r) => fmt.span(r.first, r.last), csv: (r) => `${r.first} – ${r.last}` },
    { key: "runs", label: "Runs", num: true, value: (r) => r.runs },
    { key: "score", label: "Score", num: true, value: (r) => r.score, cell: (r) => scoreCell(r.score, r.ci, false, {}) },
    { key: "change", label: "Against the version before", value: (r) => r.change.text || "first version",
      cell: (r) => (r.change.text ? toneTag(r.change.tone, r.change.text) : h("span", { class: "muted" }, "first version")) },
  ];
  return sortTable({ caption: "All recorded versions", cols, rows, sort: { key: "name", dir: 1 }, csvName: "skill-versions" }).el;
}

// The checkboxes: a skill on or off (the global skills filter), and each of its versions on or off.
function selectorCard(sel, onChange) {
  const rows = SKILLS.map((u) => {
    const box = h("input", { type: "checkbox", "aria-label": `Show ${u.name}` });
    const vboxes = (DATA.versions[u.id] || []).map((v) => {
      const b = h("input", { type: "checkbox" });
      b.addEventListener("change", () => {
        if (b.checked) sel.vers.get(u.id).add(v.key);
        else sel.vers.get(u.id).delete(v.key);
        touch();
      });
      const label = h("label", { class: "vchip" }, b, ` ${nameOf(v)}${v.recorded ? ` · ${fmt.score(v.score)}` : " · no text"}`);
      return { v, b, label };
    });
    box.addEventListener("change", () => {
      if (box.checked) sel.pick.add(u.id);
      else sel.pick.delete(u.id);
      touch();
    });
    const c = colourOf("skill", u.name);
    const key = svg("svg", { width: 12, height: 12, class: "lkey", "aria-hidden": "true" }, marker(c.shape, 6, 6, 4.5, { style: `fill:${c.css}` }));
    return { u, box, vboxes, row: h("div", { class: "srow" }, h("label", { class: "sname" }, box, key, ` ${u.name}`),
      h("div", { class: "vchips" }, vboxes.map((x) => x.label))) };
  });
  const count = h("span", { class: "selcount", "aria-live": "polite" });
  function sync() {
    for (const r of rows) {
      r.box.checked = sel.pick.has(r.u.id);
      for (const x of r.vboxes) {
        x.b.checked = sel.vers.get(r.u.id).has(x.v.key);
        x.b.disabled = !sel.pick.has(r.u.id);
      }
    }
    const recorded = SKILLS.reduce((n, u) => n + (DATA.versions[u.id] || []).filter((v) => v.recorded).length, 0);
    const shownV = SKILLS.filter((u) => sel.pick.has(u.id))
      .reduce((n, u) => n + (DATA.versions[u.id] || []).filter((v) => v.recorded && sel.vers.get(u.id).has(v.key)).length, 0);
    count.textContent = `${sel.pick.size} of ${SKILLS.length} skills · ${shownV} of ${recorded} recorded versions shown`;
  }
  function touch() {
    sync();
    onChange();
  }
  const act = (text, fn) => button(text, () => {
    fn();
    touch();
  }, { class: "btn seg" });
  const split = h("input", { type: "checkbox" });
  split.checked = sel.split;
  split.addEventListener("change", () => {
    sel.split = split.checked;
    touch();
  });
  const controls = h("div", { class: "selbar" },
    h("label", { class: "check" }, split, " Show each version as its own item in every chart"),
    act("All skills", () => SKILLS.forEach((u) => sel.pick.add(u.id))),
    act("All versions", () => SKILLS.forEach((u) => (DATA.versions[u.id] || []).forEach((v) => sel.vers.get(u.id).add(v.key)))),
    act("Latest versions only", () => SKILLS.forEach((u) => {
      const vs = DATA.versions[u.id] || [];
      sel.vers.get(u.id).clear();
      if (vs.length) sel.vers.get(u.id).add(vs[vs.length - 1].key);
    })));
  sync();
  const changed = param("v") || param("split");
  return h("details", { class: "card selector", open: changed ? true : null },
    h("summary", { class: "cardtitle" }, "Skills and versions in the charts · ", count),
    controls, rows.map((r) => r.row),
    note("Turning a skill off here is the same as the Skills filter in the bar above, so it narrows every page. Versions are chosen here only. A skill with some versions left out is scored from the versions still on: a point score, with no range."));
}

function rolesPanel(list) {
  const state = { text: param("q") || "", once: param("once") === "1" };
  const count = h("p", { class: "note", "aria-live": "polite" });
  const viewOfRole = (u) => {
    const rows = unitRunsOf(u.id);
    return { ...u, runs: new Set(rows.map((r) => r.session)).size, kpi: rows.length === (DATA.runs[u.id] || []).length ? u.kpi : { ...u.kpi, ...kpiOf(rows, "agent") },
      spend: sumOf(rows, (r) => r.cost), last_seen: rows.map((r) => r.started).filter(Boolean).sort().pop() || null, low_sample: rows.length < MIN_RUNS };
  };
  const views = list.map(viewOfRole).filter((u) => u.runs && enoughRuns(u.runs));
  const t = sortTable({ caption: "Agent roles", cols: [nameCol("Agent role"), runsCol, { key: "spend", label: "Spend", num: true, value: (u) => u.spend, cell: (u) => fmt.usd(u.spend) },
    costCol, timeCol, errCol, lastCol], rows: [], sort: { key: "spend", dir: -1 }, page: 25, csvName: "agent-roles" });
  const chartBox = h("div", { class: "grid" });
  const apply = (write) => {
    const q = state.text.trim().toLowerCase();
    const rows = views.filter((u) => (state.once || u.runs >= 2 || u.name.endsWith("roles seen in one run")) && (!q || u.name.toLowerCase().includes(q)));
    t.setRows(rows);
    const hidden = views.length - views.filter((u) => u.runs >= 2 || u.name.endsWith("roles seen in one run")).length;
    count.textContent = `${rows.length} shown${state.once || !hidden ? "" : ` · ${hidden} seen in a single run are hidden`}`;
    const top = [...rows].sort((a, b) => b.spend - a.spend).slice(0, 20);
    const typeOf = (u) => u.id.slice(6).split("|")[0];
    chartBox.replaceChildren(
      barChart({ title: "Spend by agent role", question: "Which subagent roles cost the most?", sub: `the ${top.length} roles shown that spent the most · colour = agent type`,
        items: top.map((u) => ({ label: u.name, value: u.spend, href: hrefUnit(u.id), css: colourOf("agent", typeOf(u)).css, rows: [["Runs", fmt.int(u.runs)], ["Cost per invocation", fmt.usd(u.kpi.cost)]] })),
        fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", labelTitle: "Agent role" }),
      scatterChart({ title: "Cost and time per invocation, by role", question: "Which roles are slow, which are expensive, and which are both?",
        sub: "one mark per role · bigger marks ran in more runs · colour = agent type",
        points: top.filter((u) => u.kpi.cost > 0 && u.kpi.seconds > 0).map((u) => ({ x: u.kpi.seconds, y: u.kpi.cost, label: u.name, css: colourOf("agent", typeOf(u)).css,
          shape: colourOf("agent", typeOf(u)).shape, r: 4 + 5 * Math.sqrt(u.runs / Math.max(1, ...top.map((x) => x.runs))), href: hrefUnit(u.id), hollow: u.low_sample,
          tip: { title: u.name, rows: [["Cost per invocation", fmt.usd(u.kpi.cost)], ["Time per invocation", fmt.secs(u.kpi.seconds)], ["Runs", fmt.int(u.runs)]] } })),
        x: { title: "Time per invocation (log scale)", log: true, fmt: fmt.secs }, y: { title: "Cost per invocation, US$ (log scale)", log: true, fmt: fmt.usdTick }, labelTitle: "Role",
        legendItems: [...new Set(top.map(typeOf))].map((ty) => ({ label: ty, css: colourOf("agent", ty).css, shape: colourOf("agent", ty).shape })) }));
    if (write) setParams({ q: state.text || null, once: state.once ? "1" : null });
  };
  const search = h("input", { type: "search", placeholder: "Search roles", "aria-label": "Search agent roles", value: state.text });
  let timer = null;
  search.addEventListener("input", () => {
    state.text = search.value;
    clearTimeout(timer);
    timer = setTimeout(() => apply(true), 200);
  });
  const once = h("input", { type: "checkbox" });
  once.checked = state.once;
  once.addEventListener("change", () => {
    state.once = once.checked;
    apply(true);
  });
  apply(false);
  return h("div", { class: "charts" },
    h("div", { class: "toolbar" }, search, h("label", { class: "check" }, once, " Include roles seen in a single run")),
    count, chartBox, t.el,
    note("Agent roles are the subagents Claude Code started, grouped by type and task; roles seen in a single run are folded into one row per type. Roles have no versions, so they are described, not scored."));
}

function groupsPanel(list) {
  if (!list.length) {
    return h("div", { class: "howto" },
      h("h2", {}, "Groups score a set of skills together"),
      h("p", {}, "runlens finds sets of skills you use and edit together on its own, once they share enough runs; none so far. You can also define a group, to see a whole flow at once such as a plan, a build and a review. Add one to ~/.runlens/config.toml, then run runlens dashboard again:"),
      h("pre", { class: "snippet" }, '[[group]]\nname = "my-flow"\nmembers = ["skill:my-plan", "skill:my-build"]'));
  }
  const views = list.map((u) => {
    const sc = scoreUnit(u);
    return { ...u, sc, score: sc.score, ci: sc.ci, verdict: sc.verdict, vs: sc.vs, confounders: sc.confounders, difference: sc.difference, runs: sc.runs,
      kpi: sc.kpi, low_sample: sc.runs < MIN_RUNS, last_seen: sc.rows.map((r) => r.started).filter(Boolean).sort().pop() || null };
  }).filter((u) => u.runs && enoughRuns(u.runs));
  const cols = [nameCol("Group"), { key: "source", label: "From", value: (u) => (u.auto ? "found in runs" : "config.toml") },
    { key: "nmembers", label: "Members", num: true, value: (u) => u.members.length, cell: (u) => h("span", { title: u.members.join(", ") }, fmt.int(u.members.length)) },
    scoreCol, rangeCol, runsCol, costCol, timeCol, errCol, lastCol];
  const auto = views.filter((u) => u.auto).length;
  return h("div", { class: "charts" },
    note(`A group is scored as one unit, next to each of its skills on its own: its runs are the union of its members' work, and its version is the combination of its members' versions, so it changes when any member's text changes. ${auto ? `${auto === 1 ? "One set was" : `${auto} sets were`} found in your runs: skills used together in most of their runs and edited at the same time (marked “auto”; [method] auto_groups = false turns this off).` : ""} Define your own with [[group]] in config.toml.`),
    rangeChart({ title: "Latest version of each group against its own runs", question: "Is each flow, taken as a whole, better or worse than usual?", sub: `100 = ${baseWords()}`,
      rows: views.map((u) => ({ label: u.name, ns: "group", score: u.score, ci: u.ci, href: hrefUnit(u.id), tone: verdict(u.score, u.ci, u).tone, word: verdict(u.score, u.ci, u).word })),
      ref: 100, refLabel: "typical run", axisTitle: `Score (100 = ${baseWords()})`, labelTitle: "Group" }),
    sortTable({ caption: "Groups", cols, rows: views, sort: { key: "runs", dir: -1 }, csvName: "groups" }).el);
}
