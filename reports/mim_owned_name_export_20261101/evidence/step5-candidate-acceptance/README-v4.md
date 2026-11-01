# Candidate acceptance v4

This author acceptance harness preserves v3 and its failed run unchanged. v3 stopped before native main because it required every in-use ontology transform; that precondition was stricter than the native Rule B4 warn-and-skip contract. The v4 change records available actual transform hashes and exact missing-prefix rows, invokes the unmodified native validator with only an empty in-memory Rule K baseline, and reports PASS_WITH_LIMITATIONS when otherwise successful. It neither invents transforms nor edits the canonical baseline. Captured labels are observed generation inputs and a distinct comparison supplement, not replacement ontology coverage.

Actual available/missing transforms and affected rows are reported in final-v4/b4-coverage.json. Final success must be read from final-v4/acceptance.json, not inferred from this preparation note. The known missing BTO/MICRO paths were also recorded by Step4 native-invariants/receipt.json. Missing-file checks use explicit paths, including ignored files.

The source graph replay still compiles exact captured entrypoint bytes and patches the bound private and entry aliases only in memory for the unfiltered comparison. All maintained sources and generated artifacts are read-only. This is deterministic author acceptance, not independent scientific review or canonical promotion.
