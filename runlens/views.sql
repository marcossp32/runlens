-- Analysis views. Generic: grouped by run, skill, agent role, agent type, model, tool.
-- A NULL skill means Claude Code attributed no skill to that work.

-- status: complete (the session ended) or open (it may still be running: partial numbers).
-- is_stub: too small to say anything (thresholds under [runs]). Benchmarks leave out open and stub runs.
CREATE OR REPLACE VIEW v_runs AS
SELECT r.session_id, r.started, r.ended, r.cwd, r.git_branch, r.cc_version, r.title, r.skills,
       r.cost_usd, r.cost_estimated, r.active_ms, r.human_prompts, r.n_agents,
       r.status, r.is_stub, r.entrypoint, len(coalesce(r.pr_urls, [])) AS prs, r.unpriced_models,
       t.tool_calls, t.tool_errors, round(t.tool_errors / nullif(t.tool_calls, 0), 4) AS error_rate,
       t.idle_calls, t.denied_calls, i.incidents, i.policy_incidents, m.bad_markers, a.api_errors, a.api_limits
FROM runs r
LEFT JOIN (SELECT session_id, count(*) AS tool_calls, count(*) FILTER (WHERE is_error) AS tool_errors,
                  count(*) FILTER (WHERE idle) AS idle_calls, count(*) FILTER (WHERE denied IS NOT NULL) AS denied_calls
           FROM tool_calls GROUP BY 1) t USING (session_id)
LEFT JOIN (SELECT session_id, count(*) AS incidents, count(*) FILTER (WHERE policy) AS policy_incidents
           FROM incidents GROUP BY 1) i USING (session_id)
LEFT JOIN (SELECT session_id, count(*) FILTER (WHERE bad) AS bad_markers FROM markers GROUP BY 1) m USING (session_id)
LEFT JOIN (SELECT session_id, count(*) FILTER (WHERE api_error) AS api_errors, count(*) FILTER (WHERE api_limit) AS api_limits
           FROM api_calls GROUP BY 1) a USING (session_id);

-- Token columns here, in v_model and in agents.*_tokens are what the transcript holds: output is 3-10x low, because most
-- messages never get their final count. Costs are scaled to cost-state; the model_usage table has Claude Code's own totals.
CREATE OR REPLACE VIEW v_skill AS
WITH api AS (
    SELECT coalesce(skill, '(none)') AS skill, count(*) AS api_calls, sum(cost_usd) AS cost_usd,
           sum(output_tokens) AS output_tokens, sum(input_tokens + cache_read_tokens + cache_write_5m + cache_write_1h) AS input_tokens,
           count(DISTINCT session_id) AS runs
    FROM api_calls GROUP BY 1),
tools AS (
    SELECT coalesce(skill, '(none)') AS skill, count(*) AS tool_calls, count(*) FILTER (WHERE is_error) AS tool_errors,
           count(*) FILTER (WHERE idle) AS idle_calls, sum(duration_ms) AS tool_ms
    FROM tool_calls GROUP BY 1),
inc AS (SELECT coalesce(skill, '(none)') AS skill, count(*) AS incidents FROM incidents GROUP BY 1),
mk AS (SELECT coalesce(skill, '(none)') AS skill, count(*) FILTER (WHERE bad) AS bad_markers FROM markers GROUP BY 1)
SELECT skill, runs, api_calls, cost_usd, round(100 * cost_usd / sum(cost_usd) OVER (), 1) AS cost_pct,
       input_tokens, output_tokens, tool_calls, tool_errors, round(tool_errors / nullif(tool_calls, 0), 4) AS error_rate,
       idle_calls, tool_ms, coalesce(incidents, 0) AS incidents, coalesce(bad_markers, 0) AS bad_markers
FROM api FULL JOIN tools USING (skill) LEFT JOIN inc USING (skill) LEFT JOIN mk USING (skill);

CREATE OR REPLACE VIEW v_role AS
SELECT coalesce(agent_type, '?') AS agent_type, coalesce(role, '?') AS role, count(*) AS agents,
       count(DISTINCT session_id) AS runs, sum(cost_usd) AS cost_usd, avg(cost_usd) AS avg_cost_usd,
       avg(epoch(ended - started)) AS avg_seconds, avg(tool_calls) AS avg_tool_calls, sum(tool_errors) AS tool_errors,
       round(sum(tool_errors) / nullif(sum(tool_calls), 0), 4) AS error_rate, max(peak_context) AS peak_context,
       sum(compactions) AS compactions, count(*) FILTER (WHERE status NOT IN ('completed', 'async_launched', 'running')) AS not_completed,
       string_agg(DISTINCT model, ', ') AS models
