/* ui/scorepanel.js: the "Score" menu. What 100 means, how much each measure weighs, and how sure a verdict
   must be. The defaults come from config.toml through the model; anything changed here is marked in the
   header ("Score: custom") and on every page that shows a score, and kept in the link and in this browser. */

const SCORE_EL = document.getElementById("scorepanel");

function writeScore(next) {
  Object.assign(S, next);
  saveScoreSettings();
  setParams(scoreParams(S));
  route();
}

// The unit the weights apply to: "all" or a skill / group name (the one on screen, when there is one).
let weightScope = "all";

function renderScorePanel() {
  if (!SCORE_EL) return;
  const wasOpen = SCORE_EL.open;
  const focusKey = wasOpen && document.activeElement && SCORE_EL.contains(document.activeElement) ? document.activeElement.dataset.key : null;
  const onUnit = pageOf(ROUTE.path) === "unit" && UNITS.has(ROUTE.path[1]) ? UNITS.get(ROUTE.path[1]) : null;
  const scorable = DATA.units.filter((u) => u.kind !== "agent" && u.baseline);
  if (onUnit && onUnit.kind !== "agent" && weightScope === "all" && unitCustomWeights(onUnit)) weightScope = onUnit.name;
  if (weightScope !== "all" && !scorable.some((u) => u.name === weightScope)) weightScope = "all";
  const custom = scoreCustom();
  const summary = h("summary", { class: `ghost${custom ? " custom" : ""}`, title: custom ? "Your score settings differ from the defaults" : "Score settings" },
    "Score", custom ? h("span", { class: "dotmark", "aria-label": "custom settings" }, " ● custom") : null);

  // what 100 means
  const bases = Object.entries(BASES);
  if (onUnit) for (const v of DATA.versions[onUnit.id] || []) bases.push([`ver:${v.label}`, `Version ${v.label} of ${onUnit.name}`]);
  else if (S.base.startsWith("ver:")) bases.push([S.base, `Version ${S.base.slice(4)} (chosen on a skill's page)`]);
  const baseBox = h("fieldset", { class: "sp-field" }, h("legend", {}, "100 means"),
    bases.map(([key, label]) => {
      const r = h("input", { type: "radio", name: "sp-base", value: key, "data-key": `base-${key}` });
      r.checked = S.base === key;
      r.addEventListener("change", () => writeScore({ base: key }));
      return h("label", { class: "check" }, r, ` ${label}`);
    }));

  const ci = h("select", { "data-key": "ci", "aria-label": "Confidence level" }, CI_CHOICES.map((c) =>
    h("option", { value: String(c), selected: c === S.ci ? true : null }, `${Math.round(c * 100)}%${c === MODEL_CI ? " (config)" : ""}`)));
  ci.addEventListener("change", () => writeScore({ ci: Number(ci.value) }));

  // weights, for every unit or one
  const scope = h("select", { "data-key": "scope", "aria-label": "Weights apply to" },
    h("option", { value: "all" }, "every skill and group"),
    scorable.filter((u) => u.kind !== "agent").map((u) => h("option", { value: u.name, selected: weightScope === u.name ? true : null }, `${u.name} only${unitCustomWeights(u) ? " ●" : ""}`)));
  scope.addEventListener("change", () => {
    weightScope = scope.value;
    renderScorePanel();
    SCORE_EL.open = true;
  });
  const ref = weightScope === "all" ? null : scorable.find((u) => u.name === weightScope);
  const defaults = ref ? ref.weights : Object.fromEntries(METRICS.map((m) => [m.key, m.weight]));
  const current = ref ? weightsOf(ref) : { ...defaults, ...S.w };
  const keys = METRICS.filter((m) => m.num && (ref ? m.key in (ref.weights || {}) : m.kinds.includes("skill"))).map((m) => m.key);
  const sliders = keys.map((k) => {
    const m = metricByKey.get(k);
    const val = h("output", { class: "sp-val" }, `×${fmt.num(current[k] ?? 0, 1)}`);
    const input = h("input", { type: "range", min: 0, max: 5, step: 0.5, value: current[k] ?? 0, "data-key": `w-${k}`, "aria-label": `Weight of ${metricLabel(m)}` });
    input.addEventListener("input", () => { val.textContent = `×${fmt.num(Number(input.value), 1)}`; });
    input.addEventListener("change", () => {
      const v = Number(input.value);
      if (ref) {
        const own = { ...(S.wu[ref.name] || {}) };
        if (v === (ref.weights || {})[k] && !(k in S.w)) delete own[k];
        else own[k] = v;
        writeScore({ wu: { ...S.wu, [ref.name]: own } });
      } else {
        const w = { ...S.w };
        if (v === defaults[k]) delete w[k];
        else w[k] = v;
        writeScore({ w });
      }
    });
    const changed = (current[k] ?? 0) !== (defaults[k] ?? 0);
    return h("label", { class: `sp-slider${changed ? " changed" : ""}` }, h("span", { class: "sp-name" }, metricShort(m)), input, val,
      h("span", { class: "sp-def" }, changed ? `was ×${fmt.num(defaults[k] ?? 0, 1)}` : "default"));
  });
  const presets = h("div", { class: "sp-bar" },
    button("Cost only", () => writeScore({ w: Object.fromEntries(keys.map((k) => [k, k === "cost" ? 1 : 0])), wu: {} }), { class: "btn seg" }),
    button("Quality only", () => writeScore({ w: Object.fromEntries(keys.map((k) => [k, ["cost", "seconds"].includes(k) ? 0 : defaults[k] || 1])), wu: {} }), { class: "btn seg" }),
    button(ref ? `Reset ${ref.name}` : "Reset weights", () => (ref ? writeScore({ wu: { ...S.wu, [ref.name]: {} } }) : writeScore({ w: {} })), { class: "btn seg" }));

  const panel = h("div", { class: "menu-panel sp-panel" },
    h("p", { class: "sp-state" }, custom ? h("strong", {}, "Custom settings. ") : "Defaults from config.toml. ",
      custom || slicing() ? "Scores, ranges and verdicts are worked out again in this page from each run, as runlens does." : "The numbers are runlens's own."),
    baseBox,
    h("label", { class: "sp-row" }, "Confidence ", ci),
    h("div", { class: "sp-field" }, h("div", { class: "sp-legend" }, "Weights for ", scope), sliders, presets),
    h("div", { class: "sp-bar" }, button("Reset everything", () => writeScore({ base: "self", ci: MODEL_CI, w: {}, wu: {} }), { class: "btn" })),
    note("Saved in the link and in this browser. A weight of 0 shows a measure without scoring it."));
  fill(SCORE_EL, summary, panel);
  SCORE_EL.open = wasOpen;
  if (focusKey) {
    const el = SCORE_EL.querySelector(`[data-key="${focusKey}"]`);
    if (el) el.focus({ preventScroll: true });
  }
}

// A line that says, where a score is shown, which settings made it.
function scoreSettingsNote() {
  if (!scoreCustom() && !slicing()) return null;
  const parts = [];
  if (S.base !== "self") parts.push(`100 = ${baseWords()}`);
  if (customWeights()) parts.push("your weights");
  if (S.ci !== MODEL_CI) parts.push(`${Math.round(S.ci * 100)}% intervals`);
  if (slicing()) parts.push(`only ${fmt.runs(RUNSET.size)} in the filters`);
  return h("p", { class: "settingsnote" }, h("span", { "aria-hidden": "true" }, "● "), `Worked out with ${parts.join(", ")}. `,
    h("a", { href: "#", onclick: (e) => { e.preventDefault(); e.stopPropagation(); SCORE_EL.open = true; SCORE_EL.querySelector("summary").focus(); } }, "Score settings"));
}
