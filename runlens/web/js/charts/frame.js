/* charts/frame.js: the chart container every chart is drawn in, and the pieces charts share.

   A chart is drawn at the real pixel width of its card, never scaled: a ResizeObserver redraws it
   (debounced) when the card changes width, so text is the same size at 390 px and at 2500 px.
   A chart is only drawn once it is near the viewport and visible (IntersectionObserver), so hidden tabs
   and long pages cost nothing until they are looked at. Each card has a table view (the accessible twin
   of the chart), CSV of that table, and SVG / PNG of the drawing. */

const FRAMES = new Set();
const FRAME_OF = new WeakMap();
const FONT = { axis: 12, label: 12, small: 11, title: 12 };

const RO = typeof ResizeObserver === "function" ? new ResizeObserver((entries) => {
  for (const e of entries) {
    const f = FRAME_OF.get(e.target);
    if (f) f.resize(Math.floor(e.contentRect.width));
  }
}) : null;
const IO = typeof IntersectionObserver === "function" ? new IntersectionObserver((entries) => {
  for (const e of entries) {
    const f = FRAME_OF.get(e.target);
    if (!f) continue;
    f.near = e.isIntersecting;
    if (f.near) f.maybeDraw();
  }
}, { rootMargin: "400px 0px" }) : null;

// Redraw every chart on the page, for a change of theme, locale or density. Hidden ones redraw when shown.
function redrawAll() {
  for (const f of [...FRAMES]) {
    if (!f.el.isConnected) {
      FRAMES.delete(f);
      continue;
    }
    f.stale = true;
    f.maybeDraw();
  }
}

// Before printing, draw every chart (even those far below the fold) with the print colours.
function redrawForPrint() {
  for (const f of FRAMES) f.near = true;
  redrawAll();
}

/* spec: {
     title, sub (one line under the title: units, period), notes (string or nodes),
     draw(width) -> SVG element,       the drawing, at exactly `width` px wide
     table() -> {cols, rows},          the same data as a table: cols are {label, value(r), cell?(r), num, csv?(r)}
     legend() -> element,              an HTML legend under the plot (optional)
     height,                           expected height, reserved before the first draw
     n, minN                           sample size: under minN the chart says so and is drawn muted
     controls                          at most two small controls for this chart (a measure, a scale), in its header
     question                          the question the chart answers, shown under the title
   } */
