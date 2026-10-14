/* pages/runs.js: every run (#/runs) and one run explored (#/run/<id>).

   The list answers "which runs, when, and what did they cost?"; a run's page answers "what happened in
   it?": its skills, subagents, problems, checks and tool errors on one time axis, where its money went,
   and the commands that open the raw trace. */

const runTitle = (r) => r.title || "(untitled run)";
const runTip = (r) => ({ title: `${r.run} · ${fmt.when(isoOf(r.t0))}`, sub: r.title || null,
  rows: [["Cost", `${fmt.usd(r.cost)}${r.estimated ? " (estimated)" : ""}`], ["Active", fmt.ms(r.active_ms)], ["Subagents", fmt.int(r.agents)],
    ["Repo · branch", `${r.repo || "—"} · ${r.branch || "—"}`], ["Claude Code", r.cc || "—"], ["Status", `${human(r.status)}${r.stub ? " · stub" : ""}`]] });

// Per-run counts from the facts (tool calls, errors, incidents), so the list does not need the bench model.
function runCounts() {
  const out = new Map(EX.runs.map((r) => [r.run, { calls: 0, errors: 0, denied: 0, incidents: 0 }]));
  for (const t of EX.tools) {
    const c = out.get(t.run);
    if (c) {
      c.calls += t.calls;
      c.errors += t.errors;
      c.denied += t.denied;
    }
  }
  for (const i of EX.incidents) if (!i.policy && out.has(i.run)) out.get(i.run).incidents += 1;
  return out;
}

// Pull requests opened in a run: the full count when the page has it, else the (capped) list of links.
const prCount = (r) => (r.npr != null ? r.npr : (r.prs || []).length);

