/* pages/method.js: how a score is made, followed on one of your own skills (#/method). */

function workedExample() {
  const unit = DATA.units.filter((u) => u.kind === "skill" && u.score != null).sort((a, b) => b.runs - a.runs)
    .find((u) => (DATA.versions[u.id] || []).some((v) => v.label === u.current && Object.keys(v.metrics || {}).length));
  if (!unit) return empty("There is no scored skill yet, so there is nothing to walk through.");
  const v = DATA.versions[unit.id].find((x) => x.label === unit.current);
  const parts = contributions(v);
  const wsum = parts.reduce((n, p) => n + p.d.weight, 0);
  const acc = parts.reduce((n, p) => n + p.d.weight * Math.log(p.d.ratio), 0);
  const rows = parts.map((p) => [metricLabel(p.m), fmt.metric(p.m, p.d.value), fmt.metric(p.m, p.d.ref), fmt.metric(p.m, p.d.counted), fmt.ratio(p.d.ratio),
    p.d.weight, fmt.num(p.d.weight * Math.log(p.d.ratio), 3)]);
  return h("div", { class: "prose" },
    h("p", {}, `This is ${unit.name}, version ${nameOf(v)}, which has ${fmt.runs(v.runs)}. Each row is one measure. The ratio is the average divided by the value that counts, so a ratio above 1 means better than average.`),
    plainTable("Worked example",
      [{ label: "Measure" }, { label: "Its value", num: true }, { label: "Average run", num: true }, { label: "Value that counts", num: true },
        { label: "Ratio", num: true }, { label: "Weight", num: true }, { label: "Weight × ln(ratio)", num: true }], rows),
    h("p", {}, `“Value that counts” is the value pulled toward the average when there are few runs. Ratios are capped at ×${DATA.method.max_ratio} and ×${fmt.num(1 / DATA.method.max_ratio, 2)} before they are combined.`),
    h("ol", {},
      h("li", {}, `Add the last column: ${fmt.num(acc, 3)}.`),
      h("li", {}, `Divide by the total weight, ${wsum}: ${fmt.num(acc / wsum, 3)}.`),
      h("li", {}, `Take 100 × e to that power: ${fmt.num(100 * Math.exp(acc / wsum), 1)}.`)),
    h("p", {}, `So the score is ${fmt.score(v.score)}`, v.ci ? `, with a likely range of ${fmt.interval(v.ci)}.` : "."),
    h("p", {}, "The skill's page draws the same table as bars, under “What drives the score”: each bar is one row's last column divided by the total weight."));
}

