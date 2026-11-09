# Bound native TaxonMech export validation and avoid duplicate schema passes

The real full-export launcher for CLAW #767 reads the committed GTDB inventory
at `ab35a0d0a0a2b47d250145db0c15b414fccbfdb8`: 322,327 mapping rows and
36,331,768 source bytes, verified against the native manifest.

Observed staged progress rose from 3,991 emitted rows (about 15 MiB JSONL) to
9,545 rows while the sole producer remained active. The implementation runs
the full shared JSON Schema validation serially for every generated assertion,
then repeats that validation on persisted readback. At this denominator that
is 644,654 schema checks, despite the repaired exact byte and ordered membership
digest reconciliation already proving that the persisted stream equals the
validated generated stream.

In-scope repair: retain shared validation for every generated envelope, use a
bounded four-worker spawn-safe pool with ordered results, and accept persisted
schema validity only after exact persisted byte and ordered assertion-ID/source-
position hashes reconcile. Do not eagerly submit all source rows or weaken
native scope, predicates, payloads or review status.

Required validation: serial/parallel JSONL byte identity, bounded submission,
worker failure with no publication, a real one-row canary through the same
four-worker launcher/environment, persisted artifact checks, then the complete
source export. Preserve the current full run as uncommitted temporary output;
restart only after the corrected canary succeeds.
