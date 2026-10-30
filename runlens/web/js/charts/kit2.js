/* charts/kit2.js: the chart forms the audit asked for, on the same frame as charts/kit.js.

   waterfallChart  how each measure moves a score from 100 to its value (weight × ln ratio, multiplied up)
   forestPlot      a difference with its interval per row, against "no change"
   sankeyChart     how runs move from skill to skill, step by step
   runTimeline     one run on one time axis: skills, events, spend, and every subagent as a bar (a waterfall)
   calendarChart   activity per day, weeks across
   histRows        a distribution per row (tool call durations), on shared log bins
   rateFacets      a success rate over time per unit, weekly, with its interval
   laneChart       events on a time axis, one lane per kind
   dotStack        every run as a dot, stacked where they meet (a dot plot), one row per group
   Each answers one question (spec.question, under its title), names its axes and units, has a legend when
   colour carries meaning, a table view and CSV / SVG / PNG export, and fades when its sample is small. */

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
// A ratio effect in words: ×1.21 is "21% better", ×0.8 is "25% worse" (the same distance on a log axis). An effect at the
// cap was clipped (the score stops counting there), so it is said to be, not given as a size.
const effectWords = (e) => {
  if (!valid(e) || e <= 0) return "—";
  if (Math.abs(Math.log(e)) < 0.005) return "no change";
  if (Math.abs(Math.log(e)) >= LOG_CAP - 1e-6) return e > 1 ? `better, capped at ×${fmt.num(e, 2)}` : `worse, capped at ×${fmt.num(e, 2)}`;
  return e > 1 ? `${fmt.pct(e - 1, e - 1 < 0.1 ? 1 : 0)} better` : `${fmt.pct(1 / e - 1, 1 / e - 1 < 0.1 ? 1 : 0)} worse`;
};
const isoOf = (ms) => (Number.isFinite(ms) ? new Date(ms).toISOString() : null);

/* ---- waterfall: from 100 to the score, one step per measure ----
   spec: {title, question, sub, rows: [{label, share, tip, extra}], score, base (word for 100), n, minN, notes} */
function waterfallChart(spec) {
  const rows = spec.rows.filter((r) => valid(r.share));
  if (!rows.length || !valid(spec.score)) return emptyCard(spec.title, "No measure has data for this yet.", spec.notes);
  let acc = 0;
  const steps = rows.map((r) => {
    const from = 100 * Math.exp(acc);
    acc += r.share;
    return { ...r, from, to: 100 * Math.exp(acc) };
  });
  const total = 100 * Math.exp(acc);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, n: spec.n, minN: spec.minN,
    height: (steps.length + 1) * rowH() + 70,
    legend: () => legend([{ label: `${TONE.better.icon} raises the score`, css: TONE.better.css }, { label: `${TONE.worse.icon} lowers it`, css: TONE.worse.css },
      { label: "the score", css: "var(--text2)" }]),
    table: () => ({
      cols: [{ label: "Step", value: (s) => s.label }, { label: "Score before", num: true, value: (s) => s.from, cell: (s) => fmt.num(s.from, 1) },
        { label: "Score after", num: true, value: (s) => s.to, cell: (s) => fmt.num(s.to, 1) },
        { label: "Effect", num: true, value: (s) => Math.exp(s.share) - 1, cell: (s) => fmt.signedPct(Math.exp(s.share) - 1, 1) }],
      rows: steps,
    }),
    draw(w) {
      const R = rowH(), top = 26;
      const labels = steps.map((s) => s.label).concat(["Score"]);
      const labelW = Math.min(maxLabel(labels, FONT.label) + 14, Math.max(100, w * 0.32));
      const valW = maxLabel(steps.map((s) => `▲ ${fmt.signedPct(Math.exp(s.share) - 1, 1)}`).concat([fmt.score(total)]), FONT.axis) + 16;
      const x0 = labelW, x1 = Math.max(x0 + 80, w - valW);
      const vals = steps.flatMap((s) => [s.from, s.to]).concat([100, total]);
      const lo = Math.min(...vals) / 1.06, hi = Math.max(...vals) * 1.06;
      const x = scaleLog(lo, hi, x0, x1);
      // whole-number steps: a 2.5 step labelled without decimals reads as 93, 98, 103
      const tk = ticks(lo, hi, Math.max(3, Math.floor((x1 - x0) / 70)), true).filter((t) => t > 0);
      const H = top + (steps.length + 1) * R + 46;
      const root = svgRoot(w, H, `${spec.title}: from 100 to ${fmt.score(total)} in ${steps.length} steps`);
      axisX(root, { scale: x, ticks: tk.map((v) => ({ v, label: fmt.num(v, v < 10 ? 1 : 0) })), x0, x1, y: top + (steps.length + 1) * R, grid: true, gridTop: top - 6,
        title: `Score (100 = ${spec.base || "the reference"}, log scale)` });
      root.append(svg("line", { class: "ref", x1: x(100), x2: x(100), y1: top - 8, y2: top + (steps.length + 1) * R }));
      root.append(svg("text", { class: "reflabel", x: x(100), y: top - 12, "text-anchor": "middle" }, "100"));
      steps.forEach((s, i) => {
        const y = top + i * R, bh = Math.min(BAR(), R - 10), yb = y + (R - bh) / 2;
        const tone = s.share > 1e-9 ? "better" : s.share < -1e-9 ? "worse" : "unclear";
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: y + R / 2 + 4, "text-anchor": "end" }, fitText(s.label, labelW - 12, FONT.label)));
        const a = x(Math.min(s.from, s.to)), b = x(Math.max(s.from, s.to));
        const bar = svg("rect", { class: "bar", x: a, y: yb, width: Math.max(1.5, b - a), height: bh, rx: 2, style: `fill:${TONE[tone].css}` });
        root.append(markGroup({ title: s.label, rows: [["Effect on the score", fmt.signedPct(Math.exp(s.share) - 1, 1)], ["Score before → after", `${fmt.num(s.from, 1)} → ${fmt.num(s.to, 1)}`], ...(s.tip || [])] },
          bar, svg("rect", { class: "hit", x: 0, y, width: w, height: R })));
        if (i < steps.length - 1) root.append(svg("line", { class: "connector", x1: x(s.to), x2: x(s.to), y1: yb + bh, y2: yb + R }));
        root.append(svg("text", { class: "value", x: x1 + 8, y: y + R / 2 + 4 }, `${TONE[tone].icon} ${fmt.signedPct(Math.exp(s.share) - 1, 1)}`));
      });
      const y = top + steps.length * R, bh = Math.min(BAR() + 2, R - 8), yb = y + (R - bh) / 2;
      root.append(svg("line", { class: "sep", x1: x0 - 8, x2: x1, y1: y + 1, y2: y + 1 }));
      root.append(svg("text", { class: "rowlabel strong", x: labelW - 10, y: y + R / 2 + 4, "text-anchor": "end" }, "Score"));
      const a = x(Math.min(100, total)), b = x(Math.max(100, total));
      root.append(markGroup({ title: "Score", rows: [["Score", fmt.score(spec.score)], ["Steps multiplied", fmt.num(total, 1)]] },
        svg("rect", { class: "bar total", x: a, y: yb, width: Math.max(2, b - a), height: bh, rx: 2 }), svg("rect", { class: "hit", x: 0, y, width: w, height: R })));
      root.append(svg("text", { class: "value strong", x: x1 + 8, y: y + R / 2 + 4 }, fmt.score(spec.score)));
      return root;
    },
  });
}