function chartCard(spec) {
  const id = `c${Math.random().toString(36).slice(2, 9)}`;
  const plot = h("div", { class: "plot", style: `min-height:${spec.height || 180}px` });
  const tableBox = h("div", { class: "tableview", hidden: true });
  const tools = h("div", { class: "tools" });
  const fig = h("figure", { class: "card chart-card", "aria-labelledby": `${id}-t` },
    h("div", { class: "card-head" },
      h("div", { class: "card-titles" },
        h("figcaption", { class: "cardtitle", id: `${id}-t` }, spec.title),
        spec.question ? h("div", { class: "card-q" }, spec.question) : null,
        spec.sub ? h("div", { class: "card-sub" }, spec.sub) : null),
      spec.controls ? h("div", { class: "card-controls" }, spec.controls) : null,
      tools),
    spec.n != null && spec.minN && spec.n < spec.minN
      ? h("p", { class: "smalln" }, h("span", { "aria-hidden": "true" }, "○ "), `Only ${fmt.runs(spec.n)}: read this as a hint, not a result.`) : null,
    plot,
    spec.legend ? spec.legend() : null,
    tableBox,
    [spec.notes].flat().filter(Boolean).map((n) => (n instanceof Node ? n : note(n))));
  if (spec.n != null && spec.minN && spec.n < spec.minN) fig.classList.add("low-n");

  let exportButtons = [];
  const frame = {
    el: plot, width: 0, drawn: -1, near: !IO, stale: false, timer: null, svg: null,
    resize(w) {
      if (w < 40) return; // hidden (display:none) or not laid out yet
      this.width = w;
      clearTimeout(this.timer);
      if (this.drawn < 0) this.maybeDraw();
      else this.timer = setTimeout(() => this.maybeDraw(), 120);
    },
    maybeDraw() {
      if (!this.near || this.width < 40) return;
      if (!this.stale && Math.abs(this.width - this.drawn) < 2) return;
      this.stale = false;
      this.drawn = this.width;
      let node;
      try {
        node = spec.draw(this.width);
      } catch (err) {
        console.error(err);
        node = empty("This chart could not be drawn.");
      }
      if (node && node.tagName === "svg") {
        node.classList.add("chart");
        if (!node.getAttribute("role")) node.setAttribute("role", "group");
        if (!node.getAttribute("aria-label")) node.setAttribute("aria-label", spec.title);
        wireTips(node);
        this.svg = node;
      } else this.svg = null;
      plot.replaceChildren(node || empty("Nothing to draw."));
      plot.style.minHeight = "";
      exportButtons.forEach((b) => { b.disabled = !this.svg; });
    },
  };
  FRAME_OF.set(plot, frame);
  FRAMES.add(frame);
  if (RO) RO.observe(plot);
  else requestAnimationFrame(() => frame.resize(plot.clientWidth || 600));
  if (IO) IO.observe(plot);

  if (spec.table) {
    const toggle = h("button", { type: "button", class: "tool", "aria-pressed": "false", "aria-controls": `${id}-tv` }, "Table");
    tableBox.id = `${id}-tv`;
    toggle.addEventListener("click", () => {
      const on = tableBox.hidden;
      if (on && !tableBox.firstChild) {
        const t = spec.table();
        tableBox.append(sortTable({ caption: `${spec.title}: data`, cols: t.cols, rows: t.rows, sort: t.sort || null, csvName: spec.title }).el);
      }
      tableBox.hidden = !on;
      toggle.setAttribute("aria-pressed", String(on));
    });
    const csv = h("button", { type: "button", class: "tool", title: "Download the chart's data as CSV" }, "CSV");
    csv.addEventListener("click", () => {
      const t = spec.table();
      downloadCSV(spec.title, t.cols, t.rows);
    });
    tools.append(toggle, csv);
  }
  const svgBtn = h("button", { type: "button", class: "tool", title: "Download the chart as SVG" }, "SVG");
  svgBtn.addEventListener("click", () => frame.svg && exportSVG(frame.svg, spec.title));
  const pngBtn = h("button", { type: "button", class: "tool", title: "Download the chart as PNG" }, "PNG");
  pngBtn.addEventListener("click", () => frame.svg && exportPNG(frame.svg, spec.title));
  exportButtons = [svgBtn, pngBtn];
  tools.append(svgBtn, pngBtn);
  return fig;
}

// A card that is not a chart (a stat, a list) but sits in the same grid.
const card = (title, ...kids) => h("figure", { class: "card" }, h("figcaption", { class: "cardtitle" }, title), ...kids);

// ---- export: the SVG with its colours and fonts written in, so it looks the same outside the page ----

const STYLE_PROPS = ["fill", "fill-opacity", "stroke", "stroke-width", "stroke-dasharray", "stroke-opacity", "stroke-linecap",
  "stroke-linejoin", "opacity", "font-size", "font-weight", "font-family", "paint-order", "visibility", "display"];
function standalone(svgEl, title) {
  const clone = svgEl.cloneNode(true);
  const src = [svgEl, ...svgEl.querySelectorAll("*")];
  const dst = [clone, ...clone.querySelectorAll("*")];
  src.forEach((node, i) => {
    const cs = getComputedStyle(node);
    dst[i].setAttribute("style", STYLE_PROPS.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(";"));
    dst[i].removeAttribute("class");
    dst[i].removeAttribute("tabindex");
  });
  clone.setAttribute("xmlns", SVG_NS);
  const w = Number(svgEl.getAttribute("width")), hgt = Number(svgEl.getAttribute("height"));
  const bg = svg("rect", { x: 0, y: 0, width: w, height: hgt, fill: cssVar("--surface") || "#ffffff" });
  clone.insertBefore(bg, clone.firstChild);
  const t = document.createElementNS(SVG_NS, "title");
  t.textContent = title;
  clone.insertBefore(t, clone.firstChild);
  return { text: new XMLSerializer().serializeToString(clone), w, h: hgt };
}
function exportSVG(svgEl, title) {
  const s = standalone(svgEl, title);
  download(`${slug(title)}.svg`, new Blob([s.text], { type: "image/svg+xml" }));
}
function exportPNG(svgEl, title) {
  const s = standalone(svgEl, title);
  const scale = 2;
  const img = new Image();
  const url = URL.createObjectURL(new Blob([s.text], { type: "image/svg+xml" }));
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = s.w * scale;
    c.height = s.h * scale;
    const ctx = c.getContext("2d");
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    URL.revokeObjectURL(url);
    c.toBlob((blob) => blob && download(`${slug(title)}.png`, blob), "image/png");
  };
  img.src = url;
}

