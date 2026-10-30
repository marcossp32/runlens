/* ui/views.js: saved views and the data-health badge in the header.

   A view is a name and a URL hash. Views declared in config.toml ([[dashboard.view]] name, hash) arrive in
   the model and are the same for everyone who opens this file; views saved here are kept in this browser
   (localStorage "runlens-views") and can be deleted. The badge turns on when the data has a problem worth
   knowing before reading any chart (a failed ingest, a model without a price, a queue not drained). */

const VIEWS_EL = document.getElementById("views");
const VIEWS_STORE = "runlens-views";

function savedViews() {
  try {
    const v = JSON.parse(localStorage.getItem(VIEWS_STORE) || "[]");
    return Array.isArray(v) ? v.filter((x) => x && typeof x.name === "string" && typeof x.hash === "string" && x.hash.startsWith("#")) : [];
  } catch (e) {
    return [];
  }
}
function storeViews(list) {
  try {
    localStorage.setItem(VIEWS_STORE, JSON.stringify(list.slice(0, 50)));
    return true;
  } catch (e) {
    return false;
  }
}

// `said` is a message for the status line, kept across the redraw that saving causes.
function renderViewsMenu(said = "") {
  if (!VIEWS_EL) return;
  const wasOpen = VIEWS_EL.open;
  const configured = DATA.views || [];
  const mine = savedViews();
  const item = (v, removable) => h("li", { class: location.hash === v.hash ? "current" : null },
    h("a", { href: v.hash, onclick: () => { VIEWS_EL.open = false; } }, v.name),
    removable ? h("button", { type: "button", class: "tool", "aria-label": `Delete the view ${v.name}`, onclick: (e) => {
      e.stopPropagation();
      storeViews(savedViews().filter((x) => !(x.name === v.name && x.hash === v.hash)));
      renderViewsMenu();
      VIEWS_EL.open = true;
    } }, "Delete") : h("span", { class: "muted vfrom" }, "config.toml"));
  const name = h("input", { type: "text", maxlength: 80, placeholder: "Name this view", "aria-label": "Name for the current view" });
  const status = h("span", { class: "muted", role: "status" }, said);
  const save = button("Save", () => {
    const n = name.value.trim();
    if (!n) {
      name.focus();
      return;
    }
    const list = savedViews().filter((x) => x.name !== n);
    list.unshift({ name: n, hash: location.hash || "#/" });
    renderViewsMenu(storeViews(list) ? "Saved." : "This browser does not allow saving.");
    VIEWS_EL.open = true;
    const again = VIEWS_EL.querySelector(".vsave input");
    if (again) again.focus({ preventScroll: true });
  }, { class: "btn" });
  name.addEventListener("keydown", (e) => {
    if (e.key === "Enter") save.click();
  });
  fill(VIEWS_EL, h("summary", { class: "ghost" }, "Views", mine.length + configured.length ? h("span", { class: "muted" }, ` ${mine.length + configured.length}`) : null),
    h("div", { class: "menu-panel views-panel" },
      configured.length ? [h("div", { class: "menu-title" }, "From config.toml"), h("ul", { class: "vlist2" }, configured.map((v) => item(v, false)))] : null,
      h("div", { class: "menu-title" }, "Saved in this browser"),
      mine.length ? h("ul", { class: "vlist2" }, mine.map((v) => item(v, true))) : note("None yet. A view keeps the page, its tab, the filters and the score settings."),
      h("div", { class: "vsave" }, name, save), status,
      note("To share a view with everyone who opens this file, add it to config.toml: [[dashboard.view]] name = \"…\", hash = \"#/…\".")));
  VIEWS_EL.open = wasOpen;
}

// ---- data health: what is wrong (warn) and what is only worth knowing (info) ----

function healthIssues() {
  const H = EX.health;
  if (!H) return [];
  const s = H.summary || {};
  const out = [];
  const add = (level, text, detail) => out.push({ level, text, detail });
  const current = Number(s.parser_version);
  const old = EX.runs.filter((r) => current && r.parser !== null && r.parser !== undefined && r.parser < current).length;
  if (s.runs_failed_to_ingest) add("warn", `${fmt.runs(s.runs_failed_to_ingest)} failed to ingest`, "Their numbers are missing from every chart.");
  if ((s.unpriced_models || []).length) add("warn", `No price for ${s.unpriced_models.join(", ")}`, "Their calls have no cost; spend is understated.");
  if (s.unknown_model_cost_runs) add("warn", `${fmt.runs(s.unknown_model_cost_runs)} with a model Claude Code could not price`, "Claude Code's own cost for them is incomplete.");
  if (old) add("warn", `${fmt.runs(old)} read by an older parser`, "Run runlens refresh --force to read them again.");
  if (s.unreadable_lines) add("warn", `${fmt.int(s.unreadable_lines)} transcript lines could not be read`, "A transcript may be cut or corrupt.");
  if (H.pending_count) add("warn", `${fmt.int(H.pending_count)} session${H.pending_count === 1 ? "" : "s"} waiting to be ingested`, "Run runlens refresh to process the queue.");
  if (H.orphan_labels) add("warn", `${fmt.int(H.orphan_labels)} incident label${H.orphan_labels === 1 ? "" : "s"} match no incident`, "Their incident ids changed or their run was deleted, so they are ignored until the incident is labelled again (runlens check says the same).");
  if ((H.hook_errors || []).length) add("warn", "The hook logged errors", "See hooks.log; the newest lines are on this page.");
  const last = Date.parse(s.last_ingest || "");
  const gen = Date.parse(DATA.generated || "");
  if (Number.isFinite(last) && Number.isFinite(gen) && gen - last > 3 * DAY) add("warn", `Last refreshed ${fmt.day(s.last_ingest)}`, "Newer runs are not in this page yet.");
  if (s.open_runs) add("info", `${fmt.runs(s.open_runs)} still open`, "Left out of every score until they finish.");
  if (s.stub_runs) add("info", `${fmt.runs(s.stub_runs)} too small to score (stubs)`, "Left out of every score.");
  if (s.estimated_cost_runs) add("info", `${fmt.runs(s.estimated_cost_runs)} with an estimated cost`, "No closing cost from Claude Code: priced from the transcript at list price.");
  if (valid(s.output_token_coverage) && s.output_token_coverage < 0.9) {
    add("info", `The transcripts hold ${fmt.pct(s.output_token_coverage, 0)} of the output tokens Claude Code counted`, "Token totals come from Claude Code's own counts; per-call output tokens are lower bounds.");
  }
  return out;
}

function renderHealthBadge() {
  const el = document.getElementById("healthbadge");
  if (!el) return;
  const warn = healthIssues().filter((i) => i.level === "warn");
  el.hidden = !warn.length;
  el.textContent = warn.length ? `⚠ ${warn.length} data issue${warn.length === 1 ? "" : "s"}` : "";
  el.title = warn.map((i) => i.text).join(" · ");
  el.setAttribute("href", hrefPage("health"));
}