function runsPage() {
  const runs = keptRuns().sort((a, b) => b.t0 - a.t0);
  const head = h("header", { class: "pagehead" }, h("h1", { tabindex: "-1" }, "Runs"),
    h("p", { class: "lede" }, "Every run in the filters: when it happened, what it cost, and what it did. Open one to see its subagents, skills and problems on one time axis."));
  if (!EX.runs.length) return h("article", { class: "page" }, head, empty("No runs yet. Run runlens refresh, then runlens dashboard."));
  if (!runs.length) return h("article", { class: "page" }, head, emptyFiltered());
  const counts = runCounts();
  const metric = ["runs", "cost", "active"].includes(param("cal")) ? param("cal") : "cost";
  const days = new Map();
  for (const r of runs) {
    const k = localDay(r.t0);
    const d = days.get(k) || { value: 0, runs: 0, cost: 0, active: 0 };
    d.runs += 1;
    d.active += (r.active_ms || 0) / 36e5;
    days.set(k, d);
  }
  // Spend sits on the day each call was made, as in the spend-per-day charts; runs and active time on the day a run started.
  for (const c of slice(EX.days)) {
    const d = days.get(c.day) || { value: 0, runs: 0, cost: 0, active: 0 };
    d.cost += c.cost || 0;
    days.set(c.day, d);
  }
  for (const d of days.values()) {
    d.value = d[metric];
    d.rows = [["Runs", fmt.int(d.runs)], ["Spend", fmt.usd(d.cost)], ["Active time", fmt.secs(d.active * 3600)]];
  }
  const calSel = h("select", { "aria-label": "Colour the days by" }, [["cost", "Spend"], ["runs", "Runs"], ["active", "Active time"]].map(([v, t]) => h("option", { value: v, selected: v === metric ? true : null }, t)));
  calSel.addEventListener("change", () => refreshAfter({ cal: calSel.value === "cost" ? null : calSel.value }));
  const fmtCal = metric === "cost" ? fmt.usd : metric === "runs" ? fmt.int : (v) => fmt.secs(v * 3600);
  const maxAgents = Math.max(1, ...runs.map((r) => r.agents || 0));
  const prs = sumOf(runs, prCount);
  const cols = [
    { key: "run", label: "Run", value: (r) => r.run, cell: (r) => h("a", { href: hrefRun(r.run) }, h("code", {}, r.run)) },
    { key: "started", label: "Started", value: (r) => r.t0, cell: (r) => fmt.when(isoOf(r.t0)), csv: (r) => isoOf(r.t0) },
    { key: "title", label: "Title", value: (r) => r.title, cell: (r) => h("span", { class: "task", title: r.title || "" }, runTitle(r)) },
    { key: "repo", label: "Repo", value: (r) => r.repo },
    { key: "branch", label: "Branch", value: (r) => r.branch, more: true },
    { key: "cost", label: "Cost", num: true, value: runCost, cell: (r) => `${fmt.usd(runCost(r))}${r.estimated ? " est." : ""}` },
    { key: "active", label: "Active", num: true, value: (r) => r.active_ms, cell: (r) => fmt.ms(r.active_ms) },
    { key: "agents", label: "Subagents", num: true, value: (r) => r.agents },
    { key: "errors", label: "Tool errors", num: true, value: (r) => (counts.get(r.run).calls ? counts.get(r.run).errors / counts.get(r.run).calls : null),
      cell: (r) => (counts.get(r.run).calls ? `${fmt.int(counts.get(r.run).errors)} of ${fmt.int(counts.get(r.run).calls)}` : "—") },
    { key: "incidents", label: "Problems", num: true, value: (r) => counts.get(r.run).incidents },
    { key: "prompts", label: "Your messages", num: true, value: (r) => r.prompts, more: true },
    { key: "lines", label: "Lines +/−", num: true, value: (r) => (r.added || 0) + (r.removed || 0), cell: (r) => (r.added == null ? "—" : `+${fmt.int(r.added)} −${fmt.int(r.removed)}`), more: true },
    { key: "prs", label: "PRs", num: true, value: prCount, more: true },
    { key: "cc", label: "Claude Code", value: (r) => r.cc, more: true },
    { key: "status", label: "Status", value: (r) => r.status, cell: (r) => `${human(r.status)}${r.stub ? " · stub" : ""}`, more: true },
  ];
  const costs = runs.map((r) => runCost(r) || 0), positive = costs.filter((c) => c > 0);
  const costLog = positive.length > 0 && Math.max(...costs) / Math.max(0.01, Math.min(...positive)) > 30;
  const spendAll = sumOf(runs, runCost);
  const priciest = [...runs].sort((a, b) => (runCost(b) || 0) - (runCost(a) || 0))[0];
  return h("article", { class: "page" }, head,
    answer(`${fmt.runs(runs.length)} from ${fmt.day(isoOf(runs[runs.length - 1].t0))} to ${fmt.day(isoOf(runs[0].t0))} cost ${fmt.usd(spendAll)}, about ${fmt.usd(spendAll / runs.length)} a run. The most expensive was “${runTitle(priciest)}” (${fmt.usd(runCost(priciest))}).`),
    kpiRow([
      kpi("Runs", fmt.int(runs.length), fmt.span(isoOf(runs[runs.length - 1].t0), isoOf(runs[0].t0))),
      kpi("Spend", fmt.usd(spendAll), `${fmt.usd(spendAll / runs.length)} per run`),
      kpi("Active time", fmt.ms(sumOf(runs, (r) => r.active_ms)), `${fmt.ms(sumOf(runs, (r) => r.active_ms) / runs.length)} per run`),
      kpi("Subagents", fmt.int(sumOf(runs, (r) => r.agents)), `most in one run: ${fmt.int(Math.max(0, ...runs.map((r) => r.agents || 0)))}`),
      kpi("Pull requests", fmt.int(prs), "opened during these runs")]),
    section({ title: "When and how much", intro: "Every day with a run, and every run's cost on a time axis." },
      h("div", { class: "grid" },
        calendarChart({ title: "Activity by day", question: "When do I work, and what does a day cost?", sub: "one square per day, weeks across · darker = more",
          takeaway: () => {
            const top = [...days].sort((a, b) => b[1].value - a[1].value)[0];
            return top ? `${plural(days.size, "active day")}; the busiest was ${fmt.dayKey(top[0])} (${fmtCal(top[1].value)}).` : null;
          },
          days, fmt: fmtCal, valueTitle: { cost: "Spend", runs: "Runs", active: "Active time" }[metric], controls: calSel, legendText: ["less", "more"] }),
        scatterChart({ title: "Cost of each run", question: "Which runs were expensive, and when?", sub: "one mark per run · bigger marks started more subagents · hollow = cost estimated",
          takeaway: () => {
            const sorted = runs.map((r) => runCost(r) || 0).sort((a, b) => b - a);
            const top = sorted.slice(0, Math.max(1, Math.ceil(sorted.length / 10)));
            return spendAll ? `The costliest tenth of the runs (${fmt.int(top.length)}) account for ${fmt.pct(sumOf(top, (x) => x) / spendAll, 0)} of the spend.` : null;
          },
          points: runs.map((r) => ({ x: r.t0, y: runCost(r), label: r.run, r: 3.5 + 6 * Math.sqrt((r.agents || 0) / maxAgents), hollow: r.estimated, tip: runTip(r), href: hrefRun(r.run) })),
          x: { title: "Run started", time: true }, y: { title: `Cost per run, US$${costLog ? " (log scale)" : ""}`, fmt: fmt.usdTick, log: costLog },
          labelTitle: "Run", vlines: changeMarks(["cc", "model"]) }))),
    section({ title: "Every run", count: fmt.runs(runs.length), intro: "Newest first. Open a run to see its skills, subagents and problems on one time axis." },
      sortTable({ caption: "Runs", cols, rows: runs, sort: { key: "started", dir: -1 }, page: 25, csvName: "runs", moreParam: "cols" }).el));
}

