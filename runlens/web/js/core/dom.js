/* core/dom.js: building elements. Every value from the data reaches the page as a text node, never as markup. */

const SVG_NS = "http://www.w3.org/2000/svg";

function append(node, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

// Replace a node's children; like append, it skips null, undefined and false (replaceChildren would print "null").
function fill(node, ...kids) {
  node.replaceChildren();
  return append(node, kids);
}

function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  return append(node, kids);
}

function svg(tag, attrs, ...kids) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    node.setAttribute(k, typeof v === "number" ? String(Math.round(v * 10) / 10) : String(v));
  }
  return append(node, kids);
}

const chip = (text, cls) => h("span", { class: cls ? `chip ${cls}` : "chip" }, text);
const note = (text) => h("p", { class: "note" }, text);
const empty = (text) => h("p", { class: "empty" }, text);
const button = (label, onclick, attrs = {}) => h("button", { type: "button", class: "btn", ...attrs, onclick }, label);

// A key number: a label, the value, and a line of context. `tone` adds an icon and a word, never colour alone.
function kpi(label, value, sub, opts = {}) {
  const t = opts.tone ? TONE[opts.tone] : null;
  return h("div", { class: `kpi${t ? ` tone-${opts.tone}` : ""}` },
    h("div", { class: "kl" }, label),
    h("div", { class: "kv" }, value, t ? h("span", { class: "kicon", "aria-hidden": "true" }, ` ${t.icon}`) : null),
    opts.extra || null,
    h("div", { class: "ks" }, sub || ""));
}

// Sentence case slug for file names.
const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "runlens";

function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: name, hidden: true });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// Plain text of a value for CSV: numbers stay numbers, everything else is quoted when it needs to be.
// A leading = + - @ is prefixed with ' so a spreadsheet never runs a cell as a formula.
function csvCell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "";
  if (typeof v === "boolean") return v ? "true" : "false";
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function toCSV(cols, rows) {
  const lines = [cols.map((c) => csvCell(c.csvLabel || c.label)).join(",")];
  for (const r of rows) lines.push(cols.map((c) => csvCell(c.csv ? c.csv(r) : c.value(r))).join(","));
  return `﻿${lines.join("\r\n")}\r\n`;
}
const downloadCSV = (name, cols, rows) => download(`${slug(name)}.csv`, new Blob([toCSV(cols, rows)], { type: "text/csv;charset=utf-8" }));

// Text width in the page's own font, so labels can be fitted instead of cut at a fixed letter count.
const _measure = document.createElement("canvas").getContext("2d");
let _family = null;
function textWidth(text, size = 12, weight = 400) {
  if (!_measure) return String(text).length * size * 0.56;
  if (!_family) _family = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";
  _measure.font = `${weight} ${size}px ${_family}`;
  return _measure.measureText(String(text)).width;
}
function fitText(text, max, size = 12, weight = 400) {
  const s = String(text);
  if (textWidth(s, size, weight) <= max) return s;
  let lo = 0, hi = s.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (textWidth(`${s.slice(0, mid)}…`, size, weight) <= max) lo = mid;
    else hi = mid - 1;
  }
  return lo ? `${s.slice(0, lo)}…` : "…";
}

// Copy text to the clipboard; falls back to a hidden field where the Clipboard API is not allowed (file://).
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const input = h("textarea", { "aria-hidden": "true", class: "sr" });
    input.value = text;
    document.body.append(input);
    input.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    input.remove();
    return ok;
  }
}

// A command to run in a terminal, with a button that copies it.
function cmdLine(text, label) {
  const btn = h("button", { type: "button", class: "tool", "aria-label": `Copy: ${text}` }, "Copy");
  btn.addEventListener("click", async () => {
    const ok = await copyText(text);
    btn.textContent = ok ? "Copied" : "Select and copy";
    setTimeout(() => { btn.textContent = "Copy"; }, 1800);
  });
  return h("span", { class: "cmd" }, label ? h("span", { class: "muted" }, `${label} `) : null, h("code", {}, text), btn);
}

// ---- page structure: the pieces every page is built from, so they all read the same way ----

/* Key numbers: at most four as cards (the headline), the rest as one quiet line of figures under them,
   so a page opens with what matters and still shows every number. items: kpi() elements, or null. */
