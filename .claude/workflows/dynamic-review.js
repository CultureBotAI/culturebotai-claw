export const meta = {
  name: 'dynamic-review',
  description: 'Dynamic, repo-agnostic code review of a PR or branch diff: scope the diff and profile the repo at runtime, run the repo\'s own validators as a static gate, review across dimensions, adversarially verify each finding, then synthesize a ranked report (optionally posting inline PR comments).',
  whenToUse: 'Review a PR or branch in any repo before merge. Pass target/repo/depth via args; reports to the session by default, posts inline GitHub comments only when args.postComments is true.',
  phases: [
    { title: 'Scope', detail: 'resolve the diff and profile the repo at runtime' },
    { title: 'Static gate', detail: 'run the repo\'s own validators on the change' },
    { title: 'Review', detail: 'one Fable 5 agent per review dimension (sharded when deep)' },
    { title: 'Verify', detail: 'independent skeptics refute each finding' },
    { title: 'Synthesize', detail: 'rank, dedup, report, optionally post inline comments' },
  ],
}

// ---------------------------------------------------------------------------
// args (all optional):
//   repo         abs path of repo to review (default "." = cwd repo)
//   target       "PR:<n>" | "branch" | "diff:<base>..<head>" | "local"  (default "branch")
//   base         diff base ref                                          (default "origin/main")
//   depth        "quick" | "standard" | "thorough"                      (default "standard")
//   postComments true to post inline GH comments                        (default false)
//   dimensions   optional [{key,guidance}] override of review dimensions
// ---------------------------------------------------------------------------
// args may arrive as an object or as a JSON-encoded string depending on how the
// workflow was invoked — accept both, fall back to {} (all defaults) otherwise.
let a = {}
if (args && typeof args === 'object') {
  a = args
} else if (typeof args === 'string' && args.trim()) {
  try { a = JSON.parse(args) } catch (e) { a = {} }
}
const REPO = a.repo || '.'
const TARGET = a.target || 'branch'
const BASE = a.base || 'origin/main'
const DEPTH = ['quick', 'standard', 'thorough'].includes(a.depth) ? a.depth : 'standard'
const POST = a.postComments === true
const VOTES = DEPTH === 'thorough' ? 3 : DEPTH === 'quick' ? 0 : 1
const DIM_OVERRIDE = Array.isArray(a.dimensions) && a.dimensions.length ? a.dimensions : null
// Model for the review/verify swarm. Default: omit -> inherit the session model
// (always available). Override with e.g. reviewModel:"haiku" (cheaper) or "fable"
// (when accessible). Never hardcode a model that may be unavailable.
const REVIEW_MODEL = (typeof a.reviewModel === 'string' && a.reviewModel.trim()) ? a.reviewModel.trim() : null
const modelOpt = REVIEW_MODEL ? { model: REVIEW_MODEL } : {}

const dirOf = (p) => {
  const i = String(p).lastIndexOf('/')
  return i === -1 ? '.' : String(p).slice(0, i)
}

// ----------------------------- schemas -------------------------------------
const SCOPE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    nothingToReview: { type: 'boolean' },
    repo: { type: 'string' },
    repoName: { type: 'string' },
    ownerRepo: { type: ['string', 'null'], description: '"owner/name" for gh api, or null' },
    prNumber: { type: ['integer', 'null'] },
    headSha: { type: ['string', 'null'] },
    diffCmd: { type: 'string', description: 'shell command that prints the unified diff to review (run from repo root)' },
    files: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string' },
          lang: { type: 'string' },
          group: { type: 'string', description: 'logical group (top dir / subsystem)' },
          status: { type: 'string', description: 'A/M/D/R' },
        },
        required: ['path'],
      },
    },
    repoProfile: {
      type: 'object',
      additionalProperties: false,
      properties: {
        qcRecipes: { type: 'array', items: { type: 'string' }, description: 'justfile recipes relevant to review that exist in this repo' },
        schemaPath: { type: ['string', 'null'] },
        rootClass: { type: ['string', 'null'] },
        conventions: { type: 'array', items: { type: 'string' }, description: 'repo-specific review rules drawn from CLAUDE.md / review-profile.yaml' },
      },
      required: ['qcRecipes', 'conventions'],
    },
    dimensions: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: { key: { type: 'string' }, guidance: { type: 'string' } },
        required: ['key', 'guidance'],
      },
    },
  },
  required: ['nothingToReview', 'repo', 'diffCmd', 'files', 'repoProfile', 'dimensions'],
}

const GATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    ran: { type: 'array', items: { type: 'string' } },
    skipped: { type: 'array', items: { type: 'string' } },
    failures: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          file: { type: ['string', 'null'] },
          line: { type: ['integer', 'null'] },
          recipe: { type: 'string' },
          message: { type: 'string' },
        },
        required: ['recipe', 'message'],
      },
    },
  },
  required: ['ran', 'skipped', 'failures'],
}

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          file: { type: 'string' },
          line: { type: ['integer', 'null'] },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          dimension: { type: 'string' },
          title: { type: 'string' },
          rationale: { type: 'string' },
          suggestedFix: { type: ['string', 'null'], description: 'replacement for the cited line(s), or null' },
        },
        required: ['file', 'severity', 'dimension', 'title', 'rationale'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    refuted: { type: 'boolean', description: 'true if the finding is wrong, not in the diff, or not worth raising' },
    reason: { type: 'string' },
  },
  required: ['refuted', 'reason'],
}

const REPORT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    markdown: { type: 'string' },
    posted: { type: 'boolean' },
    postedCount: { type: 'integer' },
    counts: {
      type: 'object',
      additionalProperties: true,
      properties: {
        critical: { type: 'integer' }, high: { type: 'integer' },
        medium: { type: 'integer' }, low: { type: 'integer' },
        gateFailures: { type: 'integer' },
      },
    },
  },
  required: ['markdown', 'posted'],
}

// ----------------------------- 1. Scope ------------------------------------
phase('Scope')
const scope = await agent(
  [
    'You are the scoping step of a code-review workflow. Work read-only.',
    `Repo to review: ${REPO} (if ".", use the current working directory's git repo).`,
    `Review target: ${TARGET}   Diff base: ${BASE}`,
    '',
    'Do all of the following, then return the structured object:',
    '1. cd into the repo. Resolve the target into a concrete unified diff and report the exact',
    '   command (diffCmd) that prints it, runnable from the repo root:',
    '     - "PR:<n>"        -> use `gh pr diff <n>`; also capture prNumber, ownerRepo (owner/name',
    '                          from `gh repo view --json nameWithOwner`), and headSha',
    '                          (`gh pr view <n> --json headRefOid -q .headRefOid`).',
    '     - "branch"        -> `git diff ' + BASE + '...HEAD` (merge-base diff of current branch).',
    '     - "diff:<a>..<b>" -> `git diff <a>..<b>` using the provided range.',
    '     - "local"         -> `git diff` plus `git diff --staged` for uncommitted work.',
    '   For non-PR targets, prNumber/ownerRepo/headSha may be null.',
    '2. List changed files via `--name-status`; for each give path, status, a guessed lang, and a',
    '   logical group (top-level dir or subsystem). If there are zero changed files, set',
    '   nothingToReview=true and return.',
    '3. Profile the repo AT RUNTIME (do not assume): read CLAUDE.md / README if present; list the',
    '   justfile recipes that exist and matter for review (e.g. qc, validate, validate-strict,',
    '   validate-terms, validate-references, lint, test, gen-pydantic, verify-schema-pin,',
    '   verify-validator-pin); find the LinkML schema path + root/record class if this is a',
    '   schema-backed repo; and read .claude/review-profile.yaml if present (fields qc_command,',
    '   dimensions, conventions, schema_path) as an override. Put concrete, repo-specific review',
    '   rules into repoProfile.conventions (e.g. id placement/pattern, append curation_history,',
    '   diff-stable key order, evidence supports + verbatim-snippet anti-hallucination, id<->label',
    '   term binding, prefix conventions, schema/validator pin durability). If the repo is not',
    '   schema-backed, leave schemaPath/rootClass null and focus conventions on its CLAUDE.md.',
    '4. Choose review dimensions dynamically from what changed and the profile. Always include',
    '   "bugs" and "conventions". Add "security" if shell/gh/CI/Python/secrets are touched;',
    '   "tests" if code changed without matching tests; "schema-data-integrity" if YAML records or',
    '   the LinkML schema changed; "docs" if skills/README/docs changed. Give each a one-line',
    '   guidance string tailored to this repo. ' + (DIM_OVERRIDE ? 'NOTE: the caller supplied an explicit dimension list; use exactly: ' + JSON.stringify(DIM_OVERRIDE) : ''),
    '',
    'Return ONLY the structured object. Do not post anything anywhere.',
  ].join('\n'),
  { schema: SCOPE_SCHEMA, phase: 'Scope', label: 'scope' }
)

if (!scope || scope.nothingToReview || !Array.isArray(scope.files) || scope.files.length === 0) {
  return {
    repo: scope ? scope.repo : REPO,
    target: TARGET,
    summary: 'Nothing to review: the resolved diff has no changed files.',
    scope: scope || null,
  }
}

