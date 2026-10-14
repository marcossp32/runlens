/* pages/method.js: how a score and a verdict are made, followed on one of your own skills (#/method). */

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
  const j = verdict(v.score, v.ci, v);
  return h("div", { class: "prose" },
    h("p", {}, `This is ${unit.name}, version ${nameOf(v)}, which has ${fmt.runs(v.runs)}. Each row is one measure. The ratio compares the skill's typical run with the value that counts, so a ratio above 1 means this version did better than the skill usually does.`),
    plainTable("Worked example",
      [{ label: "Measure" }, { label: "This version", num: true }, { label: "Typical run of the skill", num: true }, { label: "Value that counts", num: true },
        { label: "Ratio", num: true }, { label: "Weight", num: true }, { label: "Weight × ln(ratio)", num: true }], rows),
    h("p", {}, `“Value that counts” is this version's value pulled toward the skill's own value, as if it had ${DATA.method.shrink} extra typical runs. Ratios are capped at ×${DATA.method.max_ratio} and ×${fmt.num(1 / DATA.method.max_ratio, 2)}.`),
    h("ol", {},
      h("li", {}, `Add the last column: ${fmt.num(acc, 3)}.`),
      h("li", {}, `Divide by the total weight, ${fmt.num(wsum, 2)}: ${fmt.num(acc / (wsum || 1), 3)}.`),
      h("li", {}, `Take 100 × e to that power: ${fmt.num(100 * Math.exp(acc / (wsum || 1)), 1)}.`)),
    h("p", {}, `So the score is ${fmt.score(v.score)}`, v.ci ? `, with a range of ${fmt.interval(v.ci)}.` : "."),
    waterfallChart({ title: `The same sum, step by step: ${unit.name} ${nameOf(v)}`, question: "How does each measure take the score from 100 to its value?",
      takeaway: `Each bar is one measure's push: right raises the score, left lowers it. Together they take ${unit.name} ${nameOf(v)} from 100 to ${fmt.score(v.score)}.`,
      sub: "each step is weight × ln(ratio) ÷ total weight; the steps multiply", score: v.score, base: "the skill's typical run", n: v.runs, minN: MIN_RUNS,
      rows: [...parts].sort((a, b) => Math.abs(b.share) - Math.abs(a.share)).map((p) => ({ label: metricLabel(p.m), share: p.share,
        tip: [["Ratio", fmt.ratio(p.d.ratio)], ["Weight", `×${p.d.weight}`]] })) }),
    h("p", {}, `The verdict is separate: ${j.sentence}`));
}

