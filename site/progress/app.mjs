import { STAGES, blockerDescription, githubURL, isStale, phaseInfo, relativeTime, selectRepositories, stageLabel, validateSnapshot } from "./model.mjs";

const $ = (id) => document.getElementById(id);
const formatNumber = new Intl.NumberFormat("en-US");
let snapshot = null;
let loading = false;
let refreshFailed = false;
const expanded = new Set();

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function link(text, url, repositoryURL = null) {
  const safe = githubURL(url, repositoryURL);
  if (!safe) return node("span", "", text);
  const element = node("a", "", text);
  element.href = safe;
  return element;
}

function exactTime(value) {
  if (!value) return "Not observed";
  return new Date(value).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
}

function updateFreshness() {
  if (!snapshot) return;
  const observed = snapshot.repositories.filter((repo) => repo.current);
  const stale = observed.filter((repo) => isStale(repo.current.observed_at));
  const freshness = $("freshness");
  let label;
  if (!observed.length) label = "No session observations";
  else if (refreshFailed) label = "Showing last loaded snapshot";
  else if (isStale(snapshot.generated_at)) label = "Published snapshot is stale";
  else if (stale.length) label = `${stale.length} stale session ${stale.length === 1 ? "observation" : "observations"}`;
  else label = "Recent session observations";
  freshness.className = `freshness ${refreshFailed || stale.length || isStale(snapshot.generated_at) ? "stale" : observed.length ? "" : "unknown"}`;
  freshness.replaceChildren(node("span", "status-dot"), node("span", "", label));
  freshness.firstChild.setAttribute("aria-hidden", "true");
  $("snapshot-time").textContent = `Snapshot ${relativeTime(snapshot.generated_at)}`;
  $("snapshot-time").title = exactTime(snapshot.generated_at);
}

function renderTotals() {
  const observed = snapshot.repositories.filter((repo) => repo.current).length;
  const attention = snapshot.repositories.filter((repo) => phaseInfo(repo).kind === "attention").length;
  $("metric-mechs").textContent = formatNumber.format(observed);
  $("metric-fleet-size").textContent = `of ${snapshot.repositories.length} in the fleet`;
  $("metric-attention").textContent = `${attention} ${attention === 1 ? "Mech needs" : "Mechs need"} attention`;
  $("metric-goals").textContent = formatNumber.format(snapshot.totals.completed_goals);
  $("metric-no-change").textContent = `${formatNumber.format(snapshot.totals.no_change_goals)} verified no-change ${snapshot.totals.no_change_goals === 1 ? "outcome" : "outcomes"}`;
  $("metric-prs").textContent = formatNumber.format(snapshot.totals.merged_prs);
  $("metric-open-prs").textContent = `${formatNumber.format(snapshot.totals.open_prs)} open · ${formatNumber.format(snapshot.totals.closed_prs)} closed without merge`;
  $("metric-cycles").textContent = formatNumber.format(snapshot.totals.completed_cycles);
}

function counter(value, label, observed) {
  const result = node("span", "counter", observed ? formatNumber.format(value) : "—");
  result.setAttribute("aria-label", observed ? `${value} ${label} in retained verified history` : `${label}: not observed`);
  result.append(node("small", "", label));
  return result;
}

