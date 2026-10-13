/* core/state.js: what the page shows lives in the URL hash, so a link reproduces the exact view.

   Shape: #/<page>/<sub>?<params>. Pages read their params with param() and write them with setParams(),
   which replaces the history entry (no new entry, no re-render). Moving to another page pushes a new one.
   The global keys belong to the filter bar (core/filters.js) and the score settings (core/scoring.js): they
   are kept across pages and written into every link, so a filtered, re-weighted view survives navigation. */

const FILTER_KEYS = ["range", "from", "to", "repo", "branch", "model", "effort", "cc", "skills", "minn", "pop"];
const SCORE_KEYS = ["base", "w", "wu", "ci"];
const GLOBAL_KEYS = FILTER_KEYS.concat(SCORE_KEYS);
const ROUTE = { path: [], params: new URLSearchParams() };
const LAST_HASH = new Map(); // page -> the last hash seen on it, so nav links return to the same view

const safeDecode = (s) => {
  try {
    return decodeURIComponent(s);
  } catch (e) {
    return s;
  }
};

function readHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const cut = raw.indexOf("?");
  const path = (cut < 0 ? raw : raw.slice(0, cut)).split("/").filter(Boolean).map(safeDecode);
  ROUTE.path = path;
  ROUTE.params = new URLSearchParams(cut < 0 ? "" : raw.slice(cut + 1));
  return ROUTE;
}

const param = (key, fallback = null) => (ROUTE.params.has(key) ? ROUTE.params.get(key) : fallback);
const filters = () => Object.fromEntries(GLOBAL_KEYS.filter((k) => ROUTE.params.has(k)).map((k) => [k, ROUTE.params.get(k)]));

function hashFor(path, params = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...filters(), ...params })) if (v !== null && v !== undefined && v !== "") p.set(k, v);
  const q = p.toString();
  return `#/${path.map(encodeURIComponent).join("/")}${q ? `?${q}` : ""}`;
}

// Change some params of the current view in place. A null value removes the param.
function setParams(changes) {
  for (const [k, v] of Object.entries(changes)) {
    if (v === null || v === undefined || v === "") ROUTE.params.delete(k);
    else ROUTE.params.set(k, String(v));
  }
  const q = ROUTE.params.toString();
  const hash = `#/${ROUTE.path.map(encodeURIComponent).join("/")}${q ? `?${q}` : ""}`;
  if (hash !== location.hash) history.replaceState(null, "", hash);
  LAST_HASH.set(pageOf(ROUTE.path), hash);
  syncNav();
}

const pageOf = (path) => path[0] || "skills";
const hrefUnit = (id) => hashFor(["unit", id]);
// A page's last hash with today's filters and score settings, so the nav never brings back an old slice.
function withGlobals(hash) {
  const raw = hash.replace(/^#/, "");
  const cut = raw.indexOf("?");
  const p = new URLSearchParams(cut < 0 ? "" : raw.slice(cut + 1));
  for (const k of GLOBAL_KEYS) p.delete(k);
  for (const [k, v] of Object.entries(filters())) p.set(k, v);
  const q = p.toString();
  return `#${(cut < 0 ? raw : raw.slice(0, cut)) || "/"}${q ? `?${q}` : ""}`;
}
const hrefPage = (page) => (LAST_HASH.has(page) ? withGlobals(LAST_HASH.get(page)) : hashFor(page === "skills" ? [] : [page]));
const hrefRun = (id) => hashFor(["run", id]);

// The main navigation links back to the last view of each page, filters included.
function syncNav() {
  const current = { unit: "skills", run: "runs" }[pageOf(ROUTE.path)] || pageOf(ROUTE.path);
  for (const a of document.querySelectorAll(".top nav a[data-page]")) {
    const page = a.dataset.page;
    a.setAttribute("href", page === pageOf(ROUTE.path) ? location.hash || "#/" : hrefPage(page));
    if (page === current) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}
