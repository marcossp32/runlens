/* pages/compare.js: any two versions side by side (#/compare?a=<unit>&av=<version>&b=<unit>&bv=<version>). */

// The default pair: consecutive versions of one unit with enough runs on BOTH sides, the most balanced
// first, the newest on ties. Never "1 run against 9" when a fairer pair exists.
function defaultPair() {
  let best = null;
  for (const u of DATA.units) {
    const vs = DATA.versions[u.id] || [];
    for (let i = 1; i < vs.length; i += 1) {
      const a = vs[i - 1], b = vs[i];
      const key = [a.runs >= MIN_RUNS && b.runs >= MIN_RUNS ? 1 : 0, Math.min(a.runs, b.runs), timeOf(b.last_seen) || 0];
      if (!best || key[0] > best.key[0] || (key[0] === best.key[0] && (key[1] > best.key[1] || (key[1] === best.key[1] && key[2] > best.key[2])))) {
        best = { key, a: { id: u.id, key: a.key }, b: { id: u.id, key: b.key } };
      }
    }
  }
  if (best) return best;
  const u = DATA.units[0];
  const v = u ? (DATA.versions[u.id] || [])[0] : null;
  return { a: { id: u ? u.id : null, key: v ? v.key : null }, b: { id: u ? u.id : null, key: v ? v.key : null } };
}

// A side from the URL: the unit id, and the version by its label (v2) or, for older links, its key.
function sideFromParams(side, fallback) {
  const id = UNITS.has(param(side)) ? param(side) : fallback.id;
  const vs = DATA.versions[id] || [];
  const wanted = param(`${side}v`);
  const hit = vs.find((v) => v.label === wanted || v.key === wanted);
  const key = hit ? hit.key : id === fallback.id && vs.some((v) => v.key === fallback.key) ? fallback.key : (vs[vs.length - 1] || {}).key || null;
  return { id, key };
}

function unitOptions(selected) {
  return ["skill", "agent", "group"].map((kind) => {
    const list = DATA.units.filter((u) => u.kind === kind);
    return list.length
      ? h("optgroup", { label: `${KIND[kind]}s` },
        list.map((u) => h("option", { value: u.id, selected: u.id === selected ? true : null }, u.runs ? u.name : `${u.name} (no runs)`)))
      : null;
  });
}

function versionOptions(id, selected) {
  const vs = DATA.versions[id] || [];
  if (!vs.length) return [h("option", { value: "" }, "no versions")];
  return vs.map((v) => h("option", { value: v.key, selected: v.key === selected ? true : null },
    `${nameOf(v)} · ${partsText(v, ", ") || "–"} · ${fmt.runs(v.runs)}`));
}

function sideCard(label, v, name) {
  const t = verdict(v.score, v.ci, v);
  return h("article", { class: "sidecard" },
    h("p", { class: "kicker" }, label),
    h("h2", {}, `${name} · ${nameOf(v)}`),
    h("div", { class: "big" }, fmt.score(v.score)),
    scoreBullet(v.score, v.ci, v),
    h("p", { class: "ci" }, v.ci ? `range ${fmt.interval(v.ci)} · ` : "no range yet · ", toneTag(t.tone, t.word)),
    h("p", { class: "sub" }, `${fmt.runs(v.runs)} · ${fmt.span(v.first_seen, v.last_seen)}`),
    h("p", { class: "sub" }, h("span", { class: "muted" }, "Text: "), partsText(v) || "no skill text"),
    v.low_sample ? chip(`fewer than ${MIN_RUNS} runs`, "warn") : null);
}

const scoredVersion = (side) => (UNITS.has(side.id) ? scoreUnit(UNITS.get(side.id)).versions.find((v) => v.key === side.key) || null : null);

