/* pages/diagnostics.js: everything else the database records (#/diagnostics?tab=…&sub=…).

   Every chart here is summed from the per-run facts in the page, so the filter bar scopes it like the rest.
   Comparisons between skills, tools or models use rates (per run, per 100 calls), not raw counts, so the
   busiest one does not look the worst just for being busy. Times sit on a real time axis. */

const EFFORT_ORDER = ["(default)", "none", "minimal", "low", "medium", "high", "xhigh", "max"];
const effortRank = (e) => {
  const i = EFFORT_ORDER.indexOf(String(e).toLowerCase());
  return i < 0 ? EFFORT_ORDER.length : i;
};
const countFmt = (v) => fmt.int(v);
const per100 = (v) => `${fmt.num(v, v < 10 ? 1 : 0)} per 100`;
// Sum rows into groups: key(row) -> {label, ...sums of the fields}.
function rollup(rows, key, fields) {
  const m = new Map();
  for (const r of rows) {
    const k = key(r);
    const e = m.get(k) || Object.fromEntries([["label", k], ...fields.map((f) => [f, 0])]);
    for (const f of fields) e[f] += r[f] || 0;
    m.set(k, e);
  }
  return [...m.values()];
}
const absTime = (x) => atRun(x.run, x.t);

function diagnosticsPage() {
  const head = h("header", { class: "pagehead" },
    h("h1", { tabindex: "-1" }, "Diagnostics"),
    h("p", { class: "lede" }, "The rest of what runlens recorded, for the runs in the filters: the problems they hit, their tools and models, their subagents, and how skills hand work to each other."));
  if (!EX.runs.length) return h("article", { class: "page" }, head, empty("Run runlens dashboard again to add this page."));
  if (!RUNSET.size) return h("article", { class: "page" }, head, emptyFiltered());
  return h("article", { class: "page" }, head,
    tabs("Diagnostics", [
      { id: "problems", label: "Problems", build: () => diagProblems() },
      { id: "tools", label: "Tools", build: () => diagTools() },
      { id: "models", label: "Models", build: () => diagModels() },
      { id: "agents", label: "Agents", build: () => diagAgents() },
      { id: "flow", label: "Flow and checks", build: () => diagFlow() },
    ], { param: "tab" }));
}

