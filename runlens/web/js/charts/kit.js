/* charts/kit.js: the chart forms the dashboard uses, each built on chartCard (charts/frame.js).

   Every form draws at the card's pixel width with fixed font sizes, titles its axes with their units,
   keeps colour for one job (identity, magnitude, polarity), gives each mark a tooltip reachable by
   keyboard and touch, and hands its data to the table view and the CSV export. A form with nothing to
   draw says so; a form with one value becomes a stat instead of a one-bar chart. */

const rowH = () => (PREFS.density === "compact" ? 24 : 30);
const BAR = () => (PREFS.density === "compact" ? 12 : 16);

// A group that is one interactive mark: the visible shape first, then a larger invisible hit area.
function markGroup(info, ...kids) {
  return tipMark(svg("g", {}, ...kids), info);
}
// A bar growing from x0 to x1 (or a column from y0 up to y1), square at the baseline and rounded at the data end.
function barPath(x0, x1, y, hgt, r = 3) {
  const w = x1 - x0;
  if (w <= 0.5) return svg("rect", { x: x0, y, width: Math.max(w, 1), height: hgt });
  const rr = Math.min(r, w, hgt / 2);
  return svg("path", { d: `M${x0},${y}H${x1 - rr}Q${x1},${y} ${x1},${y + rr}V${y + hgt - rr}Q${x1},${y + hgt} ${x1 - rr},${y + hgt}H${x0}Z` });
}
function colPath(x, w, yBase, yTop, r = 3) {
  const hh = yBase - yTop;
  if (hh <= 0.5) return svg("rect", { x, y: yBase - Math.max(hh, 0), width: w, height: Math.max(hh, 0) });
  const rr = Math.min(r, w / 2, hh);
  return svg("path", { d: `M${x},${yBase}V${yTop + rr}Q${x},${yTop} ${x + rr},${yTop}H${x + w - rr}Q${x + w},${yTop} ${x + w},${yTop + rr}V${yBase}Z` });
}
const valid = (v) => v !== null && v !== undefined && Number.isFinite(v);
const entityDot = (ns, name, cx, cy) => {
  const c = colourOf(ns, name);
  return marker(c.shape, cx, cy, 4.5, { class: "edot", style: `fill:${c.css}` });
};

// A single value where a chart would have one bar or a two-slice donut.
function statCard(title, label, value, sub, notes) {
  return h("figure", { class: "card stat-card" }, h("figcaption", { class: "cardtitle" }, title),
    h("div", { class: "kpis single" }, kpi(label, value, sub)), [notes].flat().filter(Boolean).map((n) => (n instanceof Node ? n : note(n))));
}
const emptyCard = (title, text, notes) => h("figure", { class: "card" }, h("figcaption", { class: "cardtitle" }, title), empty(text),
  [notes].flat().filter(Boolean).map((n) => (n instanceof Node ? n : note(n))));

/* ---- horizontal bars: one value per category ----
   spec: {title, sub, notes, items: [{label, value, ns, href, sub}], fmt, valueTitle, share, sort = true, colour, single} */
function barChart(spec) {
  const fmtv = spec.fmt || fmt.num;
  let items = spec.items.filter((i) => valid(i.value));
  if (spec.sort !== false) items = [...items].sort((a, b) => b.value - a.value);
  if (!items.length) return emptyCard(spec.title, spec.emptyText || "Nothing recorded for this yet.", spec.notes);
  const total = items.reduce((n, i) => n + i.value, 0);
  const shareOf = (v) => (spec.share && total ? ` · ${fmt.pct(v / total, v / total < 0.1 ? 1 : 0)}` : "");
  if (items.length === 1 && spec.single !== false) {
    const it = items[0];
    return statCard(spec.title, it.label, fmtv(it.value), spec.singleSub || spec.sub || "the only one recorded", spec.notes);
  }
  const tableCols = [{ label: spec.labelTitle || "Item", value: (i) => i.label },
    { label: spec.valueTitle || "Value", num: true, value: (i) => i.value, cell: (i) => fmtv(i.value) }];
  if (spec.share) tableCols.push({ label: "Share", num: true, value: (i) => (total ? i.value / total : null), cell: (i) => fmt.pct(total ? i.value / total : null) });
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: items.length * rowH() + 50,
    table: () => ({ cols: tableCols, rows: items }),
    draw(w) {
      const R = rowH(), dotW = spec.ns ? 18 : 0;
      const labelW = Math.min(maxLabel(items.map((i) => i.label), FONT.label) + 12 + dotW, Math.max(90, w * 0.36));
      const textOf = (i) => i.text || fmtv(i.value) + shareOf(i.value);
      const valW = Math.min(maxLabel(items.map(textOf), FONT.axis) + 10, w * 0.4);
      const x0 = labelW, x1 = Math.max(x0 + 40, w - valW - 4);
      const top = 6, H = top + items.length * R + 40;
      const { max, ticks: tk } = niceMax(Math.max(...items.map((i) => i.value)), Math.max(2, Math.floor((x1 - x0) / 90)), items.every((i) => Number.isInteger(i.value)));
      const x = scaleLinear(0, max, x0, x1);
      const root = svgRoot(w, H, `${spec.title}: ${items.length} bars, largest ${items[0].label} ${fmtv(items[0].value)}`);
      axisX(root, { scale: x, ticks: tk, fmt: spec.tickFmt || fmtv, x0, x1, y: top + items.length * R, grid: true, gridTop: top, title: spec.valueTitle });
      items.forEach((it, i) => {
        const y = top + i * R, bh = Math.min(BAR(), R - 8);
        const label = fitText(it.label, labelW - 12 - dotW, FONT.label);
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: y + R / 2 + 4, "text-anchor": "end" }, label));
        if (spec.ns) root.append(entityDot(spec.ns, it.name ?? it.label, labelW - 10 - textWidth(label, FONT.label) - 10, y + R / 2));
        const bar = barPath(x0, x(it.value), y + (R - bh) / 2, bh);
        bar.setAttribute("class", "bar");
        if (spec.colour || it.css) bar.setAttribute("style", `fill:${it.css || spec.colour}`);
        root.append(markGroup({ title: it.label, rows: [[spec.valueTitle || "Value", fmtv(it.value)], ...(spec.share && total ? [["Share", fmt.pct(it.value / total)]] : []), ...(it.rows || [])], sub: it.sub, href: it.href },
          bar, svg("rect", { class: "hit", x: 0, y, width: w, height: R })));
        root.append(svg("text", { class: "value", x: x(it.value) + 6, y: y + R / 2 + 4 }, fitText(textOf(it), w - x(it.value) - 8, FONT.axis)));
      });
      return root;
    },
  });
}