/* ---- forest plot: rows of {label, effect, ci, tone, text}, effects as ratios on a log axis around 1 ----
   spec: {title, question, sub, rows, leftLabel, rightLabel, axisTitle, n, minN, notes, extraCols} */
function forestPlot(spec) {
  const rows = spec.rows.filter((r) => valid(r.effect) && r.effect > 0);
  if (!rows.length) return emptyCard(spec.title, "Nothing to compare yet.", spec.notes);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, n: spec.n, minN: spec.minN,
    height: rows.length * (rowH() + 4) + 80,
    legend: () => legend([
      { label: `${TONE.better.icon} interval clear of no change, better`, css: TONE.better.css, kind: "dot" },
      { label: `${TONE.worse.icon} clear, worse`, css: TONE.worse.css, kind: "dot" },
      { label: `${TONE.unclear.icon} interval includes no change`, css: TONE.unclear.css, kind: "dot" },
      { label: "◆ the weighted score", css: "var(--text2)", shape: "diamond" }]),
    table: () => ({
      cols: [{ label: "Row", value: (r) => r.label }, { label: "Effect (×)", num: true, value: (r) => r.effect, cell: (r) => fmt.ratio(r.effect) },
        { label: "In words", value: (r) => r.words || effectWords(r.effect) },
        { label: "Interval low", num: true, value: (r) => (r.ci ? r.ci[0] : null), cell: (r) => (r.ci ? fmt.ratio(r.ci[0]) : "—") },
        { label: "Interval high", num: true, value: (r) => (r.ci ? r.ci[1] : null), cell: (r) => (r.ci ? fmt.ratio(r.ci[1]) : "—") },
        { label: "Reading", value: (r) => TONE[r.tone].word }, ...(spec.extraCols || [])],
      rows,
    }),
    draw(w) {
      const R = rowH() + 4;
      const labelW = Math.min(maxLabel(rows.map((r) => r.label), FONT.label) + 16, Math.max(100, w * 0.3));
      const txt = (r) => r.words || effectWords(r.effect);
      const valW = Math.min(maxLabel(rows.map((r) => `▲ ${txt(r)}`), FONT.axis) + 16, Math.max(110, w * 0.3));
      const x0 = labelW, x1 = Math.max(x0 + 80, w - valW);
      const vals = rows.flatMap((r) => (r.ci ? [r.ci[0], r.ci[1], r.effect] : [r.effect])).concat([1]);
      const cap = DATA.method.max_ratio * 1.05;
      const lo = clamp(Math.min(...vals) / 1.1, 1 / (cap * 1.5), 1), hi = clamp(Math.max(...vals) * 1.1, 1, cap * 1.5);
      const x = scaleLog(lo, hi, x0, x1);
      const tk = [0.25, 0.33, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3, 4].filter((v) => v >= lo && v <= hi);
      let left = spec.leftLabel || "◀ worse", right = spec.rightLabel || "better ▶";
      if (textWidth(left, FONT.small) + textWidth(right, FONT.small) + 16 > x1 - x0) [left, right] = ["◀ worse", "better ▶"];
      // "no change" sits over ×1: on a narrow plot it would cover the direction labels, so it moves up a line.
      const half = textWidth("no change", FONT.small) / 2 + 6;
      const clash = x(1) - half < x0 + textWidth(left, FONT.small) || x(1) + half > x1 - textWidth(right, FONT.small);
      const top = clash ? 40 : 28;
      const H = top + rows.length * R + 46;
      const root = svgRoot(w, H, `${spec.title}: ${rows.length} rows`);
      axisX(root, { scale: x, ticks: tk.map((v) => ({ v, label: `×${fmt.num(v, 2)}`, ref: v === 1 })), x0, x1, y: top + rows.length * R, grid: true, gridTop: top - 6,
        title: spec.axisTitle || "Effect, log scale (×1 = no change)" });
      root.append(svg("text", { class: "dirlabel", x: x0, y: top - 12 }, left), svg("text", { class: "dirlabel", x: x1, y: top - 12, "text-anchor": "end" }, right),
        svg("text", { class: "reflabel", x: x(1), y: top - (clash ? 26 : 12), "text-anchor": "middle" }, "no change"));
      rows.forEach((r, i) => {
        const y = top + i * R + R / 2;
        const t = TONE[r.tone] || TONE.unclear;
        if (r.bold) root.append(svg("rect", { class: "rowband", x: 0, y: y - R / 2, width: w, height: R }));
        root.append(svg("text", { class: `rowlabel${r.bold ? " strong" : ""}`, x: labelW - 10, y: y + 4, "text-anchor": "end" }, fitText(r.label, labelW - 12, FONT.label, r.bold ? 600 : 400)));
        const kids = [];
        if (r.ci) kids.push(svg("line", { class: "ciline", x1: x(clamp(r.ci[0], lo, hi)), x2: x(clamp(r.ci[1], lo, hi)), y1: y, y2: y, style: `stroke:${t.css}` }));
        kids.push(marker(r.bold ? "diamond" : "circle", x(clamp(r.effect, lo, hi)), y, r.bold ? 7 : 5.5, { class: `dot${r.ci ? "" : " hollow"}`, style: r.ci ? `fill:${t.css}` : `stroke:${t.css}` }));
        kids.push(svg("rect", { class: "hit", x: x0 - 4, y: y - R / 2, width: x1 - x0 + 8, height: R }));
        root.append(markGroup({ title: r.label, rows: [["Effect", `${r.words || effectWords(r.effect)} (${fmt.ratio(r.effect)})`], ["Interval", r.ci ? `${fmt.ratio(r.ci[0])} – ${fmt.ratio(r.ci[1])}` : "none: too few runs"],
          ["Reading", `${t.icon} ${r.word || t.word}`], ...(r.tip || [])] }, ...kids));
        root.append(svg("text", { class: `value${r.bold ? " strong" : ""}`, x: x1 + 8, y: y + 4 }, fitText(`${t.icon} ${txt(r)}`, w - x1 - 10, FONT.axis)));
      });
      return root;
    },
  });
}