function diagProblems() {
  const inc = slice(EX.incidents).filter((i) => !i.policy);
  const policy = slice(EX.incidents).filter((i) => i.policy);
  const errs = slice(EX.errors);
  const tools = slice(EX.tools);
  const callsBySkill = new Map(rollup(tools, (t) => t.skill, ["calls"]).map((x) => [x.label, x.calls]));
  const callsByTool = new Map(rollup(tools, (t) => t.tool, ["calls"]).map((x) => [x.label, x.calls]));
  const types = rollup(inc, (i) => i.type, ["one"]).map((x) => ({ ...x, n: inc.filter((i) => i.type === x.label).length })).sort((a, b) => b.n - a.n);
  const skills = [...new Set(inc.map((i) => i.skill))].map((s) => ({ s, n: inc.filter((i) => i.skill === s).length })).sort((a, b) => b.n - a.n).slice(0, 10).map((x) => x.s);
  const classes = rollup(errs, (e) => e.class, ["n"]).sort((a, b) => b.n - a.n);
  const errTools = rollup(errs, (e) => e.tool, ["n"]).filter((t) => (callsByTool.get(t.label) || 0) >= 20).sort((a, b) => b.n - a.n).slice(0, 10);
  const incAt = (type, skill) => inc.filter((i) => i.type === type && i.skill === skill).length;
  const errAt = (cls, tool) => sumOf(errs.filter((e) => e.class === cls && e.tool === tool), (e) => e.n);
  const rate100 = (skill) => (callsBySkill.get(skill) ? (100 * inc.filter((i) => i.skill === skill).length) / callsBySkill.get(skill) : null);
  const maxRate = Math.max(1e-9, ...types.flatMap((t) => skills.map((s) => (callsBySkill.get(s) ? (100 * incAt(t.label, s)) / callsBySkill.get(s) : 0))));
  const maxErr = Math.max(1e-9, ...classes.flatMap((c) => errTools.map((t) => (callsByTool.get(t.label) ? (100 * errAt(c.label, t.label)) / callsByTool.get(t.label) : 0))));
  const typeList = types.map((t) => t.label);
  const comps = slice(EX.compactions);
  const events = EX.events.filter((e) => RUNSET.has(e.run) && e.kind !== "human_prompt");
  const callsAll = sumOf(tools, (t) => t.calls);
  const errN = sumOf(errs, (e) => e.n);
  const skillRates = [...callsBySkill.keys()].filter((s) => callsBySkill.get(s) >= 20 && skillShown(s)).map((s) => ({ label: human(s), value: rate100(s) })).filter((x) => x.value > 0);
  return h("div", {},
    answer(`${plural(inc.length, "problem")} in these runs, ${fmt.num((100 * inc.length) / Math.max(1, callsAll), 2)} per 100 tool calls${types[0] ? `; the most common is ${human(types[0].label).toLowerCase()} (${fmt.int(types[0].n)})` : ""}. `
      + `${plural(errN, "tool error")}${classes[0] ? `, mostly ${human(classes[0].label).toLowerCase()}` : ""}.`),
    kpiRow([
      kpi("Problems", fmt.int(inc.length), `${types.length} kinds${policy.length ? ` · ${fmt.int(policy.length)} more from permission rules, not counted` : ""}`),
      kpi("Per 100 tool calls", fmt.num((100 * inc.length) / Math.max(1, sumOf(tools, (t) => t.calls)), 2), "across the runs in the filters"),
      kpi("Tool errors", fmt.int(sumOf(errs, (e) => e.n)), `${classes.length} classes · denied calls not counted`),
      kpi("Most common problem", types[0] ? human(types[0].label) : "—", types[0] ? `${fmt.int(types[0].n)} times` : ""),
      kpi("Context compactions", fmt.int(comps.length), comps.length ? `${fmt.int(comps.filter((c) => c.trigger === "auto").length)} automatic` : "none")]),
    section({ title: "When and where problems happen", intro: "Problems are patterns that went wrong in a run: error streaks, repeated calls, idle loops, interrupts, failed subagents." },
      laneChart({
        title: "Problems over time", question: "Do problems cluster on a date, a run or a version?",
        takeaway: () => {
          const byDay = new Map();
          for (const i of inc) { const d = localDay(absTime(i)); byDay.set(d, (byDay.get(d) || 0) + 1); }
          const top = [...byDay].sort((a, b) => b[1] - a[1])[0];
          return top ? `${plural(inc.length, "problem")} on ${plural(byDay.size, "day")}; the most on ${fmt.dayKey(top[0])} (${fmt.int(top[1])}).` : null;
        },
        sub: "one dot per problem, one lane per kind · colour = the skill it happened in · dotted lines: Claude Code updates and new models",
        lanes: typeList.map((t) => ({ label: human(t), items: inc.filter((i) => i.type === t).map((i) => ({ t: absTime(i), css: i.skill === "(none)" ? "var(--other)" : colourOf("skill", i.skill).css,
          shape: colourOf("skill", i.skill).shape, href: hrefRun(i.run),
          tip: { title: human(i.type), sub: i.detail || null, rows: [["Run", i.run], ["Skill", human(i.skill)], ["When", fmt.when(isoOf(absTime(i)))], ...(i.label ? [["Label", human(i.label)]] : [])] } })) })),
        vlines: changeMarks(["cc", "model"]),
        legendItems: [...new Set(inc.map((i) => i.skill))].slice(0, 12).map((s) => ({ label: human(s), css: s === "(none)" ? "var(--other)" : colourOf("skill", s).css, shape: colourOf("skill", s).shape })),
        extraCols: [{ label: "Run", value: (r) => (r.tip ? r.tip.rows[0][1] : "") }],
        notes: "Click a dot to open its run. Problems caused by your permission rules are left out.",
      }),
      h("div", { class: "grid" },
        barChart({ title: "Problems per 100 tool calls, by skill", question: "How often does each skill hit problems for the work it does?", sub: "a rate, so a busy skill does not look worse for being busy",
          takeaway: () => (skillRates.length ? `${plural(skillRates.length, "skill")} with a rate, from ${fmt.num(Math.min(...skillRates.map((x) => x.value)), 2)} to ${fmt.num(Math.max(...skillRates.map((x) => x.value)), 2)} per 100 tool calls. Each rests on few problems, so small gaps between skills are noise.` : null),
          items: [...callsBySkill.keys()].filter((s) => callsBySkill.get(s) >= 20 && skillShown(s)).map((s) => ({ label: human(s), name: s, value: rate100(s),
            rows: [["Problems", fmt.int(inc.filter((i) => i.skill === s).length)], ["Tool calls", fmt.int(callsBySkill.get(s))]] })).filter((x) => x.value > 0),
          ns: "skill", fmt: (v) => fmt.num(v, 2), valueTitle: "Problems per 100 tool calls", labelTitle: "Skill", notes: "Skills with at least 20 tool calls." }),
        barChart({ title: "Problems by kind", question: "What goes wrong most often?", items: types.map((t) => ({ label: human(t.label), value: t.n })), fmt: countFmt, valueTitle: "Problems", share: true, labelTitle: "Kind",
          takeaway: () => shareTakeaway(types.map((t) => ({ label: human(t.label), value: t.n })), "of the problems") })),
      heatmap({
        title: "Problems per 100 tool calls, by kind and skill", question: "Which kind of problem does each skill hit?", sub: "the ten skills with most problems · darker = more per 100 tool calls",
        rows: typeList.map((t) => ({ key: t, label: human(t) })), cols: skills.map((s) => ({ key: s, label: human(s), sub: `${fmt.compact(callsBySkill.get(s) || 0)} calls` })),
        rowTitle: "Kind", scale: "seq", corner: "kind ↓ · skill →",
        cell: (r, c) => {
          const n = incAt(r.key, c.key), calls = callsBySkill.get(c.key);
          if (!n || !calls) return null;
          const rate = (100 * n) / calls;
          return { t: rate / maxRate, raw: rate, text: fmt.num(rate, 2), dim: calls < 100, tip: [["Per 100 tool calls", fmt.num(rate, 2)], ["Problems", fmt.int(n)], ["Tool calls of the skill", fmt.int(calls)]] };
        },
        legendText: ["rarer", "more frequent", "corner mark = under 100 tool calls"],
      }),
    ),
    section({ title: "How tool calls fail", intro: "Tool errors are calls that returned an error. Calls your permission rules denied are not counted." },
      h("div", { class: "grid" },
        barChart({ title: "Tool errors by class", question: "How do tool calls fail?", items: classes.map((c) => ({ label: human(c.label), value: c.n })), fmt: countFmt, valueTitle: "Tool errors", share: true, labelTitle: "Class",
          takeaway: () => shareTakeaway(classes.map((c) => ({ label: human(c.label), value: c.n })), "of the tool errors") }),
        barChart({ title: "Error rate by tool", question: "Which tool fails most often per call?", sub: "tools with at least 20 calls",
          items: [...callsByTool].filter(([, n]) => n >= 20).map(([t, n]) => ({ label: t, value: sumOf(errs.filter((e) => e.tool === t), (e) => e.n) / n,
            rows: [["Errors", `${fmt.int(sumOf(errs.filter((e) => e.tool === t), (e) => e.n))} of ${fmt.int(n)}`]] })).filter((x) => x.value > 0).slice(0, 15),
          fmt: (v) => fmt.pct(v), tickFmt: (v) => fmt.pct(v, 0), valueTitle: "Calls that failed", labelTitle: "Tool" })),
      heatmap({
        title: "Error class by tool, per 100 calls", question: "Which tool fails in which way?", sub: "errors of each class ÷ calls to that tool × 100 · tools with at least 20 calls",
        rows: classes.map((c) => ({ key: c.label, label: human(c.label) })), cols: errTools.map((t) => ({ key: t.label, label: t.label, sub: `${fmt.compact(callsByTool.get(t.label) || 0)} calls` })),
        rowTitle: "Error class", scale: "seq", corner: "error ↓ · tool →",
        cell: (r, c) => {
          const n = errAt(r.key, c.key), total = callsByTool.get(c.key);
          if (!n || !total) return null;
          const rate = (100 * n) / total;
          return { t: rate / maxErr, raw: rate, text: fmt.num(rate, rate < 10 ? 1 : 0), tip: [["Per 100 calls", per100(rate)], ["Errors", fmt.int(n)], ["Calls to the tool", fmt.int(total)]] };
        },
        legendText: ["rarer", "more frequent"],
      })),
    section({ title: "Other signals", collapsible: true, collapsed: true, intro: "Context compactions and other recorded events that are not problems." },
      comps.length ? scatterChart({
        title: "Context compactions over time", question: "Is context pressure growing, and which skills fill the context?",
        sub: "one mark per compaction · height = tokens in the context just before it",
        points: comps.map((c) => ({ x: absTime(c), y: c.pre || 0, label: c.run, css: c.trigger === "manual" ? "var(--c2)" : "var(--c1)", shape: c.trigger === "manual" ? "square" : "circle",
          href: hrefRun(c.run), tip: { title: `${human(c.trigger)} compaction · ${c.run}`, rows: [["Tokens before", fmt.compact(c.pre)], ["After", fmt.compact(c.post)], ["Skill", human(c.skill)], ["When", fmt.when(isoOf(absTime(c)))]] } })),
        x: { title: "When", time: true }, y: { title: "Tokens before the compaction", fmt: fmt.compact }, labelTitle: "Run",
        legendItems: [{ label: "automatic", css: "var(--c1)", kind: "dot" }, { label: "you asked (manual)", css: "var(--c2)", shape: "square" }],
        takeaway: `${plural(comps.length, "compaction")}, ${fmt.int(comps.filter((c) => c.trigger === "auto").length)} automatic; the context held up to ${fmt.compact(Math.max(...comps.map((c) => c.pre || 0)))} tokens before one.`,
      }) : emptyCard("Context compactions over time", "No context compaction in these runs."),
      barChart({ title: "Other events", question: "What else happened that is not a problem?", items: rollup(events, (e) => e.kind, ["one"]).map((x) => ({ label: human(x.label), value: events.filter((e) => e.kind === x.label).length })),
        fmt: countFmt, valueTitle: "Events", labelTitle: "Event" })));
}