/* ---- horizontal stacked bars: parts of a whole per category ----
   spec: {title, rows: [{label, parts: {seriesKey: value}}], series: [{key, label, css}], fmt, mode: "abs" | "share", valueTitle} */
function stackChart(spec) {
  const fmtv = spec.fmt || fmt.num;
  const series = spec.series;
  const rows = spec.rows.map((r) => ({ ...r, total: series.reduce((n, s) => n + (r.parts[s.key] || 0), 0) })).filter((r) => r.total > 0);
  if (!rows.length) return emptyCard(spec.title, "Nothing recorded for this yet.", spec.notes);
  const share = spec.mode === "share";
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: rows.length * rowH() + 50,
    legend: () => legend(series.map((s) => ({ label: s.label, css: s.css }))),
    table: () => ({
      cols: [{ label: spec.labelTitle || "Item", value: (r) => r.label },
        ...series.map((s) => ({ label: s.label, num: true, value: (r) => r.parts[s.key] || 0, cell: (r) => fmtv(r.parts[s.key] || 0) })),
        { label: "Total", num: true, value: (r) => r.total, cell: (r) => fmtv(r.total) }],
      rows,
    }),
    draw(w) {
      const R = rowH();
      const labelW = Math.min(maxLabel(rows.map((r) => r.label), FONT.label) + 12, Math.max(90, w * 0.32));
      const valW = maxLabel(rows.map((r) => fmtv(r.total)), FONT.axis) + 10;
      const x0 = labelW, x1 = Math.max(x0 + 40, w - valW - 4);
      const top = 6, H = top + rows.length * R + 40;
      const nm = share ? { max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] } : niceMax(Math.max(...rows.map((r) => r.total)), Math.max(2, Math.floor((x1 - x0) / 90)), rows.every((r) => Number.isInteger(r.total)));
      const x = scaleLinear(0, nm.max, x0, x1);
      const root = svgRoot(w, H, `${spec.title}: ${rows.length} stacked bars`);
      axisX(root, { scale: x, ticks: nm.ticks, fmt: share ? (v) => fmt.pct(v, 0) : spec.tickFmt || fmtv, x0, x1, y: top + rows.length * R, grid: true, gridTop: top,
        title: share ? "Share of the total" : spec.valueTitle });
      rows.forEach((r, i) => {
        const y = top + i * R, bh = Math.min(BAR() + 2, R - 8), yb = y + (R - bh) / 2;
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: y + R / 2 + 4, "text-anchor": "end" }, fitText(r.label, labelW - 12, FONT.label)));
        let acc = 0;
        for (const s of series) {
          const v = r.parts[s.key] || 0;
          if (v <= 0) continue;
          const a = x(share ? acc / r.total : acc), b = x(share ? (acc + v) / r.total : acc + v);
          acc += v;
          const seg = svg("rect", { class: "seg", x: a, y: yb, width: Math.max(0.5, b - a), height: bh, style: `fill:${s.css}` });
          const kids = [seg];
          const txt = share ? fmt.pct(v / r.total, 0) : fmtv(v);
          if (b - a > textWidth(txt, FONT.small) + 10) {
            kids.push(svg("text", { class: "inlabel", x: (a + b) / 2, y: yb + bh / 2 + 4, "text-anchor": "middle", style: `fill:${inkOn(resolveCss(s.css))}` }, txt));
          }
          root.append(markGroup({ title: `${r.label} · ${s.label}`, rows: [["Value", fmtv(v), s.css], ["Share of this bar", fmt.pct(v / r.total)]] }, ...kids));
        }
        root.append(svg("text", { class: "value", x: (share ? x1 : x(r.total)) + 6, y: y + R / 2 + 4 }, fmtv(r.total)));
      });
      return root;
    },
  });
}
// A CSS colour expression (var(--c3)) as the hex the theme gives it, for luminance decisions.
function resolveCss(css) {
  const m = /^var\((--[\w-]+)\)$/.exec(css || "");
  return m ? cssVar(m[1]) || "#888888" : css || "#888888";
}

/* ---- columns over calendar days: one column per day (stacked by series when given) ----
   spec: {title, days: [{day: "YYYY-MM-DD", parts: {key: value}}], series: [{key, label, css}] | null, fmt, yTitle, tipRows(day)} */
