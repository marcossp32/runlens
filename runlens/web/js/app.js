/* app.js: the page registry, the router, the settings menu and "copy link". Loaded last.

   A page is an entry in PAGES: render(path) returns its <article>, or null when the path does not fit.
   Adding a page means adding an entry here and a link with data-page in template.html. */

const app = document.getElementById("app");

const PAGES = {
  skills: { title: "Skills", render: () => skillsPage() },
  unit: { title: "Unit", render: (path) => (UNITS.has(path[1]) ? unitPage(path[1]) : null) },
  runs: { title: "Runs", render: () => runsPage() },
  run: { title: "Run", render: (path) => (RUN.has(path[1]) ? runPage(path[1]) : null) },
  compare: { title: "Compare", render: () => comparePage() },
  diagnostics: { title: "Diagnostics", render: () => diagnosticsPage() },
  health: { title: "Data health", render: () => healthPage() },
  method: { title: "How it works", render: () => methodPage() },
};

let currentPage = null;
let booted = false;
function route() {
  readHash();
  if (!booted) {
    booted = true;
    restoreScoreSettings();
  }
  readScoreSettings();
  applyFilters();
  renderFilterBar();
  renderScorePanel();
  renderViewsMenu();
  renderHealthBadge();
  let page = pageOf(ROUTE.path);
  let view = PAGES[page] ? PAGES[page].render(ROUTE.path) : null;
  if (!view) {
    page = "skills";
    view = PAGES.skills.render(ROUTE.path);
  }
  const samePage = page === currentPage && page !== "unit" && page !== "run";
  const y = window.scrollY;
  hideTip();
  app.replaceChildren(view);
  currentPage = page;
  LAST_HASH.set(page, location.hash || "#/");
  syncNav();
  const h1 = view.querySelector("h1");
  document.title = `${h1 ? h1.textContent : PAGES[page].title} · runlens`;
  if (samePage) window.scrollTo(0, y);
  else {
    window.scrollTo(0, 0);
    if (h1) h1.focus({ preventScroll: true });
  }
}

// ---- settings: theme, density, number format (kept in this browser) ----

function settingsMenu() {
  const box = document.getElementById("settings");
  if (!box) return;
  const panel = h("div", { class: "menu-panel settings-panel" },
    Object.keys(PREF_CHOICES).map((key) => {
      const sel = h("select", { id: `pref-${key}` }, PREF_CHOICES[key].map((v) => h("option", { value: v, selected: PREFS[key] === v ? true : null }, PREF_LABELS[key][v])));
      sel.addEventListener("change", () => {
        savePref(key, sel.value);
        applyPrefs();
        if (key === "locale") {
          resetFormatters();
          route();
          footer();
        } else redrawAll();
      });
      return h("label", { for: `pref-${key}` }, { theme: "Theme", density: "Density", locale: "Numbers and dates" }[key], sel);
    }),
    h("p", { class: "note" }, "Saved in this browser only. What you are looking at is saved in the link instead."));
  box.append(panel);
  document.addEventListener("click", (e) => {
    if (box.open && !box.contains(e.target)) box.open = false;
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && box.open) {
      box.open = false;
      box.querySelector("summary").focus();
    }
  });
}

function copyLink() {
  const btn = document.getElementById("copylink");
  const status = document.getElementById("status");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const url = location.href;
    let ok = false;
    try {
      await navigator.clipboard.writeText(url);
      ok = true;
    } catch (e) {
      const input = h("input", { value: url, "aria-hidden": "true", class: "sr" });
      document.body.append(input);
      input.select();
      try {
        ok = document.execCommand("copy");
      } catch (err) {
        ok = false;
      }
      input.remove();
    }
    status.textContent = ok ? "Link to this view copied." : "Copy the address bar to share this view.";
    btn.textContent = ok ? "Link copied" : "Copy link";
    setTimeout(() => {
      btn.textContent = "Copy link";
      status.textContent = "";
    }, 2400);
  });
}

function footer() {
  document.getElementById("foot").textContent =
    `Generated ${fmt.when(DATA.generated)} · ${fmt.runs(DATA.window.runs)} · computed from your local runlens database, nothing is sent anywhere.`;
}

// A theme that follows the system redraws when the system switches.
if (window.matchMedia) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const onScheme = () => PREFS.theme === "auto" && redrawAll();
  if (mq.addEventListener) mq.addEventListener("change", onScheme);
}
window.addEventListener("beforeprint", () => {
  for (const d of document.querySelectorAll("details.more, details.changes")) {
    d.dataset.wasOpen = d.open ? "1" : "";
    d.open = true;
  }
  redrawForPrint();
});
window.addEventListener("afterprint", () => {
  for (const d of document.querySelectorAll("details.more, details.changes")) d.open = d.dataset.wasOpen === "1";
  redrawAll();
});

settingsMenu();
copyLink();
footer();
window.addEventListener("hashchange", route);
route();