function comparison(sa, sb) {
  const A = scoredVersion(sa), B = scoredVersion(sb);
  if (!A || !B) return empty(slicing() ? "One of these versions has no runs in the current filters." : "Pick a unit and a version on both sides.");
  if (sa.id === sb.id && sa.key === sb.key) return empty("Pick two different versions to compare.");
  const nameA = UNITS.get(sa.id).name, nameB = UNITS.get(sb.id).name;
  const tagA = `A · ${nameA} ${nameOf(A)}`, tagB = `B · ${nameB} ${nameOf(B)}`;
  const crossSkill = sa.id !== sb.id;
  const pair = crossSkill ? null : pairIn(scoreUnit(UNITS.get(sa.id)), A.label, B.label);
  const pct = Math.round(S.ci * 100);
  let tone, text;
  if (crossSkill) [tone, text] = ["unclear", "These are different units. Different skills do different work, so runlens shows their figures side by side but does not call one better than the other."];
  else if (!pair) [tone, text] = ["few", "These two versions were not compared (only consecutive versions are, when a unit has many)."];
  else {
    const j = verdict(null, null, { ...pair, vs: `${nameOf(A)} (A)` });
    const d = pair.difference;
    tone = j.tone;
    const sentence = pair.verdict === "confounded" ? "Something else changed between the two sides (listed below), so the change cannot be put down to the skill text." : j.sentence;
    text = `B against A: ${pair.verdict}${d && d.score != null ? ` · ${fmt.score(d.score)} with A = 100${d.ci ? `, ${pct}% interval ${fmt.interval(d.ci)}` : ""}` : ""}. ${sentence}`;
  }

  const ms = METRICS.filter((m) => A.metrics[m.key] && B.metrics[m.key]);
  const rows = ms.map((m) => {
    const a = A.metrics[m.key], b = B.metrics[m.key];
    const pm = pair && pair.difference && pair.difference.measures ? pair.difference.measures[m.key] : null;
    const d = a.value ? b.value / a.value - 1 : null;
    const clear = pm && pm.ci && (pm.ci[0] > 1 || pm.ci[1] < 1);
    return { m, a: a.value, b: b.value, na: a.n, nb: b.n, d, pm,
      label: metricLabel(m), text: d == null ? (b.value ? "up from 0" : "both 0") : `${fmt.signedPct(d, Math.abs(d) < 0.1 ? 1 : 0)}`,
      tone: !pm ? "unclear" : clear ? (pm.effect > 1 ? "better" : "worse") : "unclear" };
  });
  const d = pair && pair.difference;
  const forestRows = pair && d ? [
    ...(d.score != null ? [{ label: "Weighted score", bold: true, effect: d.score / 100, ci: d.ci ? [d.ci[0] / 100, d.ci[1] / 100] : null,
      tone: { better: "better", worse: "worse" }[pair.direction] || "unclear", word: pair.verdict, tip: [["Weights", customWeights() ? "yours" : "the defaults"]] }] : []),
    // The words say what the table under the chart says. A cost or a time reads as B's change against A (B ÷ A − 1, as
    // in the table); the dot is A ÷ B, how many times better B is, so "40 % better" there would be "−29 %" here. A rate's
    // or count's effect is worked out on floored values (1 − p for a rate) and clipped, so it reads as its two values.
    ...rows.filter((r) => r.pm).map((r) => ({ label: r.label, effect: r.pm.effect, ci: r.pm.ci, tone: r.tone,
      words: r.m.type === "log" && r.d != null ? `${fmt.pct(Math.abs(r.d), Math.abs(r.d) < 0.1 ? 1 : 0)} ${r.d < 0 ? "lower" : "higher"}` : `${fmt.metric(r.m, r.a)} → ${fmt.metric(r.m, r.b)}`,
      tip: [["A", fmt.metric(r.m, r.a)], ["B", fmt.metric(r.m, r.b)], ["Weight", `×${r.pm.weight}`]] })),
  ] : [];
  const conf = pair && pair.confounders ? pair.confounders : [];
  return h("div", {},
    h("div", { class: `verdict tone-${tone}` }, h("p", {}, h("span", { class: "ticon", "aria-hidden": "true" }, TONE[tone].icon), " ", text),
      conf.length ? h("details", { class: "confounders", open: conf.length <= 2 ? true : null },
        h("summary", {}, h("strong", {}, pair.verdict === "confounded" ? `What else changed between A and B (${conf.length})` : `Also changed (${conf.length})`)),
        h("ul", {}, conf.map((c) => h("li", {}, c)))) : null,
      conf.length && pair.verdict === "confounded" && pair.direction ? h("p", { class: "muted" }, `Without these, the interval alone would say: ${pair.direction}.`) : null,
      pair && (pair.notes || []).length ? h("p", { class: "muted" }, pair.notes.join("; ")) : null),
    scoreSettingsNote(),
    h("div", { class: "sides" }, sideCard("A", A, nameA), sideCard("B", B, nameB)),
    crossSkill || !forestRows.length ? null : forestPlot({
      title: "B against A, with the interval of each difference", question: "What changed between the two versions, and how sure is it?",
      takeaway: () => {
        const clear = forestRows.filter((r) => !r.bold && r.ci && (r.ci[0] > 1 || r.ci[1] < 1));
        return clear.length ? `Clear differences: ${listWords(clear.map((r) => `${r.label.toLowerCase()} (${r.words ? `B ${r.words}` : `B ${effectWords(r.effect)}`})`))}. Every other line crosses “no change”.`
          : "No measure differs clearly: every line crosses “no change”, so the runs cannot tell the two versions apart.";
      },
      sub: `${tagB} compared with ${tagA} · dot = how much better or worse B is; line = its ${pct}% interval · right of “no change” (×1), B is better · ${pct}% intervals from resampling runs by session`,
      n: Math.min(A.runs, B.runs), minN: MIN_RUNS, rows: forestRows, leftLabel: "◀ B is worse", rightLabel: "B is better ▶",
      axisTitle: "B against A: how many times better (right) or worse (left), log scale",
      notes: `Per-measure intervals are exploratory: they are not adjusted for how many measures and pairs are looked at, so expect a false colour now and then. A row is coloured only when its whole interval is clear of ×1. Effects are capped at ×${DATA.method.max_ratio} as in the score. The top row is the verdict's own difference; with fewer than ${MIN_RUNS} runs on a side it has no interval.`,
    }),
    section({ title: "Each measure, A and B", intro: "The values behind the chart, with the number of runs on each side." }, sortTable({
      caption: "Measures compared",
      cols: [{ label: "Measure", value: (r) => r.label }, { label: "A", num: true, value: (r) => r.a, cell: (r) => fmt.metric(r.m, r.a) },
        { label: "B", num: true, value: (r) => r.b, cell: (r) => fmt.metric(r.m, r.b) },
        { label: "B against A", value: (r) => r.d, cell: (r) => (crossSkill ? r.text : toneTag(r.tone, `${r.text}${r.tone === "unclear" ? " · no clear change" : r.tone === "better" ? " · better" : " · worse"}`)) },
        { label: "Runs in A", num: true, value: (r) => r.na }, { label: "Runs in B", num: true, value: (r) => r.nb }],
      rows, csvName: `compare-${nameA}-${nameOf(A)}-${nameB}-${nameOf(B)}`,
    }).el),
    note(`The verdict comes from the difference between the two versions' runs, resampled ${fmt.int(DATA.method.resamples)} times by session; it needs ${MIN_RUNS} runs on each side. A measure is marked better or worse only when its own interval is clear of no change; "no clear change" means the interval holds no change, not that the versions are alike.`));
}