function dayColumns(spec) {
  const fmtv = spec.fmt || fmt.num;
  const series = spec.series || [{ key: "value", label: spec.yTitle || "Value", css: "var(--c1)" }];
  const byDay = new Map(spec.days.map((d) => [d.day, d]));
  const keys = [...byDay.keys()].sort();
  if (!keys.length) return emptyCard(spec.title, "Nothing recorded for this yet.", spec.notes);
  const all = [];
  for (let t = dayMs(keys[0]); t <= dayMs(keys[keys.length - 1]); t += DAY) {
    const key = new Date(t).toISOString().slice(0, 10);
    const d = byDay.get(key) || { day: key, parts: {} };
    all.push({ ...d, t, total: series.reduce((n, s) => n + (d.parts[s.key] || 0), 0) });
  }
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: 240,
    legend: spec.series && spec.series.length > 1 ? () => legend(series.map((s) => ({ label: s.label, css: s.css }))) : null,
    table: () => ({
      cols: [{ label: "Day", value: (d) => d.day, cell: (d) => fmt.dayKey(d.day) },
        ...series.map((s) => ({ label: s.label, num: true, value: (d) => d.parts[s.key] || 0, cell: (d) => fmtv(d.parts[s.key] || 0) })),
        ...(series.length > 1 ? [{ label: "Total", num: true, value: (d) => d.total, cell: (d) => fmtv(d.total) }] : [])],
      rows: all,
    }),
    draw(w) {
      const top = 26, bottom = 42, H = 250;
      const nm = niceMax(Math.max(...all.map((d) => d.total)), 4, spec.whole || all.every((d) => Number.isInteger(d.total)));
      const tickLabels = nm.ticks.map((t) => (spec.tickFmt || fmtv)(t));
      const x0 = maxLabel(tickLabels) + 12, x1 = w - 8;
      const y = scaleLinear(0, nm.max, H - bottom, top);
      const slot = (x1 - x0) / all.length, cw = Math.max(2, Math.min(24, slot * 0.7));
      const root = svgRoot(w, H, `${spec.title}: ${all.length} days, highest ${fmtv(Math.max(...all.map((d) => d.total)))}`);
      axisY(root, { scale: y, ticks: nm.ticks, fmt: spec.tickFmt || fmtv, x0, x1, top, title: spec.yTitle, labelWidth: x0 - 12 });
      const every = Math.max(1, Math.ceil(56 / slot));
      axisX(root, { scale: (i) => x0 + slot * i + slot / 2, ticks: all.map((d, i) => ({ v: i, label: i % every === 0 ? fmt.dayKey(d.day) : "" })).filter((t) => t.label),
        x0, x1, y: H - bottom, title: "Day" });
      all.forEach((d, i) => {
        const cx = x0 + slot * i + (slot - cw) / 2;
        let acc = 0;
        const kids = [];
        for (const s of series) {
          const v = d.parts[s.key] || 0;
          if (v <= 0) continue;
          const isTop = series.slice(series.indexOf(s) + 1).every((q) => !(d.parts[q.key] > 0));
          const seg = isTop ? colPath(cx, cw, y(acc), y(acc + v)) : svg("rect", { x: cx, y: y(acc + v), width: cw, height: Math.max(0, y(acc) - y(acc + v)) });
          seg.setAttribute("class", "seg");
          seg.setAttribute("style", `fill:${s.css}`);
          kids.push(seg);
          acc += v;
        }
        kids.push(svg("rect", { class: "hit", x: x0 + slot * i, y: top, width: slot, height: H - bottom - top }));
        const rows = series.length > 1
          ? series.filter((s) => d.parts[s.key] > 0).map((s) => [s.label, fmtv(d.parts[s.key]), s.css]).concat([["Total", fmtv(d.total)]])
          : [[spec.yTitle || "Value", fmtv(d.total)]];
        root.append(markGroup({ title: fmt.dayKey(d.day), rows: rows.concat(spec.tipRows ? spec.tipRows(d) : []) }, ...kids));
      });
      return root;
    },
  });
}

/* ---- scatter: two measures, one dot per item; numbers, logs or time across ----
   spec: {title, points: [{x, y, ns, name, css, shape, r, label, tip: {title, rows}, href}],
          x: {title, fmt, log, time}, y: {title, fmt, log, ref, refLabel}, labels, vlines: [{t, label}], legendItems, sizeNote} */
