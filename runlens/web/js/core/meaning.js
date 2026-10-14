/* core/meaning.js: what a verdict means in words, and the per-run measures the page recomputes.

   Verdicts come from the model (bench.py): a version against the version before it, from a bootstrap of
   the difference, with enough runs on each side and nothing else changed at the same time. A score is read
   against the unit's own typical run (100); units are never ranked against each other. */

// The confidence level in force: the score settings' (core/scoring.js), else the model's.
const pctOf = () => Math.round((S.ci || DATA.method.confidence || 0.95) * 100);

// Said of a unit listed among many: its q (Benjamini-Hochberg over every unit compared, from the model) is not clear.
const notAdjusted = (x) => (x && x.adjusted === false ? ` Listed with many other skills, though, it is not clear once adjusted for that (q = ${Number(x.q).toFixed(2)}).` : "");

// A verdict in words. `x` is a unit, a version or a pair from the model; without one (an old model), the
// interval is read against 100.
function verdict(score, ci, x) {
  if (x && x.kind === "agent") {
    return { tone: "few", word: "Described, not scored", sentence: "Agent roles have no versions to compare, so they are described, not scored." };
  }
  if (x && x.verdict !== undefined) {
    const vs = x.vs || "the version before";
    switch (x.verdict) {
      case "better":
        return { tone: "better", word: `Better than ${vs}`, sentence: `Better than ${vs}: the whole ${pctOf()}% interval of the difference is on the better side.${notAdjusted(x)}` };
      case "worse":
        return { tone: "worse", word: `Worse than ${vs}`, sentence: `Worse than ${vs}: the whole ${pctOf()}% interval of the difference is on the worse side.${notAdjusted(x)}` };
      case "no clear change":
        return { tone: "unclear", word: `No clear change from ${vs}`, sentence: `No clear change from ${vs}: the ${pctOf()}% interval of the difference includes no change. That is not evidence that the versions are alike; with few runs a real improvement often looks like this.` };
      case "not scored":
        return { tone: "few", word: "Not scored", sentence: `Not scored against ${vs}: there are enough runs, but no measure with a weight above 0 could be compared.` };
      case "not enough runs":
        return { tone: "few", word: "Not enough runs", sentence: `Not enough runs to compare with ${vs}: a verdict needs ${MIN_RUNS} runs on each side.` };
      case "confounded":
        return { tone: "confounded", word: "Confounded", sentence: `Not comparable with ${vs}: something else changed at the same time${(x.confounders || []).length ? ` (${x.confounders.join("; ")})` : ""}, so a change cannot be put down to the skill text.` };
      default:
        // A version with no verdict is a first version; a unit with none has a single version so far.
        return x.label && x.vid ? { tone: "first", word: "First version", sentence: "The first version: there is nothing earlier to compare it with." }
          : { tone: "first", word: "Only one version", sentence: "There is no earlier version to compare with yet." };
    }
  }
  // No verdict object: describe where the score sits against the typical run (100). This is a description
  // of one set of runs, not a verdict; verdicts only come from comparing two versions. The typical run pools
  // the version's own runs and is treated as fixed, so these are neutral: no better/worse tone.
  if (score == null) return { tone: "few", word: "No score yet", sentence: "There are not enough runs to score this yet." };
  if (!ci) return { tone: "few", word: "Too few runs for a range", sentence: "Too few runs for a range." };
  const note = " This describes the runs; it is not a test, since the typical run includes them.";
  if (ci[0] > 100) return { tone: "unclear", word: "Above its typical run", sentence: `Above its typical run: even the low end of its range (${fmt.score(ci[0])}) is above 100.${note}` };
  if (ci[1] < 100) return { tone: "unclear", word: "Below its typical run", sentence: `Below its typical run: even the high end of its range (${fmt.score(ci[1])}) is below 100.${note}` };
  return { tone: "unclear", word: "About its typical run", sentence: `About its typical run: its range (${fmt.interval(ci)}) includes 100.${note}` };
}

