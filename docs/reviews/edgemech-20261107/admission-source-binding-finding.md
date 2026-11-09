# Bind the infrastructure data pin to its actual immutable source snapshot

Independent read-only review of #960 found that the initial audit implementation
registered `historical[admission['source_ref']] = (current, current_payloads)`
without reading the named source commit. Its closed fetch adapter consequently
served current payloads under URLs naming that source ref. An absent or
different source commit in the first approved declaration, accompanied by the
same consumer pin, could pass despite lacking the claimed source provenance.
The existing source-ref mutation test only edited an already immutable
declaration, so it failed at the history guard instead of exercising this flaw.

Read the actual immutable source commit, manifest, fleet identities, payloads
and modes, compare them to the declaration-bound snapshot, and serve only those
verified source bytes to the checker. Keep the audit read-only. A trusted
preparation step may fetch the single declaration-bound data commit from the
canonical origin before audit; no code from the pin may execute. This preserves
squash-merge support without treating an arbitrary ref as a label for current
bytes.

Add first-introduction negative controls for an absent source commit and an
existing commit with different contents, with the consumer pinned to the same
bad ref. Keep a positive squash-history case and verify that candidate policy
cannot select a protected data-fetch target before approval.