/* ---- sankey: stages of skills, links sized by how many runs took that step ----
   spec: {title, question, sub, stages: [[{key, label, value}]], links: [{from: [stage, key], to: [stage, key], value}], fmt, notes} */
function sankeyChart(spec) {
  const stages = spec.stages.filter((s) => s.length);
  if (stages.length < 2 || !spec.links.length) return emptyCard(spec.title, spec.emptyText || "No skill handed over to another yet.", spec.notes);
  const fmtv = spec.fmt || fmt.int;
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto !== false, sub: spec.sub, notes: spec.notes, height: 380,
    legend: () => legend([...new Set(stages.flat().map((n) => n.key))].filter((k) => k !== "(end)").map((k) => {
      const c = colourOf("skill", k);
      return { label: human(k), css: c.css, shape: c.shape };
    })),
    table: () => ({
      cols: [{ label: "From step", num: true, value: (l) => l.from[0] + 1 }, { label: "From", value: (l) => human(l.from[1]) },
        { label: "To", value: (l) => human(l.to[1]) }, { label: "Runs", num: true, value: (l) => l.value }],
      rows: spec.links,
    }),
    draw(w) {
      const n = stages.length;
      const colW = 12, top = 22, H = Math.max(260, Math.min(560, 26 * Math.max(...stages.map((s) => s.length)) + 120));
      const labelRoom = Math.min(150, Math.max(80, w * 0.14));
      const x0 = 4, x1 = w - labelRoom - colW;
      const step = (x1 - x0) / Math.max(1, n - 1);
      const gap = 10;
      const totals = stages.map((s) => s.reduce((a, b) => a + b.value, 0));
      const k = Math.min(...stages.map((s, i) => (H - top - 30 - gap * (s.length - 1)) / Math.max(1, totals[i])));
      const pos = new Map();
      stages.forEach((s, i) => {
        let y = top + 4;
        for (const node of s) {
          const hgt = Math.max(2, node.value * k);
          pos.set(`${i}|${node.key}`, { x: x0 + i * step, y, h: hgt, outY: y, inY: y, node, stage: i });
          y += hgt + gap;
        }
      });
      const root = svgRoot(w, H, `${spec.title}: ${spec.links.length} links across ${n} steps`);
      stages.forEach((s, i) => root.append(svg("text", { class: "colhead", x: x0 + i * step + colW / 2, y: 12, "text-anchor": i === 0 ? "start" : i === n - 1 ? "end" : "middle" },
        spec.stageLabel ? spec.stageLabel(i) : `step ${i + 1}`)));
      const links = [...spec.links].sort((a, b) => b.value - a.value);
      for (const l of links) {
        const a = pos.get(`${l.from[0]}|${l.from[1]}`), b = pos.get(`${l.to[0]}|${l.to[1]}`);
        if (!a || !b) continue;
        const t = l.value * k;
        const ya = a.outY + t / 2, yb = b.inY + t / 2;
        a.outY += t;
        b.inY += t;
        const xa = a.x + colW, xb = b.x, mx = (xa + xb) / 2;
        const c = colourOf("skill", l.from[1]);
        root.append(markGroup({ title: `${human(l.from[1])} → ${human(l.to[1])}`, rows: [["Runs", fmtv(l.value)], ["Step", `${l.from[0] + 1} → ${l.to[0] + 1}`],
          ["Share of the step", fmt.pct(l.value / Math.max(1, totals[l.from[0]]))]] },
        svg("path", { class: "flow", d: `M${xa},${ya}C${mx},${ya} ${mx},${yb} ${xb},${yb}`, style: `stroke:${c.css};stroke-width:${Math.max(1.5, t)}px` })));
      }
      for (const p of pos.values()) {
        const c = p.node.key === "(end)" ? { css: "var(--other)" } : colourOf("skill", p.node.key);
        root.append(markGroup({ title: human(p.node.key === "(end)" ? "Run ended" : p.node.label || p.node.key), rows: [["Runs at this step", fmtv(p.node.value)], ["Step", fmt.int(p.stage + 1)]] },
          svg("rect", { class: "node", x: p.x, y: p.y, width: colW, height: p.h, rx: 2, style: `fill:${c.css}` }),
          svg("rect", { class: "hit", x: p.x - 4, y: p.y - 2, width: colW + 8, height: p.h + 4 })));
        if (p.h >= 11) {
          const last = p.stage === n - 1;
          const label = fitText(p.node.key === "(end)" ? "ended" : human(p.node.key), last ? labelRoom - 6 : Math.min(step - colW - 10, 160), FONT.small);
          root.append(svg("text", { class: "dlabel", x: p.x + colW + 5, y: p.y + Math.min(p.h / 2, 12) + 4 }, label));
        }
      }
      return root;
    },
  });
}

/* ---- calendar: one cell per day, weeks across, Monday on top ----
   spec: {title, question, sub, days: Map(day -> {value, rows}), fmt, legendText, notes} */
