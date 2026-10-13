/* pages/diagnostics.js: everything else the database records (#/diagnostics?tab=…&sub=…).

   Comparisons between skills, tools or models use rates (per run, per 100 calls), not raw counts, so the
   busiest one does not look the worst just for being busy. Runs sit on a real time axis. */

const EFFORT_ORDER = ["(default)", "none", "minimal", "low", "medium", "high", "xhigh", "max"];
const effortRank = (e) => {
  const i = EFFORT_ORDER.indexOf(String(e).toLowerCase());
  return i < 0 ? EFFORT_ORDER.length : i;
};
const skillRuns = (name) => {
  const u = UNITS.get(`skill:${name}`);
  return u ? u.runs : name === "(none)" ? DATA.window.runs : 0;
};
const countFmt = (v) => fmt.int(v);
const per100 = (v) => `${fmt.num(v, v < 10 ? 1 : 0)} per 100`;

function diagnosticsPage() {
  const D = DIAG;
  if (!D) return h("article", { class: "page" }, h("h1", { tabindex: "-1" }, "Diagnostics"), empty("Run runlens dashboard again to add this page."));
  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("h1", { tabindex: "-1" }, "Diagnostics"),
      h("p", { class: "lede" }, "The rest of what runlens recorded: each run, the problems it hit, its tools and models, its subagents, and how skills hand work to each other.")),
    tabs("Diagnostics", [
      { id: "runs", label: "Runs", build: () => diagRuns(D) },
      { id: "problems", label: "Problems", build: () => diagProblems(D) },
      { id: "tools", label: "Tools", build: () => diagTools(D) },
      { id: "models", label: "Models", build: () => diagModels(D) },
      { id: "agents", label: "Agents", build: () => diagAgents(D) },
      { id: "flow", label: "Flow and checks", build: () => diagFlow(D) },
    ], { param: "tab" }));
}

function diagRuns(D) {
  const runs = (D.runs || []).filter((r) => r.started);
  if (!runs.length) return empty("No runs recorded yet.");
  const cost = sumOf(runs, (r) => r.cost), active = sumOf(runs, (r) => r.active_ms) / 1000;
  const added = sumOf(runs, (r) => r.lines_added), removed = sumOf(runs, (r) => r.lines_removed);
  const tip = (r) => ({ title: `${fmt.when(r.started)} · ${r.run}`, sub: r.title || null,
    rows: [["Cost", fmt.usd(r.cost) + (r.estimated ? " (estimated)" : "")], ["Active", fmt.ms(r.active_ms)], ["Subagents", fmt.int(r.agents)],
      ["Incidents", fmt.int(r.incidents)], ["Tool errors", r.tool_calls ? `${fmt.int(r.tool_errors)} of ${fmt.int(r.tool_calls)}` : "—"],
      ["Repo · branch", `${r.repo || "—"} · ${r.branch || "—"}`], ["Claude Code", r.cc_version || "—"]] });
  const maxAgents = Math.max(1, ...runs.map((r) => r.agents || 0));
  const size = (r) => 3.5 + 7 * Math.sqrt((r.agents || 0) / maxAgents);
  const at = (r) => timeOf(r.started);
  const cols = [
    { key: "run", label: "Run", value: (r) => r.run, cell: (r) => h("code", {}, r.run) },
    { key: "started", label: "Started", value: (r) => r.started, cell: (r) => fmt.when(r.started) },
    { key: "repo", label: "Repo", value: (r) => r.repo },
    { key: "branch", label: "Branch", value: (r) => r.branch },
    { key: "cc", label: "Claude Code", value: (r) => r.cc_version },
    { key: "cost", label: "Cost", num: true, value: (r) => r.cost, cell: (r) => fmt.usd(r.cost) + (r.estimated ? " est." : "") },
    { key: "active", label: "Active", num: true, value: (r) => r.active_ms, cell: (r) => fmt.ms(r.active_ms) },
    { key: "agents", label: "Subagents", num: true, value: (r) => r.agents },
    { key: "prompts", label: "Your prompts", num: true, value: (r) => r.prompts },
    { key: "lines", label: "Lines +/−", num: true, value: (r) => (r.lines_added || 0) + (r.lines_removed || 0),
      cell: (r) => (r.lines_added == null ? "—" : `+${fmt.int(r.lines_added)} −${fmt.int(r.lines_removed)}`) },
    { key: "errors", label: "Tool errors", num: true, value: (r) => (r.tool_calls ? r.tool_errors / r.tool_calls : null), cell: (r) => fmt.pct(r.tool_calls ? r.tool_errors / r.tool_calls : null) },
    { key: "incidents", label: "Incidents", num: true, value: (r) => r.incidents },
    { key: "title", label: "Title", value: (r) => r.title, cell: (r) => h("span", { class: "task", title: r.title || "" }, r.title || "—") },
  ];
  return h("div", {},
    h("div", { class: "kpis" },
      kpi("Runs", fmt.int(runs.length), fmt.span(runs[0].started, runs[runs.length - 1].started)),
      kpi("Cost", fmt.usd(cost), `${fmt.usd(cost / runs.length)} per run · whole runs, every skill`),
      kpi("Active time", fmt.secs(active), `${fmt.secs(active / runs.length)} per run`),
      kpi("Code changed", `+${fmt.int(added)} −${fmt.int(removed)}`, "lines added and removed"),
      kpi("Your prompts", fmt.int(sumOf(runs, (r) => r.prompts)), "typed during the runs")),
    h("div", { class: "charts" },
      scatterChart({
        title: "Cost of each run over time", sub: "one mark per run · bigger marks started more subagents",
        points: runs.map((r) => ({ x: at(r), y: r.cost, label: r.run, r: size(r), tip: tip(r), hollow: r.estimated })),
        x: { title: "Run started", time: true }, y: { title: "Cost per run, US$", fmt: fmt.usdTick }, labelTitle: "Run",
        notes: "Hollow marks are runs still open, whose cost is estimated at list price. This is the whole run's cost; the Skills page splits it between skills.",
      }),
      h("div", { class: "grid" },
        scatterChart({
          title: "Cost against active time", sub: "one mark per run · bigger marks started more subagents",
          points: runs.map((r) => ({ x: (r.active_ms || 0) / 3.6e6, y: r.cost, label: r.run, r: size(r), tip: tip(r) })),
          x: { title: "Active time, hours", fmt: (v) => `${fmt.num(v, 1)} h` }, y: { title: "Cost per run, US$", fmt: fmt.usdTick }, labelTitle: "Run",
        }),
        scatterChart({
          title: "Code changed against cost", sub: "one mark per run with a line count",
          points: runs.filter((r) => r.lines_added != null).map((r) => ({ x: (r.lines_added || 0) + (r.lines_removed || 0), y: r.cost, label: r.run, tip: tip(r) })),
          x: { title: "Lines added + removed", fmt: fmt.compact }, y: { title: "Cost per run, US$", fmt: fmt.usdTick }, labelTitle: "Run",
        }),
        scatterChart({
          title: "Incidents per 100 tool calls, by run", sub: "a rate, so long runs do not look worse just for being long",
          points: runs.filter((r) => r.tool_calls).map((r) => ({ x: at(r), y: (100 * r.incidents) / r.tool_calls, label: r.run, tip: tip(r) })),
          x: { title: "Run started", time: true }, y: { title: "Incidents per 100 tool calls", fmt: (v) => fmt.num(v, 1) }, labelTitle: "Run",
        }),
        scatterChart({
          title: "Tool error rate, by run", sub: "share of the run's tool calls that failed",
          points: runs.filter((r) => r.tool_calls).map((r) => ({ x: at(r), y: r.tool_errors / r.tool_calls, label: r.run, tip: tip(r) })),
          x: { title: "Run started", time: true }, y: { title: "Tool calls that failed", fmt: (v) => fmt.pct(v, 0) }, labelTitle: "Run",
        }))),
    sortTable({ caption: "Runs", cols, rows: runs, sort: { key: "started", dir: -1 }, csvName: "runs" }).el);
}

