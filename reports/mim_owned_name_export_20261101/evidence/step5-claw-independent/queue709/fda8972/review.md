Queue integration review: BLOCKED by a confirmed package-verification defect.

Actual GitHub integration fda8972b1820964d2d839d44165fb948b2917762 has tree5a7bb23f17d5c537e332fd0c40330942629ca866 and sole parent6a7172585eb68da7f4fe01aee75a82458ddd470c. Its full tree equals the reviewed feature head, including all479 intended changed paths and all unchanged parent paths. No maintained-source or diagnostic-content discrepancy was found.

The advertised portable verifier fails on that actual squash tree: check_references requires a56f3ae4563619a5129ad944878c9205267315d6 to be an ancestor ofHEAD. Real integration's sole-parent squash makes that false. The exact README command was reproduced against an exported integration tree and isolated Git metadata, with no production checkout/ref/branch mutations. It exits1 at verify.py:101. Preserve the original evidence, file the finding before repair and add an actual squash/consumer regression. Consider both absent ancestry and unavailable pre-squash objects in a normal consumer clone.

This rejects queue integration approval until repaired and re-reviewed. Previous exact-feature-head/proposed-body attestations remain historical and do not claim squash portability. No scientific change or GitHub mutation was performed by this reviewer.