function scatterChart(spec) {
  const pts = spec.points.filter((p) => valid(p.x) && valid(p.y) && (!spec.x.log || p.x > 0) && (!spec.y.log || p.y > 0));
  if (!pts.length) return emptyCard(spec.title, spec.emptyText || "Not enough data for this chart yet.", spec.notes);
  const fx = spec.x.fmt || fmt.num, fy = spec.y.fmt || fmt.num;
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: 300, n: spec.n, minN: spec.minN,
    legend: spec.legendItems ? () => legend(spec.legendItems) : null,
    table: () => ({
      cols: [{ label: spec.labelTitle || "Item", value: (p) => p.label },
        { label: spec.x.title, num: !spec.x.time, value: (p) => (spec.x.time ? new Date(p.x).toISOString() : p.x), cell: (p) => (spec.x.time ? fmt.when(new Date(p.x).toISOString()) : fx(p.x)) },
        { label: spec.y.title, num: true, value: (p) => p.y, cell: (p) => fy(p.y) },
        ...(spec.extraCols || [])],
      rows: pts,
    }),
    draw(w) {
      const H = Math.max(240, Math.min(380, Math.round(w * 0.5)));
      const top = 28, bottom = 44, right = spec.labels ? 16 : 12;
      const ys = pts.map((p) => p.y).concat(spec.y.ref != null ? [spec.y.ref] : []);
      let y, yt;
      if (spec.y.log) {
        const lo = Math.min(...ys) / 1.25, hi = Math.max(...ys) * 1.25;
        yt = logTicks(lo, hi);
        y = scaleLog(lo, hi, H - bottom, top);
      } else if (spec.y.fit) {
        const lo = Math.min(...ys), hi = Math.max(...ys), pad = (hi - lo) * 0.12 || 5;
        yt = ticks(lo - pad, hi + pad, 5);
        y = scaleLinear(Math.min(lo - pad, yt[0]), Math.max(hi + pad, yt[yt.length - 1]), H - bottom, top);
      } else {
        const nm = niceMax(Math.max(...ys) * 1.04, 5);
        yt = nm.ticks;
        y = scaleLinear(0, nm.max, H - bottom, top);
      }
      const yLabels = yt.map(fy);
      const x0 = maxLabel(yLabels) + 12, x1 = w - right;
      const xs = pts.map((p) => p.x);
      let x, xt;
      if (spec.x.time) {
        const a = Math.min(...xs), b = Math.max(...xs), pad = Math.max(DAY * 0.5, (b - a) * 0.04);
        x = scaleLinear(a - pad, b + pad, x0 + 8, x1 - 8);
        xt = timeTicks(a - pad, b + pad, Math.max(2, Math.floor((x1 - x0) / 80))).map((t) => ({ v: t.t, label: t.label }));
      } else if (spec.x.log) {
        const lo = Math.min(...xs) / 1.3, hi = Math.max(...xs) * 1.3;
        x = scaleLog(lo, hi, x0 + 8, x1 - 8);
        xt = logTicks(lo, hi).map((v) => ({ v, label: fx(v) }));
      } else {
        const nm = niceMax(Math.max(...xs) * 1.04, Math.max(2, Math.floor((x1 - x0) / 90)));
        x = scaleLinear(0, nm.max, x0, x1);
        xt = nm.ticks.map((v) => ({ v, label: fx(v) }));
      }
      const root = svgRoot(w, H, `${spec.title}: ${pts.length} points`);
      axisY(root, { scale: y, ticks: yt, fmt: fy, x0, x1, top, title: spec.y.title, ref: spec.y.ref, labelWidth: x0 - 12 });
      axisX(root, { scale: x, ticks: xt, x0, x1, y: H - bottom, title: spec.x.title, grid: spec.x.log || spec.x.time, gridTop: top });
      if (spec.y.ref != null && !yt.includes(spec.y.ref)) {
        root.append(svg("line", { class: "ref", x1: x0, x2: x1, y1: y(spec.y.ref), y2: y(spec.y.ref) }));
      }
      if (spec.y.ref != null && spec.y.refLabel) root.append(svg("text", { class: "reflabel", x: x1 - 4, y: y(spec.y.ref) - 5, "text-anchor": "end" }, spec.y.refLabel));
      placeVlines(root, spec.vlines || [], x, x0, x1, top, H - bottom);
      // The Pareto frontier: the points no other point beats on both axes (cheaper and better at once).
      if (spec.frontier) {
        const lowX = spec.frontier.x !== "high", highY = spec.frontier.y !== "low";
        const sorted = [...pts].sort((a, b) => (lowX ? a.x - b.x : b.x - a.x) || (highY ? b.y - a.y : a.y - b.y));
        const front = [];
        for (const p of sorted) if (!front.length || (highY ? p.y > front[front.length - 1].y : p.y < front[front.length - 1].y)) front.push(p);
        if (front.length > 1) {
          const d = front.map((p, i) => (i ? `H${x(p.x)}V${y(p.y)}` : `M${x(p.x)},${y(p.y)}`)).join("");
          root.append(svg("path", { class: "frontier", d }));
        }
        for (const p of front) p.onFront = true;
      }
      // Bigger points first, so small ones stay on top and reachable.
      const order = [...pts].sort((a, b) => (b.r || 5) - (a.r || 5));
      const placed = [];
      for (const p of order) {
        const cx = x(p.x), cy = y(p.y), r = p.r || 5;
        const c = p.ns ? colourOf(p.ns, p.name ?? p.label) : { css: p.css || "var(--c1)", shape: p.shape || "circle" };
        root.append(markGroup({ title: p.tip ? p.tip.title : p.label, rows: p.tip ? p.tip.rows : [[spec.x.title, fx(p.x)], [spec.y.title, fy(p.y)]], href: p.href, sub: p.tip && p.tip.sub },
          marker(p.shape || c.shape, cx, cy, r, { class: `dot${p.hollow ? " hollow" : ""}`, style: p.hollow ? `stroke:${c.css}` : `fill:${c.css}` }),
          svg("circle", { class: "hit", cx, cy, r: Math.max(12, r + 5) })));
        placed.push({ p, cx, cy, r });
      }
      // Direct labels where they fit without touching another label or leaving the plot.
      if (spec.labels) {
        const boxes = [];
        for (const q of placed.sort((a, b) => b.p.y - a.p.y)) {
          const text = q.p.label;
          const tw = textWidth(text, FONT.small);
          for (const [dx, dy, anchor] of [[0, -q.r - 6, "middle"], [q.r + 5, 4, "start"], [-q.r - 5, 4, "end"], [0, q.r + 14, "middle"]]) {
            const lx = anchor === "middle" ? q.cx - tw / 2 : anchor === "start" ? q.cx + dx : q.cx + dx - tw;
            const ly = q.cy + dy - 10;
            const box = [lx - 2, ly, lx + tw + 2, ly + 13];
            if (box[0] < x0 || box[2] > x1 || box[1] < top - 4 || box[3] > H - bottom) continue;
            if (boxes.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
            if (placed.some((o) => o !== q && Math.hypot(o.cx - (box[0] + box[2]) / 2, o.cy - (box[1] + box[3]) / 2) < o.r + 4)) continue;
            boxes.push(box);
            root.append(svg("text", { class: "dlabel", x: q.cx + dx, y: q.cy + dy, "text-anchor": anchor }, text));
            break;
          }
        }
      }
      return root;
    },
  });
}

/* ---- range plot: each row's score as a dot and its likely range as a bar, against a reference ----
   spec: {title, rows: [{label, score, ci, tone, word, href, ns, name, partial}], ref, axisTitle}
   Rows without a range are set apart below, marked as too few runs, so they never read as a ranking. */
