/* pages/skills.js: the home page. Every skill compared on one screen, plus agent roles and groups.

   The selection (which skills and versions the charts show, and whether each version is its own item)
   is part of the view, so it lives in the URL hash:
     skills=a,b       the skills that are on (absent: all; "-": none)
     v=a:v1.v3;b:v2   per skill, the versions that are on (absent: all)
     split=1          each version drawn as its own item */

const SKILLS = DATA.units.filter((u) => u.kind === "skill");

function readSelection() {
  const pick = new Set(SKILLS.map((u) => u.id));
  const raw = param("skills");
  if (raw === "-") pick.clear();
  else if (raw) {
    pick.clear();
    raw.split(",").forEach((name) => UNITS.has(`skill:${name}`) && pick.add(`skill:${name}`));
  }
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
  const skills = allOn ? null : sel.pick.size ? SKILLS.filter((u) => sel.pick.has(u.id)).map((u) => u.name).join(",") : "-";
  const v = SKILLS.filter((u) => {
    const vs = DATA.versions[u.id] || [];
    return vs.length && sel.vers.get(u.id).size !== vs.length;
  }).map((u) => `${u.name}:${(DATA.versions[u.id] || []).filter((x) => sel.vers.get(u.id).has(x.key)).map((x) => x.label).join(".")}`).join(";");
  setParams({ skills, v: v || null, split: sel.split ? "1" : null });
}

// A skill as the page shows it. With every version on, this is the model's own figures. With some versions
// left out, the score, measures, spend and runs are those of the versions still on, and there is no range.
function viewOf(u, sel) {
  const all = DATA.versions[u.id] || [];
  const keys = sel ? sel.vers.get(u.id) || new Set(all.map((v) => v.key)) : new Set(all.map((v) => v.key));
  const chosen = all.filter((v) => keys.has(v.key));
  const full = chosen.length === all.length;
  const keyOfLabel = new Map(all.map((v) => [v.label, v.key]));
  const runList = (DATA.runs[u.id] || []).filter((r) => !all.length || keys.has(keyOfLabel.get(r.version)));
  let score = u.score, ci = u.ci, delta = u.delta, overlap = u.overlap;
  let judged = { verdict: u.verdict, vs: u.vs, confounders: u.confounders, difference: u.difference, kind: u.kind };
  if (!full) {
    const p = pointScore(runList, u.kind, u);
    score = p ? p.score : null;
    ci = null;
    delta = null;
    overlap = null;
    judged = { verdict: null, vs: null, confounders: [], difference: null, kind: u.kind };
    if (chosen.length >= 2) {
      const a = chosen[chosen.length - 2], b = chosen[chosen.length - 1];
      const pair = pairOf(u.id, a.label, b.label);
      if (pair) judged = { verdict: pair.verdict, vs: a.label, confounders: pair.confounders, difference: pair.difference, kind: u.kind };
      if (a.score != null && b.score != null) delta = b.score - a.score;
    }
  }
  const started = runList.map((r) => r.started).filter(Boolean).sort();
  return {
    ...u, unit: u, score, ci, partial: !full,
    kpi: full ? u.kpi : kpiOf(runList, u.kind),
    runs: runList.length, runList,
    spend: runList.reduce((n, r) => n + (r.cost || 0), 0),
    low_sample: runList.length < MIN_RUNS,
    last_seen: started.length ? started[started.length - 1] : null,
    current: chosen.length ? chosen[chosen.length - 1].label : u.current,
    chosen, recordedCount: chosen.filter((v) => v.recorded).length,
    delta, overlap, ...judged,
  };
}

// One version of a skill as its own item, so every chart treats the versions as separate entries.
function versionView(u, v) {
  const runList = (DATA.runs[u.id] || []).filter((r) => r.version === v.label);
  const started = runList.map((r) => r.started).filter(Boolean).sort();
  return {
    ...u, unit: u, name: `${u.name} ${nameOf(v)}`, score: v.score, ci: v.ci, partial: false,
    kpi: kpiOf(runList, u.kind), runs: runList.length, runList,
    spend: runList.reduce((n, r) => n + (r.cost || 0), 0), low_sample: v.low_sample,
    last_seen: started.length ? started[started.length - 1] : null,
    current: v.label, chosen: [v], recordedCount: v.recorded ? 1 : 0, delta: v.delta, overlap: v.overlap,
    verdict: v.verdict, vs: v.vs, confounders: v.confounders, difference: v.difference,
  };
}