function calendarChart(spec) {
  const keys = [...spec.days.keys()].sort();
  if (!keys.length) return emptyCard(spec.title, "No activity in this slice.", spec.notes);
  const fmtv = spec.fmt || fmt.num;
  const first = localMidnight(keys[0]), last = localMidnight(keys[keys.length - 1]);
  const monday = (t) => {
    const d = new Date(t);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime();
  };
  const start = monday(first);
  const all = [];
  for (let t = start; t <= last + 36e5; t = new Date(new Date(t).setDate(new Date(t).getDate() + 1)).getTime()) all.push(t);
  const weeks = Math.ceil(all.length / 7);
  const max = Math.max(...[...spec.days.values()].map((d) => d.value), 1e-9);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, controls: spec.controls, height: 7 * 18 + 60,
    legend: () => scaleLegend("seq", spec.legendText || ["less", "more"]),
    table: () => ({ cols: [{ label: "Day", value: (d) => d.day }, { label: spec.valueTitle || "Value", num: true, value: (d) => d.value, cell: (d) => fmtv(d.value) }],
      rows: keys.map((k) => ({ day: k, value: spec.days.get(k).value })) }),
    draw(w) {
      const S = scales();
      const labelW = 34, top = 20;
      const cell = clamp(Math.floor((w - labelW - 4) / weeks) - 3, 9, 26);
      const W = Math.max(w, labelW + weeks * (cell + 3));
      const H = top + 7 * (cell + 3) + 6;
      const root = svgRoot(W, H, `${spec.title}: ${keys.length} active days over ${weeks} weeks`);
      ["Mon", "", "Wed", "", "Fri", "", "Sun"].forEach((d, i) => d && root.append(svg("text", { class: "tick", x: labelW - 6, y: top + i * (cell + 3) + cell / 2 + 4, "text-anchor": "end" }, d)));
      let lastMonth = -1, lastX = -Infinity;
      all.forEach((t, i) => {
        const wk = Math.floor(i / 7), dow = i % 7;
        const x = labelW + wk * (cell + 3), y = top + dow * (cell + 3);
        const day = localDay(t);
        // a week column is named by the month its Sunday is in, so a week that starts on 31 Aug but holds
        // September's days says Sep
        const sunday = all[Math.min(all.length - 1, i + 6)];
        const m = new Date(sunday).getMonth();
        if (dow === 0 && m !== lastMonth && x - lastX > 30) {
          root.append(svg("text", { class: "tick", x, y: top - 7 }, df({ month: "short" }).format(new Date(sunday))));
          lastMonth = m;
          lastX = x;
        }
        if (t < first - 36e5 || t > last + 36e5) return;
        const d = spec.days.get(day);
        const fillc = d && d.value > 0 ? S.seq(Math.sqrt(d.value / max)) : S.empty;
        const rect = svg("rect", { class: "cell", x, y, width: cell, height: cell, rx: 2, style: `fill:${fillc}` });
        root.append(d ? markGroup({ title: fmt.day(isoOf(t)), rows: [[spec.valueTitle || "Value", fmtv(d.value)], ...(d.rows || [])], href: d.href }, rect) : rect);
      });
      return root;
    },
  });
}

/* ---- distributions per row on shared log bins (tool call durations) ----
   spec: {title, question, sub, rows: [{label, bins, n, css}], edges (ms), notes, unit: {one, many, row} (default: call, calls, Tool)} */
function histRows(spec) {
  const rows = spec.rows.filter((r) => r.n > 0);
  const u = spec.unit || { one: "call", many: "calls", row: "Tool" };
  const count = (n) => `${fmt.compact(n)} ${n === 1 ? u.one : u.many}`;
  if (!rows.length) return emptyCard(spec.title, "No durations recorded.", spec.notes);
  const edges = spec.edges;
  const nb = edges.length + 1;
  const binLabel = (i) => (i === 0 ? `< ${fmt.ms(edges[0])}` : i === nb - 1 ? `≥ ${fmt.ms(edges[nb - 2])}` : `${fmt.ms(edges[i - 1])}–${fmt.ms(edges[i])}`);
  const quant = (bins, q) => {
    const n = bins.reduce((a, b) => a + b, 0);
    let acc = 0;
    for (let i = 0; i < bins.length; i += 1) {
      acc += bins[i];
      if (acc >= q * n) return i;
    }
    return bins.length - 1;
  };
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, height: rows.length * 34 + 60,
    legend: () => legend([{ label: `share of the ${u.row.toLowerCase()}'s ${u.many} in each band`, css: "var(--c1)" }, { label: "median band", css: "var(--text)", kind: "line" }]),
    table: () => ({
      cols: [{ label: u.row, value: (r) => r.label }, { label: u.many.charAt(0).toUpperCase() + u.many.slice(1), num: true, value: (r) => r.n },
        { label: "Median band", value: (r) => binLabel(quant(r.bins, 0.5)) }, { label: "Slowest 10% from", value: (r) => binLabel(quant(r.bins, 0.9)) },
        ...edges.concat([Infinity]).map((e, i) => ({ label: binLabel(i), num: true, value: (r) => r.bins[i] || 0 }))],
      rows,
    }),
    draw(w) {
      const RH = PREFS.density === "compact" ? 28 : 34, top = 8;
      const labelW = Math.min(maxLabel(rows.map((r) => r.label), FONT.label) + 14, Math.max(80, w * 0.25));
      const nW = maxLabel(rows.map((r) => count(r.n)), FONT.axis) + 12;
      const x0 = labelW, x1 = Math.max(x0 + 120, w - nW);
      const bw = (x1 - x0) / nb;
      const H = top + rows.length * RH + 44;
      const root = svgRoot(w, H, `${spec.title}: ${rows.length} distributions`);
      const tickAt = [0, 2, 4, 6, 8, 10].filter((i) => i < nb - 1);
      axisX(root, { scale: (i) => x0 + (i + 1) * bw, ticks: tickAt.map((i) => ({ v: i, label: fmt.ms(edges[i]) })), x0, x1, y: top + rows.length * RH, grid: true, gridTop: top,
        title: u.axis || "Call duration (log scale)" });
      rows.forEach((r, i) => {
        const yb = top + (i + 1) * RH - 3, hmax = RH - 8;
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: yb - hmax / 2 + 4, "text-anchor": "end" }, fitText(r.label, labelW - 12, FONT.label)));
        const peak = Math.max(...r.bins, 1);
        r.bins.forEach((c, j) => {
          if (!c) return;
          const hh = Math.max(1.5, (c / peak) * hmax);
          root.append(markGroup({ title: `${r.label} · ${binLabel(j)}`, rows: [[u.many.charAt(0).toUpperCase() + u.many.slice(1), fmt.int(c)], [`Share of its ${u.many}`, fmt.pct(c / r.n)]] },
            colPath(x0 + j * bw + 1, Math.max(1, bw - 2), yb, yb - hh, 2), svg("rect", { class: "hit", x: x0 + j * bw, y: yb - hmax, width: bw, height: hmax })));
          root.lastChild.firstChild.setAttribute("style", `fill:${r.css || "var(--c1)"}`);
        });
        const med = quant(r.bins, 0.5);
        root.append(svg("line", { class: "median", x1: x0 + (med + 0.5) * bw, x2: x0 + (med + 0.5) * bw, y1: yb + 1, y2: yb - hmax - 1 }));
        root.append(svg("text", { class: "value", x: x1 + 8, y: yb - hmax / 2 + 4 }, count(r.n)));
      });
      return root;
    },
  });
}

// Wilson score interval of k successes in n, at the page's confidence level.
function wilson(k, n, conf) {
  if (!n) return null;
  const z = normInv(1 - (1 - (conf || S.ci)) / 2), p = k / n;
  const den = 1 + (z * z) / n, mid = (p + (z * z) / (2 * n)) / den, half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / den;
  return [Math.max(0, mid - half), Math.min(1, mid + half)];
}

/* ---- a rate over time, one panel per unit: weekly rate, its interval, every week's attempts ----
   spec: {title, question, sub, facets: [{label, ns, name, points: [{t, k, n}], vlines}], rateTitle, notes} */