function diagTools() {
  const tools = rollup(slice(EX.tools), (t) => t.tool, ["calls", "errors", "denied", "ms"]).sort((a, b) => b.calls - a.calls);
  if (!tools.length) return empty("No tool call in these runs.");
  const bins = new Map();
  for (const d of EX.durations.filter((x) => RUNSET.has(x.run))) {
    const b = bins.get(d.tool) || new Array(EX.duration_edges.length + 1).fill(0);
    d.bins.forEach((c, i) => { b[i] += c; });
    bins.set(d.tool, b);
  }
  const cols = [
    { key: "tool", label: "Tool", value: (t) => t.label },
    { key: "calls", label: "Calls", num: true, value: (t) => t.calls, cell: (t) => fmt.int(t.calls) },
    { key: "errors", label: "Errors", num: true, value: (t) => t.errors, cell: (t) => fmt.int(t.errors) },
    { key: "rate", label: "Error rate", num: true, value: (t) => (t.calls ? t.errors / t.calls : null), cell: (t) => fmt.pct(t.calls ? t.errors / t.calls : null) },
    { key: "denied", label: "Denied", num: true, value: (t) => t.denied, more: true },
    { key: "avg", label: "Average call", num: true, value: (t) => (t.calls ? t.ms / t.calls : null), cell: (t) => fmt.ms(t.calls ? t.ms / t.calls : null) },
    { key: "total", label: "Total time", num: true, value: (t) => t.ms, cell: (t) => fmt.ms(t.ms) },
  ];
  const top = tools.slice(0, 12);
  const slowest = [...tools].filter((t) => t.calls >= 20 && t.ms).sort((a, b) => b.ms / b.calls - a.ms / a.calls)[0];
  return h("div", {},
    answer(`${fmt.int(sumOf(tools, (t) => t.calls))} tool calls to ${plural(tools.length, "tool")}; ${tools[0].label} does most of the work (${fmt.pct(tools[0].calls / Math.max(1, sumOf(tools, (t) => t.calls)), 0)} of calls)${slowest ? `, and ${slowest.label} is the slowest on average (${fmt.ms(slowest.ms / slowest.calls)} a call)` : ""}.`),
    kpiRow([
      kpi("Tool calls", fmt.int(sumOf(tools, (t) => t.calls)), `${tools.length} tools`),
      kpi("Failed", fmt.pct(sumOf(tools, (t) => t.errors) / Math.max(1, sumOf(tools, (t) => t.calls))), "share of calls, denied ones not counted"),
      kpi("Denied", fmt.int(sumOf(tools, (t) => t.denied)), "by your permission rules or by you"),
      kpi("Time in tools", fmt.ms(sumOf(tools, (t) => t.ms)), "all runs in the filters")]),
    h("div", { class: "charts" },
      histRows({ title: "How long a call takes, by tool", question: "Which tool is slow, and how much does it vary?",
        takeaway: slowest ? `${slowest.label} takes ${fmt.ms(slowest.ms / slowest.calls)} a call on average; the black tick on each row is its median band.` : null,
        sub: "one row per tool; each column is a duration band, faster on the left · taller column = more of that tool's calls · the twelve most used tools",
        rows: top.filter((t) => bins.has(t.label)).map((t) => ({ label: t.label, bins: bins.get(t.label), n: bins.get(t.label).reduce((a, b) => a + b, 0) })), edges: EX.duration_edges,
        notes: "Bands are half a decade wide (10 ms, 32 ms, 100 ms, …), so a slow tail shows even when most calls are fast." }),
      h("div", { class: "grid" },
        barChart({ title: "Calls by tool", question: "Which tools does the work lean on?", sub: "the twelve most used", items: top.map((t) => ({ label: t.label, value: t.calls })), fmt: countFmt, tickFmt: fmt.compact, valueTitle: "Calls", share: true, labelTitle: "Tool",
          takeaway: () => shareTakeaway(tools.map((t) => ({ label: t.label, value: t.calls })), "of the calls") }),
        barChart({ title: "Where tool time goes", question: "Which tools does the waiting come from?", sub: "total time spent in each tool", items: tools.map((t) => ({ label: t.label, value: t.ms || 0 })).filter((t) => t.value > 0).slice(0, 12),
          takeaway: () => shareTakeaway(tools.map((t) => ({ label: t.label, value: t.ms || 0 })), "of the time in tools"),
          fmt: fmt.ms, valueTitle: "Total time", share: true, labelTitle: "Tool" })),
      section({ title: "Every tool", count: plural(tools.length, "tool") }, sortTable({ caption: "Tools", cols, rows: tools, sort: { key: "calls", dir: -1 }, csvName: "tools" }).el)));
}

