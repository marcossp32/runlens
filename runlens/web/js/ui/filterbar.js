/* ui/filterbar.js: the filters under the header. They scope every page.

   Closed, the bar is one quiet line: a "Filters" button, a chip for each active filter (a click removes it),
   and how many runs are left. Open, it shows every control: each dimension is a small menu of checkboxes
   (none ticked = all), the dates take a preset or a range, and two switches. Every change is written to the
   URL and the page redraws against the new slice. */

const BAR_EL = document.getElementById("filterbar");
let barOpen = null; // the dimension whose menu was open, kept open across the redraw a change causes
let barExpanded = false; // the controls are shown (the reader opened them); kept across redraws

function refreshAfter(changes) {
  setParams(changes);
  route();
}

function dimMenu(d) {
  const opts = FILTER_OPTIONS[d.key] || [];
  const set = F.sets[d.key];
  const show = d.show || String;
  const label = !set ? "all" : set.size === 1 ? show([...set][0]) : `${set.size} ${d.plural}`;
  const box = h("details", { class: `fdrop${set ? " on" : ""}`, "data-dim": d.key },
    h("summary", { class: "fbtn", "aria-label": `${d.label}: ${label}` }, h("span", { class: "fk" }, d.label), " ", h("span", { class: "fv" }, fitText(label, 150, 13))));
  if (!opts.length) {
    box.append(h("div", { class: "fpanel" }, note("Not recorded.")));
    return box;
  }
  const write = (values) => refreshAfter({ [d.key]: values.length && values.length < opts.length ? values.join(",") : null });
  const search = opts.length > 8 ? h("input", { type: "search", class: "fsearch", placeholder: `Find ${d.plural}`, "aria-label": `Find ${d.plural}` }) : null;
  const list = h("ul", { class: "flist" }, opts.map((o) => {
    const cb = h("input", { type: "checkbox", value: String(o.value) });
    cb.checked = Boolean(set && set.has(o.value));
    cb.addEventListener("change", () => {
      barOpen = { dim: d.key, value: String(o.value) };
      const cur = new Set(set || []);
      if (cb.checked) cur.add(o.value);
      else cur.delete(o.value);
      write([...cur]);
    });
    const dot = d.key === "skills" ? colourOf("skill", o.value) : d.key === "model" ? colourOf("model", o.value) : null;
    return h("li", { "data-text": String(o.value).toLowerCase() }, h("label", {}, cb,
      dot && !dot.other ? svg("svg", { class: "lkey", width: 10, height: 10, "aria-hidden": "true" }, marker(dot.shape, 5, 5, 4, { style: `fill:${dot.css}` })) : null,
      h("span", { class: "fopt" }, show(o.value)), h("span", { class: "fcount" }, fmt.int(o.runs))));
  }));
  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      for (const li of list.children) li.hidden = Boolean(q) && !li.dataset.text.includes(q);
    });
  }
  box.append(h("div", { class: "fpanel" }, search, list,
    h("div", { class: "fpanel-bar" }, h("span", { class: "muted" }, "runs"),
      button("All", () => { barOpen = { dim: d.key }; write([]); }, { class: "btn seg" }))));
  return box;
}

