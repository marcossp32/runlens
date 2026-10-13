/* core/state.js: what the page shows lives in the URL hash, so a link reproduces the exact view.

   Shape: #/<page>/<sub>?<params>. Pages read their params with param() and write them with setParams(),
   which replaces the history entry (no new entry, no re-render). Moving to another page pushes a new one.
   Filter keys are reserved for the global filter bar (wave 3): they are parsed, kept across pages and
   written into every link, but nothing applies them yet. */

const FILTER_KEYS = ["from", "to", "repo", "branch", "model"];
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
const filters = () => Object.fromEntries(FILTER_KEYS.filter((k) => ROUTE.params.has(k)).map((k) => [k, ROUTE.params.get(k)]));

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
const hrefPage = (page) => LAST_HASH.get(page) || hashFor(page === "skills" ? [] : [page]);

// The main navigation links back to the last view of each page, filters included.
function syncNav() {
  const current = pageOf(ROUTE.path) === "unit" ? "skills" : pageOf(ROUTE.path);
  for (const a of document.querySelectorAll(".top nav a[data-page]")) {
    const page = a.dataset.page;
    a.setAttribute("href", page === pageOf(ROUTE.path) ? location.hash || "#/" : hrefPage(page));
    if (page === current) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}