function diagModels() {
  const calls = slice(EX.calls);
  const ms = rollup(calls, (c) => c.model, ["calls", "cost", "input", "cw5", "cw1", "cread", "output", "thinking", "think_ms", "errors", "limits", "unpriced"]).sort((a, b) => b.cost - a.cost);
  if (!ms.length) return empty("No model call in these runs.");
  const hit = (m) => m.cread / Math.max(1, m.cread + m.input + m.cw5 + m.cw1);
  const cols = [
    { key: "model", label: "Model", value: (m) => m.label },
    { key: "calls", label: "Calls", num: true, value: (m) => m.calls, cell: (m) => fmt.int(m.calls) },
    { key: "cost", label: "Cost", num: true, value: (m) => m.cost, cell: (m) => fmt.usd(m.cost) },
    { key: "per", label: "Cost per call", num: true, value: (m) => m.cost / Math.max(1, m.calls), cell: (m) => fmt.usd(m.cost / Math.max(1, m.calls)) },
    { key: "output", label: "Output tokens (transcript, undercount)", num: true, value: (m) => m.output, cell: (m) => fmt.compact(m.output) },
    { key: "cache", label: "Cache hit", num: true, value: hit, cell: (m) => fmt.pct(hit(m)) },
    { key: "errors", label: "API errors", num: true, value: (m) => m.errors },
    { key: "limits", label: "Limits hit", num: true, value: (m) => m.limits, more: true },
    { key: "unpriced", label: "Calls without a price", num: true, value: (m) => m.unpriced, more: true },
  ];
  const spendM = sumOf(ms, (m) => m.cost);
  const kp = h("div", {},
    answer(`${fmt.usd(spendM)} across ${plural(ms.length, "model")}; ${ms[0].label} takes ${fmt.pct(ms[0].cost / Math.max(1e-9, spendM), 0)} of it. ${fmt.pct(sumOf(ms, (m) => m.cread) / Math.max(1, sumOf(ms, (m) => m.cread + m.input + m.cw5 + m.cw1)), 0)} of the input was read from the cache.`),
    kpiRow([
      kpi("Model spend", fmt.usd(spendM), `${ms.length} models`),
      kpi("API calls", fmt.int(sumOf(ms, (m) => m.calls)), "model turns"),
      kpi("Cache hit", fmt.pct(sumOf(ms, (m) => m.cread) / Math.max(1, sumOf(ms, (m) => m.cread + m.input + m.cw5 + m.cw1))), "of input read from the cache"),
      kpi("API errors", fmt.int(sumOf(ms, (m) => m.errors)), `${fmt.int(sumOf(ms, (m) => m.limits))} limits hit, which are not errors`)]));

  const efforts = [...new Set(calls.map((c) => c.effort))].sort((a, b) => effortRank(a) - effortRank(b));
  const effortCss = (e) => ordinalCss(efforts.indexOf(e), efforts.length);
  const metric = ["per", "cost", "calls", "output", "thinking"].includes(param("me")) ? param("me") : "per";
  const metricSel = h("select", { "aria-label": "Measure" }, [["per", "Cost per call"], ["cost", "Spend"], ["calls", "Calls"], ["output", "Output tokens per call"], ["thinking", "Thinking time per call"]]
    .map(([v, t]) => h("option", { value: v, selected: v === metric ? true : null }, t)));
  metricSel.addEventListener("change", () => refreshAfter({ me: metricSel.value === "per" ? null : metricSel.value }));
  const cellVal = (x) => (!x || !x.calls ? null : { per: x.cost / x.calls, cost: x.cost, calls: x.calls, output: x.output / x.calls, thinking: x.think_ms / x.calls }[metric]);
  const cellFmt = { per: fmt.usd, cost: fmt.usdTick, calls: fmt.compact, output: (v) => fmt.num(v, 0), thinking: fmt.ms }[metric];
  const me = rollup(calls, (c) => `${c.model}|${c.effort}`, ["calls", "cost", "output", "think_ms"]);
  const meOf = (m, e) => me.find((x) => x.label === `${m}|${e}`);
  const maxMe = Math.max(1e-9, ...me.map(cellVal).filter(valid));
  const effortTab = () => h("div", { class: "charts" },
    heatmap({ title: "Model by effort level", question: "Is a higher effort worth what it costs?", sub: "darker = more · effort in its natural order, lowest on the left", corner: "model ↓ · effort →",
      takeaway: () => {
        const cells = me.map((x) => ({ x, v: cellVal(x) })).filter((c) => valid(c.v)).sort((a, b) => b.v - a.v);
        if (!cells.length) return null;
        const [m, e] = cells[0].x.label.split("|");
        return `Highest ${metricSel.selectedOptions[0] ? metricSel.selectedOptions[0].textContent.toLowerCase() : "value"}: ${m} at ${human(e).toLowerCase()} effort (${cellFmt(cells[0].v)}).`;
      },
      controls: metricSel,
      rows: ms.map((m) => ({ key: m.label, label: m.label })), cols: efforts.map((e) => ({ key: e, label: human(e) })), rowTitle: "Model", scale: "seq",
      cell: (r, c) => {
        const x = meOf(r.key, c.key);
        const v = cellVal(x);
        if (!valid(v)) return null;
        return { t: v / maxMe, raw: v, text: cellFmt(v), dim: x.calls < 20,
          tip: [["Calls", fmt.int(x.calls)], ["Spend", fmt.usd(x.cost)], ["Cost per call", fmt.usd(x.cost / x.calls)], ["Output tokens per call", fmt.num(x.output / x.calls, 0)], ["Thinking time per call", fmt.ms(x.think_ms / x.calls)]] };
      },
      legendText: ["less", "more", "corner mark = under 20 calls"],
      notes: "Output tokens are those the transcript shows, a lower bound of what Claude Code counted." }),
    h("div", { class: "grid" },
      barChart({ title: "Spend by effort level", question: "How much of the spend runs at each effort?", items: efforts.map((e) => ({ label: human(e), value: sumOf(calls.filter((c) => c.effort === e), (c) => c.cost), css: effortCss(e) })),
        takeaway: () => shareTakeaway(efforts.map((e) => ({ label: `${human(e).toLowerCase()} effort`, value: sumOf(calls.filter((c) => c.effort === e), (c) => c.cost) })), "of the spend"),
        sort: false, fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Effort" }),
      stackChart({ title: "Effort level used by each model", question: "Which models run at which effort?", sub: "share of each model's calls", mode: "share",
        series: efforts.map((e) => ({ key: e, label: human(e), css: effortCss(e) })),
        rows: ms.map((m) => ({ label: m.label, parts: Object.fromEntries(efforts.map((e) => [e, (meOf(m.label, e) || {}).calls || 0])) })), fmt: (v) => `${fmt.int(v)} calls`, labelTitle: "Model" })));

  const modelSeries = ms.map((m) => ({ key: m.label, label: m.label, css: colourOf("model", m.label).css }));
  const days = slice(EX.days);
  const dayParts = (val) => [...new Set(days.map((d) => d.day))].map((day) => ({ day, parts: Object.fromEntries(rollup(days.filter((x) => x.day === day), (x) => x.model, [val]).map((x) => [x.label, x[val]])) }));
  const timeTab = () => h("div", { class: "charts" },
    dayColumns({ title: "Spend per day, by model", question: "Which models does the money go to, day by day?", days: dayParts("cost"), series: modelSeries, fmt: fmt.usd, tickFmt: fmt.usdTick, yTitle: "Spend, US$",
      takeaway: () => peakDayTakeaway(dayParts("cost"), fmt.usd, "spend") }),
    dayColumns({ title: "API calls per day, by model", question: "How busy was each model, day by day?", days: dayParts("calls"), series: modelSeries, fmt: countFmt, tickFmt: fmt.compact, yTitle: "API calls", whole: true,
      takeaway: () => peakDayTakeaway(dayParts("calls"), fmt.int, "number of calls") }));

  const stops = slice(EX.stops);
  const stopKinds = [...new Set(stops.map((s) => s.stop))].sort((a, b) => sumOf(stops.filter((s) => s.stop === b), (s) => s.n) - sumOf(stops.filter((s) => s.stop === a), (s) => s.n));
  const stopCss = { end_turn: "var(--c1)", tool_use: "var(--c3)", max_tokens: "var(--c8)", refusal: "var(--c5)", pause_turn: "var(--c4)", stop_sequence: "var(--c7)", "(not recorded)": "var(--other)" };
  const apierr = slice(EX.apierr);
  const errKinds = [...new Set(apierr.map((e) => `${e.limit ? "limit" : "error"}|${e.kind}`))];
  const callsTab = () => h("div", { class: "charts" },
    tokenCostChart("model"),
    stackChart({ title: "Why each model turn stopped", question: "Do turns get cut off by the token limit, or refused?", sub: "share of each model's turns by stop reason", mode: "share",
      takeaway: () => shareTakeaway(stopKinds.map((k) => ({ label: human(k), value: sumOf(stops.filter((s) => s.stop === k), (s) => s.n) })), "of the turns", "Most turns stop on"),
      series: stopKinds.map((k, i) => ({ key: k, label: human(k), css: stopCss[k] || `var(--c${(i % 8) + 1})` })),
      rows: ms.map((m) => ({ label: m.label, parts: Object.fromEntries(stopKinds.map((k) => [k, sumOf(stops.filter((s) => s.model === m.label && s.stop === k), (s) => s.n)])) })),
      fmt: (v) => `${fmt.int(v)} turns`, labelTitle: "Model",
      notes: "Most turns have no stop reason in the transcript: Claude Code does not write the final usage record of every message." }),
    apierr.length ? stackChart({ title: "API errors and limits, by model", question: "Did the API fail, or did I hit a limit?", sub: "limits (quota, rate) are the account's, not the work's fault",
      series: errKinds.map((k, i) => ({ key: k, label: `${k.startsWith("limit") ? "limit" : "error"}: ${human(k.split("|")[1])}`, css: k.startsWith("limit") ? `var(--o${Math.min(4, i + 2)})` : TONE.worse.css })),
      rows: ms.map((m) => ({ label: m.label, parts: Object.fromEntries(errKinds.map((k) => [k, sumOf(apierr.filter((e) => e.model === m.label && `${e.limit ? "limit" : "error"}|${e.kind}` === k), (e) => e.n)])) })),
      mode: "abs", fmt: countFmt, valueTitle: "Turns", labelTitle: "Model" }) : statCard("API errors and limits", "Turns that failed or hit a limit", "0", "none in these runs"),
    barChart({ title: "Cache hit rate", question: "How much input does each model read from the cache?", sub: "share of input tokens read from the cache (transcript)", items: ms.map((m) => ({ label: m.label, name: m.label, value: hit(m) })), ns: "model",
      takeaway: () => { const b = [...ms].sort((a, c) => hit(c) - hit(a)); return b.length > 1 ? `From ${fmt.pct(hit(b[b.length - 1]), 0)} (${b[b.length - 1].label}) to ${fmt.pct(hit(b[0]), 0)} (${b[0].label}).` : null; },
      fmt: (v) => fmt.pct(v), tickFmt: (v) => fmt.pct(v, 0), valueTitle: "Input read from the cache", labelTitle: "Model" }));

  const spendTab = () => h("div", { class: "charts" },
    h("div", { class: "grid" },
      barChart({ title: "Spend by model", question: "Which models cost the most?", items: ms.map((m) => ({ label: m.label, name: m.label, value: m.cost || 0 })), ns: "model", fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Model",
        takeaway: () => shareTakeaway(ms.map((m) => ({ label: m.label, value: m.cost || 0 })), "of the spend") }),
      barChart({ title: "Calls by model", question: "Which models do most of the turns?", items: ms.map((m) => ({ label: m.label, name: m.label, value: m.calls })), ns: "model", fmt: countFmt, tickFmt: fmt.compact, valueTitle: "API calls", share: true, labelTitle: "Model",
        takeaway: () => shareTakeaway(ms.map((m) => ({ label: m.label, value: m.calls })), "of the calls") })),
    section({ title: "Every model", count: plural(ms.length, "model") }, sortTable({ caption: "Models", cols, rows: ms, sort: { key: "cost", dir: -1 }, csvName: "models" }).el));

  return h("div", {}, kp, tabs("Model detail", [
    { id: "spend", label: "Spend", build: spendTab },
    { id: "effort", label: "Effort", build: effortTab },
    { id: "tokens", label: "Tokens and stops", build: callsTab },
    { id: "time", label: "Over time", build: timeTab },
  ], { param: "sub" }));
}

function diagAgents() {
  const all = EX.agents.filter((a) => RUNSET.has(a.run) && a.i !== 0 && (!F.sets.model || !a.model || F.sets.model.has(a.model)));
  if (!all.length) return empty("No subagent in these runs.");
  const types = rollup(all.map((a) => ({ ...a, one: 1 })), (a) => a.type, ["one", "cost", "tools", "errors"]).sort((a, b) => b.cost - a.cost);
  const dur = (a) => (valid(a.t1) && valid(a.t0) ? (a.t1 - a.t0) * 1000 : null);
  const edges = EX.duration_edges.length ? EX.duration_edges : [10, 31.6, 100, 316, 1000, 3162, 10000, 31623, 1e5, 3.16e5, 1e6];
  const binOf = (ms) => { for (let i = 0; i < edges.length; i += 1) if (ms < edges[i]) return i; return edges.length; };
  const durBins = types.map((t) => {
    const b = new Array(edges.length + 1).fill(0);
    for (const a of all.filter((x) => x.type === t.label)) if (valid(dur(a))) b[binOf(dur(a))] += 1;
    return { label: t.label, bins: b, n: b.reduce((p, q) => p + q, 0), css: colourOf("agent", t.label).css };
  });
  const runsN = new Set(all.map((a) => a.run)).size;
  const bg = all.filter((a) => a.bg).length;
  const notDone = all.filter((a) => a.status && !["completed", "async_launched", "running"].includes(a.status)).length;
  const daysMap = new Map();
  for (const a of all) {
    const day = localDay(atRun(a.run, a.t0 ?? 0));
    const d = daysMap.get(day) || { day, parts: {} };
    d.parts[a.type] = (d.parts[a.type] || 0) + 1;
    daysMap.set(day, d);
  }
  const typeSeries = types.map((t) => ({ key: t.label, label: t.label, css: colourOf("agent", t.label).css }));
  const roles = rollup(all.map((a) => ({ ...a, one: 1 })), (a) => `${a.type} · ${a.role || "—"}`, ["one", "cost"]).sort((a, b) => b.cost - a.cost);
  const models = [...new Set(all.map((a) => a.model || "?"))];
  const shapes = rollup(all.map((a) => ({ ...a, one: 1 })), (a) => `depth ${a.depth ?? "?"} · ${a.bg ? "in the background" : "waited for"}`, ["one"]);
  const cols = [
    { key: "type", label: "Agent type", value: (a) => a.label },
    { key: "agents", label: "Agents", num: true, value: (a) => a.one, cell: (a) => fmt.int(a.one) },
    { key: "cost", label: "Cost", num: true, value: (a) => a.cost, cell: (a) => fmt.usd(a.cost) },
    { key: "per", label: "Cost each", num: true, value: (a) => a.cost / Math.max(1, a.one), cell: (a) => fmt.usd(a.cost / Math.max(1, a.one)) },
    { key: "tools", label: "Tool calls", num: true, value: (a) => a.tools, cell: (a) => fmt.int(a.tools) },
    { key: "rate", label: "Error rate", num: true, value: (a) => (a.tools ? a.errors / a.tools : null), cell: (a) => fmt.pct(a.tools ? a.errors / a.tools : null) },
  ];
  return h("div", {},
    answer(`${plural(all.length, "subagent")} of ${plural(types.length, "type")}, about ${fmt.num(all.length / Math.max(1, runsN), 1)} per run that used any; they spent ${fmt.usd(sumOf(all, (a) => a.cost))}, most of it on ${types[0].label} (${fmt.pct(types[0].cost / Math.max(1e-9, sumOf(all, (a) => a.cost)), 0)}).`),
    kpiRow([
      kpi("Subagents started", fmt.int(all.length), `${types.length} types`),
      kpi("Per run", fmt.num(all.length / Math.max(1, runsN), 1), `in ${fmt.runs(runsN)} that started any`),
      kpi("In the background", fmt.pct(bg / all.length), `${fmt.int(bg)} of ${fmt.int(all.length)}`),
      kpi("Subagent spend", fmt.usd(sumOf(all, (a) => a.cost)), `${fmt.usd(sumOf(all, (a) => a.cost) / all.length)} each`),
      kpi("Did not complete", fmt.int(notDone), `${fmt.int(all.filter((a) => a.stopped).length)} stopped by you`)]),
    section({ title: "Cost and duration by type", intro: "What each kind of subagent costs, and how long it runs." },
      h("div", { class: "grid" },
        barChart({ title: "Spend by agent type", question: "Which kind of subagent costs the most?", items: types.map((a) => ({ label: a.label, name: a.label, value: a.cost || 0, rows: [["Agents", fmt.int(a.one)]] })), ns: "agent",
          takeaway: () => shareTakeaway(types.map((a) => ({ label: a.label, value: a.cost || 0 })), "of the subagent spend"),
          fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Agent type" }),
        histRows({ title: "How long subagents run, by type", question: "Which kind of subagent runs long, and how much does it vary?", sub: "one row per type; each column is a duration band, shorter on the left · taller column = more of that type's subagents",
          rows: durBins, edges }))),
    section({ title: "Over time and in detail", intro: "How delegation changes over time, which tasks cost most, the models they run on and how they were started." },
      dayColumns({ title: "Subagents started per day, by type", question: "Is the work delegated more over time?", sub: "counted on the day they started", days: [...daysMap.values()], series: typeSeries, fmt: countFmt, tickFmt: fmt.compact, yTitle: "Subagents", whole: true }),
      h("div", { class: "grid" },
        barChart({ title: "Spend by role", question: "Which subagent tasks cost the most?", sub: "the twelve roles that spent the most", items: roles.slice(0, 12).map((r) => ({ label: r.label, value: r.cost || 0, css: colourOf("agent", r.label.split(" · ")[0]).css, rows: [["Agents", fmt.int(r.one)]] })),
          fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", labelTitle: "Role" }),
        stackChart({ title: "Which model each agent type uses", question: "Do subagents run on cheaper models?", sub: "share of each type's subagents", mode: "share",
          takeaway: () => shareTakeaway(models.map((m) => ({ label: m, value: all.filter((a) => (a.model || "?") === m).length })), "of the subagents", "Most run on"),
          series: models.map((m) => ({ key: m, label: m, css: colourOf("model", m).css })),
          rows: types.map((t) => ({ label: t.label, parts: Object.fromEntries(models.map((m) => [m, all.filter((a) => a.type === t.label && (a.model || "?") === m).length])) })),
          fmt: (v) => `${fmt.int(v)} agents`, labelTitle: "Agent type" })),
      barChart({ title: "How they were started", question: "Are subagents nested, and do they run in the background?", items: shapes.map((x) => ({ label: x.label, value: x.one })), fmt: countFmt, valueTitle: "Subagents", labelTitle: "How", sort: false,
        notes: "Depth 1 was started by the main session, depth 2 by a subagent." }),
      sortTable({ caption: "Agent types", cols, rows: types, sort: { key: "cost", dir: -1 }, csvName: "agent-types" }).el));
}

function diagFlow() {
  // Each run's sequence of skills in the main session, repeats folded: the steps of the sankey.
  const segs = EX.segments.filter((s) => RUNSET.has(s.run) && s.skill !== "(none)").sort((a, b) => (a.run < b.run ? -1 : a.run > b.run ? 1 : a.t0 - b.t0));
  const seqs = new Map();
  for (const s of segs) {
    const q = seqs.get(s.run) || [];
    if (q[q.length - 1] !== s.skill) q.push(s.skill);
    seqs.set(s.run, q);
  }
  const STEPS = 6;
  const stageCount = Array.from({ length: STEPS }, () => new Map());
  const linkMap = new Map();
  for (const q of seqs.values()) {
    const steps = q.slice(0, STEPS);
    steps.forEach((s, i) => stageCount[i].set(s, (stageCount[i].get(s) || 0) + 1));
    for (let i = 1; i < steps.length; i += 1) {
      const k = `${i - 1}|${steps[i - 1]}|${steps[i]}`;
      linkMap.set(k, (linkMap.get(k) || 0) + 1);
    }
  }
  const stages = stageCount.map((m) => [...m].sort((a, b) => b[1] - a[1]).map(([key, value]) => ({ key, label: key, value })));
  const links = [...linkMap].map(([k, value]) => {
    const [i, a, b] = k.split("|");
    return { from: [Number(i), a], to: [Number(i) + 1, b], value };
  });
  const flow = slice(EX.flow.map((f) => ({ ...f })));
  const names = [...new Set(flow.flatMap((f) => [f.source, f.target]))];
  const weight = (n) => sumOf(flow.filter((f) => f.source === n || f.target === n), (f) => f.n);
  names.sort((a, b) => weight(b) - weight(a));
  const axis = names.slice(0, 10).map((n) => ({ key: n, label: human(n) }));
  const maxT = Math.max(1, ...axis.flatMap((r) => axis.map((c) => sumOf(flow.filter((f) => f.source === r.key && f.target === c.key), (f) => f.n))));
  const markers = slice(EX.markers);
  const markerNames = [...new Set(markers.map((m) => m.marker))];
  const which = markerNames.includes(param("marker")) ? param("marker") : markerNames[0];
  const markerSel = markerNames.length > 1 ? h("select", { "aria-label": "Marker" }, markerNames.map((m) => h("option", { value: m, selected: m === which ? true : null }, human(m)))) : null;
  if (markerSel) markerSel.addEventListener("change", () => refreshAfter({ marker: markerSel.value === markerNames[0] ? null : markerSel.value }));
  const mDays = new Map();
  for (const m of markers.filter((x) => x.marker === which)) {
    const day = localDay(atRun(m.run, m.t));
    const d = mDays.get(day) || { day, parts: { ok: 0, bad: 0 } };
    d.parts[m.bad ? "bad" : "ok"] += 1;
    mDays.set(day, d);
  }
  const bySkill = rollup(markers.filter((x) => x.marker === which).map((m) => ({ ...m, ok: m.bad ? 0 : 1, badN: m.bad ? 1 : 0 })), (m) => m.skill, ["ok", "badN"]);
  const labels = rollup(slice(EX.incidents).filter((i) => i.label).map((i) => ({ ...i, one: 1 })), (i) => i.label, ["one"]).sort((a, b) => b.one - a.one);
  const okBad = [{ key: "ok", label: `${TONE.better.icon} ok value`, css: TONE.better.css }, { key: "bad", label: `${TONE.worse.icon} bad value`, css: TONE.worse.css }];
  return h("div", {},
    section({ title: "The order skills run in", intro: "How a run moves from one skill to the next in the main session." },
    sankeyChart({ title: "How runs move from skill to skill", question: "In what order do the skills run, and where does a flow stop?",
      takeaway: () => {
        const s0 = stages[0] && stages[0][0];
        const l0 = [...links].sort((a, b) => b.value - a.value)[0];
        return s0 ? `Most runs start with ${human(s0.key)} (${fmt.runs(s0.value)})${l0 ? `; the most common hand-over is ${human(l0.from[1])} → ${human(l0.to[1])} (${fmt.runs(l0.value)})` : ""}.` : null;
      },
      sub: `read left to right: each column is a step of the main session (repeats folded), the first ${STEPS} steps · each block is a skill, labelled with its name · band width = how many runs took that path`, stages, links,
      stageLabel: (i) => `step ${i + 1}`, fmt: (v) => fmt.runs(v),
      notes: "A run that used one skill only has no band. The matrix below counts every hand-over, not only the first six steps." }),
    heatmap({ title: "Which skill hands over to which", question: "Which skills follow each other most often?", sub: "row = the skill that was running · column = the skill that took over, in the main session · darker = more hand-overs",
      takeaway: () => {
        const pairs = axis.flatMap((r) => axis.map((c) => [r, c, sumOf(flow.filter((f) => f.source === r.key && f.target === c.key), (f) => f.n)])).filter((x) => x[2]).sort((a, b) => b[2] - a[2]);
        return pairs.length ? `Most often: ${pairs[0][0].label} → ${pairs[0][1].label} (${fmt.int(pairs[0][2])} times)${pairs[1] ? `, then ${pairs[1][0].label} → ${pairs[1][1].label} (${fmt.int(pairs[1][2])})` : ""}.` : null;
      },
      rows: axis, cols: axis, rowTitle: "From", scale: "seq", corner: "from ↓ · to →",
      cell: (r, c) => {
        const n = sumOf(flow.filter((f) => f.source === r.key && f.target === c.key), (f) => f.n);
        return n ? { t: n / maxT, raw: n, text: fmt.int(n), tip: [["Hand-overs", fmt.int(n)]] } : null;
      },
      legendText: ["fewer hand-overs", "more"] })),
    section({ title: "Checks from your config", intro: "The values your config's markers saw: ok or bad, by day and by skill." },
    markerNames.length
      ? h("div", { class: "grid" },
        dayColumns({ title: `${human(which)} over time`, question: "Are my checks passing more often than before?", sub: "values seen per day: ok and bad", controls: markerSel,
          takeaway: () => { const ok = sumOf([...mDays.values()], (d) => d.parts.ok), bad = sumOf([...mDays.values()], (d) => d.parts.bad); return ok + bad ? `${fmt.pct(ok / (ok + bad), 0)} of ${fmt.int(ok + bad)} values were ok.` : null; },
          days: [...mDays.values()], series: okBad, fmt: countFmt, yTitle: "Values seen", whole: true }),
        stackChart({ title: `${human(which)} by skill`, question: "Which skill's checks fail?", sub: "share of each skill's values", mode: "share",
          series: [{ key: "ok", label: okBad[0].label, css: okBad[0].css }, { key: "badN", label: okBad[1].label, css: okBad[1].css }],
          rows: bySkill.map((b) => ({ label: human(b.label), parts: { ok: b.ok, badN: b.badN } })), fmt: countFmt, labelTitle: "Skill" }))
      : emptyCard("Checks from your config", "Your config defines no markers, or none matched in these runs.")),
    section({ title: "Why things failed", intro: "Problems as the labels from runlens classify sort them." },
    labels.length
      ? barChart({ title: "Problems by failure category", question: "Why did things fail, according to the labels?", items: labels.map((l) => ({ label: human(l.label), value: l.one })), fmt: countFmt, valueTitle: "Problems", share: true, labelTitle: "Category",
        takeaway: () => shareTakeaway(labels.map((l) => ({ label: human(l.label), value: l.one })), "of the labelled problems") })
      : emptyCard("Problems by failure category", "No problem has a label yet. Run runlens classify to label them.")));
}