function comparePage() {
  if (!DATA.units.length) return h("article", { class: "page" }, h("h1", { tabindex: "-1" }, "Compare"), empty("No runs yet."));
  const d = defaultPair();
  const sides = { a: sideFromParams("a", d.a), b: sideFromParams("b", d.b) };
  const results = h("div", { "aria-live": "polite" });
  const update = (write) => {
    results.replaceChildren(comparison(sides.a, sides.b));
    if (!write) return;
    const label = (s) => (findVersion(s) || {}).label || null;
    setParams({ a: sides.a.id, av: label(sides.a), b: sides.b.id, bv: label(sides.b) });
  };
  const build = (side) => {
    const unitSel = h("select", { id: `unit-${side}` }, unitOptions(sides[side].id));
    const verSel = h("select", { id: `ver-${side}` }, versionOptions(sides[side].id, sides[side].key));
    unitSel.addEventListener("change", () => {
      const vs = DATA.versions[unitSel.value] || [];
      sides[side] = { id: unitSel.value, key: vs.length ? vs[vs.length - 1].key : null };
      verSel.replaceChildren(...versionOptions(unitSel.value, sides[side].key));
      update(true);
    });
    verSel.addEventListener("change", () => {
      sides[side] = { id: unitSel.value, key: verSel.value };
      update(true);
    });
    return h("fieldset", {}, h("legend", {}, side.toUpperCase()),
      h("label", { for: `unit-${side}` }, "Skill, role or group"), unitSel, h("label", { for: `ver-${side}` }, "Version"), verSel);
  };
  const swap = button("Swap A and B", () => {
    [sides.a, sides.b] = [sides.b, sides.a];
    update(true);
    route();
  });
  update(false);
  return h("article", { class: "page" },
    h("header", { class: "pagehead" },
      h("h1", { tabindex: "-1" }, "Compare two versions"),
      h("p", { class: "lede" }, "Pick two versions of one skill or group to see the verdict and each measure. Two different units are shown side by side, without a verdict. By default this is the latest pair of versions with enough runs on both sides.")),
    h("div", { class: "pick" }, build("a"), build("b"), h("div", { class: "pickbar" }, swap)),
    results);
}
