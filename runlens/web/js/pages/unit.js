/* pages/unit.js: one skill, agent role or group (#/unit/<id>).

   The header names the period of every number: "All versions" and "Current version vN" are separate rows,
   so an all-time score is never shown beside a latest-version profile without saying so. */

// A score on a fixed log strip from 50 to 200: the dot, its range and the typical run at 100.
function scoreBullet(score, ci, judged) {
  const W = 150, H = 20, lo = 50, hi = 200;
  const x = (v) => 4 + ((Math.log(Math.min(hi, Math.max(lo, v))) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))) * (W - 8);
  const t = TONE[verdict(score, ci, judged).tone] || TONE.unclear;
  return svg("svg", { class: "bullet", width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": score == null ? "No score" : `Score ${fmt.score(score)}${ci ? `, likely ${fmt.interval(ci)}` : ""}, on a scale from 50 to 200 where 100 is its typical run` },
  svg("line", { class: "track", x1: 4, x2: W - 4, y1: H / 2, y2: H / 2 }),
  svg("line", { class: "ref", x1: x(100), x2: x(100), y1: 2, y2: H - 2 }),
  ci ? svg("line", { class: "range", x1: x(ci[0]), x2: x(ci[1]), y1: H / 2, y2: H / 2, style: `stroke:${t.css}` }) : null,
  score != null ? svg("circle", { class: ci ? "dot" : "dot hollow", cx: x(score), cy: H / 2, r: 5, style: ci ? `fill:${t.css}` : `stroke:${t.css}` }) : null);
}

function periodRow(title, sub, score, ci, k, tag, judged) {
  const v = verdict(score, ci, judged);
  return h("section", { class: "period", "aria-label": title },
    h("h2", { class: "period-title" }, title, h("span", { class: "muted" }, ` · ${sub}`)),
    h("div", { class: "kpis" },
      kpi("Score", fmt.score(score), tag || h("span", {}, ci ? `likely ${fmt.interval(ci)} · ` : "", toneTag(v.tone, v.word)), { extra: scoreBullet(score, ci, judged) }),
      kpi("Cost per invocation", fmt.usd(k.cost), "typical model spend"),
      kpi("Time per invocation", fmt.secs(k.seconds), "typical working time"),
      kpi("Tool errors", fmt.pct(k.error_rate), "of its tool calls"),
      kpi("Problems", fmt.num(k.incidents, 2), "per 100 tool calls")));
}

function unitPage(id) {
  const u = UNITS.get(id);
  const versions = DATA.versions[id] || [];
  const runs = DATA.runs[id] || [];
  const v = verdict(u.score, u.ci, u);
  const few = u.low_sample ? ` Only ${fmt.runs(u.runs)} so far, so it can still move.` : "";
  const members = u.kind === "group" ? ` Members: ${u.members.join(", ")}.` : "";
  const cur = versions.find((x) => x.label === u.current) || null;
  const curRuns = cur ? runs.filter((r) => r.version === cur.label) : [];
  const showCurrent = cur && versions.length > 1;
  const c = cur ? change(cur) : null;
  const ns = entityOfUnit(u);
  const key = ns ? (() => { const col = colourOf(ns, u.name); return svg("svg", { class: "lkey big", width: 16, height: 16, "aria-hidden": "true" }, marker(col.shape, 8, 8, 6, { style: `fill:${col.css}` })); })() : null;
  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("a", { class: "back", href: hrefPage("skills") }, "← All skills"),
      h("h1", { tabindex: "-1" }, key, u.name, " ", chip(KIND[u.kind], "kind")),
      h("p", { class: `summary tone-${v.tone}` }, h("span", { class: "ticon", "aria-hidden": "true" }, TONE[v.tone].icon), " ",
        versions.length > 1 ? `Current version ${u.current}. ` : "", v.sentence + few + members)),
    periodRow(versions.length > 1 ? "All versions" : u.kind === "agent" ? "All runs" : "Its only version", `${fmt.runs(u.runs)} · ${fmt.span(u.first_seen, u.last_seen)}`,
      u.kind === "agent" ? null : 100, null, u.kpi, h("span", { class: "muted" }, u.kind === "agent" ? "described, not scored" : "the reference: 100 is this unit's typical run"),
      u.kind === "agent" ? u : {}),
    showCurrent ? periodRow(`Current version ${cur.label}`, `${fmt.runs(cur.runs)} · ${fmt.span(cur.first_seen, cur.last_seen)}`, cur.score, cur.ci, kpiOf(curRuns, u.kind),
      h("span", {}, cur.ci ? `range ${fmt.interval(cur.ci)} · ` : "", toneTag(c.tone || verdict(cur.score, cur.ci, cur).tone, verdict(cur.score, cur.ci, cur).word)), cur) : null,
    tabs("Details", [
      { id: "versions", label: "Versions", build: () => versionsPanel(u, versions) },
      { id: "drivers", label: "What drives the score", build: () => driversPanel(u, versions) },
      { id: "runs", label: "Runs", build: () => runsPanel(u, runs, versions) },
    ], { param: "tab" }));
}