function rangeChart(spec) {
  const scored = spec.rows.filter((r) => r.score != null);
  const ranged = scored.filter((r) => r.ci).sort((a, b) => b.score - a.score);
  const bare = scored.filter((r) => !r.ci).sort((a, b) => b.score - a.score);
  if (!scored.length) return emptyCard(spec.title, "No score yet.", spec.notes);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes,
    height: (ranged.length + bare.length) * rowH() + 100,
    legend: () => toneLegend(tonesIn(scored.map((r) => r.tone || "unclear"))),
    table: () => ({
      cols: [{ label: spec.labelTitle || "Item", value: (r) => r.label }, { label: "Score", num: true, value: (r) => r.score, cell: (r) => fmt.score(r.score) },
        { label: "Range low", num: true, value: (r) => (r.ci ? r.ci[0] : null), cell: (r) => (r.ci ? fmt.score(r.ci[0]) : "—") },
        { label: "Range high", num: true, value: (r) => (r.ci ? r.ci[1] : null), cell: (r) => (r.ci ? fmt.score(r.ci[1]) : "—") },
        { label: "Verdict", value: (r) => r.word }],
      rows: ranged.concat(bare),
    }),
    draw(w) {
      const R = rowH() + 2, top = 44, gap = bare.length && ranged.length ? 30 : 0;
      const H = top + (ranged.length + bare.length) * R + gap + 44;
      const dotW = scored.some((r) => r.ns) ? 18 : 0;
      const labelW = Math.min(maxLabel(scored.map((r) => r.label), FONT.label) + 14 + dotW, Math.max(90, w * 0.32));
      const short = (r) => (TONE[r.tone] || TONE.unclear).word;
      const valText = (r) => `${fmt.score(r.score)}  ${(TONE[r.tone] || TONE.unclear).icon} ${w >= 720 ? r.word : short(r)}`;
      const verdictW = Math.min(maxLabel(scored.map(valText), FONT.axis) + 18, Math.max(110, w * 0.3));
      const x0 = labelW, x1 = Math.max(x0 + 60, w - verdictW);
      const xs = scored.flatMap((r) => (r.ci ? r.ci : [r.score])).concat(spec.ref);
      const lo = Math.min(...xs), hi = Math.max(...xs), pad = Math.max(4, (hi - lo) * 0.06);
      const tk = ticks(lo - pad, hi + pad, Math.max(3, Math.floor((x1 - x0) / 70)));
      const x = scaleLinear(Math.min(lo - pad, tk[0]), Math.max(hi + pad, tk[tk.length - 1]), x0, x1);
      const root = svgRoot(w, H, `${spec.title}: ${scored.length} rows; ${spec.ref} is ${spec.refLabel || "the reference"}`);
      const yEnd = top + (ranged.length + bare.length) * R + gap;
      axisX(root, { scale: x, ticks: tk, fmt: fmt.score, x0, x1, y: yEnd, grid: true, gridTop: top - 6, ref: spec.ref, title: spec.axisTitle });
      root.append(svg("text", { class: "reflabel strongref", x: x(spec.ref), y: top - 24, "text-anchor": "middle" }, `${spec.ref} = ${spec.refLabel || "reference"}`));
      root.append(svg("text", { class: "dirlabel", x: x(spec.ref) - 8, y: top - 8, "text-anchor": "end" }, spec.leftLabel || "◀ worse"),
        svg("text", { class: "dirlabel", x: x(spec.ref) + 8, y: top - 8 }, spec.rightLabel || "better ▶"));
      const row = (r, i, yOff) => {
        const y = yOff + i * R + R / 2;
        const t = TONE[r.tone] || TONE.unclear;
        const label = fitText(r.label, labelW - 14 - dotW, FONT.label);
        root.append(svg("text", { class: "rowlabel", x: labelW - 12, y: y + 4, "text-anchor": "end" }, label));
        if (r.ns) root.append(entityDot(r.ns, r.name ?? r.label, labelW - 12 - textWidth(label, FONT.label) - 10, y));
        const kids = [];
        if (r.ci) kids.push(svg("line", { class: "range", x1: x(r.ci[0]), x2: x(r.ci[1]), y1: y, y2: y, style: `stroke:${t.css}` }));
        kids.push(marker(r.ci ? "circle" : "circle", x(r.score), y, 5.5, { class: `dot${r.ci ? "" : " hollow"}`, style: r.ci ? `fill:${t.css}` : `stroke:${t.css}` }));
        kids.push(svg("rect", { class: "hit", x: x0 - 4, y: y - R / 2, width: x1 - x0 + 8, height: R }));
        root.append(markGroup({ title: r.label, rows: [["Score", fmt.score(r.score)], [`Likely range (${pctOf()}%)`, r.ci ? fmt.interval(r.ci) : "none: too few runs"], ["Verdict", `${t.icon} ${r.word}`]], href: r.href }, ...kids));
        root.append(svg("text", { class: "value", x: x1 + 12, y: y + 4 }, fitText(valText(r), w - x1 - 14, FONT.axis)));
      };
      ranged.forEach((r, i) => row(r, i, top));
      if (bare.length) {
        const yb = top + ranged.length * R + gap;
        if (ranged.length) {
          root.append(svg("line", { class: "sep", x1: 0, x2: w, y1: yb - gap / 2 - 4, y2: yb - gap / 2 - 4 }));
          root.append(svg("text", { class: "sectionlabel", x: 0, y: yb - 6 }, "Too few runs for a range: a point score only"));
        }
        bare.forEach((r, i) => row(r, i, yb));
      }
      return root;
    },
  });
}

/* ---- heatmap: rows by columns, each cell coloured by a diverging or sequential scale ----
   spec: {title, rows: [{key, label, href}], cols: [{key, label, sub}], cell(r, c) -> {t, text, tip: {title, rows}, dim} | null,
          scale: "div" | "seq", legendText: [low, high]} */
function heatmap(spec) {
  if (!spec.rows.length || !spec.cols.length) return emptyCard(spec.title, "Nothing recorded for this yet.", spec.notes);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: spec.rows.length * 32 + 60,
    legend: () => scaleLegend(spec.scale, spec.legendText),
    table: () => ({
      cols: [{ label: spec.rowTitle || "Row", value: (r) => r.label },
        ...spec.cols.map((c) => ({ label: c.label, num: true, value: (r) => { const v = spec.cell(r, c); return v ? v.raw ?? v.t : null; }, cell: (r) => { const v = spec.cell(r, c); return v ? v.text : "—"; } }))],
      rows: spec.rows,
    }),
    draw(w) {
      const S = scales();
      const labelW = Math.min(maxLabel(spec.rows.map((r) => r.label), FONT.label) + 14, Math.max(80, w * 0.3));
      const head = 34, RH = PREFS.density === "compact" ? 26 : 32;
      const cellW = Math.max(52, Math.min(120, (w - labelW) / spec.cols.length));
      const W = Math.max(w, labelW + cellW * spec.cols.length);
      const H = head + spec.rows.length * RH + 6;
      const root = svgRoot(W, H, `${spec.title}: ${spec.rows.length} rows by ${spec.cols.length} columns`);
      if (spec.corner) root.append(svg("text", { class: "colsub", x: labelW - 8, y: head - 7, "text-anchor": "end" }, fitText(spec.corner, labelW - 10, FONT.small)));
      spec.cols.forEach((c, j) => {
        const cx = labelW + j * cellW + cellW / 2;
        root.append(svg("text", { class: "colhead", x: cx, y: c.sub ? head - 20 : head - 10, "text-anchor": "middle" }, fitText(c.label, cellW - 4, FONT.small, 600)));
        if (c.sub) root.append(svg("text", { class: "colsub", x: cx, y: head - 7, "text-anchor": "middle" }, fitText(c.sub, cellW - 4, FONT.small)));
      });
      spec.rows.forEach((r, i) => {
        const y0 = head + i * RH;
        root.append(svg("text", { class: "rowlabel", x: labelW - 8, y: y0 + RH / 2 + 4, "text-anchor": "end" }, fitText(r.label, labelW - 12, FONT.label)));
        spec.cols.forEach((c, j) => {
          const v = spec.cell(r, c);
          const x0 = labelW + j * cellW;
          const fill = v ? (spec.scale === "div" ? S.div(v.t) : S.seq(v.t)) : S.empty;
          const kids = [svg("rect", { class: `cell${v && v.dim ? " dim" : ""}${v ? "" : " none"}`, x: x0 + 1, y: y0 + 1, width: cellW - 2, height: RH - 2, rx: 3, style: `fill:${fill}` })];
          if (v && v.text) kids.push(svg("text", { class: "celltext", x: x0 + cellW / 2, y: y0 + RH / 2 + 4, "text-anchor": "middle", style: `fill:${inkOn(fill)}` }, fitText(v.text, cellW - 6, FONT.small)));
          if (v && v.dim) kids.push(svg("path", { class: "hatch", d: `M${x0 + cellW - 12},${y0 + 3}L${x0 + cellW - 3},${y0 + 3}L${x0 + cellW - 3},${y0 + 12}Z`, style: `fill:${inkOn(fill)}` }));
          root.append(v ? markGroup({ title: `${r.label} · ${c.label}`, rows: v.tip ? v.tip : [["Value", v.text]], href: r.href }, ...kids) : kids[0]);
        });
      });
      return root;
    },
  });
}
// The key of a colour scale, as a small gradient bar with its two ends named.
function scaleLegend(kind, text) {
  const S = scales();
  const stops = kind === "div" ? [-1, -0.5, 0, 0.5, 1].map((t) => S.div(t)) : [0, 0.25, 0.5, 0.75, 1].map((t) => S.seq(t));
  return h("div", { class: "scalekey" }, h("span", {}, text ? text[0] : "less"),
    h("span", { class: "ramp", style: `background:linear-gradient(90deg,${stops.join(",")})`, "aria-hidden": "true" }),
    h("span", {}, text ? text[1] : "more"),
    text && text[2] ? h("span", { class: "muted" }, ` · ${text[2]}`) : null);
}

