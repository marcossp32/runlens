/* core/scoring.js: the score settings (baseline, weights, confidence) and the score worked out in the page.

   With the default settings and no filter, every number is the model's own (bench.py), so the page agrees
   with `runlens score`. Change the baseline, a weight, the confidence level or the filters, and the page
   works the scores out again from each run's num/den, exactly as bench.py does: the same measures, the
   same shrinkage, the same clip, and the same session bootstrap of the difference with the expanded
   percentile interval. Only the random draws differ (a seeded generator here), so a recomputed interval
   can move against the model's by several points when a side has only five or six runs (Monte Carlo error
   at the ends of the interval); the model uses more resamples than this page may.

   URL keys (kept across pages):
     base=self|prev|first|ver:v2   what 100 means: the skill's typical run (default), the version before,
                                   its first version, or one chosen version (on a skill's page)
     w=cost:3,seconds:0            weights for every unit (over config.toml's)
     wu=m-build:cost:1.errors:0    weights for one unit, over everything else
     ci=90                         confidence level of intervals and verdicts, in % */

const SCORE_STORE = "runlens-score";
const MODEL_CI = DATA.method.confidence || 0.95;
const CI_CHOICES = [0.8, 0.9, 0.95, 0.99];
const BASES = { self: "Its own typical run", prev: "The version before", first: "Its first version" };
const S = { base: "self", w: {}, wu: {}, ci: MODEL_CI };

function readScoreSettings() {
  const b = param("base") || "self";
  S.base = BASES[b] || /^ver:v\d+$/.test(b) ? b : "self";
  S.ci = CI_CHOICES.find((c) => String(Math.round(c * 100)) === param("ci")) || MODEL_CI;
  S.w = parseWeights(param("w") || "");
  S.wu = {};
  for (const part of (param("wu") || "").split(";").filter(Boolean)) {
    const cut = part.indexOf(":");
    if (cut > 0) S.wu[safeDecode(part.slice(0, cut))] = parseWeights(part.slice(cut + 1).replace(/\./g, ","));
  }
}
function parseWeights(text) {
  const out = {};
  for (const kv of text.split(",").filter(Boolean)) {
    const [k, v] = kv.split(":");
    const x = Number(v);
    if (metricByKey.has(k) && Number.isFinite(x) && x >= 0 && x <= 10) out[k] = x;
  }
  return out;
}
const weightText = (w) => Object.entries(w).map(([k, v]) => `${k}:${v}`).join(",");

// The URL params for a set of settings; null removes a param (the default).
function scoreParams(s) {
  const wu = Object.entries(s.wu).filter(([, w]) => Object.keys(w).length).map(([n, w]) => `${n}:${weightText(w).replace(/,/g, ".")}`).join(";");
  return { base: s.base === "self" ? null : s.base, ci: s.ci === MODEL_CI ? null : String(Math.round(s.ci * 100)),
    w: Object.keys(s.w).length ? weightText(s.w) : null, wu: wu || null };
}
function saveScoreSettings() {
  try {
    localStorage.setItem(SCORE_STORE, JSON.stringify(scoreParams(S)));
  } catch (e) {
    /* storage can be blocked: the settings then live in the link only */
  }
}
// A link without score settings takes the ones this browser saved last (a link that has them keeps its own).
function restoreScoreSettings() {
  if (SCORE_KEYS.some((k) => ROUTE.params.has(k))) return;
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(SCORE_STORE) || "null");
  } catch (e) {
    saved = null;
  }
  if (!saved) return;
  const p = Object.fromEntries(Object.entries(saved).filter(([k, v]) => SCORE_KEYS.includes(k) && v));
  if (Object.keys(p).length) setParams(p);
}

const customWeights = () => Object.keys(S.w).length > 0 || Object.values(S.wu).some((w) => Object.keys(w).length);
const scoreCustom = () => S.base !== "self" || S.ci !== MODEL_CI || customWeights();
// The model's own numbers can be shown as they are only with the defaults and the whole population.
const asModel = () => !scoreCustom() && !slicing();

function weightsOf(u) {
  const w = { ...(u.weights || {}) };
  for (const [k, v] of Object.entries(S.w)) if (k in w) w[k] = v;
  for (const [k, v] of Object.entries(S.wu[u.name] || {})) if (k in w) w[k] = v;
  return w;
}
const unitCustomWeights = (u) => Object.keys(S.wu[u.name] || {}).length > 0;

