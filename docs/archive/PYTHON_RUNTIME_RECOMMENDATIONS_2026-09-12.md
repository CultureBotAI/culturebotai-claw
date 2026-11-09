# Python runtime recommendations — 2026-09-12

> Historical recommendations from 2026-09-12 PDT, archived on 2026-10-08 UTC.
> Runtime and support-status statements below retain their original review date.
> Use the maintained [Python runtime guide](../guides/PYTHON_RUNTIME.md) for the supported fleet policy.
> At archival time, [KG-Microbe #1056](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1056)
> was closed; the original migration issues
> [KG-Microbe #355](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/355)
> and [MicroGrowLink #376](https://github.com/CultureBotAI/MicroGrowLink/issues/376)
> remained open. Local workspace evidence below is optional historical provenance.

Recorded on 2026-09-12 PDT from the repository and upstream-source review
completed on 2026-09-13 UTC. This records recommendations and the observed
configuration at that time; proposed KG-Microbe and KOGUT migrations remain
separate work.

Keep **CPython 3.13 as the Mech and CLAW development/CI standard**, with explicit
exceptions for other pipelines. The fleet's regular dependencies and required
CI passed on 3.13 during the completed rollout. Optional dependency stacks
outside those checks are not covered by that conclusion. The rollout's CI
savings came from removing duplicate test runs; no benchmark established that
3.12 or 3.13 makes these workloads faster.

Python 3.13 receives upstream support through October 2029, versus October 2028
for 3.12. At the review date, 3.13 still receives regular bug fixes; 3.12 receives
security fixes only. The final regular 3.13 bugfix release is scheduled for
October 2026. Sources: [Python version status](https://devguide.python.org/versions/),
[3.13 release schedule](https://peps.python.org/pep-0719/),
[3.12 release schedule](https://peps.python.org/pep-0693/).

| Project | Build/runtime configuration at review | GitHub CI |
| --- | --- | --- |
| Ten manifest Mechs and CLAW | Python **3.13** after the completed fleet rollout | Python **3.13** |
| KG-Microbe | Python **3.10** explicitly selected by the [Jenkins build](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/5f1c4dfe4265959ef30451f98495e680768e70f5/Jenkinsfile#L62) | **3.10, 3.11 and 3.12** all passed the [inspected master QC run](https://github.com/Knowledge-Graph-Hub/kg-microbe/actions/runs/34624430094) |
| KOGUT / MicroGrowLink | GPU recipe pins **Python 3.11.7, PyTorch 2.6.0 and CUDA 12.4** in the [environment recipe](https://github.com/CultureBotAI/MicroGrowLink/blob/674c459ac124731edeeeea8a8735e4d1a4dd7020/environments/nersc-cu124.yml#L13) | **3.11**, including the [test workflow](https://github.com/CultureBotAI/MicroGrowLink/blob/674c459ac124731edeeeea8a8735e4d1a4dd7020/.github/workflows/tests.yml#L16) |

The Jenkins and GPU entries are configured runtimes, not measurements of live
Jenkins or NERSC processes. Both [KG-Microbe's package metadata](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/5f1c4dfe4265959ef30451f98495e680768e70f5/pyproject.toml#L10)
and [KOGUT's package metadata](https://github.com/CultureBotAI/MicroGrowLink/blob/674c459ac124731edeeeea8a8735e4d1a4dd7020/pyproject.toml#L10)
declare `>=3.10,<3.13`. A declared installation range is distinct from a tested
runtime; testing only 3.13 in the Mechs does not certify every version permitted
by their package metadata.

Recommended next decisions:

- **Mechs and CLAW:** retain Python 3.13 as the single required interpreter
  version in CI. Preserve distinct validation jobs; add another interpreter
  only for a concrete dependency or consumer-support requirement.
- **KG-Microbe:** evaluate Python 3.12 for its next build standard, validating
  the full graph build before switching. It already passes QC. Its reviewed
  lock selects NumPy 1.26.4, which [supports Python 3.9–3.12](https://numpy.org/doc/2.1/release/1.26.4-notes.html);
  moving to 3.13 requires dependency work. Python 3.10 reaches upstream end of
  life in October 2026, making this build migration a nearer-term priority.
- **KOGUT:** retain Python 3.11 until the GPU environment is migrated and
  validated together, including PyTorch, CUDA and model loading. Downgrading
  the Mechs to 3.12 would not match KOGUT's configured runtime.
- **A combined Python environment:** 3.12 is the more plausible candidate than
  3.13 under the current KG-Microbe and KOGUT constraints. Installation and
  integration tests would still be required; a compatible declared range alone
  is not proof that the complete dependency sets work together.

Different Python versions are acceptable when projects run in separate
environments and exchange KGX/TSV, JSON, YAML or API responses. Compatible
schemas, identifiers and data contracts matter at that boundary. When one
project imports another's Python code in the same process, both must support
the chosen interpreter and compatible dependencies. Compiled extensions and
model checkpoints also need compatibility checks. Keep project environments
separate and reproducible; [virtual environments are not portable artifacts](https://docs.python.org/3/library/venv.html#how-venvs-work).

The review also found a separate KG-Microbe documentation CI defect:
[unquoted `python-version: 3.10`](https://github.com/Knowledge-Graph-Hub/kg-microbe/blob/5f1c4dfe4265959ef30451f98495e680768e70f5/.github/workflows/deploy-docs.yml#L21)
is interpreted as `3.1`. The [inspected docs job](https://github.com/Knowledge-Graph-Hub/kg-microbe/actions/runs/34624429959/job/103345961516)
failed during Python setup. Quote the intended version as a separate
configuration correction; this finding was not fixed by saving this document.

Follow-up tracking, filed or updated on 2026-09-13 UTC after checking existing
open and closed issues:

| Repository | Tracking | Scope |
| --- | --- | --- |
| KG-Microbe | [Existing #355 — migration plan added](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/355#issuecomment-5650502371) | Validate Python 3.12 for the full graph build, align runtimes and simplify CI while preserving every gate. |
| KG-Microbe | [New #1056](https://github.com/Knowledge-Graph-Hub/kg-microbe/issues/1056) | Fix documentation CI requesting Python 3.1 from unquoted 3.10. |
| KOGUT / MicroGrowLink | [New #376](https://github.com/CultureBotAI/MicroGrowLink/issues/376) | Assess a successor to Python 3.11; retain the current runtime until a candidate passes CPU, checkpoint and GPU validation. |

KOGUT's assessment links existing provisioning issue #311 and checkpoint
portability issue #285. It does not duplicate those defects or authorize a
compute campaign. No new Mech runtime issue is needed to retain the already
validated 3.13 standard. Filing these issues does not implement the migrations
or the documentation fix.

The fleet rollout's detailed local audit is retained at
`workspace/python-standard/REPORT.md` with its source, CI and merge receipts.
That workspace is gitignored and is not required to read these recommendations.