// ---- scales and ticks ----

function scaleLinear(d0, d1, r0, r1) {
  const span = d1 - d0 || 1;
  const f = (v) => r0 + ((v - d0) / span) * (r1 - r0);
  f.domain = [d0, d1];
  f.range = [r0, r1];
  return f;
}
function scaleLog(d0, d1, r0, r1) {
  const a = Math.log10(d0), b = Math.log10(d1);
  const f = (v) => r0 + ((Math.log10(Math.max(v, d0 / 10)) - a) / (b - a || 1)) * (r1 - r0);
  f.domain = [d0, d1];
  f.range = [r0, r1];
  f.log = true;
  return f;
}

// Readable tick values between lo and hi, about `count` of them.
function ticks(lo, hi, count, whole = false) {
  if (!(hi > lo)) return [lo];
  const pow = 10 ** Math.floor(Math.log10((hi - lo) / Math.max(1, count)));
  const step = (whole ? [1, 2, 5, 10] : [1, 2, 2.5, 5, 10]).map((m) => Math.max(m * pow, whole ? 1 : 0))
    .find((s) => (hi - lo) / s <= count) || pow * 10;
  const out = [];
  for (let t = Math.ceil(lo / step - 1e-9) * step; t <= hi + step / 1e6; t += step) out.push(Number(t.toPrecision(10)));
  return out;
}
// Zero to a round number above max, and its ticks.
function niceMax(max, count, whole = false) {
  const top = max > 0 ? max : 1;
  const t = ticks(0, top, count, whole);
  const last = t[t.length - 1];
  if (last < top) {
    const step = t.length > 1 ? t[1] - t[0] : top;
    t.push(Number((last + step).toPrecision(10)));
  }
  return { max: t[t.length - 1], ticks: t };
}
function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e += 1) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e;
      if (v >= lo * 0.999 && v <= hi * 1.001) out.push(Number(v.toPrecision(6)));
    }
  }
  const powers = out.filter((v) => Math.abs(Math.log10(v) % 1) < 1e-9);
  return out.length > 7 && powers.length >= 2 ? powers : out;
}
// Time ticks between a and b (ms), at most about `count`, on round hours, days, weeks or months.
function timeTicks(a, b, count) {
  const H = 36e5;
  const steps = [H, 3 * H, 6 * H, 12 * H, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 30 * DAY, 91 * DAY];
  const step = steps.find((s) => (b - a) / s <= count) || 182 * DAY;
  const out = [];
  if (step < DAY) {
    const off = new Date(a).getTimezoneOffset() * 6e4;
    for (let t = Math.ceil((a - off) / step) * step + off; t <= b; t += step) out.push({ t, label: fmt.hour(t) });
  } else {
    // local midnights, so a day tick sits where that day starts for the reader
    const d = new Date(a);
    d.setHours(0, 0, 0, 0);
    if (d.getTime() < a) d.setDate(d.getDate() + 1);
    const every = Math.round(step / DAY);
    for (; d.getTime() <= b; d.setDate(d.getDate() + every)) out.push({ t: d.getTime(), label: fmt.monthDay(d.getTime()) });
  }
  return out;
}

// ---- axes ----

