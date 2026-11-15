# Additional MIM mapping contract fixture

`native_contract.py.txt` is an exact captured copy of MIM's pure maintained
`src/mediaingredientmech/additional_mappings.py` implementation for issue #1418.
`ORIGIN.json` records its source and SHA256. It contains no ingredient data,
scientific assessment, provider calls, or approval. The fixture permits Claw's
real stable generator and transaction to execute the native assertion checks
offline without requiring a second repository checkout. The existing stable-ID
fixture and governance vendored pin are unchanged.