function viewsFor(sel) {
  return SKILLS.filter((u) => sel.pick.has(u.id)).flatMap((u) => {
    const base = viewOf(u, sel);
    return sel.split ? base.chosen.map((v) => versionView(u, v)) : [base];
  });
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
  const span = DATA.window.first ? ` (${fmt.span(DATA.window.first, DATA.window.last)})` : "";
  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("h1", { tabindex: "-1" }, "Skills"),
      h("p", { class: "lede" }, `How each skill did across ${fmt.runs(DATA.window.runs)}${span}. Each skill is compared only with its own history: 100 is its typical run, and each version is judged against the version before it. Different skills do different work, so they are never ranked against each other.`)),
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
    draw();
  });
  draw();
  return h("div", {}, picker, holder);
}

function skillsView(sel) {
  const bases = SKILLS.filter((u) => sel.pick.has(u.id)).map((u) => viewOf(u, sel));
  const shown = viewsFor(sel);
  if (!shown.length) {
    return h("div", { class: "emptybox" }, empty("No skill is on, so there is nothing to draw."),
      button("Show every skill", () => {
        SKILLS.forEach((u) => sel.pick.add(u.id));
        writeSelection(sel);
        route();
      }));
  }
  const tones = shown.map((u) => verdict(u.score, u.ci, u).tone);
  const count = (t) => tones.filter((x) => x === t).length;
  const versions = bases.reduce((n, u) => n + u.recordedCount, 0);
  const sessions = new Set(shown.flatMap((u) => u.runList.map((r) => r.session))).size;
  const spend = shown.reduce((n, u) => n + u.spend, 0);
  const partial = shown.some((u) => u.partial);
  const unrecorded = shown.filter((u) => (DATA.versions[u.id] || []).length && !u.recordedCount).map((u) => u.name);
  const cols = [nameCol("Skill"), scoreCol, rangeCol, changeCol, versionsCol, runsCol, costCol, timeCol, errCol, lastCol];
  return h("div", {},
    h("div", { class: "kpis" },
      kpi(sel.split ? "Items" : "Skills", fmt.int(shown.length), sel.split ? `${bases.length} skills split into versions` : `of ${SKILLS.length} recorded`),
      kpi("Verdicts", h("span", { class: "verdicts" },
        toneTag("better", fmt.int(count("better"))), " ", toneTag("worse", fmt.int(count("worse"))), " ", toneTag("unclear", fmt.int(count("unclear") + count("few") + count("confounded") + count("first")))),
      "latest version against the one before · better · worse · other"),
      kpi("Versions", fmt.int(versions), "recorded, shown"),
      kpi("Runs", fmt.int(sessions), DATA.window.first ? fmt.span(DATA.window.first, DATA.window.last) : ""),
      kpi("Model spend", fmt.usd(spend), "attributed to the skills shown")),
    tabs("Charts", [
      { id: "overview", label: "Overview", build: () => h("div", { class: "charts" },
        h("div", { class: "grid split-wide" },
          rangeChart({
            title: "Latest version against its own skill", sub: `100 = the skill's typical run · bar = ${Math.round((DATA.method.confidence || 0.95) * 100)}% range`,
            rows: shown.map((u, i) => ({ label: u.name, name: u.unit.name, ns: "skill", score: u.score, ci: u.ci, href: hrefUnit(u.id),
              tone: tones[i], word: verdict(u.score, u.ci, u).word })),
            ref: 100, refLabel: "typical run", axisTitle: "Score (100 = the skill's typical run)", labelTitle: "Skill",
            notes: partial ? "Skills with versions left out show a point score, with no range." : null,
          }),
          versionTimeline({
            title: "Score of each version over time", sub: "one panel per skill · shared time and score axes",
            facets: bases.map((u) => ({ label: u.name, ns: "skill", name: u.name, href: hrefUnit(u.id),
              versions: u.chosen.filter((v) => v.recorded).map((v) => ({ label: v.label, t0: timeOf(v.first_seen), t1: timeOf(v.last_seen || v.first_seen),
                score: v.score, ci: v.ci, runs: v.runs, tone: change(v).tone, text: change(v).text })) })),
            ref: 100, emptyText: "No recorded version is selected.",
            notes: "Each segment spans the dates a version was in use; the band is its likely range. Versions of different skills are only compared through time, never by their number.",
          })),
        sortTable({ caption: "Skills", cols, rows: shown, sort: { key: "runs", dir: -1 }, csvName: "skills" }).el,
        note(`Latest change compares the newest version shown with the one before it, from the difference between their runs; it needs ${MIN_RUNS} runs on each side, and is “confounded” when another skill, the model, the effort, Claude Code or the project changed at the same time.${unrecorded.length ? ` No skill text was recorded for ${unrecorded.join(", ")}, so their versions are unknown.` : ""} A skill that only ever ran inside a subagent has no version of its own yet.`),
        h("details", { class: "more" }, h("summary", {}, `${versions} recorded versions shown`), versionTable(bases))) },
      { id: "cost", label: "Cost", build: () => costPanel(shown) },
      { id: "measures", label: "Measures", build: () => h("div", { class: "charts" }, measuresHeatmap(shown)) },
    ], { param: "tab" }));
}

