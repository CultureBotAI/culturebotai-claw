# Protected-main refresh for #1225

The feature branch was refreshed by a normal merge, preserving its published
history. This is not a merge of PR #1219 into main and does not authorize one.

Before changing the branch, [CI run 43673279178](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43673279178)
at source head `5d3591224fbb44790f476dc46055090a42cda27a` was allowed to finish.
All three jobs passed. Its native test stage reported **10,516 passed, 543
skipped, 391 warnings and two subtests passed**; the separate safety-module
coverage check passed at **77%**. Skipped tests are not claimed as exercised.
The complete metadata and 537,765-byte log were saved privately before fetching
or merging. No run was cancelled or restarted to obtain this result.

The [earlier governance failure](https://github.com/CultureBotAI/culturebotai-claw/actions/runs/43672956347/job/132687175482)
remains separate evidence: its PR payload selected trusted `239efb49...`, while
the candidate merge and authoritative main used `23899092...`. The intended
exact-current-main guard rejected that stale runtime. [#1225](https://github.com/CultureBotAI/culturebotai-claw/issues/1225)
records this mismatch; [#1223](https://github.com/CultureBotAI/culturebotai-claw/issues/1223)
records the different earlier public-metadata transport failure. Neither failed
attempt is relabeled successful by this refresh.

## Merge and unchanged authority

Authoritative main was checked through GitHub, fetched, and checked again as
`23899092a4a2aedf53ff4435c0bdc03ebd79e6be`. Its sole advance over `239efb49...`
was PR #1215's public-discussion export implementation, schema, guide and tests,
plus the schema package-data entry in `pyproject.toml`. No agent instructions,
skills, workflows, dependency lockfile or governance implementation changed.
The package-data hunk and the feature branch's dev-dependency hunk merged cleanly.

Local merge commit `37d6109ec844607fb10155901c90f95b93cd3584` has parents
`5d3591224fbb44790f476dc46055090a42cda27a` and
`23899092a4a2aedf53ff4435c0bdc03ebd79e6be`, in that order. Its tree is
`0d6da045be61228170c672fe551f1e2d1c5cf894`, exactly the tree of GitHub's
`d61eb2f3d585825943e9aeac0731777fc03378aa` merge checkout tested by the successful
run above. Tree equality does not transfer required status checks to a new head.

The SupportingReference source and admission pins remained byte-identical:

| Artifact | SHA-256 |
| --- | --- |
| Canonical shared schema | `cf32864df1626201128e9311054b075bfc4ad3d8345491ac144122a5d5e67d11` |
| Vendored-artifact manifest | `54019ec731e29949ed2259f455d8a11ae1118b28c7149791a484cb10e0a2a430` |
| Skill template baseline | `6d154a0872909da30ac7258e9040198af04a88bf9b666e41b5787e66f763b105` |
| Dependency lockfile | `552d42540bce7d9acac0e5391e44e83e70e05586d602952b124a3c856639ab1b` |

No credential scope, protected-runtime equality, private obligation or required
gate was weakened. The incoming export guide continues to require caller-verified
source provenance, public membership and publication rights; recorded discussion
status is not scientific approval.

## Local combined controls

A real Discussion SupportingReference mutation/restoration test ran first through
the frozen local environment and persisted its receipt inside the test fixture:
**one passed**. The same launcher then ran the complete SupportingReference and
new public-export modules plus the exact-current-main positive/stale/dirty
runtime control: **64 passed**. Ruff and Git whitespace checks passed.

```text
uv run --no-sync --offline --extra dev python -m pytest -q \
  tests/test_supporting_reference_annotations.py \
  tests/test_discussions_public_export.py \
  tests/test_private_scaleup_audit.py::test_producer_version_requires_exact_authoritative_main_including_other_executable_files
```

Private raw artifacts are retained under `.temp/refresh-1225-20261115/`:

| Artifact | SHA-256 |
| --- | --- |
| Completed pre-refresh CI metadata | `40bac142988c9e962e01cd268990e33684ac9323071bc0c8da8b4b6a774dabb9` |
| Completed pre-refresh CI log | `2190c2cf6fb7708cd896da4d2c20e1f8a8e6c8b4b7a2acfddc6697bb55163759` |
| Earlier failed governance job log | `2b62c5f8bcea8b552f84ca67e8970443d90509f5dbe974659c5b6c44f03bc9aa` |
| Local real canary log | `076473d7a6c81a72c2c66927e274e567046a1ae3975703aafadbf10e1151adf5` |
| Local 64-control log | `b4cea94850e41e7ad8db93c3c6031afc6e0c0b04fd5e23b9dd4053223fc149f7` |

This checkpoint precedes publication of the refreshed head. After independent
review and publication, the new PR base, candidate merge parents and actual
trusted checkout must be checked against observed authoritative main, and normal
required CI must complete. A local merge alone does not prove those values agree
or that either governance execution blocker has cleared.