// What to say when the filters leave nothing.
function emptyFiltered() {
  return h("div", { class: "emptybox" }, empty("No run is left in these filters."),
    button("Reset filters", () => refreshAfter(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))));
}

/* Vertical markers for a time axis: when Claude Code changed version, when a model was first used, and
   (for one skill) when each version of its text was first used. Only changes inside the kept runs. */
function changeMarks(kinds, skillUnit) {
  const out = [];
  const runs = keptRuns().sort((a, b) => a.t0 - b.t0);
  if (kinds.includes("cc")) {
    // At the level the method treats as a confounder ([method] cc_version): patch by default, so 2.1.283 → 2.1.290 is a marker.
    const level = (v) => (DATA.method.cc_version === "minor" ? String(v).split(".").slice(0, 2).join(".") : String(v));
    let prev = null;
    for (const r of runs) {
      if (r.cc && level(r.cc) !== prev) {
        if (prev) out.push({ t: r.t0, label: `CC ${level(r.cc)}`, kind: "cc", title: `Claude Code ${prev} → ${level(r.cc)}`, rows: [["First run", r.run], ["Version", r.cc]] });
        prev = level(r.cc);
      }
    }
  }
  if (kinds.includes("model")) {
    const seen = new Set();
    const first = runs.length ? runs[0].t0 : 0;
    for (const r of runs) {
      for (const m of r.models) {
        if (seen.has(m)) continue;
        seen.add(m);
        if (r.t0 > first) out.push({ t: r.t0, label: `+${shortModel(m)}`, kind: "model", title: `First use of ${m}`, rows: [["Run", r.run]] });
      }
    }
  }
  if (skillUnit) {
    for (const v of (DATA.versions[skillUnit.id] || []).slice(1)) {
      if (v.first_seen) out.push({ t: timeOf(v.first_seen), label: `${skillUnit.name} ${v.label}`, kind: "skill", title: `${skillUnit.name} ${v.label} first used`, rows: [["Text", partsText(v)]] });
    }
  }
  return out;
}

// ---- one run ----