function methodPage() {
  const m = DATA.method;
  const formula = [
    "score    = 100 × exp( Σᵢ wᵢ · ℓᵢ / Σᵢ wᵢ )",
    "ℓᵢ       = clip( ln((avgᵢ + f) / (countedᵢ + f)), −ln 2, +ln 2 )",
    "countedᵢ = (nᵢ · meanᵢ + K · avgᵢ) / (nᵢ + K)",
    `f = ${m.floor} × avgᵢ      K = ${m.shrink}`,
  ].join("\n");
  const li = (...kids) => h("li", {}, ...kids);

  const score = () => h("div", { class: "prose" },
    h("p", {}, "Every number comes from your recorded runs. Nothing is labelled by hand, and nothing leaves this machine."),
    h("ol", {},
      li(h("strong", {}, "Group the work. "), "Each skill, agent role and group you define is a unit. Its runs are the sessions where it did any work."),
      li(h("strong", {}, "Measure each run. "), "Eight measures per run: cost, time, tool errors, problems, your messages, waiting calls, API errors and failed checks."),
      li(h("strong", {}, "Compare with the average. "), "For every measure, the unit's mean is compared with the average run of the same kind. The result is a ratio: above 1 is better."),
      li(h("strong", {}, "Trust small samples less. "), `A unit with few runs is pulled toward the average, as if it had ${m.shrink} extra average runs. A ratio never counts for more than ×${m.max_ratio} either way.`),
      li(h("strong", {}, "Combine. "), "The ratios are combined with weights (cost counts most) into one number. 100 is the average run; above 100 is better.")),
    h("h2", {}, "The likely range"),
    h("p", {}, `The runs are re-sampled ${fmt.int(m.resamples)} times and the score is worked out each time. The range is the middle 90% of those scores. If the whole range is above 100 the verdict is “better” (▲), if it is all below 100 “worse” (▼), otherwise “not clear yet” (≈). Two scores are only called different when their ranges do not overlap. A unit with fewer than ${m.min_runs} runs is marked “few runs”: with so few runs the range itself is rough, so read it as a hint.`),
    h("details", { class: "more" }, h("summary", {}, "Exact formula and settings"),
      h("pre", { class: "formula" }, formula),
      plainTable("Settings", [{ label: "Setting" }, { label: "Value", num: true }, { label: "Meaning" }], [
        ["Shrink K", m.shrink, "pseudo-runs at the average that every unit starts with"],
        ["Ratio clip", `×${m.max_ratio}`, "the most one measure can count for, either way"],
        ["Floor f", m.floor, "fraction of the average added to both sides, so zero values stay finite"],
        ["Turn cap", `${m.turn_cap} s`, "longest time credited to one gap between two model turns"],
        ["Resamples", fmt.int(m.resamples), "re-samples behind each range"],
        ["Few-runs flag", `under ${m.min_runs} runs`, "scores are still shown, but marked"],
      ])));

  const measures = () => h("div", {},
    sortTable({ caption: "Measures", csvName: "measures",
      cols: [{ label: "Measure", value: (x) => metricLabel(x) }, { label: "Weight", num: true, value: (x) => x.weight }, { label: "What it is", value: (x) => x.what },
        { label: "Scored for", value: (x) => x.kinds.map((k) => KIND[k]).join(", ") }], rows: m.metrics }).el,
    note("Every measure is a cost, a time or a count of failures, so lower is better. “Your messages” is only counted for skills and groups, since subagents never receive messages."));

  const pages = () => h("div", { class: "prose" },
    h("dl", { class: "defs" },
      h("dt", {}, "Skills"), h("dd", {}, "Every skill compared on one screen: its score and likely range, each version on a real time axis, cost, and each measure against the average. A panel chooses which skills and versions the charts show. Agent roles and groups are on the other tabs."),
      h("dt", {}, "A skill, role or group"), h("dd", {}, "Open one from any table or chart. Its numbers for all versions and for the current version, side by side and labelled. Tabs for its versions and what changed, what moves its score, and every run."),
      h("dt", {}, "Compare"), h("dd", {}, "Any two skills, roles or groups, and any of their versions, measure by measure."),
      h("dt", {}, "Diagnostics"), h("dd", {}, "Everything else that was recorded: each run, problems and tool errors, tools, models and effort, subagents, how skills hand over, and your config's checks."),
      h("dt", {}, "How it works"), h("dd", {}, "This page.")),
    h("h2", {}, "Reading and sharing"),
    h("ul", {},
      li("Every view is in the address bar: the page, the tab, the selection and the pair being compared. “Copy link” copies it, so a link opens exactly this view."),
      li("Each chart has a table view and exports its data as CSV, and its drawing as SVG or PNG. Each table exports as CSV."),
      li("Use Tab to reach a chart, then the arrow keys to move between its marks; the details show as you go. Enter opens what a mark links to."),
      li("Settings keeps the theme, the density and the number format in this browser only.")));

  const limits = () => h("div", { class: "prose" },
    h("ul", {},
      li(h("strong", {}, "It does not judge correctness. "), "The score says what a unit cost, how long it worked, and how often it failed, idled or needed you. Before acting on a drop, read the traces with ", h("code", {}, "runlens show"), "."),
      li(h("strong", {}, "The average mixes kinds of work. "), "100 is the average run of every skill, so a skill that does cheap work by design scores high. Compare a skill mostly with its own earlier versions."),
      li(h("strong", {}, "A version is one skill text. "), "Versions are numbered by first use. A skill whose text Claude Code did not record shows as unrecorded, and is not counted as a version."),
      li(h("strong", {}, "Leaving versions out re-scores a skill. "), "The score is then worked out from the versions still on, as a single number with no range."),
      li(h("strong", {}, "Time is approximate. "), `It is the gap from each model turn to the same agent's next turn, capped at ${m.turn_cap} seconds, so it includes tool time and waiting.`),
      li(h("strong", {}, "Cost comes from Claude Code. "), "A run that is still open has no final cost yet, so it is estimated at list price and marked “est.”."),
      li(h("strong", {}, "Skills that only run in subagents. "), "Claude Code credits a subagent's turns to the skill that started it. A skill that only ever ran inside a subagent therefore has no unit or versions of its own yet."),
      li(h("strong", {}, "Agent roles have no versions. "), "A role is a subagent type with its description, numbers folded, so two spawns that differ only in a number are one role."),
      li(h("strong", {}, "Groups. "), "A group's runs are the union of its members' work, each piece counted once. Its version changes when any member's text changes.")));

  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("h1", { tabindex: "-1" }, "How it works"),
      h("p", { class: "lede" }, "How a score is made, followed on a real example from your history, and what to keep in mind when reading it.")),
    tabs("How it works", [
      { id: "score", label: "The score", build: score },
      { id: "example", label: "A worked example", build: workedExample },
      { id: "measures", label: "Measures", build: measures },
      { id: "pages", label: "The pages", build: pages },
      { id: "limits", label: "Good to know", build: limits },
    ], { param: "tab" }));
}