function versionsPanel(u, versions) {
  if (u.kind === "agent") return note("Agent roles have no versions. Their runs are scored as one group.");
  if (!versions.length) return empty("No runs yet.");
  if (!versions.some((v) => v.recorded)) {
    return note("Claude Code did not record this skill's text in these runs, so there are no versions to compare.");
  }
  const list = h("ol", { class: "vlist" }, [...versions].reverse().map((v) => versionRow(u, versions, v)));
  return h("div", { class: "grid wide-first" },
    versionTimeline({
      title: "Each version over time", sub: "segment = dates in use · band = its range · 100 = this unit's typical run",
      facets: [{ label: u.name, versions: versions.filter((v) => v.recorded).map((v) => ({ label: v.label, t0: timeOf(v.first_seen), t1: timeOf(v.last_seen || v.first_seen),
        score: v.score, ci: v.ci, runs: v.runs, tone: change(v).tone, text: change(v).text })) }],
      ref: 100,
      notes: `The first version is marked as such, not as “no change”. A version is called better or worse than the one before only from the difference between their runs, with at least ${MIN_RUNS} runs on each side and nothing else changed at the same time.`,
    }),
    h("div", {}, h("h2", { class: "listtitle" }, "Versions, newest first"), list));
}

function versionRow(u, versions, v) {
  const prev = versions[versions.indexOf(v) - 1] || null;
  const cur = v.label === u.current;
  const hashes = v.recorded ? v.parts.map((p) => p.hash).join(" + ") : "text not recorded";
  const c = change(v);
  return h("li", { class: "vrow", id: `ver-${v.label}` },
    h("div", { class: "vhead" }, h("strong", {}, nameOf(v)), cur ? chip("current", "ok") : null, h("code", {}, hashes)),
    h("div", { class: "vmeta" }, `${fmt.span(v.first_seen, v.last_seen)} · ${fmt.runs(v.runs)}`, v.low_sample ? chip("few runs", "warn") : null),
    h("div", { class: "vscore" },
      h("strong", {}, fmt.score(v.score)), " ",
      h("span", { class: "ci" }, v.ci ? fmt.interval(v.ci) : "no range"), " ",
      prev ? (c.text ? toneTag(c.tone, `${c.text}${v.vs ? ` against ${v.vs}` : ""}`) : null) : toneTag("first", "first version")),
    v.confounders && v.confounders.length ? h("div", { class: "vmeta" }, `Confounders: ${v.confounders.join("; ")}`) : null,
    prev ? changesDetails(v, prev) : null);
}

function changesDetails(v, prev) {
  if (!v.changes.length) return null;
  const added = v.changes.reduce((n, c) => n + c.added, 0);
  const removed = v.changes.reduce((n, c) => n + c.removed, 0);
  return h("details", { class: "changes" },
    h("summary", {}, "What changed ", h("span", { class: "add" }, `+${added}`), " ", h("span", { class: "del" }, `−${removed}`),
      h("span", { class: "muted" }, ` since ${nameOf(prev)}`)),
    v.changes.map((c) => h("div", { class: "change-item" },
      h("div", { class: "ch-title" }, c.skill, ` · ${c.from} → ${c.to}`),
      c.lines ? diffBlock(c) : note(c.note))));
}

function diffBlock(c) {
  const lines = c.lines.map(([op, text]) =>
    h("span", { class: op === "+" ? "add" : op === "-" ? "del" : op === "@" ? "hunk" : "ctx" }, op === "@" ? text : `${op} ${text}`));
  if (c.truncated) lines.push(h("span", { class: "hunk" }, "… diff cut short"));
  return h("pre", { class: "diff", tabindex: "0", "aria-label": `Changes to ${c.skill}` }, lines);
}

// The effect of one measure on the score, as a percentage: exp(contribution) − 1.
const effect = (share) => Math.exp(share) - 1;