function rateFacets(spec) {
  const facets = spec.facets.filter((f) => f.points.some((p) => p.n > 0));
  if (!facets.length) return emptyCard(spec.title, spec.emptyText || "No attempts recorded in this slice.", spec.notes);
  const weekOf = (t) => {
    const d = new Date(t);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getTime();
  };
  const weekly = facets.map((f) => {
    const m = new Map();
    for (const p of f.points) {
      const k = weekOf(p.t);
      const e = m.get(k) || { t: k, k: 0, n: 0 };
      e.k += p.k;
      e.n += p.n;
      m.set(k, e);
    }
    return { ...f, weeks: [...m.values()].sort((a, b) => a.t - b.t).map((e) => ({ ...e, rate: e.k / e.n, ci: wilson(e.k, e.n) })) };
  });
  const allT = weekly.flatMap((f) => f.weeks.map((e) => e.t));
  const t0 = Math.min(...allT), t1 = Math.max(...allT) + 7 * DAY;
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, height: facets.length > 1 ? 380 : 260,
    legend: () => legend([{ label: "dot = one week's rate (bigger = more attempts, hollow = fewer than " + MIN_RUNS + ")", css: "var(--text2)", kind: "dot" },
      { label: `shaded band = likely range of that week's rate (${Math.round(S.ci * 100)}%)`, css: "var(--c1)" },
      { label: "dotted line = a new version", css: "var(--muted)", kind: "line", dash: "2 3" }]),
    table: () => ({
      cols: [{ label: "Unit", value: (r) => r.unit }, { label: "Week of", value: (r) => isoOf(r.t), cell: (r) => fmt.day(isoOf(r.t)) },
        { label: "Successes", num: true, value: (r) => r.k }, { label: "Attempts", num: true, value: (r) => r.n },
        { label: spec.rateTitle || "Rate", num: true, value: (r) => r.rate, cell: (r) => fmt.pct(r.rate) },
        { label: "Interval low", num: true, value: (r) => (r.ci ? r.ci[0] : null), cell: (r) => fmt.pct(r.ci && r.ci[0]) },
        { label: "Interval high", num: true, value: (r) => (r.ci ? r.ci[1] : null), cell: (r) => fmt.pct(r.ci && r.ci[1]) }],
      rows: weekly.flatMap((f) => f.weeks.map((e) => ({ ...e, unit: f.label }))),
    }),
    draw(w) {
      const cols = facets.length === 1 ? 1 : Math.max(1, Math.min(4, Math.floor(w / 300), facets.length));
      const band = weekly.some((f) => (f.vlines || []).length) ? VLINE_BAND : 0;  // room for the version labels
      const fw = (w - (cols - 1) * 18) / cols, fh = (facets.length === 1 ? 220 : 150) + band;
      const rowsN = Math.ceil(weekly.length / cols);
      const H = rowsN * (fh + 30) + 6;
      const root = svgRoot(w, H, `${spec.title}: ${weekly.length} panels on a shared time axis`);
      weekly.forEach((f, i) => {
        const g = svg("g", { transform: `translate(${(i % cols) * (fw + 18)},${Math.floor(i / cols) * (fh + 30)})` });
        const x0 = maxLabel(["100%"]) + 10, x1 = fw - 8, top = 28 + band, bottom = fh - 4;
        const x = scaleLinear(t0 - DAY, t1 + DAY, x0 + 6, x1 - 6);
        const y = scaleLinear(0, 1, bottom, top);
        if (f.ns) g.append(entityDot(f.ns, f.name ?? f.label, 5, 10));
        g.append(svg("text", { class: "facettitle", x: f.ns ? 14 : 0, y: 14 }, fitText(f.label, fw - 20, FONT.label, 600)));
        axisY(g, { scale: y, ticks: [0, 0.5, 1], fmt: (v) => fmt.pct(v, 0), x0, x1, top });
        axisX(g, { scale: x, ticks: timeTicks(t0 - DAY, t1 + DAY, Math.max(2, Math.floor((x1 - x0) / 80))).map((t) => ({ v: t.t, label: t.label })), x0, x1, y: bottom });
        placeVlines(g, f.vlines || [], x, x0, x1, top, bottom);
        const pts = f.weeks.map((e) => ({ ...e, cx: x(e.t + 3.5 * DAY) }));
        if (pts.length > 1) {
          g.append(svg("path", { class: "band-area", d: `M${pts.map((p) => `${p.cx},${y(p.ci[1])}`).join("L")}L${[...pts].reverse().map((p) => `${p.cx},${y(p.ci[0])}`).join("L")}Z` }));
          g.append(svg("path", { class: "line", d: `M${pts.map((p) => `${p.cx},${y(p.rate)}`).join("L")}` }));
        } else if (pts.length) g.append(svg("line", { class: "ciline", x1: pts[0].cx, x2: pts[0].cx, y1: y(pts[0].ci[0]), y2: y(pts[0].ci[1]), style: "stroke:var(--c1)" }));
        const maxN = Math.max(...pts.map((p) => p.n));
        for (const p of pts) {
          const r = 3.5 + 4 * Math.sqrt(p.n / maxN);
          g.append(markGroup({ title: `${f.label} · week of ${fmt.day(isoOf(p.t))}`, rows: [[spec.rateTitle || "Rate", fmt.pct(p.rate)], ["Successes", `${fmt.int(p.k)} of ${fmt.int(p.n)}`],
            ["Interval", p.ci ? `${fmt.pct(p.ci[0], 0)} – ${fmt.pct(p.ci[1], 0)}` : "—"]] },
          svg("circle", { class: `dot${p.n < MIN_RUNS ? " hollow" : ""}`, cx: p.cx, cy: y(p.rate), r, style: p.n < MIN_RUNS ? "stroke:var(--text2)" : "fill:var(--text2)" }),
          svg("circle", { class: "hit", cx: p.cx, cy: y(p.rate), r: 12 })));
        }
        root.append(g);
      });
      return root;
    },
  });
}

/* ---- lanes of events on a time axis ----
   spec: {title, question, sub, lanes: [{label, items: [{t, css, shape, r, tip, href}]}], vlines: [{t, label, kind}], legendItems, notes} */
