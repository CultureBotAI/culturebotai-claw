/** Pure presentation helpers. Public source validation remains in the exporter. */
export const STAGES = Object.freeze([
  { key: "add_records", label: "Add records" },
  { key: "causal_graphs", label: "Causal graphs" },
  { key: "protein_examples", label: "Protein examples" },
  { key: "record_review", label: "Record review" },
  { key: "resolve_review_findings", label: "Resolve findings" },
  { key: "infrastructure", label: "Infrastructure" },
]);

export const STALE_AFTER_MS = 15 * 60 * 1000;
const COUNT_KEYS = ["completed_cycles", "completed_goals", "unique_prs", "merged_prs", "no_change_goals", "open_prs", "closed_prs"];
const ATTENTION_PHASES = new Set(["blocked", "requires_intervention", "requires_migration", "closure_blocked", "unavailable"]);
const PHASE_LABELS = Object.freeze({
  assessment: "Assessing",
  waiting: "Waiting",
  ready_to_dispatch: "Ready",
  awaiting_native_acceptance: "Awaiting acceptance",
  awaiting_closure_receipt: "Awaiting closure",
  blocked: "Blocked",
  requires_intervention: "Needs attention",
  requires_migration: "Migration needed",
  closure_blocked: "Closure blocked",
  unavailable: "Unavailable",
  working: "Working",
  active: "Active",
});

export function githubURL(value, repositoryURL = null) {
  if (typeof value !== "string" || !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\/pull\/[1-9][0-9]*)?\/?$/.test(value)) return null;
  const url = new URL(value);
  if (repositoryURL && !value.startsWith(`${repositoryURL.replace(/\/$/, "")}/pull/`)) return null;
  return url.href;
}

function validTime(value) {
  return typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/.test(value) && Number.isFinite(Date.parse(value));
}

function counts(value) {
  return value && COUNT_KEYS.every((key) => Number.isSafeInteger(value[key]) && value[key] >= 0);
}

function verifiedCounts(repo) {
  const cycles = new Map();
  const goals = new Set();
  const closures = new Set();
  for (const closure of repo.closures) {
    demand(typeof closure.run_key === "string");
    const cycle = `${closure.run_key}:${closure.cycle}`;
    const goal = `${cycle}:${closure.stage_number}`;
    demand(!goals.has(goal) && !closures.has(closure.id));
    closures.add(closure.id);
    goals.add(goal);
    if (!cycles.has(cycle)) cycles.set(cycle, new Set());
    cycles.get(cycle).add(closure.stage_number);
  }
  const numbers = new Set(repo.pull_requests.map((pr) => pr.number));
  demand(numbers.size === repo.pull_requests.length);
  return {
    completed_cycles: [...cycles.values()].filter((stages) => stages.size === 6).length,
    completed_goals: repo.closures.length,
    unique_prs: repo.pull_requests.length,
    merged_prs: repo.pull_requests.filter((pr) => pr.state === "merged").length,
    open_prs: repo.pull_requests.filter((pr) => pr.state === "open").length,
    closed_prs: repo.pull_requests.filter((pr) => pr.state === "closed").length,
    no_change_goals: repo.closures.filter((closure) => closure.outcome === "no_changes").length,
  };
}

function demand(condition) {
  if (!condition) throw new Error("The published snapshot does not match the supported progress format.");
}