function driversPanel(u, versions) {
  const withData = versions.filter((x) => Object.keys(x.metrics || {}).length);
  if (!withData.length) return empty("No measure has data for this unit yet.");
  const wanted = param("ver");
  const current = withData.find((x) => x.label === wanted) || withData.find((x) => x.label === u.current) || withData[withData.length - 1];
  const select = h("select", { "aria-label": "Version" }, withData.map((x) =>
    h("option", { value: x.label, selected: x.label === current.label ? true : null }, `${nameOf(x)} · ${fmt.runs(x.runs)}`)));
  const holder = h("div", { class: "charts" });
  const draw = () => {
    const v = withData.find((x) => x.label === select.value) || current;
    const prev = versions[versions.indexOf(v) - 1];
    const prevShare = new Map(prev && prev.metrics ? contributions(prev).map((c) => [c.m.key, c.share]) : []);
    const parts = contributions(v).sort((a, b) => Math.abs(b.share) - Math.abs(a.share));
    const spend = versions.map((x) => ({ label: nameOf(x), value: sumOf((DATA.runs[u.id] || []).filter((r) => r.version === x.label), (r) => r.cost) }));
    fill(holder,
      divergingBars({
        title: `What moves the score of ${nameOf(v)}`, sub: `${fmt.runs(v.runs)} · score ${fmt.score(v.score)} · each bar is weight × ln(ratio) ÷ total weight`,
        n: v.runs, minN: MIN_RUNS,
        rows: parts.map((p) => ({ label: metricLabel(p.m), value: p.share, ratio: p.d.ratio, prev: prevShare.get(p.m.key), text: fmt.signedPct(effect(p.share), 1),
          tip: [["Effect on the score", fmt.signedPct(effect(p.share), 1)], ["This version", fmt.metric(p.m, p.d.value)], ["Typical run", fmt.metric(p.m, p.d.ref)],
            ["Ratio to typical", fmt.ratio(p.d.ratio)], ["Weight", `×${p.d.weight}`], ["Runs", fmt.int(p.d.n)],
            ...(prevShare.has(p.m.key) ? [[`Effect in ${prev.label}`, fmt.signedPct(effect(prevShare.get(p.m.key)), 1)]] : [])] })),
        tickFmt: (t) => fmt.signedPct(effect(t), 0), axisTitle: "Effect on the score",
        legendItems: [{ label: `${TONE.better.icon} raises the score`, css: TONE.better.css, kind: "rect" }, { label: `${TONE.worse.icon} lowers it`, css: TONE.worse.css, kind: "rect" },
          ...(prev ? [{ label: `${prev.label}, the version before`, css: "var(--text)", kind: "line" }] : [])],
        extraCols: [{ label: "Ratio to typical", num: true, value: (r) => r.ratio }],
        notes: `The effects multiply: together they take the score from 100 to ${fmt.score(v.score)}.`,
      }),
      breakdownTable(v),
      versions.length > 1 ? barChart({ title: "Spend by version", sub: "model spend of each version's runs", items: spend, sort: false, fmt: fmt.usd, tickFmt: fmt.usdTick, valueTitle: "Spend, US$", share: true, labelTitle: "Version" }) : null);
  };
  select.addEventListener("change", () => {
    setParams({ ver: select.value === u.current ? null : select.value });
    draw();
  });
  draw();
  return h("div", {}, h("label", { class: "inline" }, "Version ", select), holder,
    note(`Weights for this unit: ${Object.entries(u.weights || {}).map(([k, w]) => `${metricLabel(metricByKey.get(k) || { key: k, label: k })} ×${w}`).join(", ") || "the defaults"}. Change them under [weights] in config.toml.`));
}

function breakdownTable(v) {
  const rows = contributions(v);
  const cols = [
    { label: "Measure", value: (r) => metricLabel(r.m), cell: (r) => h("span", {}, metricLabel(r.m), h("span", { class: "sub block" }, metricHelp(r.m))) },
    { label: "This version", num: true, value: (r) => r.d.value, cell: (r) => fmt.metric(r.m, r.d.value) },
    { label: "Typical run", num: true, value: (r) => r.d.ref, cell: (r) => fmt.metric(r.m, r.d.ref) },
    { label: "Ratio", num: true, value: (r) => r.d.ratio, cell: (r) => fmt.ratio(r.d.ratio) },
    { label: "Weight", num: true, value: (r) => r.d.weight },
    { label: "Effect on the score", num: true, value: (r) => r.share, cell: (r) => toneTag(r.share > 0.001 ? "better" : r.share < -0.001 ? "worse" : "unclear", fmt.signedPct(effect(r.share), 1)) },
    { label: "Runs", num: true, value: (r) => r.d.n },
  ];
  return sortTable({ caption: `What drives the score of ${nameOf(v)}`, cols, rows, sort: { key: "c5", dir: 1 }, csvName: `drivers-${v.label}` }).el;
}

const RUN_MEASURES = ["cost", "seconds", "error_rate", "incidents", "interventions"];

