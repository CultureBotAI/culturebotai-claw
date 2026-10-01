# Cleanup decisions for research repositories

Read this when reviewing inventory candidates or performing authorized cleanup.
The source workflow is the user-installed repo-crud-cleanup skill used alongside
MicroGrowAgents. This adaptation retains its inventory/classification/quarantine
approach but does not reuse its mutation engine. Fixture review showed that its
cache-name rules could override protected descendants and guidance, its reference
scan could omit evidence, and a clean tracked worktree could still contain
valuable ignored files. The helper here deliberately makes no deletion claim.

## Classify by ownership and reproducibility

| Item | Decision evidence | Default |
| --- | --- | --- |
| Bytecode and familiar linter/test caches | Every descendant matches the expected tool output; no tracked files, secrets, unique results, pins, references, or explicit keep instruction | Review candidate |
| Build, distribution, documentation, or website output | Actual producing recipe, preserved inputs/version, publication contract, and whether this is the only release copy | Keep pending repository-specific proof |
| Dependency environments | Lockfile/toolchain and rebuild feasibility; local editable packages or manually installed tools may be unique | Keep unless individually included |
| Ignored data, research, downloads, reports, reference caches, provenance, curation history | Evidence/source ownership and recovery value; ignored status and remote availability do not prove reproducibility | Protect |
| New nonignored files, editor recovery files, backups, checkpoints | May contain work absent from Git or a newer version than the apparent original | Keep unless exact items are authorized |
| Symlink, nested repository, submodule, mount, or another worktree | Different ownership or containment boundary | Preserve; inventory separately when requested |
| Unknown format or incomplete scan | Name what evidence is missing | Keep |

Protect by the repository's actual paths, not a fixed list of directory names.
A literature cache can contain paid downloads, inaccessible URLs, validated
extracts, or corrections; a download catalogue can pin exact archive bytes.
A record may cite a local file without using its basename literally. A backup
whose original exists can still contain newer data. An environment or tool
cache may contain a symlink to an unrelated project. These facts override a
regeneration label.

Pages vary across Mechs: some publish tracked page trees, some build from source
in CI, and some use a different branch. Inspect the workflow's deploy input and
local generator before classifying output. A Pages site is not disposable just
because its directory matches a common build name. Generated schemas, indexes,
exports, and release assets likewise follow each repository's checked contract.

## Evidence and containment before a file action

1. Bind the selection to the exact GitHub origin, top level, Git common directory,
   branch/HEAD, path, and reviewed contents. Do not reuse a plan for a different
   clone or worktree. Preserve staged, unstaged, untracked, and ignored user work.
   The metadata inventory does not prove working-tree cleanliness. Establish any
   needed content comparison separately with filters, hooks, external diff/text
   converters, and lazy object fetching disabled; if that is unavailable, retain
   the affected item.
2. Refuse cleanup during a real merge, rebase, cherry-pick, revert, or bisect, or
   while a writer owns the target. Inspect operation state directories rather
   than assuming a stale diagnostic ref alone proves an active operation.
3. Walk the complete selected subtree without following symlinks. Recheck every
   ancestor and destination against redirection, nested Git boundaries, tracked
   paths, mounts, and newly created contents. An incomplete walk stays blocked.
4. Establish the actual rebuild command and its preserved inputs for a disposable
   item. Do not execute configuration files, import project code, or invoke hooks
   merely to classify names. Never read secrets to decide that they are secrets.
5. Write a recoverable action record outside the cleanup targets before mutation:
   original path, identity, content/metadata evidence, authorization, action,
   destination or recovery ref, time, and result. Do not rely only on a report
   written after deletion. Avoid placing quarantine inside another cleanup root.
6. Apply only the selected action, then verify immediately. If anything changed,
   stop the affected item and report the partial state. Keep independent actions
   separately accountable; an error is not permission to bypass a guard.

There is no bulk apply flag. Ordinary file/Git tools can perform an authorized,
reviewed action; the inventory JSON itself is not authority to remove anything.

## Git housekeeping has separate evidence

The helper records refs, linked worktrees, stashes, and active-operation markers;
it does not fetch, prune, merge, or prove branch disposability. Local remote-
tracking refs may be stale. Refresh remote evidence only when needed and within
the task's scope; use a private checkout when fetching shared refs would disturb
other work. Do not run project hooks or custom merge drivers as an inspection.

For an ordinary merged branch, verify its exact tip is reachable from the
current intended base. For a squash-merged branch, ancestry does not prove it:
verify the GitHub PR is actually MERGED into the expected repository/base, its
recorded head matches this branch's exact tip, and no later branch commits exist.
A queued PR or auto-merge setting is still open. A content-only merge simulation
is not sufficient evidence that this branch's work was reviewed or published.
If evidence is unavailable or ambiguous, retain the branch.

Before deleting an approved local branch, verify no registered worktree uses it,
record its exact old tip under a durable recovery reference, and use an atomic
expected-old-SHA ref deletion. A restoration must create an absent ref rather
than overwrite a branch that has since reappeared. Record every ref operation.
Do not delete the current/default branch, a stash, or another agent's active
branch. Remote branch deletion is separate; if explicitly authorized, use the
same verified PR/head association and an exact-head lease.

Worktree cleanup requires known ownership, verified merged work, no active
operation, and a full inventory of tracked, untracked **and ignored** contents.
Tracked-clean alone is insufficient. Preserve an old worktree with ignored
research even if its branch merged. Remove an eligible worktree only through
Git without force; never recursively delete its directory. A stale registration
may point at an unavailable disk rather than a deleted directory: establish that
fact before any metadata prune. A global prune must not include unreviewed
registrations. Stashes and reflogs remain recovery assets.

## Reversible handling and reports

A quarantine must have a unique session identifier, live outside every target,
and stay on the source filesystem. Verify both source and destination ownership
and containment. Record the move before it starts; confirm it afterward. Do not
follow a symlinked quarantine directory or overwrite an existing item on restore.
Retain failed/partial moves as explicit recovery work. Purge requires authorization
for the exact recorded session and a fresh containment/content check.

Logical bytes, allocated blocks, and filesystem free space are different
measurements. Reports should state which was measured and whether traversal was
complete. A bounded or failed scan cannot support "nothing remains" or an exact
reclaim estimate. Re-inventory includes ignored files just as the first scan did.