// The outcome definition a unit's outcome summary was measured with (DATA.method.outcomes), by name. Its words
// come from its kind: a PR opened is not a check passing first time.
const outcomeDef = (summary) => (DATA.method.outcomes || []).find((o) => summary && o.name === summary.measure) || null;
const outcomeWords = (o) => (o && o.kind === "pr"
  ? { rate: "PR-opened rate", verb: "opened a PR", sub: "runs that opened a PR" }
  : o ? { rate: "First-pass rate", verb: "passed first time", sub: `${human(o.marker)} passing on the first try` }
    : { rate: "Outcome rate", verb: "reached their outcome", sub: "each skill's own configured outcome" });

// The change of a version against the one before it, as the model judged it.
function change(v) {
  if (v.verdict !== undefined) {
    if (!v.vs) return { tone: "first", text: "" };
    const tone = { better: "better", worse: "worse", "no clear change": "unclear", "not enough runs": "few", "not scored": "few", confounded: "confounded" }[v.verdict] || "unclear";
    return { tone, text: v.verdict };
  }
  if (v.delta == null) return { tone: "first", text: "" };
  if (v.overlap === null || v.overlap === undefined) return { tone: "few", text: "too few runs to tell" };
  if (v.overlap) return { tone: "unclear", text: "no clear change" };
  return v.delta > 0 ? { tone: "better", text: "better" } : { tone: "worse", text: "worse" };
}

const overlaps = (a, b) => (!a || !b ? null : a[0] <= b[1] && b[0] <= a[1]);

// The precomputed comparison of two versions of one unit, oriented A -> B (null if the model has none).
function pairOf(uid, a, b) {
  for (const p of (DATA.pairs || {})[uid] || []) {
    if (p.a === a && p.b === b) return p;
    if (p.a === b && p.b === a) return flipPair(p);
  }
  return null;
}

function flipPair(p) {
  const d = p.difference || {};
  const inv = (x) => (x == null ? null : 10000 / x);
  const measures = {};
  for (const [k, m] of Object.entries(d.measures || {})) {
    measures[k] = { ...m, a: m.b, b: m.a, effect: 1 / m.effect, ci: m.ci ? [1 / m.ci[1], 1 / m.ci[0]] : null };
  }
  const o = d.outcome ? { ...d.outcome, a: d.outcome.b, b: d.outcome.a, value: -d.outcome.value, ci: d.outcome.ci ? [-d.outcome.ci[1], -d.outcome.ci[0]] : null } : null;
  const flip = { better: "worse", worse: "better" };
  return { ...p, a: p.b, b: p.a, runs_a: p.runs_b, runs_b: p.runs_a, verdict: flip[p.verdict] || p.verdict, direction: flip[p.direction] || p.direction,
    difference: { score: inv(d.score), ci: d.ci ? [inv(d.ci[1]), inv(d.ci[0])] : null, measures, outcome: o } };
}

// A tone as an icon and a word; the icon carries the meaning when colour cannot.
function toneTag(tone, text) {
  const t = TONE[tone] || TONE.unclear;
  return h("span", { class: `tone tone-${tone}`, title: t.help ? t.help.charAt(0).toUpperCase() + t.help.slice(1) : null }, h("span", { class: "ticon", "aria-hidden": "true" }, t.icon), " ", text || t.word);
}

function scoreCell(score, ci, few, x) {
  const v = verdict(score, ci, x);
  return h("span", { class: `score tone-${v.tone}` }, h("strong", {}, fmt.score(score)),
    h("span", { class: "sub" }, h("span", { class: "ticon", "aria-hidden": "true" }, (TONE[v.tone] || TONE.unclear).icon), ` ${v.word}${few && v.tone !== "few" ? " · few runs" : ""}`));
}

