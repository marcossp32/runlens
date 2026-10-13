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
    `${nameOf(v)} · ${v.parts.map((p) => p.hash).join("+") || "–"} · ${fmt.runs(v.runs)}`));
}

function sideCard(label, v, name) {
  const t = verdict(v.score, v.ci, v);
  return h("article", { class: "sidecard" },
    h("p", { class: "kicker" }, label),
    h("h2", {}, `${name} · ${nameOf(v)}`),
    h("div", { class: "big" }, fmt.score(v.score)),
    scoreBullet(v.score, v.ci, v),
    h("p", { class: "ci" }, v.ci ? `range ${fmt.interval(v.ci)} · ` : "no range yet · ", toneTag(t.tone, t.word)),
    h("p", { class: "sub" }, `${fmt.runs(v.runs)} · ${fmt.span(v.first_seen, v.last_seen)} · ${v.parts.map((p) => p.hash).join(" + ") || "no skill text"}`),
    v.low_sample ? chip(`fewer than ${MIN_RUNS} runs`, "warn") : null);
}

function comparison(sa, sb) {
  const A = findVersion(sa), B = findVersion(sb);
  if (!A || !B) return empty("Pick a unit and a version on both sides.");
  if (sa.id === sb.id && sa.key === sb.key) return empty("Pick two different versions to compare.");
  const nameA = UNITS.get(sa.id).name, nameB = UNITS.get(sb.id).name;
  const tagA = `A · ${nameA} ${nameOf(A)}`, tagB = `B · ${nameB} ${nameOf(B)}`;
  const crossSkill = sa.id !== sb.id;
  const pair = crossSkill ? null : pairOf(sa.id, A.label, B.label);
  let tone, text;
  if (crossSkill) [tone, text] = ["unclear", "These are different units. Different skills do different work, so runlens shows their figures side by side but does not call one better than the other."];
  else if (!pair) [tone, text] = ["few", "These two versions were not compared (only consecutive versions are, when a unit has many)."];
  else {
    const j = verdict(null, null, { ...pair, vs: `${nameOf(A)} (A)` });
    const d = pair.difference;
    tone = j.tone;
    text = `B against A: ${pair.verdict}${d && d.score != null ? ` · ${fmt.score(d.score)} with A = 100${d.ci ? `, ${Math.round((DATA.method.confidence || 0.95) * 100)}% interval ${fmt.interval(d.ci)}` : ""}` : ""}. ${j.sentence}`;
  }

  const ms = METRICS.filter((m) => A.metrics[m.key] && B.metrics[m.key]);
  const rows = ms.map((m) => {
    const a = A.metrics[m.key], b = B.metrics[m.key];
    const pm = pair && pair.difference && pair.difference.measures ? pair.difference.measures[m.key] : null;
    const lr = pm ? Math.log(pm.effect) : 0; // above 0: B is better on this measure
    const d = a.value ? b.value / a.value - 1 : null;
    const clear = pm && pm.ci && (pm.ci[0] > 1 || pm.ci[1] < 1);
    return { m, a: a.value, b: b.value, na: a.n, nb: b.n, value: lr, d,
      label: metricLabel(m), text: d == null ? (b.value ? "up from 0" : "both 0") : `${fmt.signedPct(d, Math.abs(d) < 0.1 ? 1 : 0)}`,
      tone: !pm ? "unclear" : clear ? (lr > 0 ? "better" : "worse") : "unclear" };
  });
  return h("div", {},
    h("div", { class: "sides" }, sideCard("A", A, nameA), sideCard("B", B, nameB)),
    h("p", { class: `verdict tone-${tone}` }, h("span", { class: "ticon", "aria-hidden": "true" }, TONE[tone].icon), " ", text,
      pair && pair.verdict !== "confounded" && pair.confounders && pair.confounders.length ? ` Confounders: ${pair.confounders.join("; ")}.` : ""),
    crossSkill ? null : h("div", { class: "grid" },
      divergingBars({
        title: "B against A, measure by measure", sub: `${tagB} compared with ${tagA} · right of the line, B is better on that measure`,
        n: Math.min(A.runs, B.runs), minN: MIN_RUNS, rows,
        ticks: (() => {
          const lim = Math.max(...rows.map((r) => Math.abs(r.value)), 0.05) * 1.1;
          return [4, 3, 2, 1.5, 1.2, 1, 1 / 1.2, 1 / 1.5, 1 / 2, 1 / 3, 1 / 4].map((q) => -Math.log(q)).filter((v) => Math.abs(v) <= lim)
            .filter((v, i, all) => all.length <= 7 || [0, Math.log(2), -Math.log(2), Math.log(4), -Math.log(4), Math.log(1.5), -Math.log(1.5)].some((k) => Math.abs(k - v) < 1e-9));
        })(),
        tickFmt: (t) => `×${fmt.num(Math.exp(t), 2)}`, axisTitle: "B against A: how many times better (right) or worse (left)",
        leftLabel: "◀ B is worse", rightLabel: "B is better ▶",
        extraCols: [{ label: "A", num: true, value: (r) => r.a }, { label: "B", num: true, value: (r) => r.b }],
        notes: "Each bar is B's effect on a log scale, so halving and doubling are the same length, capped at ×" + DATA.method.max_ratio + " as in the score. A bar is coloured only when that measure's own interval is clear of no change.",
      })),
    sortTable({
      caption: "Measures compared",
      cols: [{ label: "Measure", value: (r) => r.label }, { label: "A", num: true, value: (r) => r.a, cell: (r) => fmt.metric(r.m, r.a) },
        { label: "B", num: true, value: (r) => r.b, cell: (r) => fmt.metric(r.m, r.b) },
        { label: "B against A", value: (r) => r.d, cell: (r) => (crossSkill ? r.text : toneTag(r.tone, `${r.text}${r.tone === "unclear" ? " · no clear change" : r.tone === "better" ? " · better" : " · worse"}`)) },
        { label: "Runs in A", num: true, value: (r) => r.na }, { label: "Runs in B", num: true, value: (r) => r.nb }],
      rows, csvName: `compare-${nameA}-${nameOf(A)}-${nameB}-${nameOf(B)}`,
    }).el,
    note(`The verdict comes from the difference between the two versions' runs, resampled ${fmt.int(DATA.method.resamples)} times by session; it needs ${MIN_RUNS} runs on each side. A measure is marked better or worse only when its own interval is clear of no change.`));
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