function laneChart(spec) {
  const lanes = spec.lanes.filter((l) => l.items.some((it) => valid(it.t)));
  if (!lanes.length) return emptyCard(spec.title, spec.emptyText || "Nothing recorded in this slice.", spec.notes);
  const all = lanes.flatMap((l) => l.items.map((it) => it.t)).filter(valid);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, height: lanes.length * 30 + 70,
    legend: spec.legendItems ? () => legend(spec.legendItems) : null,
    table: () => ({
      cols: [{ label: "Lane", value: (r) => r.lane }, { label: "When", value: (r) => isoOf(r.t), cell: (r) => fmt.when(isoOf(r.t)) },
        { label: "What", value: (r) => (r.tip ? r.tip.title : "") }, ...(spec.extraCols || [])],
      rows: lanes.flatMap((l) => l.items.map((it) => ({ ...it, lane: l.label }))).sort((a, b) => a.t - b.t),
    }),
    draw(w) {
      const RH = PREFS.density === "compact" ? 24 : 30, top = spec.vlines && spec.vlines.length ? 10 + VLINE_BAND : 10;
      const labelW = Math.min(maxLabel(lanes.map((l) => l.label), FONT.label) + 14, Math.max(90, w * 0.28));
      const x0 = labelW, x1 = w - 12;
      const a = Math.min(...all), b = Math.max(...all), pad = Math.max(36e5, (b - a) * 0.03);
      const x = scaleLinear(a - pad, b + pad, x0 + 4, x1 - 4);
      const H = top + lanes.length * RH + 44;
      const root = svgRoot(w, H, `${spec.title}: ${all.length} events in ${lanes.length} lanes`);
      axisX(root, { scale: x, ticks: timeTicks(a - pad, b + pad, Math.max(2, Math.floor((x1 - x0) / 85))).map((t) => ({ v: t.t, label: t.label })), x0, x1,
        y: top + lanes.length * RH, grid: true, gridTop: top, title: spec.xTitle || "When" });
      placeVlines(root, spec.vlines || [], x, x0, x1, top, top + lanes.length * RH);
      lanes.forEach((l, i) => {
        const yc = top + i * RH + RH / 2;
        root.append(svg("line", { class: "lane", x1: x0, x2: x1, y1: yc, y2: yc }));
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: yc + 4, "text-anchor": "end" }, fitText(l.label, labelW - 12, FONT.label)));
        const seen = new Map();
        for (const it of [...l.items].filter((q) => valid(q.t)).sort((p, q) => p.t - q.t)) {
          const cx = x(it.t);
          const slot = Math.round(cx / 6);
          const k = seen.get(slot) || 0;
          seen.set(slot, k + 1);
          const cy = yc + (k % 3 === 0 ? 0 : k % 3 === 1 ? -6 : 6);
          root.append(markGroup({ title: it.tip ? it.tip.title : l.label, rows: it.tip ? it.tip.rows : [], href: it.href, sub: it.tip && it.tip.sub },
            marker(it.shape || "circle", cx, cy, it.r || 4.5, { class: "dot", style: `fill:${it.css || "var(--c1)"}` }), svg("circle", { class: "hit", cx, cy, r: 10 })));
        }
      });
      return root;
    },
  });
}

// Vertical markers on a time axis (a new skill version, a model change, a Claude Code update). Every marker keeps
// its line and a tooltip; labels go in two rows in the VLINE_BAND the caller leaves above `top`. A label that fits
// in neither row is not dropped silently: the rest are counted in a "+N more" at the end of the first row, whose
// tooltip lists them.
function placeVlines(root, vlines, x, x0, x1, top, bottom, labels = true) {
  const marks = vlines.filter((v) => valid(v.t)).map((v) => ({ v, vx: x(v.t) })).filter((m) => m.vx >= x0 && m.vx <= x1)
    .sort((a, b) => a.vx - b.vx || String(a.v.label).localeCompare(String(b.v.label)));
  for (const { v, vx } of marks) {
    const cls = `vmark${v.kind ? ` vm-${v.kind}` : ""}`;
    root.append(markGroup({ title: v.title || v.label, rows: v.rows || [] }, svg("line", { class: cls, x1: vx, x2: vx, y1: top - 4, y2: bottom }),
      svg("rect", { class: "hit", x: vx - 5, y: top - 4, width: 10, height: bottom - top + 4 })));
  }
  if (!labels || !marks.length) return;
  // row 0 clears a dot of radius 8 drawn on the top gridline
  const rowY = (r) => top - 10 - r * 12;
  const layout = (limit) => {
    const ends = [-Infinity, -Infinity], placed = [], hidden = [];
    for (const m of marks) {
      const tw = textWidth(m.v.label, FONT.small);
      const start = Math.max(x0, Math.min(m.vx + 3, limit - tw));
      const r = ends.findIndex((e) => start > e + 6);
      if (r < 0 || start + tw > limit + 0.5) { hidden.push(m); continue; }
      ends[r] = start + tw;
      placed.push({ m, start, r });
    }
    return { placed, hidden };
  };
  let { placed, hidden } = layout(x1);
  if (hidden.length) ({ placed, hidden } = layout(x1 - textWidth(`+${marks.length} more`, FONT.small) - 8));
  for (const p of placed) root.append(svg("text", { class: "vmarklabel", x: p.start, y: rowY(p.r) }, p.m.v.label));
  if (hidden.length) {
    root.append(markGroup({ title: `${hidden.length} more ${hidden.length === 1 ? "change" : "changes"} not labelled`, rows: hidden.map((m) => [m.v.label, m.v.title || ""]) },
      svg("text", { class: "vmarklabel", x: x1, y: rowY(0), "text-anchor": "end" }, `+${hidden.length} more`)));
  }
}

/* ---- a dot plot of runs: every run a dot, stacked where they meet, one row per group ----
   spec: {title, question, sub, groups: [{label, css, values: [{v, tip, href}], few}], fmt, tickFmt, axisTitle, log, notes} */
