An additional mypy check of the two new #701 helpers reports `sssom_artifacts.py:245: Item None of bytes | None has no attribute decode`. Runtime selection already excludes absent preimages, but that invariant is not expressed to the type checker at journal serialization.

Narrow the selected old content to bytes explicitly, preserve the journal binding behavior and keep the existing replacement/missing-journal tests passing. Include both new helper files in the maintained type-check invocation so this failure is gated in CI. This is a low-severity static-check defect, not evidence of a runtime identity or mapping failure.

Reproduction: `uv run --frozen mypy src/kg_microbe_utils/owned_name_policy.py src/kg_microbe_utils/sssom_artifacts.py`; log SHA256 `98f8d3efa30e6900aac2c6fc992b1414e0cb1a6ad12f072b0dfd8d1ba6018ffc` on `e78e220d153e41d4340ad0f8abfbd83d96d01b57`.
