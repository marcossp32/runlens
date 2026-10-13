/* ui/filterbar.js: the one row of filters under the header. It scopes every page.

   Each dimension is a small menu of checkboxes (none ticked = all); the dates take a preset or a range.
   Every change is written to the URL and the page redraws against the new slice. The bar always says how
   many runs are left and what is filtered, with a reset. */

const BAR_EL = document.getElementById("filterbar");
let barOpen = null; // the dimension whose menu was open, kept open across the redraw a change causes

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
    refreshAfter({ range: sel.value || null, from: null, to: null });
  });
  const apply = () => refreshAfter({ range: null, from: from.value || null, to: to.value || null });
  from.addEventListener("change", apply);
  to.addEventListener("change", apply);
  return h("span", { class: "fgroup" }, h("span", { class: "fk" }, "Dates"), sel, custom);
}

function toggle(label, key, on, title) {
  const cb = h("input", { type: "checkbox" });
  cb.checked = on;
  cb.addEventListener("change", () => refreshAfter({ [key]: cb.checked ? (key === "pop" ? "all" : "1") : null }));
  return h("label", { class: "check ftoggle", title }, cb, ` ${label}`);
}

function renderFilterBar() {
  if (!BAR_EL) return;
  const total = F.popAll ? EX.runs.length : populationRuns().length;
  const kept = RUNSET.size;
  const words = filterWords();
  const reset = button("Reset filters", () => refreshAfter(Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))), { class: "btn seg" });
  const chips = words.length ? h("span", { class: "fchips" }, words.map((w) => h("span", { class: "fchip" }, w))) : null;
  fill(BAR_EL,
    h("div", { class: "frow" },
      dateControls(),
      FILTER_DIMS.map(dimMenu),
      toggle(`Hide fewer than ${MIN_RUNS} runs`, "minn", F.minn, `Hide skills, roles and versions with fewer than ${MIN_RUNS} runs: too few for a verdict`),
      toggle("Include open and stub runs", "pop", F.popAll, "Runs still open and stub runs never count in a score; this adds them to the run lists and diagnostics")),
    h("div", { class: `fstatus${filtered() ? " active" : ""}`, role: "status" },
      h("strong", {}, `${fmt.int(kept)} of ${fmt.runs(total)}`),
      filtered() ? [" · ", chips, " ", reset] : h("span", { class: "muted" }, F.popAll ? " · every run, open and stub included" : ` · finished runs (${fmt.int(EX.runs.length - total)} open or stub left out)`),
      slicing() ? h("span", { class: "muted" }, " · scores, ranges and verdicts are worked out again from these runs") : null));
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