// ---- the method, as in bench.py ----

const MEAS = METRICS.filter((m) => m.num);

function sumsFor(rows, keys) {
  const out = {};
  for (const k of keys) {
    const m = metricByKey.get(k);
    let num = 0, den = 0;
    for (const r of rows) {
      num += r[m.num] || 0;
      den += r[m.den] || 0;
    }
    out[k] = [num, den];
  }
  return out;
}
function estimates(sums, base, pseudo, shrink) {
  const out = {};
  for (const [k, [num, den]] of Object.entries(sums)) {
    if (!(den > 0)) continue;
    if (shrink) {
      const kk = DATA.method.shrink * (pseudo[k] || 0);
      out[k] = (num + kk * base[k]) / (den + kk);
    } else out[k] = num / den;
  }
  return out;
}
// `expect` names the measures the full sample could score: in a resample one with no data counts as no change
// (l = 0) instead of dropping out, so the weights are not renormalised from draw to draw. Mirrors bench.composite.
function composite(ref, val, base, weights, expect) {
  let acc = 0, wsum = 0;
  const parts = {};
  for (const [k, w] of Object.entries(weights)) {
    const l = ell(metricByKey.get(k), ref[k], val[k], base[k]);
    if (l === null || l === undefined) {
      if (expect && expect.has(k) && w > 0) wsum += w;
      continue;
    }
    parts[k] = l;
    if (w > 0) {
      acc += w * l;
      wsum += w;
    }
  }
  return { d: wsum ? acc / wsum : null, parts };
}

// Seeded draws (mulberry32), so the same view always gives the same interval.
function seedOf(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The normal and Student's t quantiles bench.py uses (Acklam's inverse normal; A&S 26.7.5 for t).
function normInv(p) {
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const lo = 0.02425;
  if (p < lo) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p > 1 - lo) return -normInv(1 - p);
  const q = p - 0.5, r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}
function normCdf(x) {
  // Abramowitz & Stegun 7.1.26 through erf, within 1.5e-7.
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(x * x) / 2);
  return x >= 0 ? (1 + y) / 2 : (1 - y) / 2;
}
function tQuantile(p, df) {
  if (df === 1) return Math.tan(Math.PI * (p - 0.5));
  if (df === 2) return (2 * p - 1) / Math.sqrt(2 * p * (1 - p));
  const z = normInv(p), v = df;
  return z + (z ** 3 + z) / (4 * v) + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * v ** 2)
    + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * v ** 3)
    + (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / (92160 * v ** 4);
}
// The share each end of the interval cuts off, widened for small samples (Hesterberg's expanded percentile).
function tailOf(conf, n) {
  if (n < 2) return (1 - conf) / 2;
  const z = Math.sqrt(n / (n - 1)) * tQuantile(1 - (1 - conf) / 2, n - 1);
  return 1 - normCdf(z);
}
function quantile(sorted, q) {
  const i = q * (sorted.length - 1), lo = Math.floor(i);
  return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (i - lo);
}
// At most 4000 here: a recompute redoes every unit on the page's main thread, and 10000 made it take minutes on
// a slow machine. The model's own count is used when smaller; the cost is a wider Monte Carlo error.
const RESAMPLES = () => Math.min(DATA.method.resamples || 2000, 4000);

