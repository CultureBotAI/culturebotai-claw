# Guides and architecture references

This directory contains longer-lived domain and cross-repository guidance:

- `MECH_STANDARD.md` — what a repository must hold to in order to be a Mech,
  derived by measuring the five established Mechs rather than asserted:
  universal requirements, capabilities a Mech must decide about, and
  domain-specific work no other Mech should copy
- `MULTI_CLAUDE_COORDINATION.md` — the supported local coordination contract
- `MULTI_CLAUDE_ARCHITECTURE.md` — a retired proposal retained only as a
  redirect to the supported contract
- `VALIDATION_STRATEGY.md`
- `DEEP_RESEARCH_RESULTS.md` — the shared, audit-only research-result schema,
  offline scaffold/validation commands, and evidence-promotion boundary
- `DEEP_RESEARCH_EXECUTION.md` — the native Codex and OpenScientist execution,
  credential, canary, and validated-output contract vendored into Mechs
- `ENVO_TERM_SOURCING_GUIDE.md` and `SOIL_ONTOLOGY_GUIDE.md`
- `UNMAPPED_CAS_RN_TSV_GUIDE.md`
- `GITHUB_SETUP.md`
- `OAKLIB_COMPATIBILITY_ISSUE.md`

When a guide conflicts with the root `README.md`, `CLAUDE.md`, tests, or
current code, the current code and its tests are authoritative. Files under
`docs/archive/` and guides explicitly labelled retired are historical only.