FROM agents GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_model AS
SELECT model, count(*) AS api_calls, sum(cost_usd) AS cost_usd, sum(output_tokens) AS output_tokens,
       sum(thinking_tokens) AS thinking_tokens, round(sum(cache_read_tokens) / nullif(sum(input_tokens + cache_read_tokens + cache_write_5m + cache_write_1h), 0), 4) AS cache_hit,
       count(*) FILTER (WHERE api_error) AS api_errors, count(*) FILTER (WHERE api_limit) AS api_limits,
       count(*) FILTER (WHERE cost_usd IS NULL) AS unpriced_calls
FROM api_calls GROUP BY 1;

CREATE OR REPLACE VIEW v_tools AS
SELECT tool, count(*) AS calls, count(*) FILTER (WHERE is_error) AS errors,
       round(count(*) FILTER (WHERE is_error) / count(*), 4) AS error_rate,
       median(duration_ms) AS median_ms, quantile_cont(duration_ms, 0.95) AS p95_ms, sum(duration_ms) AS total_ms
FROM tool_calls GROUP BY 1;

CREATE OR REPLACE VIEW v_tool_errors AS
SELECT tool, coalesce(error_class, 'other') AS error_class, coalesce(skill, '(none)') AS skill, count(*) AS errors,
       any_value(left(result_head, 300)) AS example, any_value(tool_use_id) AS example_tool_use_id
FROM tool_calls WHERE is_error GROUP BY 1, 2, 3;

-- Cost of turns whose only tool calls were idle (waiting or printing).
CREATE OR REPLACE VIEW v_idle AS
WITH per_msg AS (
    SELECT session_id, agent_id, msg_id, bool_and(idle) AS only_idle, any_value(skill) AS skill, count(*) AS calls
    FROM tool_calls GROUP BY 1, 2, 3)
SELECT p.session_id, p.agent_id, coalesce(p.skill, '(none)') AS skill, count(*) AS idle_turns,
       sum(a.cost_usd) AS idle_cost_usd
FROM per_msg p JOIN api_calls a USING (session_id, agent_id, msg_id)
WHERE p.only_idle GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW v_markers AS
SELECT marker, value, bad, coalesce(skill, '(none)') AS skill, count(*) AS n, count(DISTINCT session_id) AS runs
FROM markers GROUP BY ALL;

-- Skill changes along the main agent: which skill hands over to which.
CREATE OR REPLACE VIEW v_skill_flow AS
WITH s AS (
    SELECT session_id, ts, coalesce(skill, '(none)') AS skill,
           lag(coalesce(skill, '(none)')) OVER (PARTITION BY session_id ORDER BY ts) AS prev
    FROM api_calls WHERE agent_id = 'main')
SELECT prev AS from_skill, skill AS to_skill, count(*) AS transitions, count(DISTINCT session_id) AS runs
FROM s WHERE prev IS NOT NULL AND prev <> skill GROUP BY 1, 2;

-- Skill versions, from the skill text Claude Code injects into the transcript when a skill loads.
CREATE OR REPLACE VIEW v_skill_versions AS
SELECT skill, content_hash, min(ts) AS first_seen, max(ts) AS last_seen, count(*) AS loads,
       count(DISTINCT session_id) AS runs, any_value(content_len) AS content_len
FROM skill_loads GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_skill_version_stats AS
WITH ver AS (
    SELECT session_id, skill, arg_max(content_hash, ts) AS content_hash FROM skill_loads GROUP BY 1, 2),
api AS (SELECT session_id, skill, count(*) AS api_calls, sum(cost_usd) AS cost_usd FROM api_calls GROUP BY 1, 2),
tools AS (SELECT session_id, skill, count(*) AS tool_calls, count(*) FILTER (WHERE is_error) AS tool_errors,
                 count(*) FILTER (WHERE idle) AS idle_calls FROM tool_calls GROUP BY 1, 2),
inc AS (SELECT session_id, skill, count(*) AS incidents FROM incidents GROUP BY 1, 2),
mk AS (SELECT session_id, skill, count(*) FILTER (WHERE bad) AS bad_markers, count(*) AS markers FROM markers GROUP BY 1, 2)
SELECT v.skill, v.content_hash, count(*) AS runs, sum(api.api_calls) AS api_calls, sum(api.cost_usd) AS cost_usd,
       avg(api.cost_usd) AS cost_per_run, sum(tools.tool_calls) AS tool_calls, sum(tools.tool_errors) AS tool_errors,
       round(sum(tools.tool_errors) / nullif(sum(tools.tool_calls), 0), 4) AS error_rate, sum(tools.idle_calls) AS idle_calls,
       sum(inc.incidents) AS incidents, sum(mk.bad_markers) AS bad_markers, sum(mk.markers) AS markers
FROM ver v LEFT JOIN api USING (session_id, skill) LEFT JOIN tools USING (session_id, skill)
LEFT JOIN inc USING (session_id, skill) LEFT JOIN mk USING (session_id, skill)
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_incident_summary AS
SELECT type, coalesce(skill, '(none)') AS skill, coalesce(role, '?') AS role, count(*) AS incidents,
       sum(n) AS occurrences, count(DISTINCT session_id) AS runs
