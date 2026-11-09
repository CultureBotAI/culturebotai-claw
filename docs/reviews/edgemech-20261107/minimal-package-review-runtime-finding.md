# Verify the optional review runtime from the installed contract distribution

Independent read-only packaging review found that the installation verifier
checks imported origins only for native identity/artifact/assertion modules.
The optional reviews environment runs native/artifact tests, whose only bundle
test rejects a native envelope as scientific review. This does not establish
that a valid canonical RecordReview and ledger path work from installed files.

Add explicit review-runtime verification of every Python module in the packaged
import closure, including review support modules. Exercise a valid review-bearing
bundle and real ledger operations from the installed wheel in an isolated test
directory. Reject support-module shadowing. Keep canonical source bytes unchanged
and keep the dependency-free native transport proof separate from the optional
LinkML review runtime. Until that proof passes, do not claim review-runtime
conformance from the native-only installation receipt.

This finding is part of the implementation advancing MediaIngredientMech #1144.