function diagProblems(D) {
  const inc = D.incidents || [];
  const errs = D.tool_errors || [];
  if (!inc.length && !errs.length) return empty("No incident or tool error was recorded.");
  const types = groupSum(inc, "type", "incidents");
  const skills = groupSum(inc, "skill", "incidents").slice(0, 10);
  const classes = groupSum(errs, "class", "errors");
  const tools = groupSum(errs, "tool", "errors").slice(0, 10);
  const calls = new Map((D.tools || []).map((t) => [t.tool, t.calls]));
  const incAt = (type, skill) => sumOf(inc.filter((r) => r.type === type && r.skill === skill), (r) => r.incidents);
  const errAt = (cls, tool) => sumOf(errs.filter((r) => r.class === cls && r.tool === tool), (r) => r.errors);
  const maxRate = Math.max(1e-9, ...types.flatMap((t) => skills.map((s) => (skillRuns(s.label) ? incAt(t.label, s.label) / skillRuns(s.label) : 0))));
  const maxErr = Math.max(1e-9, ...classes.flatMap((c) => tools.map((t) => (calls.get(t.label) ? (100 * errAt(c.label, t.label)) / calls.get(t.label) : 0))));
  return h("div", {},
    h("div", { class: "kpis" },
      kpi("Incidents", fmt.int(sumOf(inc, (r) => r.incidents)), `${types.length} types`),
      kpi("Tool errors", fmt.int(sumOf(errs, (r) => r.errors)), `${classes.length} classes`),
      kpi("Most common incident", types[0] ? human(types[0].label) : "—", types[0] ? `${fmt.int(types[0].value)} times` : ""),
      kpi("Most common error", classes[0] ? human(classes[0].label) : "—", classes[0] ? `${fmt.int(classes[0].value)} times` : "")),
    h("div", { class: "charts" },
      h("div", { class: "grid" },
        barChart({ title: "Incidents by type", items: types.map((t) => ({ label: human(t.label), value: t.value })), fmt: countFmt, valueTitle: "Incidents", share: true, labelTitle: "Type" }),
        barChart({ title: "Incidents by agent role", items: (D.incident_roles || []).map((r) => ({ label: r.role === "main" ? "Main session" : r.role, value: r.incidents })),
          fmt: countFmt, valueTitle: "Incidents", labelTitle: "Role", singleSub: "every incident happened here" })),
      heatmap({
        title: "Incidents per run, by type and skill", sub: "incidents of each type ÷ runs of that skill · the ten skills with most incidents",
        rows: types.map((t) => ({ key: t.label, label: human(t.label) })), cols: skills.map((s) => ({ key: s.label, label: human(s.label), sub: `${fmt.runs(skillRuns(s.label))}` })),
        rowTitle: "Incident type", scale: "seq",
        cell: (r, c) => {
          const n = incAt(r.key, c.key), runsN = skillRuns(c.key);
          if (!n || !runsN) return null;
          const rate = n / runsN;
          return { t: rate / maxRate, raw: rate, text: fmt.num(rate, 2), dim: runsN < MIN_RUNS,
            tip: [["Per run", fmt.num(rate, 2)], ["Incidents", fmt.int(n)], ["Runs of the skill", fmt.int(runsN)]] };
        },
        legendText: ["fewer per run", "more per run", `corner mark = fewer than ${MIN_RUNS} runs`],
        notes: "A rate per run, so a skill that ran more often does not look worse for it. “No skill” is divided by all runs.",
      }),
      h("div", { class: "grid" },
        barChart({ title: "Tool errors by class", items: classes.map((c) => ({ label: human(c.label), value: c.value })), fmt: countFmt, valueTitle: "Tool errors", share: true, labelTitle: "Class" }),
        barChart({ title: "Tool errors by tool", sub: "with each tool's error rate in the tooltip",
          items: tools.map((t) => ({ label: t.label, value: t.value, rows: calls.get(t.label) ? [["Error rate", fmt.pct(t.value / calls.get(t.label))]] : [] })),
          fmt: countFmt, valueTitle: "Tool errors", labelTitle: "Tool" })),
      heatmap({
        title: "Error class by tool, per 100 calls", sub: "errors of each class ÷ calls to that tool × 100",
        rows: classes.map((c) => ({ key: c.label, label: human(c.label) })), cols: tools.map((t) => ({ key: t.label, label: t.label, sub: `${fmt.compact(calls.get(t.label) || 0)} calls` })),
        rowTitle: "Error class", scale: "seq",
        cell: (r, c) => {
          const n = errAt(r.key, c.key), total = calls.get(c.key);
          if (!n || !total) return null;
          const rate = (100 * n) / total;
          return { t: rate / maxErr, raw: rate, text: fmt.num(rate, rate < 10 ? 1 : 0), tip: [["Per 100 calls", per100(rate)], ["Errors", fmt.int(n)], ["Calls to the tool", fmt.int(total)]] };
        },
        legendText: ["rarer", "more frequent"],
      }),
      barChart({ title: "Other events", items: (D.events || []).map((e) => ({ label: human(e.kind), value: e.n })), fmt: countFmt, valueTitle: "Events", labelTitle: "Event" })));
}

