import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const { validateSnapshot, githubURL, isStale, phaseInfo, relativeTime, selectRepositories, STAGES } = await import(pathToFileURL(process.argv[2]).href);
const now = Date.parse("2026-10-20T12:00:00Z");
const timestamp = "2026-10-20T11:59:00Z";
const counters = { completed_cycles: 0, completed_goals: 0, unique_prs: 0, merged_prs: 0, open_prs: 0, closed_prs: 0, no_change_goals: 0 };
const row = {
  key: "example", name: "ExampleMech", github_url: "https://github.com/CultureBotAI/ExampleMech",
  counters: { ...counters }, history_coverage: "partial", last_observed_at: timestamp,
  current: { run_key: "a".repeat(24), cycle: 1, stage_number: 4, stage_id: "record_review", phase: "waiting", observed_at: timestamp, blocker_code: "none" },
  stages: STAGES.map((stage, index) => ({ number: index + 1, key: stage.key, state: index < 3 ? "unverified" : index === 3 ? "current" : "pending" })),
  closures: [], pull_requests: [],
};
const snapshot = {
  schema_version: "1.0.0", generated_at: timestamp,
  tracking: { history_scope: "verified_goal_associations", earlier_history: "unknown", counts_are_lower_bounds: true },
  totals: { ...counters }, repositories: [row],
};

if (process.argv[3]) {
  const actual = JSON.parse(readFileSync(process.argv[3], "utf8"));
  validateSnapshot(actual);
  process.stdout.write(`Real snapshot validated: ${actual.repositories.length} repositories\n`);
}

validateSnapshot(snapshot);
const unobserved = structuredClone(row);
delete unobserved.current;
delete unobserved.last_observed_at;
unobserved.history_coverage = "unobserved";
validateSnapshot({ ...snapshot, repositories: [unobserved] });
assert.equal(phaseInfo(unobserved).label, "Not observed");
assert.equal(phaseInfo({ current: { phase: "unexpected <script>" } }).label, "Observed");
assert.equal(phaseInfo({ current: { phase: "unexpected <script>" } }).kind, "unknown");
assert.equal(phaseInfo({ current: { phase: "requires_intervention" } }).kind, "attention");
assert.equal(phaseInfo(row).label, "Waiting");

for (const mutate of [
  (data) => { data.schema_version = "9.0.0"; },
  (data) => { data.totals.completed_goals = -1; },
  (data) => { data.totals.completed_goals = "0"; },
  (data) => { data.totals.completed_goals = 3; },
  (data) => { data.repositories[0].counters.completed_cycles = 1; },
  (data) => { data.repositories[0].counters.completed_cycles = 1; data.totals.completed_cycles = 1; },
  (data) => { data.tracking.earlier_history = "complete"; },
  (data) => { data.repositories[0].current.stage_id = "causal_graphs"; },
  (data) => { data.repositories[0].github_url = "javascript:alert(1)"; },
  (data) => { data.repositories[0].stages[0].state = "finished"; },
  (data) => { data.repositories.push(structuredClone(data.repositories[0])); },
  (data) => { data.repositories[0].pull_requests.push({ number: 1, url: "https://github.com/evil/other/pull/1", state: "merged", observed_at: timestamp, associations: [] }); },
]) {
  const changed = structuredClone(snapshot);
  mutate(changed);
  assert.throws(() => validateSnapshot(changed));
}

assert.equal(githubURL("https://github.com/CultureBotAI/ExampleMech/pull/10", row.github_url), "https://github.com/CultureBotAI/ExampleMech/pull/10");
for (const value of ["javascript:alert(1)", "//github.com/CultureBotAI/ExampleMech", "https://github.com.evil.test/CultureBotAI/ExampleMech", "https://github.com@evil.test/CultureBotAI/ExampleMech", "https://github.com/CultureBotAI/ExampleMech?x=1", "https://github.com/CultureBotAI/ExampleMech/../../evil"]) {
  assert.equal(githubURL(value), null);
}
assert.equal(isStale(timestamp, now), false);
assert.equal(isStale("2026-10-20T11:00:00Z", now), true);
assert.equal(isStale("2026-10-20T12:05:00Z", now), true);
assert.equal(isStale(null, now), true);
assert.equal(relativeTime(timestamp, now), "1m ago");
assert.equal(relativeTime(null, now), "Not observed");
assert.equal(relativeTime("2026-10-20T12:05:00Z", now), "Timestamp ahead of clock");

const attention = structuredClone(row);
attention.key = "blocked";
attention.name = "ZebraMech";
attention.current.phase = "requires_intervention";
attention.counters.merged_prs = 8;
const stale = structuredClone(row);
stale.key = "stale";
stale.name = "StaleMech";
stale.current.observed_at = "2026-10-20T09:00:00Z";
const repositories = [row, attention, stale, unobserved];
assert.equal(selectRepositories(repositories, { now })[0], attention);
assert.deepEqual(selectRepositories(repositories, { filter: "attention", now }), [attention]);
assert.deepEqual(selectRepositories(repositories, { filter: "stale", now }), [stale]);
assert.deepEqual(selectRepositories(repositories, { filter: "unobserved", now }), [unobserved]);
assert.equal(selectRepositories(repositories, { query: "<script>", now }).length, 0);
assert.deepEqual(selectRepositories(repositories, { query: "ZEBRA", now }), [attention]);
assert.equal(selectRepositories(repositories, { sort: "prs", now })[0], attention);
assert.equal(repositories[0], row, "filtering must not mutate source order");
process.stdout.write("Progress presentation checks passed\n");