function changeCell(u) {
  const c = change(u);
  if (!c.text) return h("span", { class: "muted", title: "Only one version so far" }, "—");
  const d = u.difference;
  const title = d && d.score != null ? `${fmt.score(d.score)} against ${u.vs} (100 = no change)${d.ci ? `, interval ${fmt.interval(d.ci)}` : ""}` : "";
  return h("span", { title }, toneTag(c.tone, c.text));
}

// ---- measures: every one is Σnum / Σden over runs (see bench.py) ----

function display(m, x) {
  if (x == null || !Number.isFinite(x)) return null;
  return m.type === "log" ? Math.max(0, Math.exp(x) - m.offset) : x * (m.scale || 1);
}

function sumsOf(runs, m) {
  let num = 0, den = 0;
  for (const r of runs) {
    num += r[m.num] || 0;
    den += r[m.den] || 0;
  }
  return [num, den];
}

// One run's value of each measure (what the run tables and strip plots show).
function runMetrics(r, kind) {
  const out = {};
  for (const m of METRICS) {
    if (!m.kinds.includes(kind)) out[m.key] = null;
    else if (m.num) out[m.key] = r[m.den] ? display(m, (r[m.num] || 0) / r[m.den]) : null;
    else out[m.key] = legacyRun(r, m.key);
  }
  return out;
}

function legacyRun(r, key) {
  if (key === "error_rate") return r.calls ? r.call_errors / r.calls : null;
  if (key === "idle_rate") return r.calls ? r.idle / r.calls : null;
  if (key === "api_error_rate") return r.turns ? r.api_errors / r.turns : null;
  if (key === "bad_markers") return r.bad;
  return r[key] === undefined ? null : r[key];
}

// The pooled value of each measure over a set of runs.
function kpiOf(runs, kind) {
  const out = {};
  for (const m of METRICS) {
    if (m.num) {
      const [num, den] = sumsOf(runs, m);
      out[m.key] = m.kinds.includes(kind) && den ? display(m, num / den) : null;
    } else {
      const xs = runs.map((r) => runMetrics(r, kind)[m.key]).filter((x) => x != null);
      out[m.key] = xs.length ? xs.reduce((p, q) => p + q, 0) / xs.length : null;
    }
  }
  return out;
}

// l = ln(reference / value) on the measure's scale, clipped; positive is better. Mirrors bench.ell.
function ell(m, ref, val, base) {
  if (ref == null || val == null || base == null) return null;
  let x;
  if (m.type === "log") x = ref - val;
  else {
    if (m.better === "higher") [ref, val, base] = [1 - ref, 1 - val, 1 - base];
    if (base <= 0) return null;
    const f = DATA.method.floor * base;
    x = Math.log((ref + f) / (val + f));
  }
  if (Number.isNaN(x)) return null;
  return Math.min(LOG_CAP, Math.max(-LOG_CAP, x));
}

// The score of a set of runs against the unit's typical run, worked out as the model does (without the
// interval). `weights` defaults to the unit's own; a page may pass others.
function pointScore(runs, kind, unit, weights) {
  if (!unit || !unit.baseline) return null;
  const w = weights || unit.weights || {};
  let acc = 0, wsum = 0;
  const metrics = {};
  for (const m of METRICS) {
    const b = unit.baseline[m.key];
    if (b == null || w[m.key] == null || !m.num) continue;
    const [num, den] = sumsOf(runs, m);
    if (!den) continue;
    const k = DATA.method.shrink * (unit.pseudo[m.key] || 0);
    const v = (num + k * b) / (den + k);
    const l = ell(m, b, v, b);
    if (l == null) continue;
    metrics[m.key] = { value: display(m, num / den), counted: display(m, v), ref: display(m, b), n: runs.filter((r) => r[m.den]).length,
      ratio: Math.exp(l), weight: w[m.key] };
    if (w[m.key] > 0) {
      acc += w[m.key] * l;
      wsum += w[m.key];
    }
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
