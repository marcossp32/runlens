/* core/table.js: sortable tables (with CSV export) and tabs (built lazily, remembered in the URL). */

function compareValues(a, b, dir) {
  const aNull = a === null || a === undefined || a === "" || (typeof a === "number" && !Number.isFinite(a));
  const bNull = b === null || b === undefined || b === "" || (typeof b === "number" && !Number.isFinite(b));
  if (aNull || bNull) return (aNull ? 1 : 0) - (bNull ? 1 : 0);
  const c = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), undefined, { numeric: true });
  return dir * c;
}

/* A sortable table. cols: {key, label, num, value(row), cell(row), csv(row), csvLabel, more}. With `page`, rows arrive in pages.
   `csvName` adds a CSV button that exports every row and every column (not just what is shown), with raw values.
   Columns marked `more` start hidden behind a "More columns" toggle, so a wide table opens with what most readers
   need; the toggle is remembered in the URL under `more=1` when `moreParam` is given. */
function sortTable({ caption, cols, rows, sort, page = 0, csvName, moreParam }) {
  cols = cols.map((c, i) => ({ key: c.key || `c${i}`, ...c }));
  let key = sort ? sort.key : null;
  let dir = sort ? sort.dir : 1;
  let data = rows;
  let shown = page || Infinity;
  const extra = cols.filter((c) => c.more);
  let showMore = moreParam ? param(moreParam) === "1" : false;
  const body = h("tbody");
  const headRow = h("tr");
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
  const visible = () => cols.filter((c) => showMore || !c.more);

  function ordered() {
    const col = cols.find((c) => c.key === key);
    return col ? [...data].sort((x, y) => compareValues(col.value(x), col.value(y), dir)) : data;
  }
  function draw() {
    cols.forEach((col, i) => {
      const active = col.key === key;
      heads[i].setAttribute("aria-sort", active ? (dir > 0 ? "ascending" : "descending") : "none");
      heads[i].querySelector(".arrow").textContent = active ? (dir > 0 ? "▲" : "▼") : "";
    });
    const vis = visible();
    headRow.replaceChildren(...cols.map((c, i) => (vis.includes(c) ? heads[i] : null)).filter(Boolean));
    const all = ordered();
    const slice = all.slice(0, shown);
    body.replaceChildren(...slice.map((row) => h("tr", {}, vis.map((c, i) => {
      const content = c.cell ? c.cell(row) : (c.value(row) ?? "—");
      return i === 0 ? h("th", { scope: "row", class: c.num ? "num" : "" }, content) : h("td", { class: c.num ? "num" : "" }, content);
    }))));
    if (count) count.textContent = `${fmt.int(all.length)} row${all.length === 1 ? "" : "s"}`;
    const left = all.length - slice.length;
    more.hidden = left <= 0;
    more.textContent = `Show ${Math.min(page, left)} more · ${left} left`;
    if (moreBtn) {
      moreBtn.setAttribute("aria-pressed", String(showMore));
      moreBtn.textContent = showMore ? "Fewer columns" : `More columns (${extra.length})`;
      moreBtn.title = showMore ? "" : `Also show: ${extra.map((c) => c.label).join(", ")}`;
    }
  }

  const count = csvName ? h("span", { class: "muted" }) : null;
  const moreBtn = extra.length ? h("button", { type: "button", class: "tool morecols" }) : null;
  if (moreBtn) {
    moreBtn.addEventListener("click", () => {
      showMore = !showMore;
      if (moreParam) setParams({ [moreParam]: showMore ? "1" : null });
      draw();
    });
  }
  draw();
  const csv = csvName ? h("button", { type: "button", class: "tool", title: "Download every row and column as CSV" }, "CSV") : null;
  if (csv) csv.addEventListener("click", () => downloadCSV(csvName, cols, ordered()));
  return {
    el: h("div", { class: "tablebox" },
      csv || moreBtn ? h("div", { class: "tablebar" }, count || h("span", {}), h("span", { class: "tablebar-tools" }, moreBtn, csv)) : null,
      h("div", { class: "tw", tabindex: "0", role: "region", "aria-label": caption },
        h("table", {}, h("caption", { class: "sr" }, caption), h("thead", {}, headRow), body)),
      page ? more : null),
    setRows(next) {
      data = next;
      shown = page || Infinity;
      draw();
    },
  };
}

// A static table: heads are {label, num}, rows are arrays of cells.
function plainTable(caption, heads, rows) {
  return h("div", { class: "tw", tabindex: "0", role: "region", "aria-label": caption }, h("table", {},
    h("caption", { class: "sr" }, caption),
    h("thead", {}, h("tr", {}, heads.map((t) => h("th", { scope: "col", class: t.num ? "num" : "" }, t.label)))),
    h("tbody", {}, rows.map((r) => h("tr", {}, r.map((cell, i) => h("td", { class: heads[i].num ? "num" : "" }, cell)))))));
}

/* Tabs with arrow-key navigation (WAI-ARIA tabs pattern, automatic activation). A panel is built the
   first time it is shown, so a page only pays for what is looked at. With `param`, the selected tab is
   kept in the URL hash under that name. */
function tabs(label, items, opts = {}) {
  items = items.filter(Boolean);
  const uid = Math.random().toString(36).slice(2, 7);
  const wanted = opts.param ? param(opts.param) : null;
  const initial = items.some((it) => it.id === wanted) ? wanted : opts.initial && items.some((it) => it.id === opts.initial) ? opts.initial : items[0].id;
  const buttons = items.map((it) => h("button", {
    type: "button", role: "tab", class: "tab", id: `tab-${uid}-${it.id}`, "aria-controls": `panel-${uid}-${it.id}`, "aria-selected": "false", tabindex: "-1",
  }, it.label));
  const panels = items.map((it) => h("div", { role: "tabpanel", id: `panel-${uid}-${it.id}`, "aria-labelledby": `tab-${uid}-${it.id}`, tabindex: "0", hidden: true }));
  const built = new Set();
  const select = (id, write) => {
    items.forEach((it, i) => {
      const on = it.id === id;
      buttons[i].setAttribute("aria-selected", String(on));
      buttons[i].tabIndex = on ? 0 : -1;
      if (on && !built.has(id)) {
        built.add(id);
        panels[i].append(it.build());
      }
      panels[i].hidden = !on;
    });
    if (write && opts.param) setParams({ [opts.param]: id === items[0].id ? null : id }, true);
    if (opts.onSelect) opts.onSelect(id);
  };
  buttons.forEach((b, i) => {
    b.addEventListener("click", () => select(items[i].id, true));
    b.addEventListener("keydown", (e) => {
      let j = null;
      if (e.key === "ArrowRight") j = (i + 1) % items.length;
      else if (e.key === "ArrowLeft") j = (i - 1 + items.length) % items.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = items.length - 1;
      if (j === null) return;
      buttons[j].focus();
      select(items[j].id, true);
      e.preventDefault();
    });
  });
  select(initial, false);
  return h("div", { class: "tabs" }, h("div", { class: "tablist", role: "tablist", "aria-label": label }, buttons), panels);
}
