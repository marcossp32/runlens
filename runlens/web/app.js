/* runlens dashboard. Plain JavaScript, no libraries.
   Every value from the data reaches the page as a text node, never as markup. */
(function () {
  "use strict";

  const DATA = JSON.parse(document.getElementById("data").textContent);
  const UNITS = new Map(DATA.units.map((u) => [u.id, u]));
  const METRICS = DATA.method.metrics;
  const KIND = { skill: "Skill", agent: "Agent role", group: "Group" };
  const LOG_CAP = Math.log(DATA.method.max_ratio);
  const PAGE = 25;
  const PLAIN = {
    cost: ["Cost per run", "Model spend for this unit, averaged over its runs."],
    seconds: ["Time per run", "Working time attributed to it."],
    error_rate: ["Tool errors", "Share of its tool calls that failed."],
    incidents: ["Problems per run", "Error streaks, repeated calls, interrupts and similar."],
    interventions: ["Your messages per run", "Messages you sent while it was the active skill."],
    idle_rate: ["Waiting calls", "Share of its tool calls that only wait or print."],
    api_error_rate: ["API errors", "Share of its model turns that hit an API error."],
    bad_markers: ["Failed checks per run", "Checks that your config marks as failed."],
  };
  const SVG_NS = "http://www.w3.org/2000/svg";
  const app = document.getElementById("app");

  // ---- DOM helpers ----------------------------------------------------------------

  function append(node, kids) {
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  function h(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
    return append(node, kids);
  }

  function svg(tag, attrs, ...kids) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, String(v));
    return append(node, kids);
  }

  const chip = (text, cls) => h("span", { class: cls ? `chip ${cls}` : "chip" }, text);
  const note = (text) => h("p", { class: "note" }, text);
  const empty = (text) => h("p", { class: "empty" }, text);
  const kpi = (label, value, sub, spark) =>
    h("div", { class: "kpi" }, h("div", { class: "kl" }, label), h("div", { class: "kv" }, value),
      spark ? h("div", { class: "kspark" }, spark) : null, h("div", { class: "ks" }, sub || ""));
  const hrefUnit = (id) => `#/unit/${encodeURIComponent(id)}`;
  const hrefCompare = (a, av, b, bv) => `#/compare?${new URLSearchParams({ a, av, b, bv })}`;

  // ---- formatting and meaning -----------------------------------------------------

  const fmt = {
    usd(v) {
      if (v == null) return "—";
      const d = Math.abs(v) < 1 ? 3 : 2;
      return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
    },
    num(v, d = 1) {
      return v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: d });
    },
    pct(v) {
      return v == null ? "—" : `${(100 * v).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    },
    secs(v) {
      if (v == null) return "—";
      if (v < 60) return `${Math.round(v)} s`;
      if (v < 3600) return `${(v / 60).toFixed(1)} min`;
      return `${(v / 3600).toFixed(1)} h`;
    },
    score(v) {
      return v == null ? "—" : Math.round(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
    },
    day(iso) {
      return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
    },
    when(iso) {
      return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
    },
    signed(v, d = 1) {
      if (v == null) return "—";
      return `${v < 0 ? "−" : "+"}${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: d })}`;
    },
    metric(m, v) {
      if (v == null) return "—";
      if (m.unit === "usd") return fmt.usd(v);
      if (m.unit === "s") return fmt.secs(v);
      if (m.unit === "rate") return fmt.pct(v);
      return fmt.num(v, 2);
    },
    runs(n) {
      return `${fmt.num(n, 0)} run${n === 1 ? "" : "s"}`;
    },
    interval(ci) {
      return ci ? `${fmt.score(ci[0])}–${fmt.score(ci[1])}` : "—";
    },
  };

  const metricLabel = (m) => (PLAIN[m.key] ? PLAIN[m.key][0] : m.label);
  const metricHelp = (m) => (PLAIN[m.key] ? PLAIN[m.key][1] : m.what);

  // A unit is "better" only when its whole likely range sits above 100, "worse" only when it sits below.
  function verdict(score, ci) {
    if (score == null) return { tone: "", word: "No score yet", sentence: "There are not enough runs to score this yet." };
    if (!ci) return { tone: "", word: "Not clear yet", sentence: "Too few runs to tell whether it is better or worse than average." };
    if (ci[0] > 100) return { tone: "good", word: "Better than average", sentence: `Better than average: even the low end of its likely range (${fmt.score(ci[0])}) is above 100.` };
    if (ci[1] < 100) return { tone: "bad", word: "Worse than average", sentence: `Worse than average: even the high end of its likely range (${fmt.score(ci[1])}) is below 100.` };
    return { tone: "", word: "Not clear yet", sentence: `Not clearly better or worse than average: its likely range (${fmt.interval(ci)}) includes 100.` };
  }

  // The change against the previous version. Overlapping ranges mean no clear change.
  function change(v) {
    if (v.delta == null) return { tone: "", arrow: "", text: "" };
    if (v.overlap === null) return { tone: "", arrow: "≈", text: "too few runs to tell" };
    if (v.overlap) return { tone: "", arrow: "≈", text: "no clear change" };
    return v.delta > 0 ? { tone: "good", arrow: "↑", text: "better" } : { tone: "bad", arrow: "↓", text: "worse" };
  }

  const overlaps = (a, b) => (!a || !b ? null : a[0] <= b[1] && b[0] <= a[1]);

  function scoreCell(score, ci, few) {
    const v = verdict(score, ci);
    return h("span", { class: `score ${v.tone}` }, h("strong", {}, fmt.score(score)), h("span", { class: "sub" }, v.word + (few ? " · few runs" : "")));
  }

  function changeCell(u) {
    const c = change(u);
    if (!c.text) return h("span", { class: "muted", title: "Only one version so far" }, "—");
    return h("span", { class: `change ${c.tone}`, title: `${fmt.signed(u.delta)} points against the previous version` }, `${c.arrow} ${c.text}`);
  }

  // ---- tables and tabs ------------------------------------------------------------

  function compare(a, b, dir) {
    const aNull = a === null || a === undefined || a === "";
    const bNull = b === null || b === undefined || b === "";
    if (aNull || bNull) return (aNull ? 1 : 0) - (bNull ? 1 : 0);
    const c = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), undefined, { numeric: true });
    return dir * c;
  }

  // A sortable table. cols: {key, label, num, value(row), cell(row)}. With `page`, rows arrive in pages.
  function table({ caption, cols, rows, sort, page = 0 }) {
    let key = sort.key;
    let dir = sort.dir;
    let data = rows;
    let shown = page || Infinity;
    const body = h("tbody");
    const more = h("button", { type: "button", class: "showmore" });
    more.addEventListener("click", () => {
      shown += page;
      draw();
    });
    const heads = cols.map((col) => {
      const arrow = h("span", { class: "arrow", "aria-hidden": "true" });
      const btn = h("button", { type: "button", class: "sort" }, col.label, " ", arrow);
      btn.addEventListener("click", () => {
        if (key === col.key) dir = -dir;
        else {
          key = col.key;
          dir = col.num ? -1 : 1;
        }
        draw();
      });
      return h("th", { scope: "col", class: col.num ? "num" : "" }, btn);
    });

    function draw() {
      cols.forEach((col, i) => {
        const active = col.key === key;
        heads[i].setAttribute("aria-sort", active ? (dir > 0 ? "ascending" : "descending") : "none");
        heads[i].querySelector(".arrow").textContent = active ? (dir > 0 ? "▲" : "▼") : "";
      });
      const col = cols.find((c) => c.key === key);
      const ordered = col ? [...data].sort((x, y) => compare(col.value(x), col.value(y), dir)) : data;
      const slice = ordered.slice(0, shown);
      body.replaceChildren(...slice.map((row) => h("tr", {}, cols.map((c) =>
        h("td", { class: c.num ? "num" : "" }, c.cell ? c.cell(row) : (c.value(row) ?? "—"))))));
      const left = ordered.length - slice.length;
      more.hidden = left <= 0;
      more.textContent = `Show ${Math.min(page, left)} more · ${left} left`;
    }

    draw();
    return {
      el: h("div", { class: "tw" }, h("table", { "aria-label": caption }, h("thead", {}, h("tr", {}, heads)), body), page ? more : null),
      setRows(rows) {
        data = rows;
        shown = page || Infinity;
        draw();
      },
    };
  }

  // A static table: heads are {label, num}, rows are arrays of cells.
  function plain(caption, heads, rows) {
    return h("div", { class: "tw" }, h("table", { "aria-label": caption },
      h("thead", {}, h("tr", {}, heads.map((t) => h("th", { scope: "col", class: t.num ? "num" : "" }, t.label)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((cell, i) => h("td", { class: heads[i].num ? "num" : "" }, cell)))))));
  }

  // Tabs with arrow-key navigation. Each panel is built once and shown or hidden.
  function tabbed(label, items, initial) {
    const buttons = items.map((it) => h("button", {
      type: "button", role: "tab", class: "tab", id: `tab-${it.id}`, "aria-controls": `panel-${it.id}`, "aria-selected": "false", tabindex: "-1",
    }, it.label));
    const panels = items.map((it) => h("div", {
      role: "tabpanel", id: `panel-${it.id}`, "aria-labelledby": `tab-${it.id}`, tabindex: "0", hidden: true,
    }, it.build()));
    const select = (id) => {
      items.forEach((it, i) => {
        const on = it.id === id;
        buttons[i].setAttribute("aria-selected", String(on));
        buttons[i].tabIndex = on ? 0 : -1;
        panels[i].hidden = !on;
      });
    };
    buttons.forEach((b, i) => {
      b.addEventListener("click", () => select(items[i].id));
      b.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const j = (i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
        buttons[j].focus();
        select(items[j].id);
        e.preventDefault();
      });
    });
    select(initial || items[0].id);
    return h("div", { class: "tabs" }, h("div", { class: "tablist", role: "tablist", "aria-label": label }, buttons), panels);
  }

  // ---- columns --------------------------------------------------------------------

  const nameCol = (label) => ({ key: "name", label, value: (u) => u.name, cell: (u) => h("a", { href: hrefUnit(u.id) }, u.name) });
  const scoreCol = { key: "score", label: "Score", num: true, value: (u) => u.score, cell: (u) => scoreCell(u.score, u.ci, u.low_sample) };
  const changeCol = { key: "delta", label: "Latest change", value: (u) => u.delta, cell: (u) => changeCell(u) };
  const runsCol = { key: "runs", label: "Runs", num: true, value: (u) => u.runs };
  const costCol = { key: "cost", label: "Cost per run", num: true, value: (u) => u.kpi.cost, cell: (u) => fmt.usd(u.kpi.cost) };
  const timeCol = { key: "seconds", label: "Time per run", num: true, value: (u) => u.kpi.seconds, cell: (u) => fmt.secs(u.kpi.seconds) };
  const errCol = { key: "error_rate", label: "Tool errors", num: true, value: (u) => u.kpi.error_rate, cell: (u) => fmt.pct(u.kpi.error_rate) };
  const lastCol = { key: "last", label: "Last used", value: (u) => u.last_seen, cell: (u) => fmt.day(u.last_seen) };

  // ---- charts: plain SVG, coloured by CSS classes so both themes work ------------

  const SHORT = {
    cost: "Cost", seconds: "Time", error_rate: "Errors", incidents: "Problems", interventions: "Your messages",
    idle_rate: "Waiting", api_error_rate: "API errors", bad_markers: "Failed checks",
  };
  const DAY = 864e5;
  const card = (title, ...kids) => h("figure", { class: "card" }, h("figcaption", { class: "cardtitle" }, title), ...kids);
  const dayName = (ms) => new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const wholeUsd = (v) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: v < 10 ? 1 : 0 }).format(v);
  const legendOf = (items) => h("ul", { class: "legend" }, items.map((it) => h("li", {}, h("span", { class: `swatch ${it.cls}` }), it.label)));

  // Readable tick values between lo and hi, about `count` of them.
  function ticks(lo, hi, count) {
    if (!(hi > lo)) return [lo];
    const pow = 10 ** Math.floor(Math.log10((hi - lo) / count));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => (hi - lo) / s <= count) || pow * 10;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + step / 1e6; t += step) out.push(Number(t.toPrecision(10)));
    return out;
  }

  // Day-aligned ticks (milliseconds) between a and b.
  function dayTicks(a, b, count) {
    const step = Math.max(1, Math.ceil((b - a) / DAY / count)) * DAY;
    const out = [];
    for (let t = Math.ceil(a / DAY) * DAY; t <= b; t += step) out.push(t);
    return out;
  }

  // Each skill or group as a row: its likely range, its score, and where 100 falls.
  function rangePlot(list) {
    const rows = list.filter((u) => u.score != null).sort((p, q) => q.score - p.score);
    if (!rows.length) return empty("No score yet.");
    const W = 640, LABEL = 128, RIGHT = 168, ROW = 30, T = 22, B = 24;
    const H = T + ROW * rows.length + B;
    const xs = rows.flatMap((u) => (u.ci ? u.ci : [u.score])).concat(100);
    const lo = Math.min(...xs) - 6, hi = Math.max(...xs) + 6;
    const x = (v) => LABEL + ((v - lo) / (hi - lo)) * (W - LABEL - RIGHT);
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Score range of ${rows.length} ${rows.length === 1 ? "unit" : "units"}; 100 is an average run` });
    for (const t of ticks(lo, hi, 5)) {
      chart.append(svg("line", { class: "grid", x1: x(t), x2: x(t), y1: T - 4, y2: H - B }),
        svg("text", { class: "axis", x: x(t), y: H - 6, "text-anchor": "middle" }, t));
    }
    chart.append(svg("line", { class: "ref", x1: x(100), x2: x(100), y1: T - 6, y2: H - B }),
      svg("text", { class: "axis", x: x(100), y: T - 9, "text-anchor": "middle" }, "average"));
    rows.forEach((u, i) => {
      const y = T + ROW * i + ROW / 2;
      const v = verdict(u.score, u.ci);
      const t = v.tone || "neutral";
      chart.append(svg("text", { class: "rowlabel", x: LABEL - 10, y: y + 4, "text-anchor": "end" }, u.name));
      if (u.ci) chart.append(svg("line", { class: `range ${t}`, x1: x(u.ci[0]), x2: x(u.ci[1]), y1: y, y2: y }));
      chart.append(svg("circle", { class: `dot ${t}`, cx: x(u.score), cy: y, r: 5 },
        svg("title", {}, `${u.name}: ${fmt.score(u.score)}${u.ci ? `, likely ${fmt.interval(u.ci)}` : ""}`)));
      chart.append(svg("text", { class: "axis", x: W - RIGHT + 12, y: y + 4 }, `${fmt.score(u.score)} · ${v.word}`));
    });
    return chart;
  }

  // Runs per day: distinct runs that used any skill in the list, one column per day.
  function activityBars(list) {
    const seen = new Set();
    const perDay = new Map();
    for (const u of list) {
      for (const r of DATA.runs[u.id] || []) {
        if (!r.started || seen.has(r.session)) continue;
        seen.add(r.session);
        const day = r.started.slice(0, 10);
        perDay.set(day, (perDay.get(day) || 0) + 1);
      }
    }
    if (!perDay.size) return empty("No runs yet.");
    const keys = [...perDay.keys()].sort();
    const first = Date.parse(`${keys[0]}T00:00:00Z`), last = Date.parse(`${keys[keys.length - 1]}T00:00:00Z`);
    const days = [];
    for (let t = first; t <= last; t += DAY) days.push(t);
    const scale = ticks(0, Math.max(...perDay.values()), 3);
    const yMax = scale[scale.length - 1] || 1;
    const W = 640, H = 180, L = 30, R = 8, T = 12, B = 24;
    const slot = (W - L - R) / days.length;
    const width = Math.min(60, slot * 0.64);
    const y = (n) => T + (H - T - B) * (1 - n / yMax);
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Runs per day over ${days.length} days, most on one day: ${Math.max(...perDay.values())}` });
    for (const t of scale) {
      chart.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(t), y2: y(t) }),
        svg("text", { class: "axis", x: L - 6, y: y(t) + 4, "text-anchor": "end" }, t));
    }
    days.forEach((t, i) => {
      const n = perDay.get(new Date(t).toISOString().slice(0, 10)) || 0;
      const x0 = L + i * slot + (slot - width) / 2;
      chart.append(svg("rect", { class: "col", x: x0, y: y(n), width, height: Math.max(0, H - B - y(n)), rx: 2 },
        svg("title", {}, `${dayName(t)}: ${n} run${n === 1 ? "" : "s"}`)));
      if (i % Math.ceil(days.length / 8) === 0) {
        chart.append(svg("text", { class: "axis", x: x0 + width / 2, y: H - 8, "text-anchor": "middle" }, dayName(t)));
      }
    });
    return chart;
  }

  // When each version was in use, coloured by whether it got better or worse than the one before.
  function timeline(versions) {
    const rows = versions.filter((v) => v.first_seen);
    if (!rows.length) return empty("No dates yet.");
    const starts = rows.map((v) => Date.parse(v.first_seen));
    const ends = rows.map((v) => Date.parse(v.last_seen || v.first_seen));
    const a = Math.min(...starts) - DAY * 0.5, b = Math.max(...ends) + DAY;
    const W = 640, L = 70, R = 170, ROW = 28, T = 6, B = 22;
    const H = T + ROW * rows.length + B;
    const x = (t) => L + ((t - a) / (b - a)) * (W - L - R);
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `${rows.length} versions over time` });
    for (const t of dayTicks(a, b, 6)) {
      chart.append(svg("line", { class: "grid", x1: x(t), x2: x(t), y1: T, y2: H - B }),
        svg("text", { class: "axis", x: x(t), y: H - 6, "text-anchor": "middle" }, dayName(t)));
    }
    rows.forEach((v, i) => {
      const y0 = T + ROW * i;
      const c = change(v);
      const x0 = x(Date.parse(v.first_seen));
      const x1 = Math.max(x0 + 6, x(Date.parse(v.last_seen || v.first_seen)) + 6);
      chart.append(svg("text", { class: "rowlabel", x: L - 10, y: y0 + 18, "text-anchor": "end" }, nameOf(v)));
      chart.append(svg("rect", { class: `bar ${c.tone || "neutral"}`, x: x0, y: y0 + 5, width: x1 - x0, height: ROW - 10, rx: 3 },
        svg("title", {}, `${nameOf(v)}: ${fmt.runs(v.runs)}, ${fmt.day(v.first_seen)} – ${fmt.day(v.last_seen)}`)));
      chart.append(svg("text", { class: "axis", x: x1 + 8, y: y0 + 18 }, `${fmt.score(v.score)}${c.text ? ` · ${c.text}` : ""}`));
    });
    return chart;
  }

  // Cost of every run over time, one dot per run, coloured by version.
  function runScatter(runs, versions) {
    const pts = runs.filter((r) => r.started && r.cost != null);
    if (!pts.length) return empty("No runs with a cost yet.");
    const index = new Map(versions.map((v, i) => [v.label, i]));
    const times = pts.map((r) => Date.parse(r.started));
    const span = Math.max(...times) - Math.min(...times);
    const pad = Math.max(DAY * 0.5, span * 0.04);
    const a = Math.min(...times) - pad, b = Math.max(...times) + pad;
    const top = Math.max(...pts.map((r) => r.cost)) * 1.05;
    const yTicks = ticks(0, top, 4);
    const yMax = Math.max(top, yTicks[yTicks.length - 1]);
    const W = 640, H = 230, L = 62, R = 14, T = 12, B = 26;
    const x = (t) => L + ((t - a) / (b - a)) * (W - L - R);
    const y = (c) => T + (H - T - B) * (1 - c / yMax);
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Cost of ${pts.length} runs over time` });
    for (const t of yTicks) {
      chart.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(t), y2: y(t) }),
        svg("text", { class: "axis", x: L - 8, y: y(t) + 4, "text-anchor": "end" }, wholeUsd(t)));
    }
    for (const t of dayTicks(a, b, 6)) {
      chart.append(svg("text", { class: "axis", x: x(t), y: H - 8, "text-anchor": "middle" }, dayName(t)));
    }
    pts.forEach((r, i) => {
      chart.append(svg("circle", { class: `run s${(index.get(r.version) ?? 0) % 6}`, cx: x(times[i]), cy: y(r.cost), r: 5 },
        svg("title", {}, `${fmt.when(r.started)} · ${r.version} · ${fmt.usd(r.cost)} · ${fmt.secs(r.seconds)}${r.task ? ` · ${r.task}` : ""}`)));
    });
    const legend = legendOf(versions.map((v, i) => ({ cls: `s${i % 6}`, label: v.recorded ? v.label : "unrecorded" })));
    return h("div", {}, chart, legend);
  }

  // Two versions side by side, one pair of bars per measure, each measure on its own scale.
  function pairBars(A, B) {
    const ms = METRICS.filter((m) => A.metrics[m.key] && B.metrics[m.key]);
    if (!ms.length) return empty("No measure is shared by both sides.");
    const W = 640, LABEL = 170, PAD = 96, ROW = 36, T = 4;
    const H = T + ROW * ms.length;
    const width = W - LABEL - PAD;
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Side by side, ${ms.length} measures` });
    ms.forEach((m, i) => {
      const a = A.metrics[m.key].value, b = B.metrics[m.key].value;
      const max = Math.max(a, b) || 1;
      const y0 = T + ROW * i;
      chart.append(svg("text", { class: "rowlabel", x: LABEL - 10, y: y0 + 20, "text-anchor": "end" }, metricLabel(m)));
      [[a, "s0", 4], [b, "s1", 19]].forEach(([val, cls, dy]) => {
        const w = Math.max(2, (val / max) * width);
        chart.append(svg("rect", { class: `bar ${cls}`, x: LABEL, y: y0 + dy, width: w, height: 12, rx: 2 },
          svg("title", {}, `${metricLabel(m)}: ${fmt.metric(m, val)}`)));
        chart.append(svg("text", { class: "axis", x: LABEL + w + 6, y: y0 + dy + 10 }, fmt.metric(m, val)));
      });
    });
    return chart;
  }

  // ---- theme-aware colours and the newer charts -----------------------------------

  // Colours are read from the page's own variables, so every chart follows light and dark.
  function palette() {
    const cs = getComputedStyle(document.documentElement);
    const g = (name) => cs.getPropertyValue(name).trim();
    return { good: g("--good"), bad: g("--bad"), neutral: g("--sx"), surface: g("--surface"), accent: g("--accent"), line: g("--line"), text: g("--text") };
  }

  // Blend two #rrggbb colours: t = 0 gives a, t = 1 gives b.
  function mixHex(a, b, t) {
    const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
    const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    return "#" + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("");
  }

  // Ratio to average as a colour: green above average, red below, stronger the further away.
  function heatColor(ratio, P) {
    const t = Math.max(-1, Math.min(1, Math.log(ratio) / LOG_CAP));
    const k = 0.12 + 0.33 * Math.abs(t);
    return t >= 0 ? mixHex(P.surface, P.good, k) : mixHex(P.surface, P.bad, k);
  }

  // A small line of the last runs, for KPI cards.
  function sparkline(values) {
    const vs = values.filter((v) => v != null && Number.isFinite(v));
    if (vs.length < 2) return null;
    const W = 150, H = 40;
    const min = Math.min(...vs), max = Math.max(...vs);
    const pts = vs.map((v, i) => [2 + (i * (W - 4)) / (vs.length - 1), H - 4 - ((v - min) / (max - min || 1)) * (H - 8)]);
    const line = pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ");
    const last = pts[pts.length - 1];
    return svg("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Trend over ${vs.length} runs` },
      svg("polygon", { class: "spark-area", points: `2,${H} ${line} ${W - 2},${H}` }),
      svg("polyline", { class: "spark-line", points: line }),
      svg("circle", { class: "spark-end", cx: last[0].toFixed(1), cy: last[1].toFixed(1), r: 3 }));
  }

  // The score as a semicircle gauge. The scale is logarithmic, so 100 sits at the top.
  function gauge(score, ci) {
    const W = 260, H = 190, cx = 130, cy = 128, R = 96, lo = 50, hi = 200;
    const f = (v) => (Math.log(Math.min(hi, Math.max(lo, v))) - Math.log(lo)) / (Math.log(hi) - Math.log(lo));
    const ang = (v) => Math.PI * (1 - f(v));
    const pt = (v, r) => [cx + r * Math.cos(ang(v)), cy - r * Math.sin(ang(v))];
    const arc = (a, b, r) => {
      const [x1, y1] = pt(a, r), [x2, y2] = pt(b, r);
      return `M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}`;
    };
    const chart = svg("svg", { class: "chart gauge", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": score == null ? "No score yet" : `Score ${fmt.score(score)} on a scale from 50 to 200, where 100 is an average run` });
    chart.append(svg("path", { class: "band bad", d: arc(lo, 90, R) }), svg("path", { class: "band neutral", d: arc(90, 110, R) }),
      svg("path", { class: "band good", d: arc(110, hi, R) }));
    if (ci) chart.append(svg("path", { class: "ci-arc", d: arc(Math.max(lo, ci[0]), Math.min(hi, ci[1]), R + 12) }));
    const [lx, ly] = pt(lo, R + 22), [mx, my] = pt(100, R + 20), [hx, hy] = pt(hi, R + 22);
    chart.append(svg("text", { class: "axis", x: lx, y: ly, "text-anchor": "middle" }, "50"),
      svg("text", { class: "axis", x: mx, y: my, "text-anchor": "middle" }, "100"),
      svg("text", { class: "axis", x: hx, y: hy, "text-anchor": "middle" }, "200"));
    if (score != null) {
      const [nx, ny] = pt(score, R - 14);
      chart.append(svg("line", { class: "needle", x1: cx, y1: cy, x2: nx.toFixed(1), y2: ny.toFixed(1) }), svg("circle", { class: "hub", cx, cy, r: 6 }));
      chart.append(svg("text", { class: "gval", x: cx, y: cy + 34, "text-anchor": "middle" }, fmt.score(score)),
        svg("text", { class: "gword", x: cx, y: cy + 54, "text-anchor": "middle" }, verdict(score, ci).word));
    }
    return chart;
  }

  // The measures as a radar. One axis per measure; the distance from the centre is the ratio to average,
  // on a log scale, so the dashed ring is the average. Series: [{v, label, cls, dashed}]. Values are written
  // at the vertices of the first series.
  function radar(series) {
    const first = series.find((x) => x.v && x.v.metrics);
    const ms = METRICS.filter((m) => first && first.v.metrics[m.key]);
    if (ms.length < 3) return empty("Not enough measures to draw a profile.");
    const W = 460, H = 340, cx = 230, cy = 170, R = 98, N = ms.length;
    const ang = (i) => -Math.PI / 2 + (2 * Math.PI * i) / N;
    const at = (i, f) => [cx + R * f * Math.cos(ang(i)), cy + R * f * Math.sin(ang(i))];
    const frac = (ratio) => Math.min(1, Math.max(0, (Math.log(ratio) + LOG_CAP) / (2 * LOG_CAP)));
    const chart = svg("svg", { class: "chart radar", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Profile against average: ${ms.map((m) => `${SHORT[m.key] || m.label} ${first.v.metrics[m.key].ratio >= 1 ? "better" : "worse"}`).join(", ")}` });
    chart.append(svg("circle", { class: "ring", cx, cy, r: R }), svg("circle", { class: "ring avg", cx, cy, r: R * 0.5 }));
    ms.forEach((m, i) => {
      const [ex, ey] = at(i, 1);
      chart.append(svg("line", { class: "spoke", x1: cx, y1: cy, x2: ex.toFixed(1), y2: ey.toFixed(1) }));
      const [lx, ly] = at(i, 1.24);
      const c = Math.cos(ang(i));
      const anchor = c > 0.25 ? "start" : c < -0.25 ? "end" : "middle";
      const d = first.v.metrics[m.key];
      chart.append(svg("text", { class: "vname", x: lx.toFixed(1), y: ly.toFixed(1), "text-anchor": anchor }, SHORT[m.key] || m.label));
      chart.append(svg("text", { class: "vval", x: lx.toFixed(1), y: (ly + 14).toFixed(1), "text-anchor": anchor },
        `${fmt.metric(m, d.value)} · ×${d.ratio.toFixed(2)}`));
    });
    series.forEach((sr) => {
      if (!sr.v || !sr.v.metrics) return;
      const pts = ms.map((m, i) => (sr.v.metrics[m.key] ? at(i, frac(sr.v.metrics[m.key].ratio)) : at(i, 0)));
      chart.append(svg("polygon", { class: `profile ${sr.cls}${sr.dashed ? " dashed" : ""}`,
        points: pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ") }));
      ms.forEach((m, i) => {
        const d = sr.v.metrics[m.key];
        if (!d) return;
        chart.append(svg("circle", { class: `vert ${sr.cls}`, cx: pts[i][0].toFixed(1), cy: pts[i][1].toFixed(1), r: sr.dashed ? 3 : 4 },
          svg("title", {}, `${sr.label} · ${metricLabel(m)}: ${fmt.metric(m, d.value)} (×${d.ratio.toFixed(2)} vs average)`)));
      });
    });
    return chart;
  }

  // Each skill as a bubble: cost per run across (log scale), score up, bubble size = runs, colour = verdict.
  function bubbleChart(list) {
    const pts = list.filter((u) => u.score != null && u.kpi.cost > 0);
    if (!pts.length) return empty("Not enough data for the chart yet.");
    const W = 640, H = 300, L = 52, R = 22, T = 14, B = 34;
    const lv = pts.map((u) => Math.log10(u.kpi.cost));
    const x0 = Math.floor(Math.min(...lv) - 0.2), x1 = Math.ceil(Math.max(...lv) + 0.2);
    const y0 = 40, y1 = 215;
    const x = (v) => L + ((v - x0) / (x1 - x0)) * (W - L - R);
    const y = (sc) => T + (H - T - B) * (1 - (sc - y0) / (y1 - y0));
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `${pts.length} skills: cost per run against score` });
    for (const sc of [50, 100, 150, 200]) {
      chart.append(svg("line", { class: sc === 100 ? "ref" : "grid", x1: L, x2: W - R, y1: y(sc), y2: y(sc) }),
        svg("text", { class: "axis", x: L - 8, y: y(sc) + 4, "text-anchor": "end" }, sc));
    }
    for (let e = x0; e <= x1; e += 1) {
      chart.append(svg("line", { class: "grid", x1: x(e), x2: x(e), y1: T, y2: H - B }),
        svg("text", { class: "axis", x: x(e), y: H - 12, "text-anchor": "middle" }, wholeUsd(10 ** e)));
    }
    pts.forEach((u) => {
      const t = verdict(u.score, u.ci).tone || "neutral";
      const cx = x(Math.log10(u.kpi.cost)), cy = y(u.score), r = 4 + Math.sqrt(u.runs) * 1.5;
      chart.append(svg("circle", { class: `bub ${t}`, cx: cx.toFixed(1), cy: cy.toFixed(1), r: r.toFixed(1) },
        svg("title", {}, `${u.name}: score ${fmt.score(u.score)}, ${fmt.usd(u.kpi.cost)} per run, ${fmt.runs(u.runs)}`)));
      chart.append(svg("text", { class: "bublabel", x: cx.toFixed(1), y: (cy - r - 4).toFixed(1), "text-anchor": "middle" }, u.name));
    });
    return chart;
  }

  // Every skill against every measure, coloured by the latest version's ratio to average.
  function heatmap(list) {
    const P = palette();
    const rows = list.filter((u) => u.score != null).sort((a, b) => b.score - a.score);
    if (!rows.length) return empty("No score yet.");
    const cols = METRICS.filter((m) => m.kinds.includes("skill"));
    const LABEL = 110, CELL = 72, TOP = 40, ROWH = 30;
    const W = LABEL + cols.length * CELL, H = TOP + ROWH * rows.length + 4;
    const chart = svg("svg", { class: "chart heat", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Ratio to average for ${rows.length} skills and ${cols.length} measures` });
    cols.forEach((m, j) => chart.append(svg("text", { class: "axis", x: LABEL + j * CELL + CELL / 2, y: TOP - 12, "text-anchor": "middle" }, SHORT[m.key] || m.label)));
    rows.forEach((u, i) => {
      const cur = (DATA.versions[u.id] || []).find((v) => v.label === u.current);
      const y0 = TOP + i * ROWH;
      chart.append(svg("text", { class: "rowlabel", x: LABEL - 8, y: y0 + 19, "text-anchor": "end" }, u.name));
      cols.forEach((m, j) => {
        const d = cur && cur.metrics ? cur.metrics[m.key] : null;
        const x0 = LABEL + j * CELL;
        chart.append(svg("rect", { x: x0 + 2, y: y0 + 2, width: CELL - 4, height: ROWH - 4, rx: 4, fill: d ? heatColor(d.ratio, P) : P.line },
          svg("title", {}, d ? `${u.name} · ${metricLabel(m)}: ${fmt.metric(m, d.value)} (×${d.ratio.toFixed(2)} vs average)` : `${u.name} · ${metricLabel(m)}: no data`)));
        chart.append(svg("text", { class: "hcell", x: x0 + CELL / 2, y: y0 + 19, "text-anchor": "middle" }, d ? `×${d.ratio.toFixed(2)}` : "—"));
      });
    });
    return h("div", {}, chart, legendOf([{ cls: "bad", label: "worse than average" }, { cls: "good", label: "better than average" }]));
  }

  // Slice-and-dice treemap: split the items into two halves of similar weight, one after the other.
  function splitRects(items, x, y, w, h0, out) {
    if (!items.length) return;
    if (items.length === 1) {
      out.push({ it: items[0], x, y, w, h: h0 });
      return;
    }
    const total = items.reduce((n, it) => n + it.value, 0);
    let acc = 0, k = 0;
    while (k < items.length - 1 && acc + items[k].value <= total / 2) {
      acc += items[k].value;
      k += 1;
    }
    if (k === 0) {
      acc = items[0].value;
      k = 1;
    }
    const f = acc / total;
    const A = items.slice(0, k), B = items.slice(k);
    if (w >= h0) {
      splitRects(A, x, y, w * f, h0, out);
      splitRects(B, x + w * f, y, w * (1 - f), h0, out);
    } else {
      splitRects(A, x, y, w, h0 * f, out);
      splitRects(B, x, y + h0 * f, w, h0 * (1 - f), out);
    }
  }

  // Where the spend goes: each skill is a rectangle sized by its spend.
  function treemapChart(list) {
    const items = list.map((u) => ({ name: u.name, value: (DATA.runs[u.id] || []).reduce((n, r) => n + (r.cost || 0), 0) }))
      .filter((it) => it.value > 0).sort((a, b) => b.value - a.value);
    if (!items.length) return empty("No spend recorded yet.");
    const total = items.reduce((n, it) => n + it.value, 0);
    const W = 640, H = 240;
    const out = [];
    splitRects(items, 0, 0, W, H, out);
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Spend by skill: ${items.map((it) => `${it.name} ${fmt.pct(it.value / total)}`).join(", ")}` });
    out.forEach((r) => {
      const i = items.indexOf(r.it);
      const g = svg("g", {});
      g.append(svg("rect", { class: `tile s${i % 6}`, x: (r.x + 1).toFixed(1), y: (r.y + 1).toFixed(1), width: Math.max(0, r.w - 2).toFixed(1), height: Math.max(0, r.h - 2).toFixed(1), rx: 4 },
        svg("title", {}, `${r.it.name}: ${fmt.usd(r.it.value)} (${fmt.pct(r.it.value / total)})`)));
      if (r.w > 80 && r.h > 40) {
        g.append(svg("text", { class: "tm-label", x: (r.x + 8).toFixed(1), y: (r.y + 19).toFixed(1) }, r.it.name));
        g.append(svg("text", { class: "tm-sub", x: (r.x + 8).toFixed(1), y: (r.y + 35).toFixed(1) }, `${fmt.usd(r.it.value)} · ${fmt.pct(r.it.value / total)}`));
      }
      chart.append(g);
    });
    return h("div", {}, chart, legendOf(items.map((it, i) => ({ cls: `s${i % 6}`, label: `${it.name} · ${fmt.usd(it.value)}` }))));
  }

  // Spend split by version of one unit, as a donut.
  function versionSpend(versions, runs) {
    return versions.map((v, i) => ({ label: nameOf(v), cls: `s${i % 6}`,
      value: runs.filter((r) => r.version === v.label).reduce((n, r) => n + (r.cost || 0), 0) })).filter((p) => p.value > 0);
  }

  function donut(parts) {
    const total = parts.reduce((n, p) => n + p.value, 0);
    if (!total) return empty("No spend recorded yet.");
    const W = 200, R = 74, C = 2 * Math.PI * R, mid = W / 2;
    const chart = svg("svg", { class: "chart donut", viewBox: `0 0 ${W} ${W}`, role: "img",
      "aria-label": `Spend by version: ${parts.map((p) => `${p.label} ${fmt.pct(p.value / total)}`).join(", ")}` });
    chart.append(svg("circle", { class: "track", cx: mid, cy: mid, r: R, fill: "none", "stroke-width": 22 }));
    let acc = 0;
    for (const p of parts) {
      const len = (p.value / total) * C;
      chart.append(svg("circle", { class: p.cls, cx: mid, cy: mid, r: R, fill: "none", "stroke-width": 22,
        "stroke-dasharray": `${len.toFixed(2)} ${(C - len).toFixed(2)}`, "stroke-dashoffset": (-acc).toFixed(2),
        transform: `rotate(-90 ${mid} ${mid})` }, svg("title", {}, `${p.label}: ${fmt.usd(p.value)} (${fmt.pct(p.value / total)})`)));
      acc += len;
    }
    chart.append(svg("text", { class: "hole-val", x: mid, y: mid + 4, "text-anchor": "middle" }, fmt.usd(total)),
      svg("text", { class: "hole-lab", x: mid, y: mid + 22, "text-anchor": "middle" }, "total spend"));
    return h("div", { class: "donutbox" }, chart,
      legendOf(parts.map((p) => ({ cls: p.cls, label: `${p.label} · ${fmt.usd(p.value)} · ${fmt.pct(p.value / total)}` }))));
  }

  // Cost against time, one dot per run, coloured by version.
  function costTimeScatter(runs, versions) {
    const pts = runs.filter((r) => r.seconds != null && r.cost != null);
    if (!pts.length) return empty("No runs with a time and a cost yet.");
    const index = new Map(versions.map((v, i) => [v.label, i]));
    const mins = pts.map((r) => r.seconds / 60), costs = pts.map((r) => r.cost);
    const xTicks = ticks(0, Math.max(...mins) * 1.08, 5);
    const xMax = Math.max(Math.max(...mins) * 1.08, xTicks[xTicks.length - 1]);
    const yTicks = ticks(0, Math.max(...costs) * 1.08, 4);
    const yMax = Math.max(Math.max(...costs) * 1.08, yTicks[yTicks.length - 1]);
    const W = 640, H = 230, L = 62, R = 14, T = 12, B = 26;
    const x = (m) => L + (m / xMax) * (W - L - R);
    const y = (c) => T + (H - T - B) * (1 - c / yMax);
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Cost against time for ${pts.length} runs` });
    for (const t of yTicks) {
      chart.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(t), y2: y(t) }),
        svg("text", { class: "axis", x: L - 8, y: y(t) + 4, "text-anchor": "end" }, wholeUsd(t)));
    }
    for (const t of xTicks) {
      chart.append(svg("text", { class: "axis", x: x(t), y: H - 8, "text-anchor": "middle" }, `${t} min`));
    }
    pts.forEach((r) => {
      chart.append(svg("circle", { class: `run s${(index.get(r.version) ?? 0) % 6}`, cx: x(r.seconds / 60).toFixed(1), cy: y(r.cost).toFixed(1), r: 5 },
        svg("title", {}, `${r.version} · ${fmt.usd(r.cost)} · ${fmt.secs(r.seconds)}${r.task ? ` · ${r.task}` : ""}`)));
    });
    return h("div", {}, chart, legendOf(versions.map((v, i) => ({ cls: `s${i % 6}`, label: v.recorded ? v.label : "unrecorded" }))));
  }

  // The unit at a glance: its score as a gauge, its profile as a radar (current version against the one before),
  // and its trends as KPI cards with sparklines.
  function overview(u, versions) {
    const cur = versions.find((v) => v.label === u.current) || null;
    const prev = cur ? versions[versions.indexOf(cur) - 1] || null : null;
    const series = [];
    if (cur && Object.keys(cur.metrics || {}).length) series.push({ v: cur, label: `${nameOf(cur)} (current)`, cls: "s0" });
    if (prev && Object.keys(prev.metrics || {}).length) series.push({ v: prev, label: nameOf(prev), cls: "s1", dashed: true });
    const sorted = (DATA.runs[u.id] || []).filter((r) => r.started).sort((a, b) => (a.started < b.started ? -1 : 1));
    const spark = (f) => sparkline(sorted.map(f));
    return h("div", { class: "overview" },
      card("Score", gauge(u.score, u.ci)),
      card("Profile against average", series.length ? radar(series) : empty("No measures yet."),
        series.length ? legendOf(series.map((x) => ({ cls: x.cls, label: x.label }))) : null,
        note("Further from the centre is better than average. Each vertex shows the value and its ratio to the average run.")),
      h("div", { class: "kpis" },
        kpi("Cost per run", fmt.usd(u.kpi.cost), "model spend", spark((r) => r.cost)),
        kpi("Time per run", fmt.secs(u.kpi.seconds), "working time", spark((r) => r.seconds)),
        kpi("Tool errors", fmt.pct(u.kpi.error_rate), "of its tool calls", spark((r) => (r.calls ? r.call_errors / r.calls : null))),
        kpi("Problems per run", fmt.num(u.kpi.incidents, 2), "error streaks, repeats, interrupts", spark((r) => r.incidents))));
  }

  // ---- versions of the skills ---------------------------------------------------------

  // The versions of a unit whose skill text was recorded, in the order they first appeared.
  const recordedOf = (u) => (DATA.versions[u.id] || []).filter((v) => v.recorded);

  const versionsCol = {
    key: "versions", label: "Versions", num: true, value: (u) => recordedOf(u).length,
    cell: (u) => (recordedOf(u).length ? `${recordedOf(u).length} · now ${u.current}` : h("span", { class: "muted" }, "not recorded")),
  };

  // One lane per skill. Each version is a bar across the time it was in use, coloured by its change against the one before.
  function versionLanes(list) {
    const lanes = list.map((u) => ({ u, vs: recordedOf(u) })).filter((x) => x.vs.length);
    if (!lanes.length) return empty("No skill text was recorded, so there are no versions to show yet.");
    const starts = lanes.flatMap((x) => x.vs.map((v) => Date.parse(v.first_seen)));
    const ends = lanes.flatMap((x) => x.vs.map((v) => Date.parse(v.last_seen || v.first_seen)));
    const a = Math.min(...starts) - DAY * 0.5, b = Math.max(...ends) + DAY;
    const W = 640, L = 130, R = 16, ROW = 46, T = 6, B = 24;
    const H = T + ROW * lanes.length + B;
    const x = (t) => L + ((t - a) / (b - a)) * (W - L - R);
    const total = lanes.reduce((n, ln) => n + ln.vs.length, 0);
    const chart = svg("svg", { class: "chart lanes", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `${total} recorded versions across ${lanes.length} skills` });
    for (const t of dayTicks(a, b, 6)) {
      chart.append(svg("line", { class: "grid", x1: x(t), x2: x(t), y1: T, y2: H - B }),
        svg("text", { class: "axis", x: x(t), y: H - 6, "text-anchor": "middle" }, dayName(t)));
    }
    lanes.forEach((ln, i) => {
      const y0 = T + ROW * i;
      chart.append(svg("a", { href: hrefUnit(ln.u.id) },
        svg("text", { class: "lanelabel", x: L - 12, y: y0 + ROW / 2 + 5, "text-anchor": "end" }, ln.u.name)));
      ln.vs.forEach((v) => {
        const c = change(v);
        const x0 = x(Date.parse(v.first_seen));
        const x1 = Math.max(x0 + 8, x(Date.parse(v.last_seen || v.first_seen)) + 6);
        chart.append(svg("text", { class: "vlab", x: x0.toFixed(1), y: (y0 + 14).toFixed(1) }, `${nameOf(v)} · ${fmt.score(v.score)}`));
        chart.append(svg("rect", { class: `bar ${c.tone || "neutral"}`, x: x0.toFixed(1), y: (y0 + 20).toFixed(1),
          width: (x1 - x0).toFixed(1), height: 18, rx: 4 },
          svg("title", {}, `${ln.u.name} ${nameOf(v)}: ${fmt.runs(v.runs)}, ${fmt.day(v.first_seen)} – ${fmt.day(v.last_seen)}, score ${fmt.score(v.score)}${c.text ? `, ${c.text}` : ""}`)));
      });
    });
    return chart;
  }

  // Every recorded version in the list, one row each.
  function versionTable(list) {
    const rows = list.flatMap((u) => recordedOf(u).map((v) => ({
      id: u.id, name: u.name, label: v.label, hash: v.parts.map((p) => p.hash).join(" + "),
      first: v.first_seen, last: v.last_seen, runs: v.runs, score: v.score, ci: v.ci, change: change(v),
    })));
    const cols = [
      { key: "name", label: "Skill", value: (r) => r.name, cell: (r) => h("a", { href: hrefUnit(r.id) }, r.name) },
      { key: "label", label: "Version", value: (r) => r.label, cell: (r) => h("strong", {}, r.label) },
      { key: "hash", label: "Text", value: (r) => r.hash, cell: (r) => h("code", {}, r.hash) },
      { key: "first", label: "In use", value: (r) => r.first, cell: (r) => `${fmt.day(r.first)} – ${fmt.day(r.last)}` },
      { key: "runs", label: "Runs", num: true, value: (r) => r.runs },
      { key: "score", label: "Score", num: true, value: (r) => r.score, cell: (r) => scoreCell(r.score, r.ci, false) },
      { key: "change", label: "Against the version before", value: (r) => r.change.text || "first version",
        cell: (r) => (r.change.text ? h("span", { class: `change ${r.change.tone}` }, `${r.change.arrow} ${r.change.text}`) : h("span", { class: "muted" }, "first version")) },
    ];
    return table({ caption: "All recorded versions", cols, rows, sort: { key: "name", dir: 1 } }).el;
  }

  // ---- the skills page ------------------------------------------------------------

  function homeView() {
    const skills = DATA.units.filter((u) => u.kind === "skill");
    const roles = DATA.units.filter((u) => u.kind === "agent");
    const groups = DATA.units.filter((u) => u.kind === "group");
    if (!DATA.units.length) {
      return h("article", { class: "page" }, h("h1", { tabindex: "-1" }, "Skills"),
        empty("No runs yet. Run `runlens refresh`, then `runlens dashboard`."));
    }
    const span = DATA.window.first ? `${fmt.day(DATA.window.first)} – ${fmt.day(DATA.window.last)}` : "";
    return h("article", { class: "page" },
      h("header", { class: "pagehead" },
        h("h1", { tabindex: "-1" }, "Skills"),
        h("p", { class: "lede" }, `How each skill performed across ${fmt.runs(DATA.window.runs)}${span ? ` (${span})` : ""}, compared with an average run. 100 is average; higher is better.`)),
      tabbed("Kind of unit", [
        { id: "skills", label: `Skills · ${skills.length}`, build: () => skillsPanel(skills) },
        { id: "roles", label: `Agent roles · ${roles.length}`, build: () => rolesPanel(roles) },
        { id: "groups", label: `Groups · ${groups.length}`, build: () => groupsPanel(groups) },
      ]));
  }

  function skillsPanel(list) {
    if (!list.length) return empty("No skill has run yet.");
    const cols = [nameCol("Skill"), scoreCol, changeCol, versionsCol, runsCol, costCol, timeCol, errCol, lastCol];
    const better = list.filter((u) => verdict(u.score, u.ci).tone === "good").length;
    const worse = list.filter((u) => verdict(u.score, u.ci).tone === "bad").length;
    const spend = list.reduce((n, u) => n + (DATA.runs[u.id] || []).reduce((m, r) => m + (r.cost || 0), 0), 0);
    const versions = list.flatMap((u) => recordedOf(u));
    const unrecorded = list.filter((u) => (DATA.versions[u.id] || []).length && !recordedOf(u).length).map((u) => u.name);
    return h("div", {},
      h("div", { class: "kpis" },
        kpi("Skills", fmt.num(list.length, 0), `${better} better than average`),
        kpi("Versions", fmt.num(versions.length, 0), `recorded, across ${list.filter((u) => recordedOf(u).length).length} skills`),
        kpi("Runs", fmt.num(DATA.window.runs, 0), DATA.window.first ? `${fmt.day(DATA.window.first)} – ${fmt.day(DATA.window.last)}` : ""),
        kpi("Model spend", fmt.usd(spend), "across the skills"),
        kpi("Worse than average", fmt.num(worse, 0), `${list.length - better - worse} not clear yet`)),
      h("div", { class: "charts" },
        card("Score range by skill", rangePlot(list)),
        card("Version history", versionLanes(list),
          legendOf([{ cls: "good", label: "better than the version before" }, { cls: "bad", label: "worse" },
            { cls: "neutral", label: "no clear change" }]),
          note(`${unrecorded.length ? `No skill text was recorded for ${unrecorded.join(", ")}, so their versions are unknown. ` : ""}A version is one distinct skill text. A skill that only ever ran inside a subagent has no version of its own yet.`)),
        h("div", { class: "grid2" },
          card("Score against cost per run", bubbleChart(list),
            note("Each bubble is a skill. Further right costs more per run, higher is a better score, bigger means more runs.")),
          card("Where the spend goes", treemapChart(list))),
        card("Measures by skill", heatmap(list),
          note("The latest version against the average run. Green is better, red is worse.")),
        card("Runs per day", activityBars(list))),
      table({ caption: "Skills", cols, rows: list, sort: { key: "runs", dir: -1 } }).el,
      note("Latest change compares the newest version with the one before it. “Unclear” means their likely ranges overlap."),
      h("details", { class: "more" }, h("summary", {}, `All ${versions.length} recorded versions`), versionTable(list)));
  }

  function rolesPanel(list) {
    const state = { text: "", once: false };
    const count = h("p", { class: "note", "aria-live": "polite" });
    const t = table({ caption: "Agent roles", cols: [nameCol("Agent role"), scoreCol, runsCol, costCol, timeCol, errCol, lastCol],
      rows: [], sort: { key: "runs", dir: -1 }, page: PAGE });
    const apply = () => {
      const q = state.text.trim().toLowerCase();
      const rows = list.filter((u) => (state.once || u.runs >= 2) && (!q || u.name.toLowerCase().includes(q)));
      t.setRows(rows);
      const hidden = list.length - list.filter((u) => u.runs >= 2).length;
      count.textContent = `${rows.length} shown${state.once || !hidden ? "" : ` · ${hidden} seen only once are hidden`}`;
    };
    const search = h("input", { type: "search", placeholder: "Search roles", "aria-label": "Search agent roles" });
    search.addEventListener("input", () => {
      state.text = search.value;
      apply();
    });
    const once = h("input", { type: "checkbox" });
    once.addEventListener("change", () => {
      state.once = once.checked;
      apply();
    });
    apply();
    return h("div", {},
      h("div", { class: "toolbar" }, search, h("label", { class: "check" }, once, " Include roles seen once")),
      count, t.el,
      note("Agent roles are the subagents Claude Code started, grouped by type and task. Each is scored against an average subagent run."));
  }

  function groupsPanel(list) {
    if (!list.length) {
      return h("div", { class: "howto" },
        h("h2", {}, "Groups score a set of skills together"),
        h("p", {}, "Use a group to see a whole flow at once, such as a plan, a build and a review. Add one to ~/.runlens/config.toml, then run runlens dashboard again:"),
        h("pre", { class: "snippet" }, '[[group]]\nname = "my-flow"\nmembers = ["skill:my-plan", "skill:my-build"]'));
    }
    const cols = [nameCol("Group"), scoreCol, runsCol, costCol, timeCol, errCol, lastCol];
    return h("div", {}, card("Score range by group", rangePlot(list)),
      table({ caption: "Groups", cols, rows: list, sort: { key: "runs", dir: -1 } }).el);
  }

  // ---- one skill, role or group ---------------------------------------------------

  function unitPage(id) {
    const u = UNITS.get(id);
    const versions = DATA.versions[id] || [];
    const runs = DATA.runs[id] || [];
    const v = verdict(u.score, u.ci);
    const few = u.low_sample ? ` Only ${fmt.runs(u.runs)} so far, so it can still move.` : "";
    const members = u.kind === "group" ? ` Members: ${u.members.join(", ")}.` : "";
    return h("article", { class: "page" },
      h("header", { class: "pagehead" },
        h("a", { class: "back", href: "#/" }, "← All skills"),
        h("h1", { tabindex: "-1" }, u.name, " ", chip(KIND[u.kind], "kind")),
        h("p", { class: `summary ${v.tone}` }, v.sentence + few + members)),
      overview(u, versions),
      tabbed("Details", [
        { id: "versions", label: "Versions", build: () => versionsPanel(u, versions) },
        { id: "drivers", label: "What drives the score", build: () => driversPanel(u, versions) },
        { id: "runs", label: "Runs", build: () => runsPanel(u, runs, versions) },
      ]));
  }

  // How many versions this unit really has: only those whose skill text Claude Code recorded.
  function versionNote(u, versions) {
    if (u.kind === "agent") return "no versions";
    const recorded = versions.filter((v) => v.recorded).length;
    if (!recorded) return "text not recorded";
    return `${recorded} recorded ${recorded === 1 ? "version" : "versions"}`;
  }

  // A version without a recorded skill text is named by what is known, not by a number.
  const nameOf = (v) => (v.recorded ? v.label : "unrecorded");

  function versionsPanel(u, versions) {
    if (u.kind === "agent") return note("Agent roles have no versions. Their runs are scored as one group.");
    if (!versions.length) return empty("No runs yet.");
    if (!versions.some((v) => v.recorded)) {
      return note("Claude Code did not record this skill's text in these runs, so there are no versions to compare.");
    }
    const chart = versions.some((x) => x.score != null)
      ? card("Score by version", scoreChart(versions),
        note("Each dot is a version's score. The bar is its likely range. The dashed line is an average run."))
      : empty("No version has a score yet.");
    const list = h("ol", { class: "vlist" }, [...versions].reverse().map((v) => versionRow(u, versions, v)));
    return h("div", {},
      card("When each version was in use", timeline(versions),
        legendOf([{ cls: "good", label: "clearly better than the version before" }, { cls: "bad", label: "clearly worse" },
          { cls: "neutral", label: "no clear change" }])),
      h("div", { class: "twocol" }, chart, list));
  }

  function versionRow(u, versions, v) {
    const prev = versions[versions.indexOf(v) - 1] || null;
    const cur = v.label === u.current;
    const hashes = v.recorded ? v.parts.map((p) => p.hash).join(" + ") : "text not recorded";
    const c = change(v);
    return h("li", { class: "vrow", id: `ver-${v.label}` },
      h("div", { class: "vhead" }, h("strong", {}, nameOf(v)), cur ? chip("current", "ok") : null, h("code", {}, hashes)),
      h("div", { class: "vmeta" }, `${fmt.day(v.first_seen)} – ${fmt.day(v.last_seen)} · ${fmt.runs(v.runs)}`, v.low_sample ? chip("few runs", "warn") : null),
      h("div", { class: "vscore" },
        h("strong", {}, fmt.score(v.score)), " ",
        h("span", { class: "ci" }, v.ci ? fmt.interval(v.ci) : ""), " ",
        prev ? h("span", { class: `change ${c.tone}` }, c.text ? `${c.arrow} ${c.text}` : "") : h("span", { class: "muted" }, "first version seen")),
      prev ? changesDetails(v, prev, u) : null);
  }

  function changesDetails(v, prev, u) {
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

  function scoreChart(versions) {
    const pts = versions.filter((v) => v.score != null);
    const W = 400, H = 230, L = 36, R = 12, T = 12, B = 30;
    const lows = pts.map((v) => (v.ci ? v.ci[0] : v.score)).concat(100);
    const highs = pts.map((v) => (v.ci ? v.ci[1] : v.score)).concat(100);
    const low = Math.min(...lows), high = Math.max(...highs);
    const step = [5, 10, 25, 50].find((s) => (high - low + 10) / s <= 7) || 50;
    const lo = Math.floor((low - 5) / step) * step;
    const hi = Math.ceil((high + 5) / step) * step;
    const x = (i) => (pts.length === 1 ? (L + W - R) / 2 : L + (i * (W - L - R)) / (pts.length - 1));
    const y = (s) => T + (H - T - B) * (1 - (s - lo) / (hi - lo));
    const chart = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Score by version: ${pts.map((v) => `${v.label} ${fmt.score(v.score)}`).join(", ")}` });
    for (let t = lo; t <= hi; t += step) {
      chart.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y(t), y2: y(t) }),
        svg("text", { class: "axis", x: L - 6, y: y(t) + 4, "text-anchor": "end" }, t));
    }
    chart.append(svg("line", { class: "ref", x1: L, x2: W - R, y1: y(100), y2: y(100) }));
    chart.append(svg("polyline", { class: "trendline", points: pts.map((v, i) => `${x(i)},${y(v.score)}`).join(" ") }));
    pts.forEach((v, i) => {
      if (v.ci) chart.append(svg("line", { class: "ci-bar", x1: x(i), x2: x(i), y1: y(v.ci[0]), y2: y(v.ci[1]) }));
      chart.append(svg("circle", { class: "pt", cx: x(i), cy: y(v.score), r: 5 }, svg("title", {}, `${v.label}: ${fmt.score(v.score)}`)));
      chart.append(svg("text", { class: "axis", x: x(i), y: H - 10, "text-anchor": "middle" }, v.label));
    });
    return chart;
  }

  function driversPanel(u, versions) {
    const withData = versions.filter((x) => Object.keys(x.metrics || {}).length);
    if (!withData.length) return empty("No measure has data for this unit yet.");
    const current = withData.find((x) => x.label === u.current) || withData[withData.length - 1];
    const select = h("select", { "aria-label": "Version" }, withData.map((x) =>
      h("option", { value: x.key, selected: x.key === current.key ? true : null }, `${x.label} · ${fmt.runs(x.runs)}`)));
    const holder = h("div", {});
    const draw = () => {
      const v = withData.find((x) => x.key === select.value) || current;
      holder.replaceChildren(h("div", { class: "twocol side" },
        card("Spend by version", donut(versionSpend(versions, DATA.runs[u.id] || []))),
        breakdownTable(v)));
    };
    select.addEventListener("change", draw);
    draw();
    return h("div", {},
      h("label", { class: "inline" }, "Version ", select),
      holder,
      note("A bar to the right of the centre line is better than average. Weights: cost counts three times; time, tool errors, problems and your messages count twice; the rest once."));
  }

  function ratioBar(ratio) {
    const W = 140, H = 14, mid = W / 2;
    const lr = Math.log(ratio);
    const len = Math.min(1, Math.abs(lr) / LOG_CAP) * (mid - 2);
    return svg("svg", { class: "ratio", viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" },
      svg("line", { class: "axis", x1: mid, x2: mid, y1: 0, y2: H }),
      svg("rect", { class: lr >= 0 ? "bar-pos" : "bar-neg", x: lr >= 0 ? mid : mid - len, y: 3, width: Math.max(len, 0.5), height: H - 6, rx: 2 }));
  }

  function breakdownTable(v) {
    const rows = METRICS.filter((m) => v.metrics[m.key]).map((m) => {
      const d = v.metrics[m.key];
      const word = d.ratio >= 1.05 ? "better" : d.ratio <= 0.95 ? "worse" : "about average";
      const tone = d.ratio >= 1.05 ? "good" : d.ratio <= 0.95 ? "bad" : "";
      return [
        h("span", {}, metricLabel(m), h("span", { class: "sub block" }, metricHelp(m))),
        fmt.metric(m, d.value),
        fmt.metric(m, d.ref),
        h("span", { class: `ratio-cell ${tone}` }, ratioBar(d.ratio), h("span", {}, word)),
        fmt.num(d.n, 0),
      ];
    });
    return plain("What drives the score",
      [{ label: "Measure" }, { label: "This unit", num: true }, { label: "Average run", num: true }, { label: "Compared with average" }, { label: "Runs", num: true }],
      rows);
  }

  function runsPanel(u, runs, versions) {
    if (!runs.length) return empty("No runs yet.");
    const cols = [
      { key: "started", label: "Started", value: (r) => r.started, cell: (r) => fmt.when(r.started) },
      { key: "task", label: "Task", value: (r) => r.task, cell: (r) => h("span", { class: "task", title: r.task || "" }, r.task || "—") },
      { key: "version", label: "Version", value: (r) => r.version },
      { key: "cost", label: "Cost", num: true, value: (r) => r.cost, cell: (r) => fmt.usd(r.cost) },
      { key: "seconds", label: "Time", num: true, value: (r) => r.seconds, cell: (r) => fmt.secs(r.seconds) },
      { key: "errors", label: "Tool errors", num: true, value: (r) => (r.calls ? r.call_errors / r.calls : null),
        cell: (r) => (r.calls ? `${r.call_errors} of ${r.calls}` : "—") },
      { key: "incidents", label: "Problems", num: true, value: (r) => r.incidents },
    ];
    if (u.kind !== "agent") cols.push({ key: "prompts", label: "Your messages", num: true, value: (r) => r.interventions });
    return h("div", {},
      h("div", { class: "charts" },
        card("Cost per run over time", runScatter(runs, versions)),
        card("Cost against time per run", costTimeScatter(runs, versions))),
      table({ caption: "Runs", cols, rows: runs, sort: { key: "started", dir: -1 }, page: PAGE }).el);
  }

  // ---- compare two versions -------------------------------------------------------

  function defaultPair() {
    const candidates = DATA.units.filter((u) => (DATA.versions[u.id] || []).length >= 2).sort((a, b) => b.runs - a.runs);
    const base = candidates[0] || DATA.units[0];
    const vs = (base && DATA.versions[base.id]) || [];
    const last = vs[vs.length - 1];
    const prev = vs[vs.length - 2] || last;
    return {
      a: { id: base ? base.id : null, key: prev ? prev.key : null },
      b: { id: base ? base.id : null, key: last ? last.key : null },
    };
  }

  const findVersion = (s) => (DATA.versions[s.id] || []).find((v) => v.key === s.key) || null;

  function unitOptions(selected) {
    return ["skill", "agent", "group"].map((kind) => {
      const list = DATA.units.filter((u) => u.kind === kind);
      return list.length
        ? h("optgroup", { label: `${KIND[kind]}s` },
          list.map((u) => h("option", { value: u.id, selected: u.id === selected ? true : null }, u.runs ? u.name : `${u.name} (no runs)`)))
        : null;
    });
  }

  function versionOptions(id, selected) {
    const vs = DATA.versions[id] || [];
    if (!vs.length) return [h("option", { value: "" }, "no versions")];
    return vs.map((v) => h("option", { value: v.key, selected: v.key === selected ? true : null },
      `${v.label} · ${v.parts.map((p) => p.hash).join("+") || "–"} · ${fmt.runs(v.runs)}`));
  }

  function pctChange(a, b) {
    if (!a) return "—";
    const d = b / a - 1;
    const word = Math.abs(d) < 0.02 ? "about the same" : d < 0 ? "lower (better)" : "higher (worse)";
    return `${fmt.signed(100 * d, 0)}% · ${word}`;
  }

  function sideCard(label, v, name) {
    return h("article", { class: "sidecard" },
      h("p", { class: "kicker" }, label),
      h("h2", {}, `${name} · ${v.label}`),
      h("div", { class: "big" }, fmt.score(v.score)),
      h("p", { class: "ci" }, v.ci ? `likely range ${fmt.interval(v.ci)}` : "no range yet"),
      h("p", { class: "sub" }, `${fmt.runs(v.runs)} · ${v.parts.map((p) => p.hash).join(" + ") || "no skill text"}`),
      v.low_sample ? chip("few runs", "warn") : null);
  }

  function comparison(sa, sb) {
    const A = findVersion(sa), B = findVersion(sb);
    if (!A || !B) return empty("Pick a unit and a version on both sides.");
    if (A === B) return empty("Pick two different versions to compare.");
    const nameA = UNITS.get(A.id).name, nameB = UNITS.get(B.id).name;
    const ov = overlaps(A.ci, B.ci);
    let text;
    if (A.score == null || B.score == null) text = "At least one side has no score yet.";
    else if (ov === null) text = "One side has too few runs for a range, so no difference can be called.";
    else if (ov) text = `No clear difference: their likely ranges overlap (${fmt.score(A.score)} and ${fmt.score(B.score)}).`;
    else text = `${B.score > A.score ? `${nameB} · ${B.label}` : `${nameA} · ${A.label}`} is clearly higher: the ranges do not overlap (${fmt.score(A.score)} vs ${fmt.score(B.score)}).`;

    const rows = METRICS.filter((m) => A.metrics[m.key] && B.metrics[m.key]).map((m) => {
      const a = A.metrics[m.key].value, b = B.metrics[m.key].value;
      return [metricLabel(m), fmt.metric(m, a), fmt.metric(m, b), pctChange(a, b), fmt.num(A.metrics[m.key].n, 0), fmt.num(B.metrics[m.key].n, 0)];
    });
    return h("div", {},
      h("div", { class: "sides" }, sideCard("A", A, nameA), sideCard("B", B, nameB)),
      h("p", { class: "verdict" }, text),
      card("Profile", radar([{ v: A, label: `A · ${nameA} ${A.label}`, cls: "s0" }, { v: B, label: `B · ${nameB} ${B.label}`, cls: "s1", dashed: true }]),
          legendOf([{ cls: "s0", label: `A · ${nameA} ${A.label}` }, { cls: "s1", label: `B · ${nameB} ${B.label}` }])),
      card("Side by side", legendOf([{ cls: "s0", label: `A · ${nameA} ${A.label}` }, { cls: "s1", label: `B · ${nameB} ${B.label}` }]), pairBars(A, B)),
      plain("Measures compared",
        [{ label: "Measure" }, { label: "A", num: true }, { label: "B", num: true }, { label: "B against A" }, { label: "Runs in A", num: true }, { label: "Runs in B", num: true }],
        rows),
      note("Every measure here is a cost, a time or a count of failures, so lower is better. A change under 2% is shown as about the same."));
  }

  function compareView(params) {
    if (!DATA.units.length) return h("article", { class: "page" }, h("h1", { tabindex: "-1" }, "Compare"), empty("No runs yet."));
    const d = defaultPair();
    const pick = (side) => {
      const fallback = d[side];
      const id = UNITS.has(params.get(side)) ? params.get(side) : fallback.id;
      const vs = DATA.versions[id] || [];
      const wanted = params.get(`${side}v`);
      const usesDefault = id === fallback.id && vs.some((v) => v.key === fallback.key);
      const key = vs.some((v) => v.key === wanted) ? wanted
        : usesDefault ? fallback.key
        : (vs[vs.length - 1] || {}).key || null;
      return { id, key };
    };
    const sides = { a: pick("a"), b: pick("b") };
    const results = h("div", { "aria-live": "polite" });

    const update = () => {
      results.replaceChildren(comparison(sides.a, sides.b));
      history.replaceState(null, "", `#/compare?${new URLSearchParams({ a: sides.a.id || "", av: sides.a.key || "", b: sides.b.id || "", bv: sides.b.key || "" })}`);
    };

    const build = (side) => {
      const unitSel = h("select", { id: `unit-${side}` }, unitOptions(sides[side].id));
      const verSel = h("select", { id: `ver-${side}` }, versionOptions(sides[side].id, sides[side].key));
      unitSel.addEventListener("change", () => {
        const vs = DATA.versions[unitSel.value] || [];
        sides[side] = { id: unitSel.value, key: vs.length ? vs[vs.length - 1].key : null };
        verSel.replaceChildren(...versionOptions(unitSel.value, sides[side].key));
        update();
      });
      verSel.addEventListener("change", () => {
        sides[side] = { id: unitSel.value, key: verSel.value };
        update();
      });
      return h("fieldset", {}, h("legend", {}, side.toUpperCase()), h("label", {}, "Skill or role", unitSel), h("label", {}, "Version", verSel));
    };

    update();
    return h("article", { class: "page" },
      h("header", { class: "pagehead" },
        h("h1", { tabindex: "-1" }, "Compare two versions"),
        h("p", { class: "lede" }, "Pick any two skills, roles or groups, and any of their versions. The verdict says whether the scores differ beyond their likely ranges.")),
      h("div", { class: "pick" }, build("a"), build("b")),
      results);
  }

  // ---- how it works ---------------------------------------------------------------

  function methodView() {
    const m = DATA.method;
    const formula = [
      "score    = 100 × exp( Σᵢ wᵢ · ℓᵢ / Σᵢ wᵢ )",
      "ℓᵢ       = clip( ln((avgᵢ + f) / (countedᵢ + f)), −ln 2, +ln 2 )",
      "countedᵢ = (nᵢ · meanᵢ + K · avgᵢ) / (nᵢ + K)",
      `f = ${m.floor} × avgᵢ      K = ${m.shrink}`,
    ].join("\n");
    const qa = (q, a) => h("div", { class: "qa-item" }, h("h2", {}, q), h("p", {}, a));
    return h("article", { class: "page" },
      h("header", { class: "pagehead" },
        h("h1", { tabindex: "-1" }, "How it works"),
        h("p", { class: "lede" }, "Every number comes from your recorded runs. Nothing is labelled by hand, and nothing leaves this machine.")),
      h("div", { class: "qa" },
        qa("What does 100 mean?",
          "The average run of the same kind (skill, agent role or group) in your history. Above 100 means the unit did better than that average on the measures below; below 100, worse."),
        qa("What is the likely range?",
          `The range comes from re-sampling its runs ${m.resamples} times. If the whole range is above 100 the verdict is "better"; if it is all below 100, "worse"; otherwise "not clear yet". Two versions are only called different when their ranges do not overlap.`),
        qa("What does it measure?",
          "Cost, time, tool errors, problems (error streaks, repeated calls, interrupts), your messages while the skill ran, waiting calls, API errors, and the checks your config marks as failed. Cost counts three times; time, errors, problems and messages twice; the rest once."),
        qa("What does it not measure?",
          "Whether a run produced the right result. Before acting on a drop, read the traces with runlens show.")),
      h("details", { class: "more" },
        h("summary", {}, "Exact formula and settings"),
        h("pre", { class: "formula" }, formula),
        plain("Settings", [{ label: "Setting" }, { label: "Value", num: true }, { label: "Meaning" }], [
          ["Shrink K", m.shrink, "pseudo-runs at the average that every unit starts with"],
          ["Ratio clip", `×${m.max_ratio}`, "the most one measure can count for, either way"],
          ["Floor f", m.floor, "fraction of the average added to both sides, so zero values stay finite"],
          ["Turn cap", `${m.turn_cap} s`, "longest time credited to one gap between two model turns"],
          ["Resamples", m.resamples, "re-samples behind each range"],
          ["Few-runs flag", `under ${m.min_runs} runs`, "scores are still shown, but marked"],
        ])),
      h("details", { class: "more" },
        h("summary", {}, "How runs are assigned to versions and groups"),
        h("p", {}, "A run belongs to the version of each skill it loaded, identified by a hash of the skill text. A run that did not load a skill uses the version that was current when it started. Versions are numbered by first appearance. A group's runs are the union of its members' work, each piece counted once, and its version changes when any member's text changes."),
        h("p", {}, "An agent role is a subagent type with its folded description. Roles have no versions, and your messages are not attributed to them.")));
  }

  // ---- routing, theme, footer -----------------------------------------------------

  const safeDecode = (s) => {
    try {
      return decodeURIComponent(s);
    } catch (e) {
      return s;
    }
  };

  function route() {
    const raw = location.hash.replace(/^#/, "") || "/";
    const [path, query = ""] = raw.split("?");
    const parts = path.split("/").filter(Boolean).map(safeDecode);
    const params = new URLSearchParams(query);
    let page = "skills";
    let view;
    if (parts[0] === "unit" && UNITS.has(parts[1])) view = unitPage(parts[1]);
    else if (parts[0] === "compare") {
      page = "compare";
      view = compareView(params);
    } else if (parts[0] === "method") {
      page = "method";
      view = methodView();
    } else view = homeView();

    app.replaceChildren(view);
    window.scrollTo(0, 0);
    const target = { skills: "#/", compare: "#/compare", method: "#/method" }[page];
    for (const a of document.querySelectorAll(".top nav a")) {
      if (a.getAttribute("href") === target) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    const title = view.querySelector("h1");
    if (title) title.focus({ preventScroll: true });
  }

  const themeBtn = document.getElementById("theme");
  const THEMES = ["auto", "light", "dark"];
  let theme = "auto";
  try {
    theme = localStorage.getItem("runlens-theme") || "auto";
  } catch (e) {
    theme = "auto";
  }
  function applyTheme() {
    if (theme === "auto") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    themeBtn.textContent = `Theme: ${theme}`;
  }
  themeBtn.addEventListener("click", () => {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    try {
      localStorage.setItem("runlens-theme", theme);
    } catch (e) {
      /* storage can be blocked; the choice then lasts for this page only */
    }
    applyTheme();
    const y = window.scrollY;
    route();
    window.scrollTo(0, y);
  });
  applyTheme();

  document.getElementById("foot").textContent =
    `Generated ${fmt.when(DATA.generated)} · ${fmt.runs(DATA.window.runs)} · computed from your local runlens database, nothing is sent anywhere.`;

  window.addEventListener("hashchange", route);
  route();
})();
