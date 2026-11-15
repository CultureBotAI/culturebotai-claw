# Authenticated historical helper provenance

Prepared for issues1266/1268 on2026-11-15. These results describe their recorded source
revisions and observation times. Every selected original byte stream is checked
against a fixed reviewed SHA256 manifest before any output is created. The
manifest itself is bound by the packager source's literal digest. Caller-supplied
substitute pins are not accepted. All syntax, harmless help paths, shapes and
public-data checks pass before writing an exclusive output outside input roots.

The original v1 and v2 packagers and stages remain retained privately. This correction
replaces their historical-narrative packaging path; it does not rerun or rewrite
the review results. PROVENANCE-V3.json records exact original/packaged hashes and
all packaging edits. Private plans, absolute paths, process/session identities
and raw histories are excluded. Cleanups, current CI readiness, merges, runtime
adoption and deployment are not authorized by these historical receipts.

The canonical packager and fixed manifest are in the sibling provenance-v3
folder under scripts/adhoc/cycle-maintenance-20261115. The cleanup inventory
helper uses an explicit --inventory-helper path. Its plan renderer accepts only
the pinned historical input bytes, parsing those exact cached bytes without rereading, and a new --output outside retained inputs;
it performs no cleanup. Audit helpers retain their original explicit arguments.