// A vertical value axis: gridlines across the plot, tick labels on the left, the title above.
function axisY(root, o) {
  const g = svg("g", { class: "axis-y" });
  for (const t of o.ticks) {
    const y = o.scale(t);
    g.append(svg("line", { class: t === o.ref ? "ref" : "grid", x1: o.x0, x2: o.x1, y1: y, y2: y }));
    g.append(svg("text", { class: "tick", x: o.x0 - 6, y: y + 4, "text-anchor": "end" }, o.fmt(t)));
  }
  if (o.title) g.append(svg("text", { class: "axis-title", x: Math.max(2, o.x0 - (o.labelWidth || 0) - 6), y: o.top - 10 }, o.title));
  root.append(g);
}
// A horizontal axis: ticks as {v, label} or values, the title under them, right-aligned.
function axisX(root, o) {
  const g = svg("g", { class: "axis-x" });
  g.append(svg("line", { class: "baseline", x1: o.x0, x2: o.x1, y1: o.y, y2: o.y }));
  let lastRight = -Infinity;
  for (const t of o.ticks) {
    const v = typeof t === "object" ? t.v ?? t.t : t;
    const label = typeof t === "object" ? t.label : o.fmt(t);
    const x = o.scale(v);
    if (o.grid) g.append(svg("line", { class: t.ref || v === o.ref ? "ref" : "grid", x1: x, x2: x, y1: o.gridTop, y2: o.y }));
    const w = textWidth(label, FONT.axis);
    // A label that would run past the right edge is right-aligned to it; one that would touch its neighbour is skipped.
    const edge = x + w / 2 > o.x1 + 8;
    const left = edge ? o.x1 + 8 - w : x - w / 2;
    if (left < lastRight + 6 || left < o.x0 - 30 || (edge && x - o.x1 > 2)) continue;
    g.append(svg("text", { class: "tick", x: edge ? o.x1 + 8 : x, y: o.y + 16, "text-anchor": edge ? "end" : "middle" }, label));
    lastRight = left + w;
  }
  if (o.title) g.append(svg("text", { class: "axis-title", x: o.x1, y: o.y + 34, "text-anchor": "end" }, fitText(o.title, Math.max(60, o.x1 - 2), FONT.axis, 600)));
  root.append(g);
}
const maxLabel = (labels, size = FONT.axis) => Math.max(0, ...labels.map((l) => textWidth(l, size)));

// A filled marker: circle, square, triangle or diamond, so identity never rests on hue alone.
function marker(shape, cx, cy, r, attrs = {}) {
  if (shape === "square") return svg("rect", { x: cx - r * 0.9, y: cy - r * 0.9, width: r * 1.8, height: r * 1.8, rx: 1.5, ...attrs });
  if (shape === "triangle") return svg("path", { d: `M${cx},${cy - r * 1.15}L${cx + r * 1.1},${cy + r * 0.85}L${cx - r * 1.1},${cy + r * 0.85}Z`, ...attrs });
  if (shape === "diamond") return svg("path", { d: `M${cx},${cy - r * 1.25}L${cx + r * 1.15},${cy}L${cx},${cy + r * 1.25}L${cx - r * 1.15},${cy}Z`, ...attrs });
  return svg("circle", { cx, cy, r, ...attrs });
}

// The legend under a chart. items: {label, css, kind: "rect" | "line" | "dot", shape, dash}.
function legend(items, title) {
  if (!items.length) return null;
  return h("ul", { class: "legend", "aria-label": title || "Legend" }, items.map((it) => {
    const key = svg("svg", { class: "lkey", width: 16, height: 12, "aria-hidden": "true" });
    if (it.kind === "line") key.append(svg("line", { x1: 1, x2: 15, y1: 6, y2: 6, style: `stroke:${it.css}`, "stroke-width": 2, "stroke-dasharray": it.dash || null }));
    else if (it.kind === "dot" || it.shape) key.append(marker(it.shape || "circle", 8, 6, 4.5, { style: `fill:${it.css}` }));
    else key.append(svg("rect", { x: 2, y: 1, width: 12, height: 10, rx: 2, style: `fill:${it.css}` }));
    return h("li", {}, key, it.label);
  }));
}
const toneLegend = (tones) => legend(tones.map((t) => ({ label: `${TONE[t].icon} ${t === "better" ? "better" : t === "worse" ? "worse" : TONE[t].word}`, css: TONE[t].css, kind: "dot" })));

function svgRoot(w, hgt, label) {
  return svg("svg", { width: w, height: hgt, viewBox: `0 0 ${w} ${hgt}`, role: "group", "aria-label": label });
}
