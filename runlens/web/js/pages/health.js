/* pages/health.js: is the data complete and current? (#/health)

   Everything a chart could be silently wrong about: runs that failed to ingest, runs still open or too
   small to score, models without a price, runs read by an older parser, a hook queue not drained, and how
   much of Claude Code's own token count the transcripts hold. The header badge links here when any of it
   needs action. */

function healthPage() {
  const H = EX.health;
  const head = h("header", { class: "pagehead" }, h("h1", { tabindex: "-1" }, "Data health"),
    h("p", { class: "lede" }, "Whether the numbers on the other pages are complete and current, and what to run when they are not."));
  if (!H) return h("article", { class: "page" }, head, empty("This database has no health view yet. Run runlens refresh, then runlens dashboard."));
  const s = H.summary || {};
  const issues = healthIssues();
  const warn = issues.filter((i) => i.level === "warn"), info = issues.filter((i) => i.level === "info");
  const runs = EX.runs;
  const status = h("section", { class: `healthbox ${warn.length ? "bad" : "good"}`, "aria-label": "Status" },
    h("h2", {}, warn.length ? `⚠ ${warn.length} thing${warn.length === 1 ? "" : "s"} to fix` : "✓ Nothing to fix"),
    warn.length ? h("ul", {}, warn.map((i) => h("li", {}, h("strong", {}, i.text), ". ", i.detail))) : h("p", { class: "muted" }, "Every run ingested, every model has a price, and the queue is empty."),
    info.length ? [h("h3", {}, "Worth knowing"), h("ul", { class: "info" }, info.map((i) => h("li", {}, h("strong", {}, i.text), ". ", i.detail)))] : null);

  const kp = kpiRow([
    kpi("Runs in the database", fmt.int(s.runs ?? runs.length), `${fmt.int(runs.filter((r) => r.pop).length)} finished and scored`),
    kpi("Still open", fmt.int(s.open_runs || 0), "left out of scores until they end"),
    kpi("Stubs", fmt.int(s.stub_runs || 0), "too small to score"),
    kpi("Failed ingests", fmt.int(s.runs_failed_to_ingest || 0), (H.ingest_errors || []).length ? "see the list below" : "none recorded", { tone: s.runs_failed_to_ingest ? "worse" : null }),
    kpi("Parser", `v${s.parser_version || "?"}`, s.min_parser_version && String(s.min_parser_version) !== String(s.parser_version) ? `oldest run read with v${s.min_parser_version}` : "every run read with it"),
    kpi("Last refresh", s.last_ingest ? fmt.when(s.last_ingest) : "—", `page generated ${fmt.when(DATA.generated)}`),
    kpi("Queue", fmt.int(H.pending_count || 0), H.pending_count ? "sessions waiting: run runlens refresh" : "nothing waiting")]);

  const cov = (H.coverage || []).map(([run, seen, counted, cost]) => ({ run, seen, counted, cost, r: RUN.get(run) })).filter((c) => c.counted);
  const covChart = scatterChart({
    title: "Output tokens the transcript shows, by run", question: "How much of Claude Code's own token count does each transcript hold?",
    takeaway: () => {
      const xs = cov.filter((c) => c.r).map((c) => c.seen / c.counted);
      return xs.length ? `Typically ${fmt.pct(median(xs), 0)} (median of ${fmt.runs(xs.length)}). That is low by design; the other pages count tokens from Claude Code itself.` : null;
    },
    sub: "one mark per run · transcript output tokens ÷ Claude Code's count (cost-state) · higher = the transcript holds more of it",
    points: cov.filter((c) => c.r).map((c) => ({ x: c.r.t0, y: c.seen / c.counted, label: c.run, href: hrefRun(c.run),
      tip: { title: `${c.run} · ${fmt.when(isoOf(c.r.t0))}`, rows: [["Share in the transcript", fmt.pct(c.seen / c.counted)], ["In the transcript", fmt.tokens(c.seen)],
        ["Claude Code counted", fmt.tokens(c.counted)], ["Claude Code's cost", fmt.usd(c.cost)]] } })),
    x: { title: "Run started", time: true }, y: { title: "Share of output tokens in the transcript", fmt: (v) => fmt.pct(v, 0) }, labelTitle: "Run",
    notes: "The transcript misses Claude Code's own side calls and most final usage records, so this is low by design. Token totals on the other pages use Claude Code's count; per-call output tokens are lower bounds.",
  });

  const listCols = [
    { key: "run", label: "Run", value: (r) => r.run, cell: (r) => h("a", { href: hrefRun(r.run) }, h("code", {}, r.run)) },
    { key: "started", label: "Started", value: (r) => r.t0, cell: (r) => fmt.when(isoOf(r.t0)) },
    { key: "status", label: "Status", value: (r) => r.status, cell: (r) => `${human(r.status)}${r.stub ? " · stub" : ""}${r.ended_by ? ` · ended by ${human(r.ended_by).toLowerCase()}` : ""}` },
    { key: "cost", label: "Cost", num: true, value: (r) => r.cost, cell: (r) => `${fmt.usd(r.cost)}${r.estimated ? " est." : ""}` },
    { key: "title", label: "Title", value: (r) => r.title, cell: (r) => h("span", { class: "task", title: r.title || "" }, r.title || "—") },
  ];
  const flagged = runs.filter((r) => !r.pop || r.estimated || r.unknown_cost || (r.unpriced || []).length || r.bad_lines || (s.parser_version && r.parser < Number(s.parser_version)));
  const why = (r) => [!r.pop ? (r.status !== "complete" ? "still open" : "stub") : null, r.estimated ? "estimated cost" : null, r.unknown_cost ? "unknown model cost" : null,
    (r.unpriced || []).length ? `no price: ${r.unpriced.join(", ")}` : null, r.bad_lines ? `${r.bad_lines} unreadable lines` : null,
    s.parser_version && r.parser < Number(s.parser_version) ? `parser v${r.parser}` : null].filter(Boolean).join(" · ");
  const errCols = [
    { key: "run", label: "Run", value: (e) => e.run, cell: (e) => h("code", {}, e.run) },
    { key: "stage", label: "Stage", value: (e) => e.stage },
    { key: "error", label: "Error", value: (e) => e.error, cell: (e) => h("span", { class: "task", title: e.detail || e.error }, e.error) },
    { key: "at", label: "When", value: (e) => e.failed_at, cell: (e) => fmt.when(e.failed_at) },
  ];
  return h("article", { class: "page" }, head, status, kp,
    section({ title: "What to run", intro: "Commands that bring the data up to date." },
      h("section", { class: "card" }, h("h2", { class: "cardtitle" }, "Commands"),
        h("ul", { class: "cmds" },
          h("li", {}, cmdLine("runlens refresh"), h("span", { class: "muted" }, " archive and ingest new runs, drain the hook queue, rebuild this page")),
          h("li", {}, cmdLine("runlens check"), h("span", { class: "muted" }, " compare the database with the archive and with ~/.claude/projects")),
          h("li", {}, cmdLine("runlens refresh --force"), h("span", { class: "muted" }, " read every run again (after a parser update)"))))),
    flagged.length ? section({ title: "Runs to keep in mind", count: fmt.int(flagged.length), intro: "Runs that are open, too small, estimated, unpriced or read by an older parser, with the reason." },
      sortTable({ caption: "Runs to keep in mind", cols: listCols.concat([{ key: "why", label: "Why", value: why }]), rows: flagged, sort: { key: "started", dir: -1 }, csvName: "runs-to-keep-in-mind" }).el) : null,
    (H.ingest_errors || []).length ? section({ title: "Failed ingests", count: fmt.int(H.ingest_errors.length), intro: "Runs whose transcript could not be read; their numbers are missing everywhere." },
      sortTable({ caption: "Failed ingests", cols: errCols, rows: H.ingest_errors, sort: { key: "at", dir: -1 }, csvName: "ingest-errors" }).el) : null,
    h("div", { class: "charts spaced" },
      cov.length ? covChart : null,
      (H.hook_errors || []).length ? h("section", { class: "card" }, h("h2", { class: "cardtitle" }, "Newest hook errors (hooks.log)"),
        h("pre", { class: "snippet", tabindex: "0" }, H.hook_errors.join("\n"))) : null,
      (H.pending || []).length ? h("section", { class: "card" }, h("h2", { class: "cardtitle" }, "Waiting in the queue"), h("ul", {}, H.pending.map((p) => h("li", {}, h("code", {}, p))))) : null));
}