function dateControls() {
  const minDay = EX.runs.length ? localDay(Math.min(...EX.runs.map((r) => r.t0))) : "";
  const maxDay = EX.runs.length ? localDay(Math.max(...EX.runs.map((r) => r.t0))) : "";
  const sel = h("select", { "aria-label": "Dates" },
    [["", "All dates"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["90d", "Last 90 days"], ["custom", "Between dates…"]].map(([v, t]) =>
      h("option", { value: v, selected: (F.range || ((F.from || F.to) ? "custom" : "")) === v ? true : null }, t)));
  const from = h("input", { type: "date", "aria-label": "From", value: F.from || "", min: minDay, max: maxDay });
  const to = h("input", { type: "date", "aria-label": "To", value: F.to || "", min: minDay, max: maxDay });
  const custom = h("span", { class: "fdates", hidden: !(F.from || F.to) || F.range ? true : null }, from, h("span", { class: "muted" }, "–"), to);
  sel.addEventListener("change", () => {
    if (sel.value === "custom") {
      custom.hidden = false;
      from.focus();
      return;
    }
    barExpanded = true;
    refreshAfter({ range: sel.value || null, from: null, to: null });
  });
  const apply = () => {
    barExpanded = true;
    refreshAfter({ range: null, from: from.value || null, to: to.value || null });
  };
  from.addEventListener("change", apply);
  to.addEventListener("change", apply);
  return h("span", { class: "fgroup" }, h("span", { class: "fk" }, "Dates"), sel, custom);
}

function toggle(label, key, on, title) {
  const cb = h("input", { type: "checkbox" });
  cb.checked = on;
  cb.addEventListener("change", () => {
    barExpanded = true;
    refreshAfter({ [key]: cb.checked ? (key === "pop" ? "all" : "1") : null });
  });
  return h("label", { class: "check ftoggle", title }, cb, ` ${label}`);
}

// The active filters as chips; each one removes its filter.
function filterChips() {
  const out = [];
  const chipBtn = (text, changes, what) => button(h("span", {}, text, h("span", { class: "fx", "aria-hidden": "true" }, " ×")),
    () => refreshAfter(changes), { class: "fchip", "aria-label": `Remove the filter ${what}: ${text}`, title: "Remove this filter" });
  if (F.range) out.push(chipBtn(`last ${RANGES[F.range]} days`, { range: null }, "dates"));
  else if (F.from || F.to) out.push(chipBtn(F.from && F.to ? `${fmt.dayKey(F.from)} – ${fmt.dayKey(F.to)}` : F.from ? `from ${fmt.dayKey(F.from)}` : `until ${fmt.dayKey(F.to)}`, { from: null, to: null }, "dates"));
  for (const d of FILTER_DIMS) {
    const set = F.sets[d.key];
    if (set) out.push(chipBtn(`${d.label.toLowerCase()} ${[...set].map(d.show || String).join(", ")}`, { [d.key]: null }, d.label.toLowerCase()));
  }
  if (F.minn) out.push(chipBtn(`at least ${MIN_RUNS} runs`, { minn: null }, "minimum runs"));
  if (F.popAll) out.push(chipBtn("open and stub runs included", { pop: null }, "open and stub runs"));
  return out;
}

function renderFilterBar() {
  if (!BAR_EL) return;
  const total = F.popAll ? EX.runs.length : populationRuns().length;
  const kept = RUNSET.size;
  const chips = filterChips();
  if (barOpen) barExpanded = true;
  const reset = button("Reset filters", () => refreshAfter(Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))), { class: "btn seg" });
  const panel = h("div", { class: "frow", id: "filterpanel", hidden: barExpanded ? null : true },
    dateControls(),
    FILTER_DIMS.map(dimMenu),
    toggle(`Hide fewer than ${MIN_RUNS} runs`, "minn", F.minn, `Hide skills, roles and versions with fewer than ${MIN_RUNS} runs: too few for a verdict`),
    toggle("Include open and stub runs", "pop", F.popAll, "Runs still open and stub runs never count in a score; this adds them to the run lists and diagnostics"));
  const trigger = h("button", { type: "button", class: `ftrigger${chips.length ? " on" : ""}`, "aria-expanded": String(barExpanded), "aria-controls": "filterpanel" },
    h("span", { class: "ficon", "aria-hidden": "true" }, barExpanded ? "▴" : "▾"), "Filters",
    chips.length ? h("span", { class: "fbadge", "aria-label": `${chips.length} active` }, fmt.int(chips.length)) : null);
  trigger.addEventListener("click", () => {
    barExpanded = !barExpanded;
    panel.hidden = !barExpanded;
    trigger.setAttribute("aria-expanded", String(barExpanded));
    trigger.querySelector(".ficon").textContent = barExpanded ? "▴" : "▾";
  });
  fill(BAR_EL,
    h("div", { class: "fbar" },
      trigger,
      h("div", { class: `fstatus${filtered() ? " active" : ""}`, role: "status" },
        h("strong", {}, `${fmt.int(kept)} of ${fmt.runs(total)}`),
        filtered() ? [h("span", { class: "fchips" }, chips), reset]
          : h("span", { class: "muted fextra" }, F.popAll ? "every run, open and stub included" : `finished runs (${fmt.int(EX.runs.length - total)} open or stub left out)`),
        slicing() ? h("span", { class: "muted fextra" }, "scores, ranges and verdicts are worked out again from these runs") : null,
        F.sets.model || F.sets.effort ? h("span", { class: "muted fextra" }, "a model or effort filter keeps the runs that used it: scores and per-skill spend count those runs whole, the charts built from calls only that model's or effort's calls") : null)),
    panel);
  // A change redraws the bar: reopen the menu the reader was using and put the focus back where it was.
  if (barOpen) {
    const box = BAR_EL.querySelector(`details[data-dim="${barOpen.dim}"]`);
    if (box) {
      box.open = true;
      const cb = barOpen.value !== undefined ? [...box.querySelectorAll("input[type=checkbox]")].find((x) => x.value === barOpen.value) : null;
      (cb || box.querySelector("summary")).focus({ preventScroll: true });
    }
    barOpen = null;
  }
}

// One open menu at a time; a click outside or Escape closes it.
document.addEventListener("click", (e) => {
  for (const d of document.querySelectorAll("details.fdrop[open], details.menu[open]")) if (!d.contains(e.target)) d.open = false;
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  for (const d of document.querySelectorAll("details.fdrop[open], details.menu[open]")) {
    d.open = false;
    d.querySelector("summary").focus();
  }
});
document.addEventListener("toggle", (e) => {
  const d = e.target;
  if (!d.open || !d.matches || !d.matches("details.fdrop, details.menu")) return;
  for (const o of document.querySelectorAll("details.fdrop[open], details.menu[open]")) if (o !== d) o.open = false;
}, true);