function kpiRow(items, opts = {}) {
  const list = items.filter(Boolean);
  const head = list.slice(0, opts.max || 4), rest = list.slice(opts.max || 4);
  return h("div", { class: "kpiblock" },
    h("div", { class: "kpis" }, head),
    rest.length ? h("dl", { class: "kpi-more", "aria-label": "More figures" }, rest.map((k) => h("div", { class: `kpi-mini${k.className.includes("tone-") ? ` ${k.className.split(" ").find((c) => c.startsWith("tone-"))}` : ""}` },
      h("dt", {}, k.querySelector(".kl").textContent),
      h("dd", {}, h("strong", {}, ...[...k.querySelector(".kv").childNodes].map((n) => n.cloneNode(true))),
        k.querySelector(".ks") && k.querySelector(".ks").textContent ? h("span", { class: "muted" }, ` · ${k.querySelector(".ks").textContent}`) : null,
        ...[...k.children].filter((c) => !["kl", "kv", "ks"].some((x) => c.classList.contains(x))))))) : null);
}

// The answer to the page's question, first: one or two plain sentences worked out from the data.
function answer(text, tone, attrs = {}) {
  return h("p", { class: `answer${tone ? ` tone-${tone}` : ""}`, ...attrs }, text);
}

/* A section: a heading, a one-line intro, then its content. With `collapsed`, the section is a disclosure
   that starts closed (its summary still names what is inside); `id` makes it a link target. */
function section(opts, ...kids) {
  const head = [h("h2", { class: "section-title" }, opts.title), opts.count != null ? h("span", { class: "section-count" }, opts.count) : null];
  const intro = opts.intro ? h("p", { class: "section-intro" }, opts.intro) : null;
  if (opts.collapsible) {
    return h("details", { class: "section fold", id: opts.id || null, open: opts.collapsed ? null : true },
      h("summary", { class: "section-head" }, head, opts.intro ? h("span", { class: "section-count" }, `· ${opts.intro}`) : null), kids);
  }
  return h("section", { class: "section", id: opts.id || null, "aria-label": typeof opts.title === "string" ? opts.title : null },
    h("div", { class: "section-head" }, head), intro, kids);
}

/* A word with its meaning on hand: dotted underline, the meaning shown on hover, tap or keyboard focus,
   and read out by screen readers as part of the sentence. */
const GLOSSARY = {
  "usual level": "100 on every score: the skill's own typical run. Above 100 is better than usual, below is worse. Skills are only compared with themselves.",
  "typical run": "The skill's usual level, scored 100: its runs pooled over every version. Above 100 is better than usual.",
  range: "The likely range of the score: where the true value probably sits, given how much the runs vary. A range that crosses 100 means not clearly different from usual.",
  confounded: "Something else changed at the same time as the skill text (another skill, the model, the effort, Claude Code or the project), so a difference cannot be put down to this skill.",
  "not scored": "There are enough runs, but no measure with a weight above 0 could be compared.",
  "not enough runs": "A verdict needs enough runs on each side of a change; with fewer, the difference could be noise.",
  verdict: "Better, worse or no clear change: the newest version against the one before it, from the difference between their runs.",
  "Pareto frontier": "The line through the items that nothing else beats on both axes at once: cheaper and better. Items below and right of it are beaten by something on the line.",
  "Wilson interval": "A range for a success rate that stays sensible with few attempts; the true weekly rate probably sits inside the band.",
  "stub runs": "Runs too small to score: a skill loaded and barely used.",
  "log scale": "Each step along the axis multiplies the value (1, 10, 100), so small and large values both stay readable.",
};
function term(word, def) {
  const text = def || GLOSSARY[word] || GLOSSARY[String(word).toLowerCase()] || "";
  if (!text) return word;
  return h("span", { class: "term", tabindex: "0", "data-def": text }, word, h("span", { class: "sr" }, ` (${text})`));
}

// A version's text, named: the hash of each skill text in it, with the skill's name when it holds several.
function partsText(v, sep = " · ") {
  const parts = (v && v.parts) || [];
  if (!parts.length) return "";
  return parts.length === 1 ? parts[0].hash : parts.map((p) => `${p.skill} ${p.hash}`).join(sep);
}

// "1 skill", "3 skills": a count with its noun.
const plural = (n, one, many) => `${fmt.int(n)} ${n === 1 ? one : many || `${one}s`}`;
// A list in words: "a, b and c".
function listWords(xs, max = 4) {
  const a = xs.slice(0, max);
  const more = xs.length - a.length;
  if (more > 0) return `${a.join(", ")} and ${more} more`;
  return a.length > 1 ? `${a.slice(0, -1).join(", ")} and ${a[a.length - 1]}` : a.join("");
}
