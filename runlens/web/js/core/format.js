/* core/format.js: the one place numbers, money, durations and dates become text.
   Every formatter uses the same locale (the reader's preference, or the browser's), so a table never
   mixes "0,998 $" with "29.8 min". The UI is in English, so units are English words. */

const _formatters = new Map();
const LOCALE = () => (PREFS.locale === "auto" ? undefined : PREFS.locale);

function nf(opts) {
  const key = `${PREFS.locale}|${JSON.stringify(opts)}`;
  if (!_formatters.has(key)) _formatters.set(key, new Intl.NumberFormat(LOCALE(), opts));
  return _formatters.get(key);
}
function df(opts) {
  const key = `${PREFS.locale}|d|${JSON.stringify(opts)}`;
  if (!_formatters.has(key)) _formatters.set(key, new Intl.DateTimeFormat(LOCALE(), opts));
  return _formatters.get(key);
}
const isNum = (v) => v !== null && v !== undefined && Number.isFinite(v);
const DASH = "—";

const fmt = {
  num(v, d = 1) {
    return isNum(v) ? nf({ maximumFractionDigits: d }).format(v) : DASH;
  },
  int(v) {
    return isNum(v) ? nf({ maximumFractionDigits: 0 }).format(v) : DASH;
  },
  // 1.2K, 3.4M: for axes and tight labels.
  compact(v) {
    if (!isNum(v)) return DASH;
    // English suffixes (the UI is English) with the locale's own decimal mark: "1.2K" or "1,2K", never "1,2 mil".
    const a = Math.abs(v);
    if (a < 1000) return fmt.num(v, a < 10 ? 1 : 0);
    const [div, suffix] = a >= 1e9 ? [1e9, "B"] : a >= 1e6 ? [1e6, "M"] : [1e3, "K"];
    return `${fmt.num(v / div, a / div < 100 ? 1 : 0)}${suffix}`;
  },
  usd(v) {
    if (!isNum(v)) return DASH;
    const d = Math.abs(v) < 1 ? 3 : 2;
    return nf({ style: "currency", currency: "USD", currencyDisplay: "narrowSymbol", minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
  },
  // Money on an axis: as few digits as the tick needs.
  usdTick(v) {
    if (!isNum(v)) return DASH;
    if (Math.abs(v) >= 1000) {
      // the locale's currency layout, with the number written the compact way: "12K $" or "$12K"
      let done = false;
      return nf({ style: "currency", currency: "USD", currencyDisplay: "narrowSymbol", maximumFractionDigits: 0 }).formatToParts(v)
        .map((p) => (["integer", "group", "decimal", "fraction"].includes(p.type) ? (done ? "" : ((done = true), fmt.compact(Math.abs(v)))) : p.value)).join("");
    }
    const d = v === 0 ? 0 : Math.abs(v) < 0.1 ? 3 : Math.abs(v) < 1 ? 2 : Math.abs(v) < 10 && !Number.isInteger(v) ? 1 : 0;
    return nf({ style: "currency", currency: "USD", currencyDisplay: "narrowSymbol", minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
  },
  pct(v, d = 1) {
    return isNum(v) ? nf({ style: "percent", maximumFractionDigits: d }).format(v) : DASH;
  },
  // A duration in seconds: "45 s", "29.8 min", "1.1 h", with the locale's decimal mark.
  secs(v) {
    if (!isNum(v)) return DASH;
    const a = Math.abs(v);
    if (a < 1) return `${fmt.num(v * 1000, 0)} ms`;
    if (a < 60) return `${fmt.num(v, a < 10 ? 1 : 0)} s`;
    if (a < 3600) return `${fmt.num(v / 60, 1)} min`;
    return `${fmt.num(v / 3600, 1)} h`;
  },
  ms(v) {
    return isNum(v) ? fmt.secs(v / 1000) : DASH;
  },
  score(v) {
    return isNum(v) ? fmt.int(v) : DASH;
  },
  signed(v, d = 1) {
    if (!isNum(v)) return DASH;
    return `${v < 0 ? "−" : "+"}${fmt.num(Math.abs(v), d)}`;
  },
  signedPct(v, d = 0) {
    if (!isNum(v)) return DASH;
    if (Math.abs(v) < 0.5 * 10 ** -(d + 2)) return fmt.pct(0, d);
    return `${v < 0 ? "−" : "+"}${fmt.pct(Math.abs(v), d)}`;
  },
  ratio(v) {
    return isNum(v) ? `×${fmt.num(v, 2)}` : DASH;
  },
  day(iso) {
    return iso ? df({ dateStyle: "medium" }).format(new Date(iso)) : DASH;
  },
  when(iso) {
    return iso ? df({ dateStyle: "medium", timeStyle: "short" }).format(new Date(iso)) : DASH;
  },
  // A calendar day kept as "YYYY-MM-DD" (or its midnight in UTC): it is shown as that day everywhere.
  dayKey(t) {
    const d = typeof t === "number" ? new Date(t) : new Date(`${t}T00:00:00Z`);
    return df({ month: "short", day: "numeric", timeZone: "UTC" }).format(d);
  },
  monthDay(t) {
    return df({ month: "short", day: "numeric" }).format(new Date(t));
  },
  hour(t) {
    return df({ hour: "numeric", minute: "2-digit" }).format(new Date(t));
  },
  span(a, b) {
    if (!a) return DASH;
    return a.slice(0, 10) === (b || a).slice(0, 10) ? fmt.day(a) : `${fmt.day(a)} – ${fmt.day(b)}`;
  },
  runs(n) {
    return `${fmt.int(n)} run${n === 1 ? "" : "s"}`;
  },
  interval(ci) {
    return ci ? `${fmt.score(ci[0])}–${fmt.score(ci[1])}` : DASH;
  },
  metric(m, v) {
    if (!isNum(v)) return DASH;
    if (m.unit === "usd") return fmt.usd(v);
    if (m.unit === "s") return fmt.secs(v);
    if (m.unit === "rate") return fmt.pct(v);
    return fmt.num(v, 2);
  },
  metricTick(m, v) {
    if (m.unit === "usd") return fmt.usdTick(v);
    if (m.unit === "s") return fmt.secs(v);
    if (m.unit === "rate") return fmt.pct(v, 0);
    return fmt.compact(v);
  },
  tokens(v) {
    return isNum(v) ? `${fmt.compact(v)} tokens` : DASH;
  },
};

function resetFormatters() {
  _formatters.clear();
}