function costPanel(shown) {
  const series = topSeries(shown.filter((u) => u.spend > 0).sort((a, b) => b.spend - a.spend), 7);
  const days = new Map();
  for (const s of series) {
    for (const u of s.items) {
      for (const r of u.runList) {
        if (!r.started || !r.cost) continue;
        const day = r.started.slice(0, 10);
        const d = days.get(day) || { day, parts: {}, runs: new Set() };
        d.parts[s.key] = (d.parts[s.key] || 0) + r.cost;
        d.runs.add(r.session);
        days.set(day, d);
      }
    }
  }
  const maxRuns = Math.max(1, ...shown.map((u) => u.runs));
  return h("div", { class: "charts" },
    scatterChart({
      title: "Score against cost per invocation", sub: "each mark is one item · bigger marks have more runs · each score is against its own skill",
      points: shown.filter((u) => u.score != null && u.kpi.cost > 0).map((u) => ({
        x: u.kpi.cost, y: u.score, label: u.name, ns: "skill", name: u.unit.name, r: 4 + 6 * Math.sqrt(u.runs / maxRuns), href: hrefUnit(u.id), hollow: !u.ci,
        tip: { title: u.name, rows: [["Score", fmt.score(u.score)], ["Range", u.ci ? fmt.interval(u.ci) : "none: too few runs"], ["Cost per invocation", fmt.usd(u.kpi.cost)], ["Runs", fmt.int(u.runs)]] },
      })),
      x: { title: "Cost per invocation, US$ (log scale)", log: true, fmt: fmt.usdTick }, y: { title: "Score", fmt: fmt.score, fit: true, ref: 100, refLabel: "typical run" },
      labels: true, labelTitle: "Skill",
      legendItems: [...new Set(shown.map((u) => u.unit.name))].map((n) => { const c = colourOf("skill", n); return { label: n, css: c.css, shape: c.shape }; }),
      notes: "Each score is against its own skill's typical run, so marks of different skills are not ranked. Hollow marks have too few runs for a range.",
    }),
    h("div", { class: "grid" },
      barChart({ title: "Where the spend goes", sub: "model spend attributed to each item", items: shown.map((u) => ({ label: u.name, name: u.unit.name, value: u.spend, href: hrefUnit(u.id) })),
        ns: "skill", fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Skill" }),
      dayColumns({ title: "Spend per day, by skill", sub: "model spend on the day each run started", days: [...days.values()].map((d) => ({ ...d, runs: d.runs.size })),
        series: series.map((s) => ({ key: s.key, label: s.label, css: s.css })), fmt: fmt.usd, tickFmt: fmt.usdTick, yTitle: "Spend, US$",
        tipRows: (d) => [["Runs that day", fmt.int(d.runs || 0)]] })));
}

// Up to n named series in their own colour; the rest folded into one grey "Other".
function topSeries(views, n) {
  const head = views.slice(0, views.length > n + 1 ? n : views.length).map((u) => ({ key: u.name, label: u.name, css: colourOf("skill", u.unit.name).css, items: [u] }));
  const rest = views.slice(head.length);
  return rest.length ? head.concat({ key: "(other)", label: `Other (${rest.length})`, css: "var(--other)", items: rest }) : head;
}

function measuresHeatmap(shown) {
  const rows = shown.filter((u) => u.score != null).sort((a, b) => b.score - a.score);
  const cols = METRICS.filter((m) => m.kinds.includes("skill"));
  const cur = new Map(rows.map((u) => [u.id + u.name, u.chosen.length ? u.chosen[u.chosen.length - 1] : (DATA.versions[u.id] || []).find((v) => v.label === u.current)]));
  return heatmap({
    title: "Measures against the skill's typical run", sub: "the latest version shown of each item · ratio to its own typical run, above ×1 is better",
    rows: rows.map((u) => ({ key: u.id + u.name, label: u.name, href: hrefUnit(u.id), u })), rowTitle: "Skill",
    cols: cols.map((m) => ({ key: m.key, label: metricShort(m), sub: `weight ×${m.weight}`, m })),
    scale: "div",
    cell: (r, c) => {
      const v = cur.get(r.key);
      const d = v && v.metrics ? v.metrics[c.key] : null;
      if (!d) return null;
      return {
        t: Math.log(d.ratio) / LOG_CAP, raw: d.ratio, text: fmt.ratio(d.ratio), dim: d.n < MIN_RUNS,
        tip: [["Ratio to typical", `${fmt.ratio(d.ratio)} (${d.ratio >= 1 ? "better" : "worse"})`], [metricLabel(c.m), fmt.metric(c.m, d.value)], ["Typical run", fmt.metric(c.m, d.ref)],
          ["Runs", `${fmt.int(d.n)}${d.n < MIN_RUNS ? " (too few to trust)" : ""}`], ["Weight in the score", `×${d.weight}`], ["Version", v.label]],
      };
    },
    legendText: ["worse than typical", "better than typical", "corner mark = fewer than " + MIN_RUNS + " runs"],
    notes: "Blue is better than the skill's typical run, red is worse, grey is about the same. The colour saturates at ×" + DATA.method.max_ratio + " either way, where the score stops counting.",
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

// The checkboxes: a skill on or off, and each of its versions on or off. The buttons set many at once.
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
    act("No skills", () => sel.pick.clear()),
    act("All versions", () => SKILLS.forEach((u) => (DATA.versions[u.id] || []).forEach((v) => sel.vers.get(u.id).add(v.key)))),
    act("Latest versions only", () => SKILLS.forEach((u) => {
      const vs = DATA.versions[u.id] || [];
      sel.vers.get(u.id).clear();
      if (vs.length) sel.vers.get(u.id).add(vs[vs.length - 1].key);
    })));
  sync();
  const changed = param("skills") || param("v") || param("split");
  return h("details", { class: "card selector", open: changed ? true : null },
    h("summary", { class: "cardtitle" }, "Show in the charts · ", count),
    controls, rows.map((r) => r.row),
    note("Every chart and table on this tab follows this selection, and so does the link to this page. A skill with some versions left out is scored from the versions still on: a point score, with no range."));
}

function rolesPanel(list) {
  const state = { text: param("q") || "", once: param("once") === "1" };
  const count = h("p", { class: "note", "aria-live": "polite" });
  const spendOf = (u) => sumOf(DATA.runs[u.id] || [], (r) => r.cost);
  const t = sortTable({ caption: "Agent roles", cols: [nameCol("Agent role"), scoreCol, runsCol, costCol, timeCol, errCol, lastCol],
    rows: [], sort: { key: "runs", dir: -1 }, page: 25, csvName: "agent-roles" });
  const chartBox = h("div", {});
  const apply = (write) => {
    const q = state.text.trim().toLowerCase();
    const rows = list.filter((u) => (state.once || u.runs >= 2) && (!q || u.name.toLowerCase().includes(q)));
    t.setRows(rows);
    const hidden = list.length - list.filter((u) => u.runs >= 2).length;
    count.textContent = `${rows.length} shown${state.once || !hidden ? "" : ` · ${hidden} seen only once are hidden`}`;
    chartBox.replaceChildren(barChart({
      title: "Spend by agent role", sub: `the ${Math.min(15, rows.length)} roles shown that spent the most`,
      items: rows.map((u) => ({ label: u.name, value: spendOf(u), href: hrefUnit(u.id), rows: [["Runs", fmt.int(u.runs)]] })).sort((a, b) => b.value - a.value).slice(0, 15),
      fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", labelTitle: "Agent role",
    }));
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
    h("div", { class: "toolbar" }, search, h("label", { class: "check" }, once, " Include roles seen once")),
    count, chartBox, t.el,
    note("Agent roles are the subagents Claude Code started, grouped by type and task; roles seen in a single run are folded into one row per type. Roles have no versions, so they are described, not scored."));
}

function groupsPanel(list) {
  if (!list.length) {
    return h("div", { class: "howto" },
      h("h2", {}, "Groups score a set of skills together"),
      h("p", {}, "Use a group to see a whole flow at once, such as a plan, a build and a review. Add one to ~/.runlens/config.toml, then run runlens dashboard again:"),
      h("pre", { class: "snippet" }, '[[group]]\nname = "my-flow"\nmembers = ["skill:my-plan", "skill:my-build"]'));
  }
  const cols = [nameCol("Group"), scoreCol, rangeCol, runsCol, costCol, timeCol, errCol, lastCol];
  return h("div", { class: "charts" },
    rangeChart({ title: "Latest version of each group against its own runs", sub: "100 = the group's typical run",
      rows: list.map((u) => ({ label: u.name, ns: "group", score: u.score, ci: u.ci, href: hrefUnit(u.id), tone: verdict(u.score, u.ci, u).tone, word: verdict(u.score, u.ci, u).word })),
      ref: 100, refLabel: "typical run", axisTitle: "Score (100 = the group's typical run)", labelTitle: "Group" }),
    sortTable({ caption: "Groups", cols, rows: list, sort: { key: "runs", dir: -1 }, csvName: "groups" }).el);
}
