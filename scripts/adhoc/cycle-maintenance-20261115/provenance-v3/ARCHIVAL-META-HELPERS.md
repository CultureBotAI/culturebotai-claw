# Historical packaging helper archives

The four `.py.txt` files listed in ARCHIVAL-META-HELPERS.json retain the exact
source bytes that produced the recorded packaging and validation results. They
are historical source archives, not supported executables or current operational
commands. Private originals and previous manifests remain intact. The historical
VALIDATION-PROVENANCE.json records the original filenames; the archive mapping
records their final publication paths without replacing that provenance.

Review identified a possible overwrite in the one-time v3 preparation generator
(issue1265) and overly broad exit-code classification in the one-time mutation
runner (issue1263). Freezing these generators avoids presenting them as safe
reusable tools. No historical pass claim depends on their future execution.
The actual two retained mutation logs were read back: the inventory case fails
the intended original-item assertion, and the drift case fails the intended
original-evidence assertion. Neither failure is a setup or import error.

The reviewed operational `package_review_provenance_v3.py` remains executable.
The four ongoing synthetic regression cases remain in
`tests/test_cycle_cleanup_plan_packaging.py`. Both the original v1/v2 stages and
all historical evidence are retained. No expensive validation was repeated for
this archival packaging change.