function runsPanel(u, runs, versions) {
  if (!runs.length) return empty("No runs yet.");
  const options = RUN_MEASURES.map((k) => metricByKey.get(k)).filter((m) => m && m.kinds.includes(u.kind));
  const wanted = metricByKey.get(param("metric")) && options.includes(metricByKey.get(param("metric"))) ? metricByKey.get(param("metric")) : options[0];
  const select = h("select", { "aria-label": "Measure" }, options.map((m) => h("option", { value: m.key, selected: m === wanted ? true : null }, metricLabel(m))));
  const charts = h("div", { class: "charts" });
  const cur = u.current;
  const tipOf = (r) => ({ title: `${fmt.when(r.started)} · ${r.version}`, rows: [["Task", r.task || "—"], ["Cost", fmt.usd(r.cost)], ["Time", fmt.secs(r.seconds)]] });
  const draw = () => {
    const m = metricByKey.get(select.value) || wanted;
    const val = (r) => runMetrics(r, u.kind)[m.key];
    const vlist = versions.length ? versions : [{ label: "all", recorded: true }];
    const boundaries = versions.slice(1).filter((v) => v.first_seen).map((v) => ({ t: timeOf(v.first_seen), label: nameOf(v) }));
    const isCur = (r) => !versions.length || r.version === cur;
    fill(charts,
      stripPlot({
        title: `${metricLabel(m)}, every run by version`, sub: "each dot is one run · the line is the median",
        groups: [...vlist].reverse().map((v) => ({ label: versions.length ? `${nameOf(v)}${v.label === cur ? " (current)" : ""}` : "All runs", css: v.label === cur || !versions.length ? "var(--c1)" : "var(--other)",
          values: runs.filter((r) => !versions.length || r.version === v.label).map((r) => ({ v: val(r), tip: tipOf(r) })) })),
        fmt: (x) => fmt.metric(m, x), tickFmt: (x) => fmt.metricTick(m, x), axisTitle: metricLabel(m),
      }),
      h("div", { class: "grid" },
        scatterChart({
          title: `${metricLabel(m)}, run by run over time`, sub: "vertical lines mark when a new version was first used",
          points: runs.filter((r) => r.started).map((r) => ({ x: timeOf(r.started), y: val(r), label: r.task || r.session, css: isCur(r) ? "var(--c1)" : "var(--other)", tip: tipOf(r) })),
          x: { title: "Run started", time: true }, y: { title: metricLabel(m), fmt: (x) => fmt.metricTick(m, x) }, vlines: boundaries, labelTitle: "Run",
          legendItems: versions.length > 1 ? [{ label: `current version (${cur})`, css: "var(--c1)", kind: "dot" }, { label: "earlier versions", css: "var(--other)", kind: "dot" }] : null,
        }),
        scatterChart({
          title: "Cost against time per run", sub: "one mark per run",
          points: runs.map((r) => ({ x: r.seconds / 60, y: r.cost, label: r.task || r.session, css: isCur(r) ? "var(--c1)" : "var(--other)", tip: tipOf(r) })),
          x: { title: "Time per run, minutes", fmt: (x) => `${fmt.num(x, x < 10 ? 1 : 0)} min` }, y: { title: "Cost per run, US$", fmt: fmt.usdTick }, labelTitle: "Run",
          legendItems: versions.length > 1 ? [{ label: `current version (${cur})`, css: "var(--c1)", kind: "dot" }, { label: "earlier versions", css: "var(--other)", kind: "dot" }] : null,
        })));
  };
  select.addEventListener("change", () => {
    setParams({ metric: select.value === options[0].key ? null : select.value });
    draw();
  });
  draw();
  const cols = [
    { key: "started", label: "Started", value: (r) => r.started, cell: (r) => fmt.when(r.started) },
    { key: "task", label: "Task", value: (r) => r.task, cell: (r) => h("span", { class: "task", title: r.task || "" }, r.task || "—") },
    { key: "version", label: "Version", value: (r) => r.version },
    { key: "cost", label: "Cost", num: true, value: (r) => r.cost, cell: (r) => fmt.usd(r.cost) },
    { key: "seconds", label: "Time", num: true, value: (r) => r.seconds, cell: (r) => fmt.secs(r.seconds) },
    { key: "errors", label: "Tool errors", num: true, value: (r) => (r.calls ? r.call_errors / r.calls : null), cell: (r) => (r.calls ? `${fmt.int(r.call_errors)} of ${fmt.int(r.calls)}` : "—") },
    { key: "incidents", label: "Problems", num: true, value: (r) => r.incidents },
  ];
  if (u.kind !== "agent") cols.push({ key: "prompts", label: "Your messages", num: true, value: (r) => r.interventions });
  return h("div", {},
    h("label", { class: "inline" }, "Measure ", select), charts,
    sortTable({ caption: "Runs", cols, rows: runs, sort: { key: "started", dir: -1 }, page: 25, csvName: `${u.name}-runs` }).el);
}