function repoDetail(repo) {
  const detail = node("div", "repo-detail");
  const intro = node("div", "detail-intro");
  let description = "No workflow state has been observed for this Mech. Historical progress is unknown.";
  if (repo.current) {
    description = `Cycle ${repo.current.cycle}, goal ${repo.current.stage_number} of 6: ${stageLabel(repo.current.stage_number)}. `;
    description += blockerDescription(repo.current.blocker_code) ||
      (phaseInfo(repo).kind === "attention" ? "The supervisor reports a condition requiring attention before the sequence can advance. " : "The stage advances only after a verified closure. ");
    description += " ";
    if (repo.current.blocker_code && repo.current.blocker_code !== "none") description += "Detailed session context remains in the local supervisor.";
  }
  intro.append(node("p", "", description), link("Open repository ↗", repo.github_url));
  detail.append(intro);
  const columns = node("div", "detail-columns");
  const history = node("section", "detail-section");
  history.append(node("h3", "", "Verified goal history"));
  if (!repo.closures.length) {
    history.append(node("p", "muted", repo.current ? "No verified goal closures in the retained history yet. Earlier work may exist." : "Goal history is not observed."));
  } else {
    const list = node("ol", "history-list");
    [...repo.closures].sort((a, b) => Date.parse(b.verified_at) - Date.parse(a.verified_at)).forEach((closure) => {
      const item = node("li");
      item.append(node("p", "history-title", `Cycle ${closure.cycle} · ${closure.stage_number}. ${stageLabel(closure.stage_number)}`));
      const meta = node("p", "history-meta", `${closure.outcome === "no_changes" ? "Verified no changes" : "Merged and closed"} · ${exactTime(closure.verified_at)}`);
      if (closure.pr_url) meta.append(link(`PR #${closure.pr_number} ↗`, closure.pr_url, repo.github_url));
      item.append(meta);
      list.append(item);
    });
    history.append(list);
  }
  const prs = node("section", "detail-section");
  prs.append(node("h3", "", "Pull requests associated with goals"));
  if (!repo.pull_requests.length) {
    prs.append(node("p", "muted", "No verified PR associations in the retained history. Unassociated or earlier PRs are not counted."));
  } else {
    const list = node("ul", "pr-list");
    [...repo.pull_requests].sort((a, b) => b.number - a.number).forEach((pr) => {
      const item = node("li");
      const description = node("div");
      description.append(link(`PR #${pr.number} ↗`, pr.url, repo.github_url));
      description.append(node("small", "", pr.associations.map((association) => `Cycle ${association.cycle} · ${stageLabel(association.stage_number)}`).join("; ")));
      const status = node("span", `pr-state ${pr.state}`, pr.state === "closed" ? "Closed, unmerged" : pr.state);
      status.title = `Verified ${exactTime(pr.observed_at)}`;
      item.append(description, status);
      list.append(item);
    });
    prs.append(list);
  }
  columns.append(history, prs);
  detail.append(columns);
  const footnote = repo.current
    ? `Session observed ${exactTime(repo.current.observed_at)}. Tracking covers retained verified evidence; lifetime totals are unknown.`
    : "No session observation is available. A dash means unknown, not zero.";
  detail.append(node("p", "detail-footnote", footnote));
  return detail;
}

function repositoryCard(repo) {
  const card = node("details", "repo");
  card.dataset.key = repo.key;
  card.open = expanded.has(repo.key);
  card.addEventListener("toggle", () => card.open ? expanded.add(repo.key) : expanded.delete(repo.key));
  const summary = node("summary", "repo-summary");
  const identity = node("span", "repo-identity");
  identity.append(node("span", "repo-name", repo.name));
  const state = node("span", "repo-state");
  const phase = phaseInfo(repo);
  const badge = node("span", `badge ${phase.kind}`, phase.label);
  state.append(badge);
  if (repo.current) {
    const time = node("span", `row-time${isStale(repo.current.observed_at) ? " stale" : ""}`, `${isStale(repo.current.observed_at) ? "Stale · " : ""}${relativeTime(repo.current.observed_at)}`);
    time.title = exactTime(repo.current.observed_at);
    state.append(time);
  }
  identity.append(state);
  summary.append(identity);
  const cycle = node("span", "cycle-cell");
  const heading = node("span", "cycle-heading");
  heading.append(node("span", "", repo.current ? `Cycle ${String(repo.current.cycle).padStart(2, "0")}` : "Cycle unknown"));
  heading.append(node("span", "stage-name", repo.current ? `${repo.current.stage_number} / 6 · ${stageLabel(repo.current.stage_number)}` : "Awaiting an observation"));
  cycle.append(heading);
  const track = node("span", "stage-track");
  const description = [];
  repo.stages.forEach((stage, index) => {
    const segment = node("span", `stage-segment ${stage.state}`);
    const text = `${index + 1}. ${STAGES[index].label}: ${stage.state}`;
    segment.title = text;
    segment.setAttribute("aria-hidden", "true");
    track.append(segment);
    description.push(text);
  });
  track.setAttribute("role", "img");
  track.setAttribute("aria-label", description.join(". "));
  cycle.append(track);
  const completed = repo.stages.filter((stage) => stage.state === "completed").length;
  cycle.append(node("span", "cycle-caption", repo.current ? `${completed} of 6 closures verified in this cycle` : "History not observed"));
  summary.append(cycle);
  const observed = repo.history_coverage !== "unobserved";
  summary.append(counter(repo.counters.completed_cycles, "cycles", observed), counter(repo.counters.completed_goals, "goals", observed), counter(repo.counters.merged_prs, "PRs merged", observed));
  const chevron = node("span", "chevron", "›");
  chevron.setAttribute("aria-hidden", "true");
  summary.append(chevron);
  card.append(summary, repoDetail(repo));
  return card;
}