const dims = DIM_OVERRIDE || scope.dimensions || []
log(`Scoped ${scope.files.length} changed file(s) in ${scope.repoName || scope.repo}; dimensions: ${dims.map((d) => d.key).join(', ')}`)

// ----------------------------- 2. Static gate ------------------------------
phase('Static gate')
const gate = await agent(
  [
    'You are the static-gate step. Run the repo\'s OWN validators as ground truth; do not',
    're-implement their logic, and make no edits.',
    `Repo: ${scope.repo}`,
    `Relevant recipes that exist here: ${(scope.repoProfile.qcRecipes || []).join(', ') || '(none found)'}`,
    `Changed files:\n${scope.files.map((f) => '  ' + (f.status || '?') + ' ' + f.path).join('\n')}`,
    '',
    'Run the available quality recipes that are cheap and relevant (prefer ones scoped to changed',
    'files; e.g. `just validate <file>` / `just validate-terms <file>` per changed record, plus',
    'repo-wide cheap gates like verify-schema-pin / verify-validator-pin). Skip anything that needs',
    'network, long builds, or is clearly irrelevant to the changed files, and record it under',
    '"skipped" with a reason. Capture each failure with the file/line if the tool reports one, the',
    'recipe name, and the message. A non-zero exit is expected when there are findings — capture,',
    'do not abort. Return the structured object.',
  ].join('\n'),
  { schema: GATE_SCHEMA, phase: 'Static gate', label: 'static-gate' }
)

// ----------------------------- 3+4. Review -> Verify -----------------------
// Build review tasks = dimensions x shards. Shard by file group only when deep + large.
const groups = [...new Set(scope.files.map((f) => f.group || dirOf(f.path)))]
const shards = (DEPTH === 'thorough' && scope.files.length > 12)
  ? groups.map((g) => ({ name: g, files: scope.files.filter((f) => (f.group || dirOf(f.path)) === g).map((f) => f.path) }))
  : [{ name: 'all', files: scope.files.map((f) => f.path) }]
const tasks = dims.flatMap((d) => shards.map((s) => ({ dim: d, shard: s })))

const lenses = ['correctness — is the claim technically right?', 'reproduce — does it actually occur in THIS diff?', 'convention-accuracy — does the cited repo rule really exist and apply?']

phase('Review')
// Barrier (not pipeline) so a FAILED finder (agent returns null) is distinguishable
// from a genuinely clean one — a degraded run must never look like "no issues".
const reviewResults = await parallel(tasks.map((t) => () =>
  agent(
    [
      `You are a meticulous code reviewer for the "${t.dim.key}" dimension. Review ONLY the diff.`,
      `Repo: ${scope.repo}  (${scope.repoName || ''})`,
      `Dimension guidance: ${t.dim.guidance}`,
      t.shard.name !== 'all' ? `Restrict to these files: ${t.shard.files.join(', ')}` : 'Review all changed files.',
      `Repo-specific conventions to enforce:\n${(scope.repoProfile.conventions || []).map((c) => '  - ' + c).join('\n') || '  (none)'}`,
      '',
      `Get the diff by running, from the repo root: ${scope.diffCmd}`,
      t.shard.name !== 'all' ? '(then focus on the listed files only)' : '',
      '',
      'Report only real, actionable problems introduced or surfaced BY THIS DIFF — not pre-existing',
      'issues outside it, not nitpicks. For each: file, the RIGHT-side line number in the new file,',
      'severity, a short title, a concrete rationale, and a suggestedFix (the corrected line[s]) when',
      'you are confident, else null. If nothing real, return an empty findings array. Be precise; a',
      'false positive is worse than a miss.',
    ].join('\n'),
    { schema: FINDINGS_SCHEMA, ...modelOpt, phase: 'Review', label: `review:${t.dim.key}${t.shard.name === 'all' ? '' : ':' + t.shard.name}` }
  ).then((r) => ({ task: t, review: r }))
))

const reviewFailures = reviewResults.filter((r) => !r || r.review == null).length
const rawFindings = reviewResults
  .filter((r) => r && r.review && Array.isArray(r.review.findings))
  .flatMap((r) => r.review.findings.map((f) => ({ ...f, shard: r.task.shard.name })))
if (reviewFailures > 0) log(`WARNING: ${reviewFailures}/${tasks.length} review agents failed — this review is INCOMPLETE.`)

