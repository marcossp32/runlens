/* core/prefs.js: personal preferences, kept in this browser (localStorage), never in a link.
   What a view shows lives in the URL hash (core/state.js); how the reader likes to see it lives here. */

const PREF_KEY = "runlens-prefs";
const PREF_CHOICES = {
  theme: ["auto", "light", "dark"],
  density: ["comfortable", "compact"],
  locale: ["auto", "en-US", "en-GB", "es-ES", "de-DE", "fr-FR"],
};
const PREF_LABELS = {
  theme: { auto: "Match the system", light: "Light", dark: "Dark" },
  density: { comfortable: "Comfortable", compact: "Compact" },
  locale: { auto: "This browser's", "en-US": "1,234.5 (US)", "en-GB": "1,234.5 (UK)", "es-ES": "1.234,5 (ES)", "de-DE": "1.234,5 (DE)", "fr-FR": "1 234,5 (FR)" },
};

const PREFS = (() => {
  const out = { theme: "auto", density: "comfortable", locale: "auto" };
  try {
    const saved = JSON.parse(localStorage.getItem(PREF_KEY) || "null") || {};
    if (!saved.theme) saved.theme = localStorage.getItem("runlens-theme"); // the key older pages used
    for (const k of Object.keys(out)) if (PREF_CHOICES[k].includes(saved[k])) out[k] = saved[k];
  } catch (e) {
    /* storage can be blocked; the defaults then apply */
  }
  return out;
})();

function savePref(key, value) {
  if (!PREF_CHOICES[key] || !PREF_CHOICES[key].includes(value)) return;
  PREFS[key] = value;
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(PREFS));
  } catch (e) {
    /* storage can be blocked; the choice then lasts for this page only */
  }
}

// Theme and density are attributes on <html>, so the stylesheet does the rest.
function applyPrefs() {
  const root = document.documentElement;
  if (PREFS.theme === "auto") delete root.dataset.theme;
  else root.dataset.theme = PREFS.theme;
  root.dataset.density = PREFS.density;
}
applyPrefs();

const reducedMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
