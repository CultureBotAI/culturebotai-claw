While implementing #701, the candidate publication validator was confirmed to fail open for an unrecognized nonzero subprocess exit.

At main `6a7172585eb68da7f4fe01aee75a82458ddd470c`, `scripts/build_mim_ingredient_sssom.py::_sssom_validate` and `scripts/publish_sssom.py::_validate` only collect three hard-coded diagnostic substrings and never check `proc.returncode`. A local offline probe supplies `CompletedProcess([], 2, "", "validator failed without known marker")`; the builder returns `[]`, which its caller treats as successful validation. This is a regression-test reproduction, not a claim that an actual bad canonical mapping was published.

Fix both SSSOM validation boundaries to treat every nonzero validator exit as failure while retaining useful diagnostics and the existing explicit diagnostic-only `--no-validate` contract. Add positive and negative subprocess controls, including a nonzero exit without one of the recognized marker strings, and prove the old behavior fails the regression. This is separate from #351, which concerns OAK label retrieval.

The correction is needed for the approved #701 guarded candidate publication. No source identity decision, paid provider call or validator waiver is authorized.