function runPage(id) {
  const r = RUN.get(id);
  const counts = runCounts().get(id);
  const agents = EX.agents.filter((a) => a.run === id).sort((a, b) => a.i - b.i);
  const incidents = EX.incidents.filter((x) => x.run === id);
  const markers = EX.markers.filter((x) => x.run === id);
  const events = EX.events.filter((x) => x.run === id);
  const errors = EX.toolerr.filter((x) => x.run === id);
  const segments = EX.segments.filter((x) => x.run === id);
  const calls = EX.calls.filter((x) => x.run === id);
  const at = (t) => atRun(id, t);
  const end = Math.max(r.t1, ...agents.map((a) => (valid(a.t1) ? at(a.t1) : 0)), ...segments.map((s) => at(s.t1)));
  const byIndex = new Map(agents.map((a) => [a.i, a]));
  // "Explore · Explore step #" reads as "Explore · step #": a role that repeats its type drops the repeat.
  const roleOf = (a) => {
    const r = (a.role || "").startsWith(a.type) ? a.role.slice(a.type.length).replace(/^[\s·:-]+/, "") : a.role || "";
    return r && r !== a.type ? r : "";
  };
  const agentName = (i) => {
    const a = byIndex.get(i);
    return !a ? "—" : a.i === 0 ? "main session" : `${a.type}${roleOf(a) ? ` · ${roleOf(a)}` : ""}`;
  };

  // the tree: depth-first from the main session, children in start order
  const kids = new Map();
  for (const a of agents) if (a.i !== 0) (kids.get(a.parent ?? 0) || kids.set(a.parent ?? 0, []).get(a.parent ?? 0)).push(a);
  const ordered = [];
  const walk = (a, depth) => {
    ordered.push({ a, depth });
    for (const k of (kids.get(a.i) || []).sort((p, q) => (p.t0 ?? 0) - (q.t0 ?? 0))) walk(k, depth + 1);
  };
  const main = byIndex.get(0);
  if (main) walk(main, 0);
  for (const a of agents) if (!ordered.some((o) => o.a === a)) ordered.push({ a, depth: 1 }); // orphans: parent not recorded
  const layout = param("layout") === "tree" || (param("layout") !== "packed" && agents.length <= 40) ? "tree" : "packed";
  const timelineAgents = ordered.map(({ a, depth }) => ({
    label: agentName(a.i), group: a.i === 0 ? "main session" : a.type, depth,
    t0: at(a.t0), t1: valid(a.t1) ? at(a.t1) : NaN, css: a.i === 0 ? "var(--other)" : colourOf("agent", a.type).css,
    cost: a.cost, a,
    tip: { title: agentName(a.i), sub: a.i === 0 ? null : `started by ${agentName(a.parent ?? 0)}`,
      rows: [["Cost", fmt.usd(a.cost)], ["Ran for", valid(a.t1) && valid(a.t0) ? fmt.secs(a.t1 - a.t0) : "still running"], ["Model", a.model || "—"],
        ["Tool calls", a.tools != null ? `${fmt.int(a.tools)}${a.errors ? ` · ${fmt.int(a.errors)} failed` : ""}` : "—"], ["Ended", `${human(a.status || "—")}${a.stopped ? " · stopped by you" : ""}`],
        ...(a.peak ? [["Largest context", fmt.tokens(a.peak)]] : []), ...(a.compactions ? [["Compactions", fmt.int(a.compactions)]] : []),
        ...(a.stop ? [["Last turn stopped on", human(a.stop)]] : []), ...(a.bg ? [["Started", "in the background"]] : [])] },
  }));
  const layoutSel = h("select", { "aria-label": "Agent layout" }, [["tree", "One row per agent"], ["packed", "Packed by type"]].map(([v, t]) => h("option", { value: v, selected: v === layout ? true : null }, t)));
  layoutSel.addEventListener("change", () => refreshAfter({ layout: layoutSel.value }));

  const skillLane = { label: "Skill", items: segments.map((s) => ({ t0: at(s.t0), t1: Math.max(at(s.t1), at(s.t0) + 20e3), css: s.skill === "(none)" ? "var(--other)" : colourOf("skill", s.skill).css, name: human(s.skill),
    tip: { title: human(s.skill), rows: [["From", fmt.hour(at(s.t0))], ["To", fmt.hour(at(s.t1))], ["Model turns", fmt.int(s.calls)], ["Spend", fmt.usd(s.cost)]] },
    href: UNITS.has(`skill:${s.skill}`) ? hrefUnit(`skill:${s.skill}`) : null })) };
  const prompts = events.filter((e) => e.kind === "human_prompt");
  const others = events.filter((e) => e.kind !== "human_prompt");
  const lanes = [skillLane,
    { label: "Your messages", items: prompts.map((e) => ({ t: at(e.t), css: "var(--text2)", shape: "diamond", tip: { title: "You wrote", rows: [["When", fmt.hour(at(e.t))], ["How", human(e.source || "typed")]] } })) },
    { label: "Problems", items: incidents.map((x) => ({ t: at(x.t), css: x.policy ? "var(--other)" : "var(--worse)", shape: "triangle",
      tip: { title: human(x.type), sub: x.detail || null, rows: [["When", fmt.hour(at(x.t))], ["Agent", agentName(x.agent)], ["Skill", human(x.skill)], ...(x.label ? [["Label", human(x.label)]] : []), ["Show", `runlens show ${x.id}`]] } })) },
    { label: "Checks", items: markers.map((m) => ({ t: at(m.t), css: m.bad ? "var(--worse)" : "var(--better)", shape: m.bad ? "square" : "circle",
      tip: { title: `${human(m.marker)}: ${m.value}`, rows: [["When", fmt.hour(at(m.t))], ["Skill", human(m.skill)], ["Reading", m.bad ? `${TONE.worse.icon} bad value` : `${TONE.better.icon} ok`]] } })) },
    { label: "Tool errors", items: errors.map((e) => ({ t: at(e.t), css: "var(--worse)", shape: "tick", tip: { title: `${e.tool}: ${human(e.class)}`, rows: [["When", fmt.hour(at(e.t))], ["Agent", agentName(e.agent)], ["Show", `runlens show ${e.id}`]] } })) },
    { label: "Other events", items: others.map((e) => ({ t: at(e.t), css: "var(--c7)", shape: "square", tip: { title: human(e.kind), rows: [["When", fmt.hour(at(e.t))], ["Agent", agentName(e.agent)], ...(e.value != null ? [["Value", fmt.int(e.value)]] : [])] } })) },
  ].filter((l) => l.items.length);
  const curve = (EX.curves[id] || []).map(([t, c]) => [at(t), c]);
  const types = [...new Set(agents.filter((a) => a.i !== 0).map((a) => a.type))];

  const byType = new Map();
  for (const a of agents) {
    const k = a.i === 0 ? "main session" : a.type;
    const e = byType.get(k) || { value: 0, n: 0 };
    e.value += a.cost || 0;
    e.n += 1;
    byType.set(k, e);
  }
  const spendModel = groupSum(calls, "model", "cost");
  const prs = r.prs || [];
  const nprs = prCount(r);
  const incCols = [
    { key: "t", label: "When", value: (x) => x.t, cell: (x) => fmt.hour(at(x.t)) },
    { key: "type", label: "Problem", value: (x) => human(x.type), cell: (x) => h("span", {}, human(x.type), x.policy ? h("span", { class: "muted" }, " · permission rule") : null) },
    { key: "agent", label: "Agent", value: (x) => agentName(x.agent) },
    { key: "skill", label: "Skill", value: (x) => human(x.skill) },
    { key: "label", label: "Label", value: (x) => (x.label ? human(x.label) : "") },
    { key: "show", label: "Open the trace", value: (x) => `runlens show ${x.id}`, cell: (x) => cmdLine(`runlens show ${x.id}`) },
  ];
  const errCols = [
    { key: "t", label: "When", value: (x) => x.t, cell: (x) => fmt.hour(at(x.t)) },
    { key: "tool", label: "Tool", value: (x) => x.tool },
    { key: "class", label: "Error", value: (x) => human(x.class) },
    { key: "agent", label: "Agent", value: (x) => agentName(x.agent) },
    { key: "show", label: "Open the trace", value: (x) => `runlens show ${x.id}`, cell: (x) => (x.id ? cmdLine(`runlens show ${x.id}`) : "—") },
  ];
  const wall = (end - r.t0) / 1000;
  const runSkills = [...new Set(segments.map((s) => s.skill))];
  const topAgent = [...byType].filter(([k]) => k !== "main session").sort((a, b) => b[1].value - a[1].value)[0];
  const story = `${fmt.usd(r.cost)} over ${fmt.secs(wall)}${runSkills.filter((s) => s !== "(none)").length ? `, under ${listWords(runSkills.filter((s) => s !== "(none)").map(human))}` : ""}. `
    + `${agents.length - (main ? 1 : 0) ? `${plural(agents.length - (main ? 1 : 0), "subagent")}${topAgent ? `, ${topAgent[0]} costing the most (${fmt.usd(topAgent[1].value)})` : ""}` : "No subagents"}; `
    + `${plural(counts.incidents, "problem")} and ${plural(counts.errors, "tool error")}.`;
  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("a", { class: "back", href: hrefPage("runs") }, "← All runs"),
      h("h1", { tabindex: "-1" }, h("code", { class: "h1code" }, r.run), " ", runTitle(r)),
      h("p", { class: "lede" }, `${fmt.when(isoOf(r.t0))} · ${r.repo || "no repo"}${r.branch ? ` · ${r.branch}` : ""} · Claude Code ${r.cc || "?"}`,
        chip(r.status === "complete" ? "finished" : "still open", r.status === "complete" ? "ok" : "warn"), r.stub ? chip("stub: too small to score", "warn") : null,
        r.estimated ? chip("cost estimated", "warn") : null, !RUNSET.has(r.run) ? chip("outside the current filters", "warn") : null)),
    answer(story, counts.incidents ? "worse" : null),
    kpiRow([
      kpi("Cost", fmt.usd(r.cost), r.estimated ? "estimated at list price" : "Claude Code's own figure"),
      kpi("Wall time", fmt.secs(wall), `active ${fmt.ms(r.active_ms)}`),
      kpi("Subagents", fmt.int(agents.length - (main ? 1 : 0)), types.length ? `${types.length} type${types.length === 1 ? "" : "s"}` : "none"),
      kpi("Tool calls", fmt.int(counts.calls), counts.calls ? `${fmt.pct(counts.errors / counts.calls)} failed${counts.denied ? ` · ${fmt.int(counts.denied)} denied` : ""}` : ""),
      kpi("Problems", fmt.int(counts.incidents), incidents.some((x) => x.policy) ? `${incidents.filter((x) => x.policy).length} more from permission rules` : "not counting permission rules"),
      kpi("Your messages", fmt.int(r.prompts), "typed during the run"),
      kpi("Code changed", r.added == null ? "—" : `+${fmt.int(r.added)} −${fmt.int(r.removed)}`, nprs ? `${nprs} PR${nprs === 1 ? "" : "s"} opened` : "lines added and removed")]),
    section({ title: "What happened, and when", intro: "Top: the active skill and each event. Middle: the money spent so far. Bottom: every subagent as a bar from its start to its end." },
      runTimeline({
        title: "The run on one time axis", question: "What happened in this run, and when?",
        takeaway: () => {
          const first = errors.length ? fmt.hour(at(errors[0].t)) : null;
          return `${plural(agents.length - (main ? 1 : 0), "subagent")} in ${plural(types.length, "type")}${counts.incidents ? `, ${plural(counts.incidents, "problem")}` : ""}${errors.length ? `, the first tool error at ${first}` : ""}. Hover or tab to any mark for details.`;
        },
        sub: "skills, your messages, problems, checks and errors on top · spend so far · every subagent as a bar, coloured by type",
        t0: r.t0, t1: end, lanes, curve, agents: timelineAgents, layout, controls: layoutSel,
        legendItems: runSkills.filter((s) => s !== "(none)").map((s) => ({ label: `skill: ${human(s)}`, css: colourOf("skill", s).css }))
          .concat(types.map((t) => ({ label: `agent: ${t}`, css: colourOf("agent", t).css }))).concat([{ label: "main session", css: "var(--other)" },
          { label: `${TONE.worse.icon} problem / error / bad check`, css: "var(--worse)", shape: "triangle" }, { label: "ok check", css: "var(--better)", kind: "dot" },
          { label: "your message", css: "var(--text2)", shape: "diamond" }]),
        agentCols: [{ label: "Type", value: (a) => a.group }, { label: "Cost", num: true, value: (a) => a.cost, cell: (a) => fmt.usd(a.cost) },
          { label: "Depth", num: true, value: (a) => a.depth }],
        notes: "Times are your local time. A bar that runs to the right edge never recorded its end. Skill segments are the main session's model turns under each skill.",
      })),
    section({ title: "Where the money went", intro: "The run's spend by agent type, single agent, model and skill." },
      h("div", { class: "grid" },
        barChart({ title: "Spend by agent type", question: "Which kind of agent did the money go to?",
          takeaway: () => shareTakeaway([...byType].map(([k, e]) => ({ label: k, value: e.value })), "of the run's spend"), items: [...byType].map(([k, e]) => ({ label: k, name: k, value: e.value, rows: [["Agents", fmt.int(e.n)]],
          css: k === "main session" ? "var(--other)" : colourOf("agent", k).css })), fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Agent type" }),
        barChart({ title: "The costliest agents", question: "Which single agents cost the most?", sub: "the twelve most expensive",
          items: agents.filter((a) => a.cost > 0).sort((a, b) => b.cost - a.cost).slice(0, 12).map((a) => ({ label: agentName(a.i), value: a.cost,
            css: a.i === 0 ? "var(--other)" : colourOf("agent", a.type).css, rows: [["Ran for", valid(a.t1) && valid(a.t0) ? fmt.secs(a.t1 - a.t0) : "—"], ["Model", a.model || "—"]] })),
          fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", labelTitle: "Agent" })),
      h("div", { class: "grid" },
        barChart({ title: "Spend by model", question: "Which models did this run pay for?", items: spendModel.map((m) => ({ label: m.label, name: m.label, value: m.value })), ns: "model",
          fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$ (transcript)", share: true, labelTitle: "Model" }),
        barChart({ title: "Spend by skill", question: "Which skills did the work?", items: groupSum(calls, "skill", "cost").map((s) => ({ label: human(s.label), name: s.label, value: s.value,
          href: UNITS.has(`skill:${s.label}`) ? hrefUnit(`skill:${s.label}`) : null })), ns: "skill", fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Skill" }))),
    incidents.length ? section({ title: "Problems", count: `${counts.incidents}${incidents.length > counts.incidents ? `, and ${incidents.length - counts.incidents} from permission rules` : ""}`, intro: "Each problem with the command that opens its trace." },
      sortTable({ caption: "Problems in this run", cols: incCols, rows: incidents, sort: { key: "t", dir: 1 }, page: 25, csvName: `run-${id}-problems` }).el) : null,
    errors.length ? section({ title: "Tool errors", count: `${counts.errors}${counts.errors > errors.length ? ` (the first ${errors.length} listed)` : ""}`, intro: "Each failed tool call with the command that opens its trace." },
      sortTable({ caption: "Tool errors in this run", cols: errCols, rows: errors, sort: { key: "t", dir: 1 }, page: 25, csvName: `run-${id}-tool-errors` }).el) : null,
    section({ title: "Open the raw data", collapsible: true, collapsed: true, intro: "Commands that open this run's session, its database row and its first problem." },
      h("ul", { class: "cmds" },
        h("li", {}, cmdLine(r.sid, "Session")),
        h("li", {}, cmdLine(`runlens sql "SELECT * FROM v_runs WHERE session_id = '${r.sid}'"`)),
        incidents[0] ? h("li", {}, cmdLine(`runlens show ${incidents[0].id}`), h("span", { class: "muted" }, " the first problem, with what led to it")) : null,
        prs.map((u) => h("li", {}, h("span", { class: "muted" }, "PR "), /^https:\/\//i.test(u) ? h("a", { href: u, rel: "noopener noreferrer", target: "_blank" }, u) : u)))));
}