function diagTools(D) {
  const tools = D.tools || [];
  if (!tools.length) return empty("Nothing recorded for this yet.");
  const cols = [
    { key: "tool", label: "Tool", value: (t) => t.tool },
    { key: "calls", label: "Calls", num: true, value: (t) => t.calls, cell: (t) => fmt.int(t.calls) },
    { key: "errors", label: "Errors", num: true, value: (t) => t.errors, cell: (t) => fmt.int(t.errors) },
    { key: "rate", label: "Error rate", num: true, value: (t) => (t.calls ? t.errors / t.calls : null), cell: (t) => fmt.pct(t.calls ? t.errors / t.calls : null) },
    { key: "median", label: "Median call", num: true, value: (t) => t.median_ms, cell: (t) => fmt.ms(t.median_ms) },
    { key: "p95", label: "Slowest 5%", num: true, value: (t) => t.p95_ms, cell: (t) => fmt.ms(t.p95_ms) },
    { key: "total", label: "Total time", num: true, value: (t) => t.total_ms, cell: (t) => fmt.ms(t.total_ms) },
  ];
  const idle = (D.idle || []).filter((i) => i.calls).map((i) => ({ label: human(i.skill), name: i.skill, value: i.idle_calls / i.calls, rows: [["Waiting calls", `${fmt.int(i.idle_calls)} of ${fmt.int(i.calls)}`]] }));
  const top = tools.slice(0, 12);
  return h("div", {},
    h("div", { class: "kpis" },
      kpi("Tool calls", fmt.int(sumOf(tools, (t) => t.calls)), `${tools.length} tools`),
      kpi("Failed", fmt.pct(sumOf(tools, (t) => t.errors) / Math.max(1, sumOf(tools, (t) => t.calls))), "share of calls"),
      kpi("Time in tools", fmt.ms(sumOf(tools, (t) => t.total_ms)), "all runs")),
    h("div", { class: "charts" },
      h("div", { class: "grid" },
        barChart({ title: "Calls by tool", sub: "the twelve most used", items: top.map((t) => ({ label: t.tool, value: t.calls })), fmt: countFmt, tickFmt: fmt.compact, valueTitle: "Calls", labelTitle: "Tool" }),
        barChart({ title: "Error rate by tool", sub: "tools with at least 20 calls",
          items: top.filter((t) => t.calls >= 20).map((t) => ({ label: t.tool, value: t.errors / t.calls, rows: [["Errors", `${fmt.int(t.errors)} of ${fmt.int(t.calls)}`]] })),
          fmt: (v) => fmt.pct(v), tickFmt: (v) => fmt.pct(v, 0), valueTitle: "Calls that failed", labelTitle: "Tool" })),
      h("div", { class: "grid" },
        barChart({ title: "How long a call takes", sub: "bar = the slowest 5% of calls · label = median and slowest 5%",
          items: top.filter((t) => t.p95_ms != null).map((t) => ({ label: t.tool, value: t.p95_ms, text: `median ${fmt.ms(t.median_ms)} · slowest 5% ${fmt.ms(t.p95_ms)}`,
            rows: [["Median call", fmt.ms(t.median_ms)]] })),
          fmt: fmt.ms, valueTitle: "Slowest 5% of calls", labelTitle: "Tool" }),
        barChart({ title: "Where tool time goes", sub: "total time spent in each tool", items: tools.map((t) => ({ label: t.tool, value: t.total_ms || 0 })).filter((t) => t.value > 0).slice(0, 12),
          fmt: fmt.ms, valueTitle: "Total time", share: true, labelTitle: "Tool" })),
      barChart({ title: "Waiting calls by skill", sub: "share of each skill's tool calls that only wait or print", items: idle, ns: "skill",
        fmt: (v) => fmt.pct(v), tickFmt: (v) => fmt.pct(v, 0), valueTitle: "Calls that only wait", labelTitle: "Skill" })),
    sortTable({ caption: "Tools", cols, rows: tools, sort: { key: "calls", dir: -1 }, csvName: "tools" }).el);
}