/* ---- diverging bars: a signed value per row around a centre line, better to the right ----
   spec: {title, rows: [{label, value, text, prev, tip}], domain, tickFmt, axisTitle, leftLabel, rightLabel} */
function divergingBars(spec) {
  const rows = spec.rows.filter((r) => valid(r.value));
  if (!rows.length) return emptyCard(spec.title, "Nothing to compare yet.", spec.notes);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: rows.length * rowH() + 70, n: spec.n, minN: spec.minN,
    legend: spec.legendItems ? () => legend(spec.legendItems) : () => toneLegend(["better", "worse"]),
    table: () => ({ cols: [{ label: "Measure", value: (r) => r.label }, { label: spec.axisTitle, num: true, value: (r) => r.value, cell: (r) => r.text }, ...(spec.extraCols || [])], rows }),
    draw(w) {
      const R = rowH(), top = 24;
      const labelW = Math.min(maxLabel(rows.map((r) => r.label), FONT.label) + 12, Math.max(90, w * 0.3));
      const valW = maxLabel(rows.map((r) => `▲ ${r.text}`), FONT.axis) + 14;
      const x0 = labelW, x1 = Math.max(x0 + 80, w - valW);
      const lim = spec.domain || Math.max(...rows.map((r) => Math.abs(r.value)), ...rows.map((r) => Math.abs(r.prev || 0)), 1e-6) * 1.1;
      const x = scaleLinear(-lim, lim, x0, x1);
      const H = top + rows.length * R + 44;
      const root = svgRoot(w, H, spec.title);
      const tk = spec.ticks || ticks(-lim, lim, Math.max(2, Math.floor((x1 - x0) / 80)));
      axisX(root, { scale: x, ticks: tk.map((v) => ({ v, label: spec.tickFmt(v), ref: v === 0 })), x0, x1, y: top + rows.length * R, grid: true, gridTop: top - 4, title: spec.axisTitle });
      let left = spec.leftLabel || "◀ worse", right = spec.rightLabel || "better ▶";
      if (textWidth(left, FONT.small) + textWidth(right, FONT.small) + 16 > x1 - x0) [left, right] = ["◀ worse", "better ▶"];
      root.append(svg("text", { class: "reflabel", x: x0, y: top - 10 }, left),
        svg("text", { class: "reflabel", x: x1, y: top - 10, "text-anchor": "end" }, right));
      rows.forEach((r, i) => {
        const y = top + i * R, bh = Math.min(BAR(), R - 10), yb = y + (R - bh) / 2;
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: y + R / 2 + 4, "text-anchor": "end" }, fitText(r.label, labelW - 12, FONT.label)));
        const tone = r.tone || (r.value > 0 ? "better" : r.value < 0 ? "worse" : "unclear");
        const a = x(0), b = x(Math.max(-lim, Math.min(lim, r.value)));
        const shape = b >= a ? barPath(a, b, yb, bh) : mirrorBar(a, b, yb, bh);
        shape.setAttribute("class", "bar");
        shape.setAttribute("style", `fill:${TONE[tone].css}`);
        const kids = [shape];
        if (valid(r.prev)) kids.push(svg("line", { class: "prevmark", x1: x(r.prev), x2: x(r.prev), y1: yb - 4, y2: yb + bh + 4 }));
        kids.push(svg("rect", { class: "hit", x: 0, y, width: w, height: R }));
        root.append(markGroup({ title: r.label, rows: r.tip || [[spec.axisTitle, r.text]] }, ...kids));
        root.append(svg("text", { class: "value", x: x1 + 6, y: y + R / 2 + 4 }, `${TONE[tone].icon} ${r.text}`));
      });
      return root;
    },
  });
}
function mirrorBar(a, b, y, hgt, r = 3) {
  const w = a - b;
  if (w <= 0.5) return svg("rect", { x: b, y, width: Math.max(w, 1), height: hgt });
  const rr = Math.min(r, w, hgt / 2);
  return svg("path", { d: `M${a},${y}H${b + rr}Q${b},${y} ${b},${y + rr}V${y + hgt - rr}Q${b},${y + hgt} ${b + rr},${y + hgt}H${a}Z` });
}