function methodPage() {
  const m = DATA.method;
  const pct = Math.round((m.confidence || 0.95) * 100);
  const formula = [
    "value     = Σ num / Σ den over the runs          (log measures: num = Σ ln(x + offset) per invocation)",
    "counted   = (Σ num + K · d · typical) / (Σ den + K · d)      d = the skill's mean den per run",
    "ℓ         = clip( typical − counted, ±ln 2 )                  for log measures",
    "ℓ         = clip( ln((typical + f) / (counted + f)), ±ln 2 )  for rates and counts, f = " + m.floor + " × typical",
    "score     = 100 × exp( Σ w · ℓ / Σ w )",
    "verdict   = interval of the same sum between two versions' own values, B against A",
  ].join("\n");
  const li = (...kids) => h("li", {}, ...kids);

  const score = () => h("div", { class: "prose" },
    h("p", {}, "Every number comes from your recorded runs. Nothing is labelled by hand, and nothing leaves this machine."),
    h("ol", {},
      li(h("strong", {}, "Keep finished runs. "), `Runs still open and stub runs (a skill loaded and barely used) are left out${DATA.population ? `: ${fmt.int(DATA.population.open)} open and ${fmt.int(DATA.population.stub)} stub runs this time` : ""}.`),
      li(h("strong", {}, "Group the work. "), "Each skill, agent role and group you define is a unit. A piece of work belongs to the skill invocation it ran under, so a skill used ten times in one run counts ten invocations."),
      li(h("strong", {}, "Measure. "), "Cost and time are typical values per invocation (geometric means: one giant run does not set the level). Rates are totals over totals, so a big run weighs as much as its size. If you set an outcome in config.toml, such as a check that passes first time or a PR opened, it is a measure too, with the most weight."),
      li(h("strong", {}, "Compare with the skill itself. "), "A version is compared with its own skill's typical run (100) and with the version before it, never with other skills: research is cheaper than building, and that says nothing about either skill."),
      li(h("strong", {}, "Combine. "), "The measures are combined with weights into one number. Weights can be set per skill under [weights] in config.toml, for example 0 for your messages in a skill that is meant to ask you questions.")),
    h("h2", {}, "The verdict"),
    h("p", {}, `A version is judged against the version before it. Their runs are resampled ${fmt.int(m.resamples)} times, by session so that a run's invocations stay together, and the weighted difference is worked out each time. If the ${pct}% interval of the difference is entirely on the better side the verdict is “better” (▲), entirely on the worse side “worse” (▼), otherwise “no clear change” (≈), which says the interval holds zero and is not evidence that the versions are alike: with a handful of runs most real improvements land here. The interval is widened for small samples, which keeps false “better” or “worse” calls at about ${100 - pct}% when nothing changed.`),
    h("p", {}, `Fewer than ${m.min_runs} runs on either side is “not enough runs” (○): no verdict is given. When something else changed between the two sides, the verdict is “confounded” (?) and names it: another skill's text, the model or effort mix, the Claude Code version${m.cc_version === "patch" ? "" : " (its minor version)"}, or the project. A change can then not be put down to the skill text. Skills edited together are best judged together, as a group. With enough runs but no measure that has a weight above 0, the verdict is “not scored”.`),
    h("p", {}, "Limits worth knowing. Power is low: with five to ten runs a side, even a large real improvement usually shows as “no clear change”. The verdict is recomputed with the runs so far each time you refresh, so checking it as runs arrive calls a change more often than the nominal rate; judge a version once, after a number of runs you chose in advance. A unit listed among many is one of many tests, so the model also gives each unit a Benjamini-Hochberg q, and a “better” or “worse” it does not support is flagged. A reverted skill (A, then B, then A again) counts as three versions."),
    h("details", { class: "more" }, h("summary", {}, "Exact formula and settings"),
      h("pre", { class: "formula" }, formula),
      plainTable("Settings", [{ label: "Setting" }, { label: "Value", num: true }, { label: "Meaning" }], [
        ["Shrink K", m.shrink, "pseudo-runs at the skill's own value that every version starts with"],
        ["Ratio clip", `×${m.max_ratio}`, "the most one measure can count for, either way"],
        ["Floor f", m.floor, "fraction of the skill's own rate added to both sides of a rate ratio, so zeros stay finite"],
        ["Turn cap", `${m.turn_cap} s`, "longest time credited to one gap between two model turns"],
        ["Resamples", fmt.int(m.resamples), "bootstrap resamples behind each interval"],
        ["Interval", `${pct}%`, "expanded for small samples (Hesterberg's expanded percentile)"],
        ["Runs for a verdict", `${m.min_runs} a side`, "fewer is “not enough runs”"],
        ["Mix shift", m.mix_shift, "how different two sides' model, effort, Claude Code or project mix must be to count as a confounder"],
      ])));

  const measures = () => h("div", {},
    sortTable({ caption: "Measures", csvName: "measures",
      cols: [{ label: "Measure", value: (x) => metricLabel(x) }, { label: "Default weight", num: true, value: (x) => x.weight }, { label: "What it is", value: (x) => x.what },
        { label: "Scored for", value: (x) => x.kinds.map((k) => KIND[k]).join(", ") }], rows: m.metrics }).el,
    note("Lower is better for every measure except the outcome. Not counted twice: denied tool calls are not tool errors; policy denials, failed checks, idle loops and error streaks are not problems (other measures already count them); problems a label calls expected behaviour are left out. Shown but never scored: cost per success and cost per 1,000 changed lines."));

  const pages = () => h("div", { class: "prose" },
    h("dl", { class: "defs" },
      h("dt", {}, "Skills"), h("dd", {}, "Every skill on one screen: its latest version against its own history, each version on a real time axis with Claude Code updates and new models marked, cost (with the Pareto frontier of cost against outcome, spend per day and cost by token type), the outcome over time, and every measure. Skills are shown side by side, never ranked. Agent roles and groups are on the other tabs."),
      h("dt", {}, "A skill, role or group"), h("dd", {}, "Open one from any table or chart. Its versions with their verdicts and what changed, a waterfall of what moves its score, every run as a dot by version, and its outcome over time."),
      h("dt", {}, "Runs"), h("dd", {}, "Every run on a calendar and a time axis. Open one to see its skills, your messages, problems, checks, tool errors, spend and every subagent on one time axis, and the commands that open the raw trace."),
      h("dt", {}, "Compare"), h("dd", {}, "Two versions of one skill or group: the verdict, what else changed between them, and a forest plot of each difference with its interval. Two different units side by side, without a verdict."),
      h("dt", {}, "Diagnostics"), h("dd", {}, "Everything else that was recorded: problems over time and per 100 tool calls, tool durations, models by effort, token types and stop reasons, subagents, how runs move from skill to skill, and your config's checks over time."),
      h("dt", {}, "Data health"), h("dd", {}, "Whether the data is complete and current: failed ingests, open and stub runs, models without a price, the parser version, the hook queue and how many tokens the transcripts hold. The header badge links there when something needs fixing."),
      h("dt", {}, "How it works"), h("dd", {}, "This page.")),
    h("h2", {}, "Filters, settings and sharing"),
    h("ul", {},
      li("The filter bar under the header narrows every page to some dates, repos, branches, models, effort levels, skills or Claude Code versions: “Filters” opens it, each active filter shows as a chip you can click to remove, and it always says how many runs are left. Scores, ranges and verdicts are then worked out again from those runs, in this page, the same way runlens does."),
      li("Score, in the header, sets what 100 means (the skill's typical run, the version before, its first version or a chosen version), the weight of each measure for every skill or for one, and the confidence level. When they differ from config.toml the button says “custom” and pages that show a score say how it was made."),
      li("Every view is in the address bar: the page, the tab, the filters and the score settings. “Copy link” copies it. Views saves a view under a name in this browser; views listed in config.toml under [[dashboard.view]] are there for everyone."),
      li("Each chart opens with the question it answers and a one-line answer from your data. “How to read this”, under the chart, explains its marks and caveats. Its “⋯” menu shows the data as a table and downloads it as CSV, and the drawing as SVG or PNG. Each table exports as CSV; wide tables keep their rarer columns behind “More columns”."),
      li("Words with a dotted underline explain themselves: hover, tap or tab to them."),
      li("Use Tab to reach a chart, then the arrow keys to move between its marks; the details show as you go. Enter opens what a mark links to."),
      li("Settings keeps the theme, the density and the number format in this browser only.")));

  const limits = () => h("div", { class: "prose" },
    h("ul", {},
      li(h("strong", {}, "Without an outcome it does not judge correctness. "), "The score says what a version cost, how long it worked, and how often it failed, idled or needed you. Set [outcome] in config.toml to add what success means. Before acting on a verdict, read the traces with ", h("code", {}, "runlens show"), "."),
      li(h("strong", {}, "Real runs are not an experiment. "), "Tasks differ from run to run. A verdict says the runs differed beyond noise, not that the edit caused it. To prove an edit helped, replay fixed tasks with and without it: ", h("code", {}, "runlens export-eval"), " turns real incidents into eval cases."),
      li(h("strong", {}, "A version is one skill text. "), "Versions are numbered by first use. A skill whose text Claude Code did not record shows as unrecorded."),
      li(h("strong", {}, "Leaving versions out re-scores a skill. "), "The score is then worked out from the versions still on, as a single number with no range."),
      li(h("strong", {}, "Time is approximate. "), `It is the gap from each model turn to the same agent's next turn, capped at ${m.turn_cap} seconds, so it includes tool time and waiting.`),
      li(h("strong", {}, "Skills that only run in subagents. "), "Claude Code credits a subagent's turns to the skill that started it, so a skill loaded only inside subagents may have little or no work of its own."),
      li(h("strong", {}, "Agent roles have no versions. "), "A role is a subagent type with its description, numbers folded. Roles seen in a single run are folded into one row per type. They are described, not scored."),
      li(h("strong", {}, "Groups. "), "A group's runs are the union of its members' work, each piece counted once. Its version changes when any member's text changes, so skills edited together are judged together.")));

  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("h1", { tabindex: "-1" }, "How it works"),
      h("p", { class: "lede" }, "How a score and a verdict are made, followed on a real example from your history, and what to keep in mind when reading them.")),
    tabs("How it works", [
      { id: "score", label: "Score and verdict", build: score },
      { id: "example", label: "A worked example", build: workedExample },
      { id: "measures", label: "Measures", build: measures },
      { id: "pages", label: "The pages", build: pages },
      { id: "limits", label: "Good to know", build: limits },
    ], { param: "tab" }));
}