function dotStack(spec) {
  const groups = spec.groups.map((g) => ({ ...g, values: g.values.filter((p) => valid(p.v)) })).filter((g) => g.values.length);
  if (!groups.length) return emptyCard(spec.title, spec.emptyText || "No runs with this measure yet.", spec.notes);
  const fmtv = spec.fmt || fmt.num;
  const allV = groups.flatMap((g) => g.values.map((p) => p.v));
  const log = spec.log !== false && allV.every((v) => v > 0) && Math.max(...allV) / Math.min(...allV) > 20;
  const q = (xs, p) => {
    const s = [...xs].sort((a, b) => a - b);
    const i = p * (s.length - 1), lo = Math.floor(i);
    return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (i - lo);
  };
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, height: groups.length * 56 + 60,
    legend: () => legend([{ label: "one run", css: "var(--c1)", kind: "dot" }, { label: "median", css: "var(--text)", kind: "line" },
      { label: "middle half of the runs", css: "var(--muted)", kind: "line" }, { label: `hollow: fewer than ${MIN_RUNS} runs`, css: "var(--text2)", kind: "dot" }]),
    table: () => ({
      cols: [{ label: "Group", value: (r) => r.group }, { label: spec.axisTitle, num: true, value: (r) => r.v, cell: (r) => fmtv(r.v) }, { label: "Run", value: (r) => (r.tip ? r.tip.title : "") }],
      rows: groups.flatMap((g) => g.values.map((p) => ({ ...p, group: g.label }))),
    }),
    draw(w) {
      const r = 4.5, D = 2 * r + 1.5;
      const labelW = Math.min(maxLabel(groups.map((g) => g.label), FONT.label) + 14, w * 0.3);
      const statW = maxLabel(groups.map((g) => `n = ${g.values.length} · median ${fmtv(median(g.values.map((p) => p.v)))}`), FONT.axis) + 14;
      const showStat = w > 620;
      const x0 = labelW, x1 = w - (showStat ? statW : maxLabel(groups.map((g) => `n = ${g.values.length}`)) + 14);
      let x, xt;
      if (log) {
        const lo = Math.min(...allV) / 1.25, hi = Math.max(...allV) * 1.25;
        x = scaleLog(lo, hi, x0 + 6, x1 - 6);
        xt = logTicks(lo, hi).map((v) => ({ v, label: (spec.tickFmt || fmtv)(v) }));
      } else {
        const nm = niceMax(Math.max(...allV) * 1.04, Math.max(2, Math.floor((x1 - x0) / 90)));
        x = scaleLinear(0, nm.max, x0 + 6, x1 - 6);
        xt = nm.ticks.map((v) => ({ v, label: (spec.tickFmt || fmtv)(v) }));
      }
      // Stack: dots that would overlap move up, alternating sides, like a dot histogram.
      const layouts = groups.map((g) => {
        const placed = [];
        for (const p of [...g.values].sort((a, b) => a.v - b.v)) {
          const cx = x(p.v);
          let level = 0;
          while (placed.some((o) => Math.abs(o.cx - cx) < D && o.level === level)) level += 1;
          placed.push({ p, cx, level });
        }
        return { g, placed, height: Math.max(36, (Math.max(...placed.map((o) => o.level)) + 1) * D + 14) };
      });
      const top = 8;
      let y = top;
      const H = top + layouts.reduce((n, l) => n + l.height, 0) + 44;
      const root = svgRoot(w, H, `${spec.title}: ${allV.length} runs in ${groups.length} groups`);
      const yEnd = top + layouts.reduce((n, l) => n + l.height, 0);
      axisX(root, { scale: x, ticks: xt, x0, x1, y: yEnd, grid: true, gridTop: top, title: `${spec.axisTitle}${log ? " (log scale)" : ""}` });
      for (const L of layouts) {
        const base = y + L.height - 8;
        const few = L.g.values.length < MIN_RUNS;
        const vs = L.g.values.map((p) => p.v);
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: base - 2, "text-anchor": "end" }, fitText(L.g.label, labelW - 12, FONT.label)));
        if (vs.length >= 3) root.append(svg("line", { class: "iqr", x1: x(q(vs, 0.25)), x2: x(q(vs, 0.75)), y1: base + 5, y2: base + 5 }));
        const med = median(vs);
        root.append(svg("line", { class: "median", x1: x(med), x2: x(med), y1: base + 8, y2: base - Math.min(L.height - 14, 3 * D) }));
        for (const o of L.placed) {
          const cy = base - r - o.level * D;
          root.append(markGroup({ title: o.p.tip ? o.p.tip.title : L.g.label, rows: (o.p.tip ? o.p.tip.rows : []).concat([[spec.axisTitle, fmtv(o.p.v)]]), href: o.p.href },
            svg("circle", { class: `dot${few ? " hollow" : ""}`, cx: o.cx, cy, r, style: few ? `stroke:${L.g.css || "var(--c1)"}` : `fill:${L.g.css || "var(--c1)"}` }),
            svg("circle", { class: "hit", cx: o.cx, cy, r: 11 })));
        }
        root.append(svg("text", { class: "value", x: x1 + 8, y: base - 2 }, showStat ? `n = ${vs.length} · median ${fmtv(med)}` : `n = ${vs.length}`));
        y += L.height;
      }
      return root;
    },
  });
}

/* ---- one run on one time axis ----
   spec: {title, question, sub, t0, t1 (ms), lanes: [{label, items: [{t0, t1, t, css, shape, tip}]}],
          curve: [[ms, US$]], agents: [{label, depth, t0, t1, css, tip, few}], layout: "tree"|"packed", legendItems, notes} */
