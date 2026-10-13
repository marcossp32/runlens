/* core/colour.js: every colour has one job (dataviz method: identity, order, magnitude, polarity, state).

   Identity: each skill, model, agent type and group gets ONE colour for the whole page, decided once from
   the data: skills and models in order of first use (so a new skill takes the next slot and the old ones
   keep theirs), the rest by name. Eight validated hues (--c1..--c8, light and dark steps in app.css);
   past eight the hue repeats with a different marker shape, never a generated hue.
   Polarity / state: better is blue with ▲, worse is red with ▼, unclear is grey with ≈. The pair was
   checked with the dataviz validator for protanopia and deuteranopia, and never relies on colour alone.
   Magnitude: one blue ramp (sequential) and a blue–grey–red ramp (diverging), mixed in OKLab. */

const SLOTS = 8;
const SHAPES = ["circle", "square", "triangle", "diamond"];

const ENTITY = (() => {
  const maps = { skill: new Map(), model: new Map(), agent: new Map(), group: new Map() };
  const order = (ns, items) => {
    const seen = new Map();
    for (const [name, t] of items) {
      if (name === null || name === undefined || name === "(none)" || name === "?") continue;
      const prev = seen.get(name);
      if (prev === undefined || (Number.isFinite(t) && !(prev <= t))) seen.set(name, Number.isFinite(t) ? t : Infinity);
    }
    [...seen].sort((a, b) => (a[1] - b[1]) || String(a[0]).localeCompare(String(b[0])))
      .forEach(([name], i) => maps[ns].set(name, i));
  };
  const D = DIAG || {};
  const units = (kind) => DATA.units.filter((u) => u.kind === kind).map((u) => [u.name, timeOf(u.first_seen)]);
  order("skill", units("skill").concat(
    [D.model_skill, D.incidents, D.idle, D.agents_by_skill, D.agent_skills, D.markers].flatMap((rows) => (rows || []).map((r) => [r.skill, NaN])),
    (D.flow || []).flatMap((f) => [[f.source, NaN], [f.target, NaN]])));
  order("model", (D.model_day || []).map((r) => [r.model, dayMs(r.day)]).concat((D.models || []).map((m) => [m.model, NaN]),
    (D.agent_models || []).map((m) => [m.model, NaN])));
  order("agent", (D.agent_types || []).map((a) => [a.agent_type, NaN]));
  order("group", units("group").map(([n]) => [n, NaN]));
  return maps;
})();

// {css, slot (1..8, 0 = no identity), shape} for one entity.
function colourOf(ns, name) {
  const i = ENTITY[ns] ? ENTITY[ns].get(name) : undefined;
  if (i === undefined) return { css: "var(--other)", slot: 0, shape: "circle", other: true };
  return { css: `var(--c${(i % SLOTS) + 1})`, slot: (i % SLOTS) + 1, shape: SHAPES[Math.floor(i / SLOTS) % SHAPES.length] };
}
const entityOfUnit = (u) => ({ skill: "skill", group: "group" }[u.kind] || null);

// Better, worse, unclear and "too few runs", each with its icon and word.
const TONE = {
  better: { icon: "▲", css: "var(--better)", word: "better" },
  worse: { icon: "▼", css: "var(--worse)", word: "worse" },
  unclear: { icon: "≈", css: "var(--neutral)", word: "unclear" },
  few: { icon: "○", css: "var(--neutral)", word: "too few runs" },
  first: { icon: "•", css: "var(--neutral)", word: "first version" },
  confounded: { icon: "?", css: "var(--neutral)", word: "confounded" },
};

// ---- colour arithmetic: sRGB <-> OKLab, for ramps that step evenly to the eye ----

function hexToRgb(hex) {
  let c = String(hex).trim().replace("#", "");
  if (c.length === 3) c = c.split("").map((x) => x + x).join("");
  const n = parseInt(c.slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const _lin = (v) => {
  v /= 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
const _gam = (v) => {
  const x = v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(x * 255)));
};
function toOklab(hex) {
  const [r, g, b] = hexToRgb(hex).map(_lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromOklab([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s].map(_gam);
  return `#${rgb.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}
function mix(a, b, t) {
  const p = toOklab(a), q = toOklab(b);
  return fromOklab(p.map((v, i) => v + (q[i] - v) * Math.max(0, Math.min(1, t))));
}
function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(_lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
// Ink for text set on a filled cell: whichever clears contrast.
const inkOn = (hex) => (luminance(hex) > 0.36 ? "#111111" : "#ffffff");

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Ordered categories (effort levels): one hue in steps (--o1 lightest .. --o4 darkest in light mode).
const ORDINAL_STEPS = { 1: [4], 2: [2, 4], 3: [2, 3, 4], 4: [1, 2, 3, 4] };
const ordinalCss = (i, n) => `var(--o${n <= 4 ? ORDINAL_STEPS[Math.max(1, n)][i] : Math.round((i / (n - 1)) * 3) + 1})`;

// Read once per draw: the theme can change between draws.
function scales() {
  const lo = cssVar("--seq-lo"), hi = cssVar("--seq-hi"), empty = cssVar("--cell-empty");
  const neg = cssVar("--worse"), mid = cssVar("--div-mid"), pos = cssVar("--better");
  return {
    empty,
    // t in 0..1: magnitude.
    seq: (t) => mix(lo, hi, 0.08 + 0.92 * Math.max(0, Math.min(1, t))),
    // t in -1..1: below the midpoint is worse (red), above is better (blue), 0 is a neutral grey.
    div: (t) => (t >= 0 ? mix(mid, pos, Math.min(1, t)) : mix(mid, neg, Math.min(1, -t))),
  };
}