/* ---- versions on a real time axis: one panel per unit, each version a segment from first to last use ----
   spec: {title, facets: [{label, ns, name, href, versions: [{label, t0, t1, score, ci, runs, tone, text}]}], ref} */
function versionTimeline(spec) {
  const facets = spec.facets.map((f) => ({ ...f, versions: f.versions.filter((v) => v.score != null && valid(v.t0)) })).filter((f) => f.versions.length);
  if (!facets.length) return emptyCard(spec.title, spec.emptyText || "No version has a score yet.", spec.notes);
  const all = facets.flatMap((f) => f.versions);
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: facets.length > 1 ? 420 : 260,
    legend: () => {
      const l = toneLegend(tonesIn(all.map((v) => v.tone || "unclear")));
      l.prepend(h("li", {}, svg("svg", { class: "lkey", width: 16, height: 12, "aria-hidden": "true" }, svg("rect", { x: 1, y: 1, width: 14, height: 10, rx: 2, style: "fill:var(--neutral);opacity:.25" }),
        svg("line", { x1: 1, x2: 15, y1: 6, y2: 6, style: "stroke:var(--neutral)", "stroke-width": 2.5 })), "line = a version's score while it was in use; shaded band = its likely range"),
      h("li", {}, svg("svg", { class: "lkey", width: 16, height: 12, "aria-hidden": "true" }, svg("line", { class: "ref", x1: 1, x2: 15, y1: 6, y2: 6 })), `dashed line = ${spec.ref}, the usual level`));
      const kinds = new Set((spec.vlines || []).concat(facets.flatMap((f) => f.vlines || [])).map((v) => v.kind));
      const extra = [["cc", "Claude Code update"], ["model", "first use of a model"], ["skill", "another skill changed"]].filter(([k]) => kinds.has(k));
      if (extra.length) l.append(...extra.map(([k, t]) => h("li", {}, svg("svg", { class: "lkey", width: 16, height: 12, "aria-hidden": "true" },
        svg("line", { class: `vmark vm-${k}`, x1: 8, x2: 8, y1: 0, y2: 12 })), t)));
      return l;
    },
    table: () => ({
      cols: [{ label: "Unit", value: (v) => v.unit }, { label: "Version", value: (v) => v.label },
        { label: "First used", value: (v) => new Date(v.t0).toISOString(), cell: (v) => fmt.when(new Date(v.t0).toISOString()) },
        { label: "Last used", value: (v) => new Date(v.t1).toISOString(), cell: (v) => fmt.when(new Date(v.t1).toISOString()) },
        { label: "Runs", num: true, value: (v) => v.runs }, { label: "Score", num: true, value: (v) => v.score, cell: (v) => fmt.score(v.score) },
        { label: "Range low", num: true, value: (v) => (v.ci ? v.ci[0] : null) }, { label: "Range high", num: true, value: (v) => (v.ci ? v.ci[1] : null) },
        { label: "Against the version before", value: (v) => v.text || "first version" }],
      rows: facets.flatMap((f) => f.versions.map((v) => ({ ...v, unit: f.label }))),
    }),
    draw(w) {
      const cols = facets.length === 1 ? 1 : Math.max(1, Math.min(6, Math.floor(w / 250), facets.length));
      const fw = (w - (cols - 1) * 16) / cols;
      const fh = facets.length === 1 ? 230 : 140;
      const rowsN = Math.ceil(facets.length / cols);
      const H = rowsN * (fh + 34) + 8;
      const t0 = Math.min(...all.map((v) => v.t0)), t1 = Math.max(...all.map((v) => v.t1));
      const pad = Math.max(DAY * 0.6, (t1 - t0) * 0.05);
      const ys = all.flatMap((v) => (v.ci ? v.ci : [v.score])).concat(spec.ref);
      const lo = Math.min(...ys), hi = Math.max(...ys), ypad = Math.max(4, (hi - lo) * 0.08);
      const yt = ticks(lo - ypad, hi + ypad, facets.length > 1 ? 3 : 5);
      const root = svgRoot(w, H, `${spec.title}: ${facets.length} panels on a shared time axis`);
      facets.forEach((f, k) => {
        const ox = (k % cols) * (fw + 16), oy = Math.floor(k / cols) * (fh + 34);
        const g = svg("g", { transform: `translate(${ox},${oy})` });
        const yLabels = yt.map(fmt.score);
        const x0 = maxLabel(yLabels) + 10, x1 = fw - 10, top = 30, bottom = fh - 4;
        const x = scaleLinear(t0 - pad, t1 + pad, x0 + 6, x1 - 6);
        const y = scaleLinear(Math.min(lo - ypad, yt[0]), Math.max(hi + ypad, yt[yt.length - 1]), bottom, top);
        if (f.ns) g.append(entityDot(f.ns, f.name ?? f.label, 5, 10));
        const latest = [...f.versions].sort((a, b) => a.t0 - b.t0).pop();
        const lt = TONE[latest.tone] || TONE.unclear;
        const tx = f.ns ? 14 : 0;
        const name = fitText(f.label, fw - 20, FONT.label, 600);
        g.append(svg("text", { class: "facettitle", x: tx, y: 14 }, name));
        const verdictText = `${latest.label}: ${lt.icon} ${latest.text || "first version"}`;
        const room = fw - tx - textWidth(name, FONT.label, 600) - 14;
        if (room > 40) g.append(svg("text", { class: "facetsub", x: tx + textWidth(name, FONT.label, 600) + 8, y: 14 }, fitText(verdictText, room, FONT.small)));
        axisY(g, { scale: y, ticks: yt, fmt: fmt.score, x0, x1, top, ref: spec.ref });
        if (!yt.includes(spec.ref)) g.append(svg("line", { class: "ref", x1: x0, x2: x1, y1: y(spec.ref), y2: y(spec.ref) }));
        axisX(g, { scale: x, ticks: timeTicks(t0 - pad, t1 + pad, Math.max(2, Math.floor((x1 - x0) / 75))).map((t) => ({ v: t.t, label: t.label })), x0, x1, y: bottom });
        placeVlines(g, (spec.vlines || []).concat(f.vlines || []), x, x0, x1, top, bottom, facets.length === 1);
        // a thin step between consecutive versions, so the order reads at a glance
        const vs = [...f.versions].sort((a, b) => a.t0 - b.t0);
        for (let i = 1; i < vs.length; i += 1) {
          g.append(svg("path", { class: "vstep", d: `M${x(vs[i - 1].t1) + 3},${y(vs[i - 1].score)}L${x(vs[i].t0)},${y(vs[i].score)}` }));
        }
        vs.forEach((v) => {
          const a = x(v.t0), b = Math.max(a + 8, x(v.t1));
          const t = TONE[v.tone] || TONE.unclear;
          const kids = [];
          if (v.ci) kids.push(svg("rect", { class: "band", x: a, y: y(v.ci[1]), width: b - a, height: Math.max(1, y(v.ci[0]) - y(v.ci[1])), style: `fill:${t.css}` }));
          kids.push(svg("line", { class: "seg-line", x1: a, x2: b, y1: y(v.score), y2: y(v.score), style: `stroke:${t.css}` }));
          kids.push(marker("circle", b, y(v.score), 4.5, { class: v.ci ? "dot" : "dot hollow", style: v.ci ? `fill:${t.css}` : `stroke:${t.css}` }));
          kids.push(svg("rect", { class: "hit", x: a - 4, y: y(v.score) - 12, width: b - a + 8, height: 24 }));
          g.append(markGroup({ title: `${f.label} ${v.label}`, href: f.href,
            rows: [["Score", fmt.score(v.score)], [`Likely range (${pctOf()}%)`, v.ci ? fmt.interval(v.ci) : "none: too few runs"], ["In use", fmt.span(new Date(v.t0).toISOString(), new Date(v.t1).toISOString())],
              ["Runs", fmt.int(v.runs)], ["Against the version before", `${t.icon} ${v.text || "first version"}`]] }, ...kids));
          const lab = `${v.label}`;
          if (b - a > textWidth(lab, FONT.small) + 4 || vs.length <= 4) g.append(svg("text", { class: "vlabel", x: (a + b) / 2, y: y(v.score) - 8, "text-anchor": "middle" }, lab));
        });
        root.append(g);
      });
      return root;
    },
  });
}

