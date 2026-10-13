/* charts/tooltip.js: one tooltip for the whole page, reachable by mouse, touch and keyboard.

   A mark becomes interactive with tipMark(el, info). Its details then show on hover, on tap, and when it
   has keyboard focus. Within one chart the marks form a single tab stop: Tab enters the chart, the arrow
   keys move between its marks, Home and End jump to the ends, Enter follows a mark's link, Escape hides
   the tooltip. Each mark's aria-label carries the same text, so a screen reader hears what a mouse sees.
   The tooltip never holds the only copy of a value: every chart has a table view and a CSV export. */

const TIP = h("div", { class: "tip", role: "tooltip", id: "tip", hidden: true });
const TIP_INFO = new WeakMap();
let tipOwner = null;

// info: {title, rows: [[label, value]], href, sub}
function tipMark(el, info) {
  TIP_INFO.set(el, info);
  el.classList.add("mark");
  el.setAttribute("tabindex", "-1");
  el.setAttribute("role", info.href ? "link" : "img");
  el.setAttribute("aria-label", tipText(info));
  return el;
}
const tipText = (info) => [info.title, ...(info.rows || []).map(([k, v]) => (k ? `${k}: ${v}` : v)), info.sub].filter(Boolean).join(", ");

function showTip(el, x, y) {
  const info = TIP_INFO.get(el);
  if (!info) return;
  if (!TIP.isConnected) document.body.append(TIP);
  tipOwner = el;
  fill(TIP,
    info.title ? h("div", { class: "tip-title" }, info.title) : null,
    (info.rows || []).length ? h("dl", { class: "tip-rows" }, info.rows.map(([k, v, key]) => [
      h("dt", {}, key ? h("span", { class: "tip-key", style: `background:${key}` }) : null, k || ""),
      h("dd", {}, v)])) : null,
    info.sub ? h("div", { class: "tip-sub" }, info.sub) : null,
    info.href ? h("div", { class: "tip-sub" }, "Press Enter or click to open") : null);
  TIP.hidden = false;
  const r = TIP.getBoundingClientRect();
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  let left = x + 14, top = y + 14;
  if (left + r.width > vw - 8) left = Math.max(8, x - r.width - 14);
  if (top + r.height > vh - 8) top = Math.max(8, y - r.height - 14);
  TIP.style.left = `${left}px`;
  TIP.style.top = `${top}px`;
  el.classList.add("hot");
}
function hideTip() {
  if (tipOwner) tipOwner.classList.remove("hot");
  tipOwner = null;
  TIP.hidden = true;
}
const anchorOf = (el) => {
  const r = el.getBoundingClientRect();
  return [r.left + r.width / 2, r.top + Math.min(r.height / 2, 12)];
};

// Event delegation: one set of listeners per chart, whatever the number of marks.
function wireTips(root) {
  const marks = () => [...root.querySelectorAll(".mark")];
  const first = root.querySelector(".mark");
  if (first) first.setAttribute("tabindex", "0");
  const markOf = (e) => (e.target && e.target.closest ? e.target.closest(".mark") : null);
  root.addEventListener("pointermove", (e) => {
    const m = markOf(e);
    if (m) showTip(m, e.clientX, e.clientY);
    else if (tipOwner && root.contains(tipOwner)) hideTip();
  });
  root.addEventListener("pointerleave", () => {
    if (tipOwner && root.contains(tipOwner)) hideTip();
  });
  let armed = null; // on touch, the first tap shows the details and a second tap on the same mark follows its link
  root.addEventListener("pointerdown", (e) => {
    const m = markOf(e);
    if (!m || e.pointerType === "mouse") return;
    armed = tipOwner === m ? m : null;
    showTip(m, e.clientX, e.clientY);
  });
  root.addEventListener("click", (e) => {
    const m = markOf(e);
    const info = m && TIP_INFO.get(m);
    if (!info || !info.href) return;
    if (e.pointerType === "touch" || e.pointerType === "pen") {
      if (armed !== m) return;
    }
    location.hash = info.href;
  });
  root.addEventListener("focusin", (e) => {
    const m = markOf(e);
    if (!m) return;
    for (const x of marks()) x.setAttribute("tabindex", x === m ? "0" : "-1");
    const [x, y] = anchorOf(m);
    showTip(m, x, y);
  });
  root.addEventListener("focusout", (e) => {
    if (!root.contains(e.relatedTarget)) hideTip();
  });
  root.addEventListener("keydown", (e) => {
    const m = markOf(e);
    if (!m) return;
    const all = marks();
    const i = all.indexOf(m);
    let j = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") j = Math.min(all.length - 1, i + 1);
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = Math.max(0, i - 1);
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = all.length - 1;
    else if (e.key === "Escape") {
      hideTip();
      return;
    } else if (e.key === "Enter") {
      const info = TIP_INFO.get(m);
      if (info && info.href) location.hash = info.href;
      return;
    }
    if (j === null) return;
    e.preventDefault();
    all[j].focus();
  });
}

// A tap outside any chart, a scroll or Escape anywhere hides the tooltip.
document.addEventListener("pointerdown", (e) => {
  if (tipOwner && !(e.target.closest && e.target.closest(".mark"))) hideTip();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideTip();
});
window.addEventListener("scroll", () => {
  if (tipOwner && document.activeElement !== tipOwner) hideTip();
}, { passive: true });

// Glossary terms (core/dom.js term()): their meaning in the same tooltip, on hover, tap and keyboard focus.
let termOwner = null;
function showTermTip(el) {
  if (!TIP.isConnected) document.body.append(TIP);
  hideTip();
  termOwner = el;
  fill(TIP, h("div", { class: "tip-title" }, el.firstChild ? el.firstChild.textContent : ""), h("div", { class: "tip-def" }, el.dataset.def));
  TIP.hidden = false;
  const a = el.getBoundingClientRect(), r = TIP.getBoundingClientRect();
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  const left = Math.max(8, Math.min(vw - r.width - 8, a.left));
  const top = a.bottom + 6 + r.height > vh - 8 ? Math.max(8, a.top - r.height - 6) : a.bottom + 6;
  TIP.style.left = `${left}px`;
  TIP.style.top = `${top}px`;
}
function hideTermTip() {
  if (!termOwner) return;
  termOwner = null;
  TIP.hidden = true;
}
const termOf = (e) => (e.target && e.target.closest ? e.target.closest(".term") : null);
document.addEventListener("pointerover", (e) => { const t = termOf(e); if (t) showTermTip(t); });
document.addEventListener("pointerout", (e) => { const t = termOf(e); if (t && t === termOwner && !t.contains(e.relatedTarget)) hideTermTip(); });
document.addEventListener("focusin", (e) => { const t = termOf(e); if (t) showTermTip(t); });
document.addEventListener("focusout", (e) => { if (termOf(e) === termOwner) hideTermTip(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTermTip(); });
window.addEventListener("scroll", hideTermTip, { passive: true });