function renderRepositories() {
  if (!snapshot) return;
  const repositories = selectRepositories(snapshot.repositories, { query: $("search").value, filter: $("filter").value, sort: $("sort").value });
  $("repositories").replaceChildren(...repositories.map(repositoryCard));
  $("empty-state").hidden = repositories.length > 0;
  $("results-count").textContent = `${repositories.length} of ${snapshot.repositories.length} Mechs · counts reflect verified tracking history`;
}

async function loadSnapshot() {
  if (loading) return;
  loading = true;
  $("refresh").disabled = true;
  try {
    const response = await fetch(new URL("data/progress.json", import.meta.url), { cache: "no-store", signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`Snapshot request returned ${response.status}.`);
    const candidate = validateSnapshot(await response.json());
    snapshot = candidate;
    refreshFailed = false;
    $("dashboard").hidden = false;
    $("load-status").hidden = true;
    renderTotals();
    renderRepositories();
    updateFreshness();
  } catch {
    refreshFailed = true;
    const status = $("load-status");
    status.hidden = false;
    status.className = "notice notice-warning";
    status.textContent = snapshot
      ? "The latest snapshot could not be loaded or validated. The last successfully loaded data remains below; its timestamps are unchanged. Try Refresh data again."
      : "Progress data is unavailable or could not be validated. No completion counts are shown. Try Refresh data again or open the structured data link below.";
    updateFreshness();
  } finally {
    loading = false;
    $("refresh").disabled = false;
  }
}

$("search").addEventListener("input", renderRepositories);
$("filter").addEventListener("change", renderRepositories);
$("sort").addEventListener("change", renderRepositories);
$("reset").addEventListener("click", () => {
  $("search").value = "";
  $("filter").value = "all";
  $("sort").value = "attention";
  renderRepositories();
});
$("refresh").addEventListener("click", loadSnapshot);
document.addEventListener("visibilitychange", () => { if (!document.hidden) loadSnapshot(); });
setInterval(() => {
  if (!document.hidden) {
    updateFreshness();
    // Updating in place preserves keyboard focus and open disclosures.
    document.querySelectorAll(".repo").forEach((card) => {
      const repo = snapshot?.repositories.find((item) => item.key === card.dataset.key);
      const time = card.querySelector(".row-time");
      if (repo?.current && time) {
        time.className = `row-time${isStale(repo.current.observed_at) ? " stale" : ""}`;
        time.textContent = `${isStale(repo.current.observed_at) ? "Stale · " : ""}${relativeTime(repo.current.observed_at)}`;
      }
    });
  }
}, 30000);
setInterval(() => { if (!document.hidden && !document.activeElement?.closest(".repo")) loadSnapshot(); }, 120000);
loadSnapshot();