phase('Verify')
const verified = await parallel(rawFindings.map((f) => () => {
  if (VOTES === 0) return Promise.resolve({ ...f, verdict: { real: true, votes: 'unverified (quick)' } })
  return parallel(Array.from({ length: VOTES }, (_, i) => () =>
    agent(
      [
        'You are an adversarial verifier. Try to REFUTE the finding below. Default to refuted=true',
        'when uncertain, when it is not clearly caused by this diff, or when it is a nitpick.',
        `Lens for this pass: ${lenses[i % lenses.length]}`,
        `Repo: ${scope.repo}`,
        `Reproduce the diff with: ${scope.diffCmd}`,
        '',
        `Finding: ${JSON.stringify({ file: f.file, line: f.line, severity: f.severity, dimension: f.dimension, title: f.title, rationale: f.rationale })}`,
        '',
        'Inspect the actual diff/files to check it. Return refuted (boolean) + a one-line reason.',
      ].join('\n'),
      { schema: VERDICT_SCHEMA, ...modelOpt, phase: 'Verify', label: `verify:${f.file}` }
    )
  )).then((vs) => {
    const valid = vs.filter(Boolean)
    const kept = valid.filter((v) => !v.refuted).length
    const real = valid.length === 0 ? true : kept > valid.length / 2
    return { ...f, verdict: { real, kept, of: valid.length, votes: valid } }
  })
}))

const confirmed = verified.filter(Boolean).filter((f) => f.verdict && f.verdict.real)

// dedup by file+line+title
const seen = new Set()
const deduped = confirmed.filter((f) => {
  const k = `${f.file}|${f.line}|${f.title}`
  if (seen.has(k)) return false
  seen.add(k)
  return true
})
log(`Confirmed ${deduped.length} finding(s) after adversarial verification; ${(gate && gate.failures || []).length} static-gate failure(s).`)

// ----------------------------- 5. Synthesize -------------------------------
phase('Synthesize')
const report = await agent(
  [
    'You are the synthesis step. Produce the final review.',
    `Repo: ${scope.repo}  Target: ${TARGET}  Depth: ${DEPTH}`,
    `PR number: ${scope.prNumber == null ? '(none)' : scope.prNumber}  ownerRepo: ${scope.ownerRepo || '(none)'}  headSha: ${scope.headSha || '(none)'}`,
    `Review coverage: ${tasks.length - reviewFailures}/${tasks.length} review agents succeeded.` +
      (reviewFailures > 0
        ? ` ${reviewFailures} FAILED. This review is INCOMPLETE — do NOT call it "clean"; state prominently at the top that ${reviewFailures} review agent(s) did not run and findings may be missing.`
        : ''),
    '',
    `Confirmed review findings (already adversarially verified):\n${JSON.stringify(deduped, null, 2)}`,
    '',
    `Static-gate failures from the repo's own validators:\n${JSON.stringify((gate && gate.failures) || [], null, 2)}`,
    '',
    'Build a single markdown report: a one-line verdict, a summary table of counts by severity,',
    'then findings grouped by severity (critical -> low) each as: `file:line` — title — rationale —',
    'and the suggested fix when present. Put static-gate failures in their own section. Dedup',
    'anything that overlaps a gate failure. Keep it tight and skimmable. Set counts.',
    '',
    POST && scope.prNumber != null && scope.ownerRepo
      ? [
          'THEN post to the PR (the caller asked for inline comments):',
          `- Use the exact gh pattern documented in CultureMech/dismech/.github/workflows/post-review-agent.yml`,
          '  (read that file for the precise form): for each finding with a concrete location, post an',
          '  inline review comment via `gh api repos/' + scope.ownerRepo + '/pulls/' + scope.prNumber + '/comments`',
          '  with -f body (include a one-click suggestion block when suggestedFix is present), -f commit_id=' + (scope.headSha || '<HEAD sha from gh pr view --json headRefOid>') + ',',
          '  -f path, -f line, -f side=RIGHT. Then post a single summary via `gh pr review ' + scope.prNumber + ' --comment` with the verdict + counts.',
          '- Skip findings without a concrete file/line. Set posted=true and postedCount to the number of',
          '  inline comments created. If any gh call fails, stop posting, report the error in the markdown,',
          '  and set posted=false.',
        ].join('\n')
      : 'Do NOT post anything (report-only mode). Set posted=false, postedCount=0.',
  ].join('\n'),
  { schema: REPORT_SCHEMA, phase: 'Synthesize', label: 'synthesize' }
)

return {
  repo: scope.repo,
  repoName: scope.repoName,
  target: TARGET,
  depth: DEPTH,
  prNumber: scope.prNumber,
  counts: report.counts || null,
  gateFailures: (gate && gate.failures) || [],
  confirmedFindings: deduped.length,
  reviewTasks: tasks.length,
  reviewFailures,
  degraded: reviewFailures > 0,
  reviewModel: REVIEW_MODEL || '(inherited session model)',
  posted: report.posted === true,
  postedCount: report.postedCount || 0,
  report: report.markdown,
}