// Two-sided p of "no change" from the sorted draws of a difference: the confidence level at which the expanded
// interval would first touch 0. Mirrors bench.p_value.
function pValue(draws, n) {
  const m = draws.length;
  if (m < 20) return null;
  let below = 0;
  while (below < m && draws[below] <= 0) below += 1;
  let atOrAbove = 0;
  while (atOrAbove < m && draws[m - 1 - atOrAbove] >= 0) atOrAbove += 1;
  const q = (Math.min(below, atOrAbove) + 1) / (m + 1);
  if (q >= tailOf(0, n)) return 1;
  let lo = 0, hi = 1;
  for (let i = 0; i < 40; i += 1) {
    const mid = (lo + hi) / 2;
    if (tailOf(1 - mid, n) < q) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

// Per-run (num, den) vectors of some rows, so a resample is a few sums.
function arm(rows, keys) {
  const vec = rows.map((r) => keys.flatMap((k) => {
    const m = metricByKey.get(k);
    return [r[m.num] || 0, r[m.den] || 0];
  }));
  return {
    n: rows.length,
    sums(pick) {
      const out = {};
      const src = pick || vec;
      keys.forEach((k, i) => {
        let a = 0, b = 0;
        for (const v of src) {
          a += v[2 * i];
          b += v[2 * i + 1];
        }
        out[k] = [a, b];
      });
      return out;
    },
    draw(next) {
      const pick = new Array(vec.length);
      for (let i = 0; i < vec.length; i += 1) pick[i] = vec[Math.floor(next() * vec.length)];
      return this.sums(pick);
    },
  };
}

// B against A: the weighted difference (positive: B better), its interval and each measure's effect.
function compareRows(rowsA, rowsB, base, pseudo, weights, seed, conf, interval) {
  const keys = Object.keys(weights).filter((k) => k in base);
  const a = arm(rowsA, keys), b = arm(rowsB, keys);
  const rawA = estimates(a.sums(), base, pseudo, false), rawB = estimates(b.sums(), base, pseudo, false);
  const { d, parts } = composite(rawA, rawB, base, weights);
  const out = { d, ci: null, p: null, measures: {}, outcome: null };
  const draws = [], mdraws = {}, odraws = [];
  const expect = new Set(Object.keys(parts));
  if (interval && a.n && b.n && d !== null) {
    const next = rng(seedOf(seed));
    for (let i = 0; i < RESAMPLES(); i += 1) {
      const ea = estimates(a.draw(next), base, pseudo, false), eb = estimates(b.draw(next), base, pseudo, false);
      const c = composite(ea, eb, base, weights, expect);
      if (c.d !== null) draws.push(c.d);
      for (const [k, v] of Object.entries(c.parts)) (mdraws[k] = mdraws[k] || []).push(v);
      if (ea.outcome !== undefined && eb.outcome !== undefined) odraws.push(eb.outcome - ea.outcome);
    }
  }
  const lo = tailOf(conf, Math.min(rowsA.length, rowsB.length)), hi = 1 - lo;
  const ci = (xs) => (xs.length >= 20 ? (xs.sort((p, q) => p - q), [quantile(xs, lo), quantile(xs, hi)]) : null);
  out.ci = ci(draws);
  if (out.ci) out.p = pValue(draws, Math.min(rowsA.length, rowsB.length));
  for (const k of keys) {
    if (!(k in parts)) continue;
    const m = metricByKey.get(k);
    const mci = mdraws[k] ? ci(mdraws[k]) : null;
    out.measures[k] = { a: display(m, rawA[k]), b: display(m, rawB[k]), effect: Math.exp(parts[k]), ci: mci ? [Math.exp(mci[0]), Math.exp(mci[1])] : null, weight: weights[k] };
  }
  if (rawA.outcome !== undefined && rawB.outcome !== undefined) {
    out.outcome = { a: rawA.outcome, b: rawB.outcome, value: rawB.outcome - rawA.outcome, ci: ci(odraws) };
  }
  return out;
}

function verdictOf(ci, nA, nB, confounders, scored) {
  if (nA < MIN_RUNS || nB < MIN_RUNS) return ["not enough runs", null];
  if (scored === false) return ["not scored", null]; // runs enough, but no measure with a weight above 0 to compare
  if (!ci) return ["not enough runs", null];
  const direction = ci[0] > 0 ? "better" : ci[1] < 0 ? "worse" : "no clear change";
  return [confounders && confounders.length ? "confounded" : direction, direction];
}

// One version's score against a reference (the baseline, or another version's own values), with its range.
// Against the baseline the version's values are shrunk toward it; against another version both sides are unshrunk.
function versionScore(rows, ref, base, pseudo, weights, seed, conf, shrink) {
  const keys = Object.keys(weights).filter((k) => k in base);
  const a = arm(rows, keys);
  const sums = a.sums();
  const raw = estimates(sums, base, pseudo, false), est = shrink ? estimates(sums, base, pseudo, true) : raw;
  const { d, parts } = composite(ref, est, base, weights);
  let ci = null;
  if (d !== null && rows.length >= MIN_RUNS) {
    const next = rng(seedOf(seed));
    const draws = [];
    const expect = new Set(Object.keys(parts));
    for (let i = 0; i < RESAMPLES(); i += 1) {
      const c = composite(ref, estimates(a.draw(next), base, pseudo, shrink), base, weights, expect);
      if (c.d !== null) draws.push(c.d);
    }
    draws.sort((p, q) => p - q);
    const lo = tailOf(conf, rows.length);
    if (draws.length) ci = [100 * Math.exp(quantile(draws, lo)), 100 * Math.exp(quantile(draws, 1 - lo))];
  }
  const metrics = {};
  for (const k of keys) {
    if (!(k in parts)) continue;
    const m = metricByKey.get(k);
    metrics[k] = { value: display(m, raw[k]), counted: display(m, est[k]), ref: display(m, ref[k]), n: rows.filter((r) => r[m.den]).length,
      ratio: Math.exp(parts[k]), weight: weights[k] };
  }
  return { score: d === null ? null : 100 * Math.exp(d), ci, metrics, raw };
}

// The base each version is read against, as internal values; null when that version has none (v1 under "prev").
function refFor(u, scored, i) {
  if (S.base === "self") return scored.baseline;
  if (S.base === "prev") return i > 0 ? scored.rawOf[i - 1] : null;
  if (S.base === "first") return scored.rawOf[0] || null;
  const label = S.base.slice(4);
  const j = scored.order.findIndex((v) => v.label === label);
  return j >= 0 ? scored.rawOf[j] : scored.baseline;
}
const baseWords = () => (S.base === "self" ? "the skill's typical run" : S.base === "prev" ? "the version before" : S.base === "first" ? "its first version" : `${S.base.slice(4)}`);

const SCORE_CACHE = new Map();
const settingsKey = () => JSON.stringify([S, [...RUNSET].sort().join(","), slicing()]);

/* A unit as the page shows it: its versions (score, range, measures, against the chosen base), the pairs
   (verdict and difference), and the unit's current score. With the defaults and no filter, the model's. */
function scoreUnit(u) {
  const key = `${u.id}|${settingsKey()}`;
  if (SCORE_CACHE.has(key)) return SCORE_CACHE.get(key);
  // The model's numbers stand whenever they would come out the same: default settings and all of the unit's runs kept.
  const same = !scoreCustom() && unitRunsOf(u.id).length === (DATA.runs[u.id] || []).length;
  const out = asModel() || same ? fromModel(u) : recompute(u);
  SCORE_CACHE.set(key, out);
  return out;
}

function fromModel(u) {
  const versions = (DATA.versions[u.id] || []).map((v) => ({ ...v }));
  const pairs = (DATA.pairs || {})[u.id] || [];
  return { u, recomputed: false, rows: DATA.runs[u.id] || [], baseline: u.baseline, pseudo: u.pseudo, weights: u.weights, versions,
    pairs, score: u.score, ci: u.ci, verdict: u.verdict, direction: u.direction, vs: u.vs, difference: u.difference,
    confounders: u.confounders || [], delta: u.delta, kpi: u.kpi, runs: u.runs, current: u.current, outcome: u.outcome };
}

function recompute(u) {
  const rows = unitRunsOf(u.id);
  const keys = MEAS.filter((m) => m.kinds.includes(u.kind)).map((m) => m.key);
  // The typical run of the slice: pooled over the kept runs (the whole history when nothing filters).
  const sums = sumsFor(rows, keys);
  const baseline = {}, pseudo = {};
  for (const k of keys) {
    const [num, den] = sums[k];
    const m = metricByKey.get(k);
    const withData = rows.filter((r) => r[m.den]).length;
    if (den > 0 && (u.baseline || {})[k] !== undefined) {
      baseline[k] = slicing() ? num / den : u.baseline[k];
      pseudo[k] = slicing() ? den / withData : u.pseudo[k];
    }
  }
  const weights = Object.fromEntries(Object.entries(weightsOf(u)).filter(([k]) => k in baseline));
  const sessions = new Set(rows.map((r) => r.session)).size;
  const all = DATA.versions[u.id] || [];
  const order = all.filter((v) => rows.some((r) => r.version === v.label));
  const rowsOf = (v) => rows.filter((r) => r.version === v.label);
  const scored = { baseline, order, rawOf: order.map((v) => estimates(sumsFor(rowsOf(v), Object.keys(weights)), baseline, pseudo, false)) };
  const versions = order.map((v, i) => {
    const vr = rowsOf(v);
    const ref = refFor(u, scored, i);
    const s = ref ? versionScore(vr, ref, baseline, pseudo, weights, `${u.id}|${v.key}`, S.ci, ref === scored.baseline) : { score: null, ci: null, metrics: {} };
    const kp = kpiOf(vr, u.kind);
    return { ...v, runs: vr.length, low_sample: vr.length < MIN_RUNS, score: s.score, ci: s.ci, metrics: s.metrics,
      first_seen: vr.map((r) => r.started).filter(Boolean).sort()[0] || v.first_seen,
      last_seen: vr.map((r) => r.started).filter(Boolean).sort().pop() || v.last_seen,
      outcome: v.outcome ? { ...v.outcome, value: kp.outcome, n: sumOf(vr, (r) => r.on) } : null,
      kpi: { ...v.kpi, spend: sumOf(vr, (r) => r.cost) },
      verdict: null, direction: null, vs: null, difference: null, confounders: [], delta: null };
  });
  // Pairs: every pair with up to six versions, else consecutive ones (as bench.py).
  const idx = [];
  if (versions.length <= 6) for (let j = 0; j < versions.length; j += 1) for (let i = 0; i < j; i += 1) idx.push([i, j]);
  else for (let j = 1; j < versions.length; j += 1) idx.push([j - 1, j]);
  const modelPairs = (DATA.pairs || {})[u.id] || [];
  const pairs = idx.map(([i, j]) => {
    const A = versions[i], B = versions[j];
    const ra = rowsOf(order[i]), rb = rowsOf(order[j]);
    const enough = ra.length >= MIN_RUNS && rb.length >= MIN_RUNS;
    const res = compareRows(ra, rb, baseline, pseudo, weights, `${u.id}|${A.key}|${B.key}`, S.ci, enough);
    const mp = modelPairs.find((p) => p.a === A.label && p.b === B.label);
    const confounders = mp ? mp.confounders || [] : [];
    let [verdict, direction] = verdictOf(res.ci, ra.length, rb.length, confounders, res.d !== null);
    // A pair the model never compared (filtered runs can make new ones) has no confounder check: no direction is claimed.
    if (!mp && (verdict === "better" || verdict === "worse")) verdict = "no clear change";
    return { a: A.label, b: B.label, vs_previous: j === i + 1, runs_a: ra.length, runs_b: rb.length, verdict, direction, confounders, p: res.p,
      notes: mp ? mp.notes || [] : [], difference: { score: res.d === null ? null : 100 * Math.exp(res.d), ci: res.ci ? res.ci.map((x) => 100 * Math.exp(x)) : null,
        measures: res.measures, outcome: res.outcome } };
  });
  for (const p of pairs.filter((x) => x.vs_previous)) {
    const v = versions.find((x) => x.label === p.b);
    const prev = versions[versions.indexOf(v) - 1];
    Object.assign(v, { verdict: p.verdict, direction: p.direction, vs: p.a, difference: p.difference, confounders: p.confounders,
      delta: v.score !== null && prev.score !== null ? v.score - prev.score : null });
  }
  const last = versions[versions.length - 1] || null;
  const kp = kpiOf(rows, u.kind);
  return { u, recomputed: true, rows, baseline, pseudo, weights, versions, pairs,
    score: u.kind === "agent" ? null : last ? last.score : null, ci: last ? last.ci : null,
    verdict: last ? last.verdict : null, direction: last ? last.direction : null, vs: last ? last.vs : null,
    difference: last ? last.difference : null, confounders: last ? last.confounders : [], delta: last ? last.delta : null,
    kpi: { ...u.kpi, ...kp, spend: sumOf(rows, (r) => r.cost) }, runs: sessions, current: last ? last.label : u.current,
    outcome: u.outcome ? { ...u.outcome, value: kp.outcome, n: sumOf(rows, (r) => r.on) } : null };
}

// The pair B against A from a scored unit, oriented either way.
function pairIn(sc, a, b) {
  for (const p of sc.pairs) {
    if (p.a === a && p.b === b) return p;
    if (p.a === b && p.b === a) return flipPair(p);
  }
  return null;
}
