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
  const lines = [cols.map((c) => csvCell(c.label)).join(",")];
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