/* ---- strip plot: every run as a dot, one row per group (version), with the median marked ----
   spec: {title, groups: [{label, values: [{v, tip, href}]}], fmt, axisTitle, log} */
function stripPlot(spec) {
  const groups = spec.groups.map((g) => ({ ...g, values: g.values.filter((p) => valid(p.v)) })).filter((g) => g.values.length);
  if (!groups.length) return emptyCard(spec.title, "No runs with this measure yet.", spec.notes);
  const fmtv = spec.fmt || fmt.num;
  const allV = groups.flatMap((g) => g.values.map((p) => p.v));
  const log = spec.log !== false && allV.every((v) => v > 0) && Math.max(...allV) / Math.min(...allV) > 30;
  return chartCard({
    title: spec.title, question: spec.question, takeaway: spec.takeaway, howto: spec.howto, legendInHowto: spec.legendInHowto, controls: spec.controls, sub: spec.sub, notes: spec.notes, height: groups.length * 44 + 60,
    table: () => ({
      cols: [{ label: "Group", value: (r) => r.group }, { label: spec.axisTitle, num: true, value: (r) => r.v, cell: (r) => fmtv(r.v) }, { label: "Run", value: (r) => (r.tip ? r.tip.title : "") }],
      rows: groups.flatMap((g) => g.values.map((p) => ({ ...p, group: g.label }))),
    }),
    draw(w) {
      const RH = PREFS.density === "compact" ? 36 : 44, top = 10;
      const labelW = Math.min(maxLabel(groups.map((g) => `${g.label}`), FONT.label) + 14, w * 0.3);
      const nW = maxLabel(groups.map((g) => `n = ${g.values.length}`), FONT.axis) + 14;
      const x0 = labelW, x1 = w - nW;
      let x, xt;
      if (log) {
        const lo = Math.min(...allV) / 1.3, hi = Math.max(...allV) * 1.3;
        x = scaleLog(lo, hi, x0 + 6, x1 - 6);
        xt = logTicks(lo, hi).map((v) => ({ v, label: (spec.tickFmt || fmtv)(v) }));
      } else {
        const nm = niceMax(Math.max(...allV) * 1.04, Math.max(2, Math.floor((x1 - x0) / 90)));
        x = scaleLinear(0, nm.max, x0, x1);
        xt = nm.ticks.map((v) => ({ v, label: (spec.tickFmt || fmtv)(v) }));
      }
      const H = top + groups.length * RH + 44;
      const root = svgRoot(w, H, `${spec.title}: ${allV.length} runs in ${groups.length} groups`);
      axisX(root, { scale: x, ticks: xt, x0, x1, y: top + groups.length * RH, grid: true, gridTop: top, title: `${spec.axisTitle}${log ? " (log scale)" : ""}` });
      groups.forEach((g, i) => {
        const yc = top + i * RH + RH / 2;
        root.append(svg("text", { class: "rowlabel", x: labelW - 10, y: yc + 4, "text-anchor": "end" }, fitText(g.label, labelW - 12, FONT.label)));
        const med = median(g.values.map((p) => p.v));
        root.append(svg("line", { class: "median", x1: x(med), x2: x(med), y1: yc - RH * 0.36, y2: yc + RH * 0.36 }));
        g.values.forEach((p, j) => {
          const jitter = (((j * 7919) % 13) / 12 - 0.5) * RH * 0.5;
          root.append(markGroup({ title: p.tip ? p.tip.title : g.label, rows: (p.tip ? p.tip.rows : []).concat([[spec.axisTitle, fmtv(p.v)]]), href: p.href },
            svg("circle", { class: "dot", cx: x(p.v), cy: yc + jitter, r: 4.5, style: `fill:${g.css || "var(--c1)"}` }),
            svg("circle", { class: "hit", cx: x(p.v), cy: yc + jitter, r: 11 })));
        });
        root.append(svg("text", { class: "value", x: x1 + 8, y: yc + 4 }, `n = ${g.values.length}`));
      });
      return root;
    },
    legend: () => legend([{ label: "one run", css: "var(--c1)", kind: "dot" }, { label: "median", css: "var(--text)", kind: "line" }]),
  });
}