export function validateSnapshot(snapshot) {
  demand(snapshot && snapshot.schema_version === "1.0.0" && validTime(snapshot.generated_at));
  demand(snapshot.tracking?.earlier_history === "unknown" && snapshot.tracking?.counts_are_lower_bounds === true);
  demand(counts(snapshot.totals) && Array.isArray(snapshot.repositories));
  const keys = new Set();
  for (const repo of snapshot.repositories) {
    demand(repo && typeof repo.key === "string" && /^[a-z][a-z0-9_-]*$/.test(repo.key) && !keys.has(repo.key));
    keys.add(repo.key);
    demand(typeof repo.name === "string" && repo.name.length > 0 && repo.name.length < 150 && githubURL(repo.github_url));
    demand(counts(repo.counters) && ["partial", "unobserved"].includes(repo.history_coverage));
    demand(repo.last_observed_at == null || validTime(repo.last_observed_at));
    demand(repo.current == null || (
      typeof repo.current === "object" && Number.isSafeInteger(repo.current.cycle) && repo.current.cycle > 0 &&
      Number.isSafeInteger(repo.current.stage_number) && repo.current.stage_number >= 1 && repo.current.stage_number <= 6 &&
      STAGES[repo.current.stage_number - 1].key === repo.current.stage_id &&
      typeof repo.current.phase === "string" && validTime(repo.current.observed_at)
    ));
    demand(Array.isArray(repo.stages) && repo.stages.length === 6);
    repo.stages.forEach((stage, index) => demand(stage.number === index + 1 && stage.key === STAGES[index].key && ["completed", "current", "pending", "unverified"].includes(stage.state)));
    demand(Array.isArray(repo.closures) && Array.isArray(repo.pull_requests));
    for (const closure of repo.closures) {
      demand(typeof closure.id === "string" && Number.isSafeInteger(closure.cycle) && closure.cycle > 0 &&
        Number.isSafeInteger(closure.stage_number) && closure.stage_number >= 1 && closure.stage_number <= 6 &&
        STAGES[closure.stage_number - 1].key === closure.stage_id &&
        ["merged", "no_changes"].includes(closure.outcome) && validTime(closure.verified_at));
      demand(!closure.pr_url || githubURL(closure.pr_url, repo.github_url));
    }
    for (const pr of repo.pull_requests) {
      demand(Number.isSafeInteger(pr.number) && pr.number > 0 &&
        githubURL(pr.url, repo.github_url) && new URL(pr.url).pathname.endsWith(`/pull/${pr.number}`) &&
        ["open", "closed", "merged"].includes(pr.state) && validTime(pr.observed_at) && Array.isArray(pr.associations));
      for (const association of pr.associations) {
        demand(Number.isSafeInteger(association.cycle) && association.cycle > 0 &&
          Number.isSafeInteger(association.stage_number) && association.stage_number >= 1 && association.stage_number <= 6);
      }
    }
    const expected = verifiedCounts(repo);
    demand(COUNT_KEYS.every((key) => repo.counters[key] === expected[key]));
  }
  demand(COUNT_KEYS.every((key) => snapshot.totals[key] === snapshot.repositories.reduce((total, repo) => total + repo.counters[key], 0)));
  return snapshot;
}

export function stageLabel(number) {
  return STAGES[number - 1]?.label ?? "Unknown stage";
}

export function isStale(value, now = Date.now()) {
  if (!value || !validTime(value)) return true;
  const age = now - Date.parse(value);
  return age > STALE_AFTER_MS || age < -60000;
}

export function relativeTime(value, now = Date.now()) {
  if (!value || !validTime(value)) return "Not observed";
  const elapsed = now - Date.parse(value);
  if (elapsed < -60000) return "Timestamp ahead of clock";
  if (elapsed < 60000) return "just now";
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function phaseInfo(repo) {
  if (!repo.current) return { label: "Not observed", kind: "unknown" };
  const phase = repo.current.phase;
  const kind = ATTENTION_PHASES.has(phase) ? "attention" : phase === "waiting" || phase.startsWith("awaiting_") ? "waiting" : phase in PHASE_LABELS ? "working" : "unknown";
  return { label: PHASE_LABELS[phase] ?? "Observed", kind };
}

export function blockerDescription(code) {
  const descriptions = {
    closure_repairs_exhausted: "The closure repair limit was reached. The session needs an operator review.",
    working_tree_changes: "Working tree changes require review before closure can finish.",
    goal_cancelled: "The native goal was cancelled. Continuation needs review.",
    goal_identity_changed: "The native goal changed. The supervisor needs reconciliation.",
    agent_busy: "The agent is busy; the supervisor is waiting for a safe handoff.",
    composer_unavailable: "The supervisor is waiting for the session input to become available.",
    review_required: "The supervisor reports a condition requiring review before the sequence can advance.",
  };
  return descriptions[code] ?? "";
}

export function selectRepositories(repositories, { query = "", filter = "all", sort = "attention", now = Date.now() } = {}) {
  const text = query.toLocaleLowerCase().trim();
  const selected = repositories.filter((repo) => {
    if (text && !`${repo.name} ${repo.key}`.toLocaleLowerCase().includes(text)) return false;
    if (filter === "attention") return phaseInfo(repo).kind === "attention";
    if (filter === "active") return !!repo.current && phaseInfo(repo).kind !== "attention";
    if (filter === "stale") return !!repo.current && isStale(repo.current.observed_at, now);
    if (filter === "unobserved") return !repo.current;
    return true;
  });
  selected.sort((a, b) => {
    let difference = 0;
    if (sort === "attention") difference = Number(phaseInfo(b).kind === "attention") - Number(phaseInfo(a).kind === "attention");
    if (sort === "stage") difference = (b.current?.stage_number ?? 0) - (a.current?.stage_number ?? 0);
    if (sort === "goals") difference = b.counters.completed_goals - a.counters.completed_goals;
    if (sort === "prs") difference = b.counters.merged_prs - a.counters.merged_prs;
    return difference || a.name.localeCompare(b.name);
  });
  return selected;
}
