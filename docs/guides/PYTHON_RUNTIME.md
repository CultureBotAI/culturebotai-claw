# Python runtime and CI

The Mech fleet and CLAW use **CPython 3.13** for development, automation, and
GitHub Actions. Each repository records `3.13` in `.python-version`; patch
releases may advance within that minor. Python 3.13 already runs the CultureMech
full suite, CommunityMech compatibility suite, TraitMech tests, and CLAW tests.
It receives upstream support through October 2029
([Python release status](https://devguide.python.org/versions/)).

Run each test suite on this one Python version. Keep distinct fast, integration,
schema, corpus, and packaging checks where they test different behavior, but do
not duplicate them across Python versions. Keep check names independent of the
minor version so a future runtime upgrade does not require another merge queue
rules migration.

Select the interpreter explicitly. With a supported `astral-sh/setup-uv`
revision, set `python-version: "3.13"`; this also selects the interpreter for
`uv sync`, `uv run`, and isolated `uvx` tools. Older actions can use
`UV_PYTHON: "3.13"` with an explicit Python installation. Merely running
`uv python install 3.13` does not by itself express which interpreter a later
command must select. The root `.python-version` supplies the local default.

Package `requires-python` bounds describe install compatibility and need not be
narrowed to save CI time. A lower bound is not a commitment to test every
allowed interpreter on every PR. New syntax or dependency requirements should
still update package metadata when necessary.

An additional CI version needs a concrete dependency or consumer compatibility
requirement, documented beside the job with its scope and removal condition.
Keep such a check as small as possible. The September 2026 audit found no need
for an additional version in the fleet's regular CI dependency sets. Optional
extras outside CI are not validated by that conclusion.

When collapsing a matrix, update the corresponding entries in
`src/kg_microbe_merge_queue/policy.json` and the effective GitHub required status
checks together. Prove the replacement checks on the candidate commit before
changing a rule; retain every unrelated requirement and the merge queue itself.
Wait for the queue's own checks and confirm the merged main revision.