function diagModels(D) {
  const ms = D.models || [];
  if (!ms.length) return empty("Nothing recorded for this yet.");
  const modelSeries = ms.map((m) => ({ key: m.model, label: m.model, css: colourOf("model", m.model).css }));
  const hit = (m) => (m.cache_read || 0) / Math.max(1, (m.cache_read || 0) + (m.fresh_input || 0));
  const cols = [
    { key: "model", label: "Model", value: (m) => m.model },
    { key: "calls", label: "Calls", num: true, value: (m) => m.calls, cell: (m) => fmt.int(m.calls) },
    { key: "cost", label: "Cost", num: true, value: (m) => m.cost, cell: (m) => fmt.usd(m.cost) },
    { key: "per", label: "Cost per call", num: true, value: (m) => (m.cost || 0) / Math.max(1, m.calls), cell: (m) => fmt.usd((m.cost || 0) / Math.max(1, m.calls)) },
    { key: "output", label: "Output tokens", num: true, value: (m) => m.output, cell: (m) => fmt.compact(m.output) },
    { key: "thinking", label: "Thinking tokens", num: true, value: (m) => m.thinking, cell: (m) => fmt.compact(m.thinking) },
    { key: "cache", label: "Cache hit", num: true, value: hit, cell: (m) => fmt.pct(hit(m)) },
  ];
  const kp = h("div", { class: "kpis" },
    kpi("Model spend", fmt.usd(sumOf(ms, (m) => m.cost)), `${ms.length} models`),
    kpi("API calls", fmt.int(sumOf(ms, (m) => m.calls)), "model turns"),
    kpi("Output", fmt.tokens(sumOf(ms, (m) => m.output)), "written"),
    kpi("Thinking", fmt.tokens(sumOf(ms, (m) => m.thinking)), "thought"),
    kpi("Cache hit", fmt.pct(sumOf(ms, (m) => m.cache_read) / Math.max(1, sumOf(ms, (m) => m.cache_read) + sumOf(ms, (m) => m.fresh_input))), "of input read from cache"));

  const me = D.model_effort || [];
  const efforts = [...new Set(me.map((r) => r.effort))].sort((a, b) => effortRank(a) - effortRank(b) || String(a).localeCompare(String(b)));
  const effortSeries = efforts.map((e, i) => ({ key: e, label: human(e), css: ordinalCss(i, efforts.length) }));
  const weighted = (key) => efforts.map((e) => {
    const rows = me.filter((r) => r.effort === e);
    const n = sumOf(rows, (r) => r.calls);
    return { label: human(e), value: n ? sumOf(rows, (r) => (r[key] || 0) * r.calls) / n : null };
  });
  const perCall = me.map((r) => (r.calls ? r.cost / r.calls : 0));
  const maxPer = Math.max(1e-9, ...perCall);
  const effortTab = () => h("div", { class: "charts" },
    h("div", { class: "grid" },
      barChart({ title: "Spend by effort level", items: efforts.map((e, i) => ({ label: human(e), value: sumOf(me.filter((r) => r.effort === e), (r) => r.cost), css: effortSeries[i].css })),
        sort: false, fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Effort" }),
      barChart({ title: "Calls by effort level", items: efforts.map((e, i) => ({ label: human(e), value: sumOf(me.filter((r) => r.effort === e), (r) => r.calls), css: effortSeries[i].css })),
        sort: false, fmt: countFmt, tickFmt: fmt.compact, valueTitle: "Calls", share: true, labelTitle: "Effort" })),
    stackChart({ title: "Effort level used by each model", sub: "share of each model's calls", mode: "share", series: effortSeries,
      rows: ms.map((m) => ({ label: m.model, parts: Object.fromEntries(efforts.map((e) => [e, sumOf(me.filter((r) => r.model === m.model && r.effort === e), (r) => r.calls)])) })),
      fmt: (v) => `${fmt.int(v)} calls`, labelTitle: "Model" }),
    heatmap({ title: "Cost per call, by model and effort", sub: "lighter is cheaper per call",
      rows: ms.map((m) => ({ key: m.model, label: m.model })), cols: efforts.map((e) => ({ key: e, label: human(e) })), rowTitle: "Model", scale: "seq",
      cell: (r, c) => {
        const x = me.find((q) => q.model === r.key && q.effort === c.key);
        if (!x || !x.calls) return null;
        const per = x.cost / x.calls;
        return { t: per / maxPer, raw: per, text: fmt.usd(per), tip: [["Cost per call", fmt.usd(per)], ["Calls", fmt.int(x.calls)], ["Thinking tokens per call", fmt.num(x.avg_thinking, 0)], ["Output tokens per call", fmt.num(x.avg_output, 0)]] };
      },
      legendText: ["cheaper per call", "dearer per call"] }),
    h("div", { class: "grid" },
      barChart({ title: "Thinking tokens per call", sub: "average, by effort level", items: weighted("avg_thinking").map((x, i) => ({ ...x, css: effortSeries[i].css })), sort: false, fmt: (v) => fmt.num(v, 0), tickFmt: fmt.compact, valueTitle: "Tokens per call", labelTitle: "Effort" }),
      barChart({ title: "Thinking time per call", sub: "average, by effort level", items: weighted("avg_thinking_ms").map((x, i) => ({ ...x, css: effortSeries[i].css })), sort: false, fmt: fmt.ms, valueTitle: "Time per call", labelTitle: "Effort" })));

  const msk = D.model_skill || [];
  const skillsBySpend = groupSum(msk, "skill", "cost").slice(0, 9);
  const maxSk = Math.max(1e-9, ...msk.map((x) => x.cost || 0));
  const skillTab = () => h("div", { class: "charts" },
    heatmap({ title: "Spend by skill and model", sub: "the nine skills that spent the most",
      rows: skillsBySpend.map((k) => ({ key: k.label, label: human(k.label) })), cols: ms.map((m) => ({ key: m.model, label: m.model })), rowTitle: "Skill", scale: "seq",
      cell: (r, c) => {
        const v = sumOf(msk.filter((x) => x.skill === r.key && x.model === c.key), (x) => x.cost);
        return v ? { t: v / maxSk, raw: v, text: fmt.usdTick(v), tip: [["Spend", fmt.usd(v)]] } : null;
      },
      legendText: ["less spend", "more spend"] }),
    stackChart({ title: "Which models each skill uses", sub: "share of each skill's model spend", mode: "share", series: modelSeries,
      rows: skillsBySpend.map((k) => ({ label: human(k.label), parts: Object.fromEntries(ms.map((m) => [m.model, sumOf(msk.filter((x) => x.skill === k.label && x.model === m.model), (x) => x.cost)])) })),
      fmt: fmt.usd, labelTitle: "Skill" }));

  const md = D.model_day || [];
  const dayParts = (val) => [...new Set(md.map((d) => d.day))].map((day) => ({ day, parts: Object.fromEntries(md.filter((x) => x.day === day).map((x) => [x.model, x[val] || 0])) }));
  const timeTab = () => h("div", { class: "charts" },
    dayColumns({ title: "Spend per day, by model", days: dayParts("cost"), series: modelSeries, fmt: fmt.usd, tickFmt: fmt.usdTick, yTitle: "Spend, US$" }),
    dayColumns({ title: "API calls per day, by model", days: dayParts("calls"), series: modelSeries, fmt: countFmt, tickFmt: fmt.compact, yTitle: "API calls", whole: true }));

  const errs = D.api_errors || [];
  const tokenSeries = [
    { key: "fresh_input", label: "fresh input and cache writes", css: "var(--c1)" }, { key: "cache_read", label: "read from cache", css: "var(--c3)" },
    { key: "output", label: "output", css: "var(--c2)" }, { key: "thinking", label: "thinking", css: "var(--c7)" }];
  const callsTab = () => h("div", { class: "charts" },
    h("div", { class: "grid" },
      barChart({ title: "API error rate by model", items: errs.map((e) => ({ label: e.model, name: e.model, value: e.calls ? e.errors / e.calls : null, rows: [["Errors", `${fmt.int(e.errors)} of ${fmt.int(e.calls)}`]] })),
        ns: "model", fmt: (v) => fmt.pct(v), tickFmt: (v) => fmt.pct(v, 1), valueTitle: "Calls that hit an API error", labelTitle: "Model" }),
      barChart({ title: "Cache hit rate", sub: "share of input tokens read from cache", items: ms.map((m) => ({ label: m.model, name: m.model, value: hit(m) })), ns: "model",
        fmt: (v) => fmt.pct(v), tickFmt: (v) => fmt.pct(v, 0), valueTitle: "Input read from cache", labelTitle: "Model" })),
    stackChart({ title: "What each model processed", sub: "tokens, as shares of each model's total", mode: "share", series: tokenSeries,
      rows: ms.map((m) => ({ label: m.model, parts: { fresh_input: m.fresh_input || 0, cache_read: m.cache_read || 0, output: m.output || 0, thinking: m.thinking || 0 } })),
      fmt: fmt.tokens, labelTitle: "Model",
      notes: "Fresh input includes the tokens written to the cache, which the database does not yet split out. Cost by token type comes in a later version." }));

  const spendTab = () => h("div", { class: "charts" },
    h("div", { class: "grid" },
      barChart({ title: "Spend by model", items: ms.map((m) => ({ label: m.model, name: m.model, value: m.cost || 0 })), ns: "model", fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Model" }),
      barChart({ title: "Calls by model", items: ms.map((m) => ({ label: m.model, name: m.model, value: m.calls })), ns: "model", fmt: countFmt, tickFmt: fmt.compact, valueTitle: "API calls", share: true, labelTitle: "Model" })),
    sortTable({ caption: "Models", cols, rows: ms, sort: { key: "cost", dir: -1 }, csvName: "models" }).el);

  return h("div", {}, kp, tabs("Model detail", [
    { id: "spend", label: "Spend", build: spendTab },
    { id: "effort", label: "Effort", build: effortTab },
    { id: "skill", label: "By skill", build: skillTab },
    { id: "time", label: "Over time", build: timeTab },
    { id: "calls", label: "Calls", build: callsTab },
  ], { param: "sub" }));
}

function diagAgents(D) {
  const ag = D.agent_types || [];
  if (!ag.length) return empty("No subagent was recorded.");
  const types = ag.map((a) => a.agent_type);
  const typeSeries = types.map((t) => ({ key: t, label: t, css: colourOf("agent", t).css }));
  const total = sumOf(ag, (a) => a.agents);
  const byRun = D.agents_by_run || [];
  const runs = D.runs || [];
  const perRun = runs.map((r) => ({ run: r.run, started: r.started, n: sumOf(byRun.filter((x) => x.run === r.run), (x) => x.n) }));
  const background = sumOf((D.agent_shape || []).filter((x) => x.background), (x) => x.n);
  const status = D.agent_status || [];
  const done = sumOf(status.filter((s) => s.status === "completed"), (s) => s.agents);
  const cols = [
    { key: "type", label: "Agent type", value: (a) => a.agent_type },
    { key: "agents", label: "Agents", num: true, value: (a) => a.agents, cell: (a) => fmt.int(a.agents) },
    { key: "cost", label: "Cost", num: true, value: (a) => a.cost, cell: (a) => fmt.usd(a.cost) },
    { key: "per", label: "Cost each", num: true, value: (a) => (a.cost || 0) / Math.max(1, a.agents), cell: (a) => fmt.usd((a.cost || 0) / Math.max(1, a.agents)) },
    { key: "tools", label: "Tool calls", num: true, value: (a) => a.tool_calls, cell: (a) => fmt.int(a.tool_calls) },
    { key: "rate", label: "Error rate", num: true, value: (a) => (a.tool_calls ? a.tool_errors / a.tool_calls : null), cell: (a) => fmt.pct(a.tool_calls ? a.tool_errors / a.tool_calls : null) },
    { key: "peak", label: "Peak context", num: true, value: (a) => a.peak_context, cell: (a) => fmt.tokens(a.peak_context) },
    { key: "compactions", label: "Compactions", num: true, value: (a) => a.compactions },
    { key: "failed", label: "Not completed", num: true, value: (a) => a.not_completed },
  ];
  const kp = h("div", { class: "kpis" },
    kpi("Subagents started", fmt.int(total), `${ag.length} types`),
    kpi("Per run", fmt.num(total / Math.max(1, runs.length), 1), `most in one run: ${fmt.int(Math.max(0, ...perRun.map((r) => r.n)))}`),
    kpi("In the background", fmt.pct(background / Math.max(1, total)), `${fmt.int(background)} of ${fmt.int(total)}`),
    kpi("Subagent spend", fmt.usd(sumOf(ag, (a) => a.cost)), `${fmt.usd(sumOf(ag, (a) => a.cost) / Math.max(1, total))} each`),
    kpi("Completed", fmt.pct(done / Math.max(1, sumOf(status, (s) => s.agents))), status.filter((s) => s.status !== "completed").map((s) => `${fmt.int(s.agents)} ${human(s.status).toLowerCase()}`).join(" · ") || "all of them"));

  const overview = () => h("div", { class: "charts" },
    h("div", { class: "grid" },
      barChart({ title: "Spend by agent type", items: ag.map((a) => ({ label: a.agent_type, name: a.agent_type, value: a.cost || 0 })), ns: "agent", fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Agent type" }),
      status.length > 2
        ? barChart({ title: "How subagents ended", items: status.map((s) => ({ label: human(s.status), value: s.agents })), fmt: countFmt, valueTitle: "Subagents", share: true, labelTitle: "Status" })
        : h("figure", { class: "card stat-card" }, h("figcaption", { class: "cardtitle" }, "How subagents ended"),
          h("div", { class: "kpis" }, status.map((s) => kpi(human(s.status), fmt.int(s.agents), fmt.pct(s.agents / Math.max(1, total))))))),
    h("div", { class: "grid" },
      barChart({ title: "Tool calls by agent type", items: ag.map((a) => ({ label: a.agent_type, name: a.agent_type, value: a.tool_calls })), ns: "agent", fmt: countFmt, tickFmt: fmt.compact, valueTitle: "Tool calls", labelTitle: "Agent type" }),
      barChart({ title: "Largest context reached", items: ag.map((a) => ({ label: a.agent_type, name: a.agent_type, value: a.peak_context })), ns: "agent", fmt: fmt.tokens, tickFmt: fmt.compact, valueTitle: "Tokens", labelTitle: "Agent type" })),
    sortTable({ caption: "Agent types", cols, rows: ag, sort: { key: "cost", dir: -1 }, csvName: "agent-types" }).el);

  const runDay = new Map(runs.map((r) => [r.run, (r.started || "").slice(0, 10)]));
  const days = new Map();
  for (const x of byRun) {
    const day = runDay.get(x.run);
    if (!day) continue;
    const d = days.get(day) || { day, parts: {} };
    d.parts[x.agent_type] = (d.parts[x.agent_type] || 0) + x.n;
    days.set(day, d);
  }
  const shape = (D.agent_shape || []).map((x) => ({ label: `depth ${x.depth} · ${x.background ? "in the background" : "waited for"}`, value: x.n }));
  const skillRows = groupSum(D.agents_by_skill || [], "skill", "n");
  const maxAS = Math.max(1, ...(D.agents_by_skill || []).map((x) => x.n));
  const generated = () => h("div", { class: "charts" },
    dayColumns({ title: "Subagents started per day, by type", sub: "counted on the day their run started", days: [...days.values()], series: typeSeries, fmt: countFmt, tickFmt: fmt.compact, yTitle: "Subagents", whole: true }),
    h("div", { class: "grid" },
      barChart({ title: "How they were started", items: shape, fmt: countFmt, valueTitle: "Subagents", labelTitle: "How", sort: false,
        notes: "Depth 1 was started by the main session, depth 2 by a subagent." }),
      heatmap({ title: "Subagents started by each skill", sub: "the skill running when each subagent started",
        rows: skillRows.map((k) => ({ key: k.label, label: human(k.label) })), cols: types.map((t) => ({ key: t, label: t })), rowTitle: "Skill", scale: "seq",
        cell: (r, c) => {
          const n = sumOf((D.agents_by_skill || []).filter((x) => x.skill === r.key && x.agent_type === c.key), (x) => x.n);
          return n ? { t: n / maxAS, raw: n, text: fmt.int(n), tip: [["Subagents", fmt.int(n)]] } : null;
        },
        legendText: ["fewer", "more"] })));

  const roles = D.agent_roles || [];
  const times = D.agent_time || [];
  const roleCols = [
    { key: "type", label: "Agent type", value: (r) => r.agent_type },
    { key: "role", label: "Role", value: (r) => r.role, cell: (r) => h("span", { class: "task", title: r.role }, r.role) },
    { key: "agents", label: "Agents", num: true, value: (r) => r.agents },
    { key: "cost", label: "Cost", num: true, value: (r) => r.cost, cell: (r) => fmt.usd(r.cost) },
    { key: "time", label: "Average time", num: true, value: (r) => r.avg_seconds, cell: (r) => fmt.secs(r.avg_seconds) },
    { key: "tools", label: "Average tool calls", num: true, value: (r) => r.avg_tools, cell: (r) => fmt.num(r.avg_tools, 0) },
    { key: "peak", label: "Peak context", num: true, value: (r) => r.peak_context, cell: (r) => fmt.tokens(r.peak_context) },
  ];
  const rolesTab = () => h("div", { class: "charts" },
    h("div", { class: "grid" },
      barChart({ title: "Spend by role", sub: "the twelve roles that spent the most", items: roles.slice(0, 12).map((r) => ({ label: r.role, value: r.cost || 0, rows: [["Agent type", r.agent_type], ["Agents", fmt.int(r.agents)]] })),
        fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", labelTitle: "Role" }),
      barChart({ title: "How long subagents run", sub: "bar = the slowest 5% · label = median and slowest 5%",
        items: times.map((t) => ({ label: t.agent_type, name: t.agent_type, value: t.p95_s, text: `median ${fmt.secs(t.median_s)} · slowest 5% ${fmt.secs(t.p95_s)}`, rows: [["Median", fmt.secs(t.median_s)], ["Average", fmt.secs(t.avg_s)]] })),
        ns: "agent", fmt: fmt.secs, valueTitle: "Slowest 5% of runs", labelTitle: "Agent type" })),
    sortTable({ caption: "Roles", cols: roleCols, rows: roles, sort: { key: "cost", dir: -1 }, csvName: "agent-roles-detail" }).el);

  const am = D.agent_models || [];
  const modelNames = [...new Set(am.map((x) => x.model))];
  const maxAM = Math.max(1e-9, ...am.map((x) => x.cost || 0));
  const modelsTab = () => h("div", { class: "charts" },
    stackChart({ title: "Which model each agent type uses", sub: "share of each type's subagents", mode: "share",
      series: modelNames.map((m) => ({ key: m, label: human(m), css: colourOf("model", m).css })),
      rows: types.map((t) => ({ label: t, parts: Object.fromEntries(modelNames.map((m) => [m, sumOf(am.filter((x) => x.agent_type === t && x.model === m), (x) => x.n)])) })),
      fmt: (v) => `${fmt.int(v)} agents`, labelTitle: "Agent type" }),
    heatmap({ title: "Spend by agent type and model", rows: types.map((t) => ({ key: t, label: t })), cols: modelNames.map((m) => ({ key: m, label: human(m) })), rowTitle: "Agent type", scale: "seq",
      cell: (r, c) => {
        const v = sumOf(am.filter((x) => x.agent_type === r.key && x.model === c.key), (x) => x.cost);
        return v ? { t: v / maxAM, raw: v, text: fmt.usdTick(v), tip: [["Spend", fmt.usd(v)]] } : null;
      },
      legendText: ["less spend", "more spend"] }));

  const loaded = D.agent_skills || [];
  const loadedCols = [
    { key: "skill", label: "Skill", value: (r) => r.skill },
    { key: "type", label: "Agent type", value: (r) => r.agent_type },
    { key: "loads", label: "Loads", num: true, value: (r) => r.loads },
    { key: "agents", label: "Subagents", num: true, value: (r) => r.agents },
    { key: "cost", label: "Cost of those subagents", num: true, value: (r) => r.cost, cell: (r) => fmt.usd(r.cost) },
  ];
  const loadedTab = () => (loaded.length
    ? h("div", { class: "charts" },
      barChart({ title: "Skills loaded inside subagents", items: loaded.slice(0, 12).map((r) => ({ label: `${r.skill} · ${r.agent_type}`, value: r.loads })), fmt: countFmt, valueTitle: "Loads", labelTitle: "Skill · agent type",
        notes: "A skill a subagent loads for itself is counted under the skill that started the subagent, so it has no score or versions of its own. It is listed here instead." }),
      sortTable({ caption: "Skills loaded by subagents", cols: loadedCols, rows: loaded, sort: { key: "loads", dir: -1 }, csvName: "skills-in-subagents" }).el)
    : h("div", { class: "charts" }, note("No subagent loaded a skill for itself.")));

  return h("div", {}, kp, tabs("Subagent detail", [
    { id: "overview", label: "Overview", build: overview },
    { id: "generated", label: "Started", build: generated },
    { id: "roles", label: "Roles and time", build: rolesTab },
    { id: "models", label: "Models", build: modelsTab },
    { id: "skills", label: "Skills inside", build: loadedTab },
  ], { param: "sub" }));
}

function diagFlow(D) {
  const flow = D.flow || [];
  const names = [...new Set(flow.flatMap((f) => [f.source, f.target]))];
  const weight = (n) => sumOf(flow.filter((f) => f.source === n || f.target === n), (f) => f.transitions);
  names.sort((a, b) => weight(b) - weight(a));
  const axis = names.slice(0, 10).map((n) => ({ key: n, label: human(n) }));
  const maxT = Math.max(1, ...flow.map((f) => f.transitions));
  const marks = new Map();
  for (const m of D.markers || []) {
    const e = marks.get(m.marker) || { label: human(m.marker), parts: { ok: 0, bad: 0 } };
    e.parts[m.bad ? "bad" : "ok"] += m.n;
    marks.set(m.marker, e);
  }
  const labels = D.labels || [];
  return h("div", { class: "charts" },
    heatmap({ title: "Which skill hands over to which", sub: "row = the skill that was running · column = the skill that took over, in the main session",
      rows: axis, cols: axis, rowTitle: "From", scale: "seq",
      cell: (r, c) => {
        const n = sumOf(flow.filter((f) => f.source === r.key && f.target === c.key), (f) => f.transitions);
        return n ? { t: n / maxT, raw: n, text: fmt.int(n), tip: [["Hand-overs", fmt.int(n)]] } : null;
      },
      legendText: ["fewer hand-overs", "more"] }),
    h("div", { class: "grid" },
      marks.size
        ? stackChart({ title: "Checks from your config", sub: "count of each marker's values", mode: "abs",
          series: [{ key: "ok", label: `${TONE.better.icon} ok value`, css: TONE.better.css }, { key: "bad", label: `${TONE.worse.icon} bad value`, css: TONE.worse.css }],
          rows: [...marks.values()], fmt: countFmt, valueTitle: "Values seen", labelTitle: "Marker" })
        : emptyCard("Checks from your config", "Your config defines no markers, or none matched."),
      labels.length
        ? barChart({ title: "Incidents by failure category", items: labels.map((l) => ({ label: human(l.category), value: l.n })), fmt: countFmt, valueTitle: "Incidents", share: true, labelTitle: "Category" })
        : emptyCard("Incidents by failure category", "No incident has a label yet. Run runlens classify to label them.")));
}