FROM incidents GROUP BY 1, 2, 3;

-- Latest label per incident and source; 'human' labels are the ground truth for judging the 'llm' ones.
CREATE OR REPLACE VIEW v_labels AS
SELECT * FROM labels QUALIFY row_number() OVER (PARTITION BY incident_id, source ORDER BY labeled_at DESC) = 1;

CREATE OR REPLACE VIEW v_label_summary AS
SELECT l.source, l.category, i.type, coalesce(i.skill, '(none)') AS skill, count(*) AS incidents
FROM v_labels l JOIN incidents i USING (incident_id) GROUP BY ALL;

-- Tokens the transcript shows against what Claude Code counted (cost-state), per run and model.
-- The transcript misses auxiliary calls (titles, classifiers), so input coverage is low by design;
-- output coverage well under 100% means the transcript lacks the final usage of some messages.
CREATE OR REPLACE VIEW v_token_coverage AS
WITH seen AS (
    SELECT session_id, regexp_replace(regexp_replace(model, '\[.*\]$', ''), '-\d{8}$', '') AS model,
           sum(output_tokens) AS output_tokens, sum(input_tokens + cache_read_tokens + cache_write_5m + cache_write_1h) AS input_tokens
    FROM api_calls GROUP BY 1, 2),
counted AS (
    SELECT session_id, regexp_replace(regexp_replace(model, '\[.*\]$', ''), '-\d{8}$', '') AS model,
           sum(output_tokens) AS output_tokens, sum(input_tokens + cache_read_tokens + cache_write_tokens) AS input_tokens,
           sum(cost_usd) AS cost_usd
    FROM model_usage GROUP BY 1, 2)
SELECT session_id, model, s.output_tokens AS transcript_output, c.output_tokens AS cost_state_output,
       round(s.output_tokens / nullif(c.output_tokens, 0), 3) AS output_coverage,
       s.input_tokens AS transcript_input, c.input_tokens AS cost_state_input,
       round(s.input_tokens / nullif(c.input_tokens, 0), 3) AS input_coverage, c.cost_usd AS cost_state_usd
FROM counted c FULL JOIN seen s USING (session_id, model);

-- API errors by kind. quota and rate_limit are limits on the account (api_limit), not failures of the work.
CREATE OR REPLACE VIEW v_api_errors AS
SELECT coalesce(api_error_kind, 'other') AS kind, api_error_status AS status, bool_or(api_limit) AS is_limit,
       coalesce(skill, '(none)') AS skill, count(*) AS n, count(DISTINCT session_id) AS runs
FROM api_calls WHERE api_error OR api_limit GROUP BY ALL;

-- How often a skill named in a prompt (skill_mention) was then invoked in the same agent.
CREATE OR REPLACE VIEW v_skill_mentions AS
SELECT skill, count(*) AS mentions, count(*) FILTER (WHERE invoked) AS invoked,
       round(count(*) FILTER (WHERE invoked) / count(*), 3) AS invoke_rate, count(DISTINCT session_id) AS runs
FROM skill_mentions GROUP BY 1;

-- Context pressure: compactions per skill active in the agent at the time.
CREATE OR REPLACE VIEW v_compactions AS
SELECT c.session_id, c.agent_id, c.ts, c.trigger, c.pre_tokens, c.post_tokens, c.duration_ms,
       (SELECT a.skill FROM api_calls a WHERE a.session_id = c.session_id AND a.agent_id = c.agent_id AND a.ts <= c.ts
        ORDER BY a.ts DESC LIMIT 1) AS skill
FROM compactions c;

-- One row: is the data complete and current? For a "data health" page and for `runlens check`.
CREATE OR REPLACE VIEW v_data_health AS
SELECT (SELECT count(*) FROM runs) AS runs,
       (SELECT count(*) FROM runs WHERE status = 'open') AS open_runs,
       (SELECT count(*) FROM runs WHERE is_stub) AS stub_runs,
       (SELECT count(*) FROM runs WHERE cost_estimated) AS estimated_cost_runs,
       (SELECT count(*) FROM runs WHERE unknown_model_cost) AS unknown_model_cost_runs,
       (SELECT list(DISTINCT m ORDER BY m) FROM (SELECT unnest(unpriced_models) AS m FROM runs)) AS unpriced_models,
       (SELECT count(DISTINCT session_id) FROM ingest_errors) AS runs_failed_to_ingest,
       (SELECT min(parser_version) FROM runs) AS min_parser_version,
       (SELECT value FROM meta WHERE key = 'parser_version') AS parser_version,
       (SELECT value FROM meta WHERE key = 'last_ingest') AS last_ingest,
       (SELECT sum(bad_lines) FROM runs) AS unreadable_lines,
       (SELECT round(sum(output_tokens) / nullif((SELECT sum(output_tokens) FROM model_usage), 0), 3)
          FROM api_calls WHERE session_id IN (SELECT session_id FROM model_usage)) AS output_token_coverage;
