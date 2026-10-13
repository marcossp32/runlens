/* core/meaning.js: what a score means in words, and the per-run measures the page recomputes. */

// A unit is "better" only when its whole likely range sits above 100, "worse" only when it sits below.
function verdict(score, ci) {
  if (score == null) return { tone: "few", word: "No score yet", sentence: "There are not enough runs to score this yet." };
  if (!ci) return { tone: "few", word: "Too few runs", sentence: "Too few runs to tell whether it is better or worse than average." };
  if (ci[0] > 100) return { tone: "better", word: "Better than average", sentence: `Better than average: even the low end of its likely range (${fmt.score(ci[0])}) is above 100.` };
  if (ci[1] < 100) return { tone: "worse", word: "Worse than average", sentence: `Worse than average: even the high end of its likely range (${fmt.score(ci[1])}) is below 100.` };
  return { tone: "unclear", word: "Not clear yet", sentence: `Not clearly better or worse than average: its likely range (${fmt.interval(ci)}) includes 100.` };
}

// The change against the previous version. Overlapping ranges mean no clear change.
function change(v) {
  if (v.delta == null) return { tone: "first", text: "" };
  if (v.overlap === null) return { tone: "few", text: "too few runs to tell" };
  if (v.overlap) return { tone: "unclear", text: "no clear change" };
  return v.delta > 0 ? { tone: "better", text: "better" } : { tone: "worse", text: "worse" };
}

const overlaps = (a, b) => (!a || !b ? null : a[0] <= b[1] && b[0] <= a[1]);

// A tone as an icon and a word; the icon carries the meaning when colour cannot.
function toneTag(tone, text) {
  const t = TONE[tone] || TONE.unclear;
  return h("span", { class: `tone tone-${tone}` }, h("span", { class: "ticon", "aria-hidden": "true" }, t.icon), " ", text || t.word);
}

function scoreCell(score, ci, few) {
  const v = verdict(score, ci);
  return h("span", { class: `score tone-${v.tone}` }, h("strong", {}, fmt.score(score)),
    h("span", { class: "sub" }, h("span", { class: "ticon", "aria-hidden": "true" }, TONE[v.tone].icon), ` ${v.word}${few && v.tone !== "few" ? " · few runs" : ""}`));
}

function changeCell(u) {
  const c = change(u);
  if (!c.text) return h("span", { class: "muted", title: "Only one version so far" }, "—");
  return h("span", { title: `${fmt.signed(u.delta)} points against the previous version` }, toneTag(c.tone, c.text));
}

// The metrics of one run, as the score uses them.
function runMetrics(r, kind) {
  return {
    cost: r.cost,
    seconds: r.seconds,
    error_rate: r.calls ? r.call_errors / r.calls : null,
    incidents: r.incidents,
    interventions: kind === "agent" ? null : r.interventions,
    idle_rate: r.calls ? r.idle / r.calls : null,
    api_error_rate: r.turns ? r.api_errors / r.turns : null,
    bad_markers: r.bad,
  };
}

// The mean of each measure over a set of runs.
function kpiOf(runs, kind) {
  const out = {};
  for (const m of METRICS) {
    const xs = runs.map((r) => runMetrics(r, kind)[m.key]).filter((x) => x != null);
    out[m.key] = xs.length ? xs.reduce((p, q) => p + q, 0) / xs.length : null;
  }
  return out;
}

// The score of a set of runs, worked out the same way as the model's score (without the range).
function pointScore(runs, kind) {
  const ref = DATA.reference[kind] || {};
  const M = DATA.method;
  const vals = runs.map((r) => runMetrics(r, kind));
  let acc = 0, wsum = 0;
  const metrics = {};
  for (const m of METRICS) {
    const avg = ref[m.key];
    if (!avg || !m.kinds.includes(kind)) continue;
    const xs = vals.map((v) => v[m.key]).filter((x) => x != null);
    if (!xs.length) continue;
    const n = xs.length, mean = xs.reduce((p, q) => p + q, 0) / n;
    const counted = (n * mean + M.shrink * avg) / (n + M.shrink);
    const floor = M.floor * avg;
    const lr = Math.min(LOG_CAP, Math.max(-LOG_CAP, Math.log((avg + floor) / (counted + floor))));
    metrics[m.key] = { value: mean, counted, n, ref: avg, ratio: Math.exp(lr), weight: m.weight };
    acc += m.weight * lr;
    wsum += m.weight;
  }
  return wsum ? { score: 100 * Math.exp(acc / wsum), metrics } : null;
}

// How much each measure moves the score: weight × ln(ratio) over the total weight. Their sum is ln(score / 100).
function contributions(v) {
  const ms = METRICS.filter((m) => v.metrics && v.metrics[m.key]);
  const wsum = ms.reduce((n, m) => n + v.metrics[m.key].weight, 0) || 1;
  return ms.map((m) => {
    const d = v.metrics[m.key];
    return { m, d, share: (d.weight * Math.log(d.ratio)) / wsum };
  });
}