function runTimeline(spec) {
  const t0 = spec.t0, t1 = Math.max(spec.t1, spec.t0 + 60e3);
  const agents = spec.agents.filter((a) => valid(a.t0));
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, sub: spec.sub, notes: spec.notes, controls: spec.controls,
    height: 160 + Math.min(agents.length, 60) * 14,
    legend: spec.legendItems ? () => legend(spec.legendItems) : null,
    table: () => ({
      cols: [{ label: "Agent", value: (a) => a.label }, { label: "Started", value: (a) => isoOf(a.t0), cell: (a) => fmt.when(isoOf(a.t0)) },
        { label: "Ended", value: (a) => isoOf(a.t1), cell: (a) => (valid(a.t1) ? fmt.when(isoOf(a.t1)) : "—") },
        { label: "Duration", num: true, value: (a) => (valid(a.t1) ? (a.t1 - a.t0) / 1000 : null), cell: (a) => (valid(a.t1) ? fmt.secs((a.t1 - a.t0) / 1000) : "—") },
        ...(spec.agentCols || [])],
      rows: agents,
    }),
    draw(w) {
      const labelW = Math.min(Math.max(120, maxLabel(spec.lanes.map((l) => l.label).concat(agents.slice(0, 80).map((a) => a.label)), FONT.small) + 18), Math.max(110, w * 0.3));
      const x0 = labelW, x1 = w - 12;
      const x = scaleLinear(t0, t1, x0 + 2, x1 - 2);
      const laneH = 20, curveH = spec.curve && spec.curve.length > 1 ? 70 : 0;
      // agent rows: tree = one row each, nested; packed = per agent type, bars share rows when they do not overlap
      let rowsOut = [];
      if (spec.layout === "packed") {
        const byType = new Map();
        for (const a of agents) (byType.get(a.group) || byType.set(a.group, []).get(a.group)).push(a);
        for (const [type, list] of byType) {
          const ends = [];
          for (const a of list.sort((p, q) => p.t0 - q.t0)) {
            const end = valid(a.t1) ? a.t1 : a.t0;
            let k = ends.findIndex((e) => e + (t1 - t0) * 0.004 < a.t0);
            if (k < 0) {
              k = ends.length;
              ends.push(end);
            } else ends[k] = end;
            a.row = k;
          }
          rowsOut.push({ label: `${type} · ${fmt.int(list.length)}`, items: list, rows: ends.length });
        }
      } else rowsOut = agents.map((a) => ({ label: a.label, items: [{ ...a, row: 0 }], rows: 1, depth: a.depth }));
      const aH = agents.length > 60 ? 12 : 16;
      const agentRows = rowsOut.reduce((n, r) => n + r.rows, 0);
      const top = 24;
      const yLanes = top, yCurve = yLanes + spec.lanes.length * laneH + (curveH ? 14 : 0), yAgents = yCurve + curveH + 18;
      const H = yAgents + agentRows * aH + 44;
      const root = svgRoot(w, H, `${spec.title}: ${agents.length} agents over ${fmt.secs((t1 - t0) / 1000)}`);
      const tk = timeTicks(t0, t1, Math.max(2, Math.floor((x1 - x0) / 90))).map((t) => ({ v: t.t, label: t.label }));
      axisX(root, { scale: x, ticks: tk, x0, x1, y: H - 44, grid: true, gridTop: top - 6, title: "Time of day" });
      // lanes: skill segments, then point events
      spec.lanes.forEach((l, i) => {
        const yc = yLanes + i * laneH + laneH / 2;
        root.append(svg("text", { class: "lanelabel", x: labelW - 8, y: yc + 4, "text-anchor": "end" }, fitText(l.label, labelW - 12, FONT.small)));
        root.append(svg("line", { class: "lane", x1: x0, x2: x1, y1: yc, y2: yc }));
        for (const it of l.items) {
          if (valid(it.t0) && valid(it.t1)) {
            const a = x(it.t0), b = Math.max(a + 2, x(it.t1));
            root.append(markGroup({ title: it.tip.title, rows: it.tip.rows, href: it.href },
              svg("rect", { class: "seg", x: a, y: yc - 7, width: b - a, height: 14, rx: 2, style: `fill:${it.css}` }), svg("rect", { class: "hit", x: a - 2, y: yc - 9, width: b - a + 4, height: 18 })));
            if (it.name && b - a > textWidth(it.name, FONT.small) + 8) {
              root.append(svg("text", { class: "inlabel", x: a + 4, y: yc + 4, style: `fill:${inkOn(resolveCss(it.css))}` }, it.name));
            }
          } else if (valid(it.t)) {
            const cx = x(it.t);
            root.append(markGroup({ title: it.tip.title, rows: it.tip.rows, href: it.href, sub: it.tip.sub },
              it.shape === "tick" ? svg("line", { class: "tickmark", x1: cx, x2: cx, y1: yc - 6, y2: yc + 6, style: `stroke:${it.css}` })
                : marker(it.shape || "circle", cx, yc, 4.5, { class: "dot", style: `fill:${it.css}` }),
              svg("rect", { class: "hit", x: cx - 6, y: yc - 9, width: 12, height: 18 })));
          }
        }
      });
      // cumulative spend: its own small panel on the same time axis (never a second y-axis on the same plot)
      if (curveH) {
        const maxC = spec.curve[spec.curve.length - 1][1] || 1;
        const nm = niceMax(maxC, 2);
        const y = scaleLinear(0, nm.max, yCurve + curveH, yCurve);
        root.append(svg("text", { class: "lanelabel", x: labelW - 8, y: yCurve + 10, "text-anchor": "end" }, "Spend so far"));
        root.append(svg("text", { class: "tick", x: labelW - 8, y: yCurve + 24, "text-anchor": "end" }, `top: ${fmt.usdTick(nm.max)}`));
        root.append(svg("text", { class: "tick", x: labelW - 8, y: yCurve + curveH, "text-anchor": "end" }, fmt.usdTick(0)));
        root.append(svg("line", { class: "grid", x1: x0, x2: x1, y1: yCurve, y2: yCurve }), svg("line", { class: "baseline", x1: x0, x2: x1, y1: yCurve + curveH, y2: yCurve + curveH }));
        const pts = spec.curve.map(([t, c]) => [x(t), y(c)]);
        root.append(svg("path", { class: "area", d: `M${pts[0][0]},${yCurve + curveH}L${pts.map((p) => p.join(",")).join("L")}L${pts[pts.length - 1][0]},${yCurve + curveH}Z` }));
        root.append(svg("path", { class: "line", d: `M${pts.map((p) => p.join(",")).join("L")}` }));
        spec.curve.forEach(([t, c], i) => {
          if (i % Math.max(1, Math.floor(spec.curve.length / 30)) && i !== spec.curve.length - 1) return;
          root.append(markGroup({ title: fmt.when(isoOf(t)), rows: [["Spend so far", fmt.usd(c)]] }, svg("circle", { class: "hit", cx: x(t), cy: y(c), r: 9 })));
        });
      }
      // agents
      // The caption in the longest wording that fits the width (a phone gets the short one).
      const captions = spec.layout === "packed"
        ? ["Subagents grouped by type: one bar per subagent, from start to end; bars share a row when they do not overlap", "Subagents by type: one bar each, start to end", "Subagents by type"]
        : ["Agents: one bar per agent, from start to end, indented under the agent that started it", "Agents: one bar each, under the agent that started it", "Agents, under their parent"];
      const caption = captions.find((c) => textWidth(c, 11, 600) <= w - 4) || fitText(captions[captions.length - 1], w - 4, 11, 600);
      root.append(svg("text", { class: "sectionlabel", x: 0, y: yAgents - 6 }, caption));
      let yy = yAgents;
      for (const r of rowsOut) {
        const indent = spec.layout === "packed" ? 0 : Math.min(5, r.depth || 0) * 10;
        const text = fitText(r.label, labelW - 16 - indent, FONT.small);
        if (indent) root.append(svg("path", { class: "treeline", d: `M${indent - 6},${yy + 1}V${yy + aH / 2}H${indent - 1}` }));
        root.append(svg("text", { class: "lanelabel", x: 2 + indent, y: yy + aH / 2 + 4 }, text));
        for (const a of r.items) {
          const ya = yy + a.row * aH;
          const xa = x(a.t0), xb = valid(a.t1) ? Math.max(xa + 2, x(a.t1)) : x1;
          root.append(markGroup({ title: a.tip.title, rows: a.tip.rows, sub: a.tip.sub },
            svg("rect", { class: `agentbar${valid(a.t1) ? "" : " open"}`, x: xa, y: ya + 2, width: xb - xa, height: aH - 4, rx: 2, style: `fill:${a.css}` }),
            svg("rect", { class: "hit", x: xa - 2, y: ya, width: xb - xa + 4, height: aH })));
        }
        yy += r.rows * aH;
      }
      return root;
    },
  });
}
