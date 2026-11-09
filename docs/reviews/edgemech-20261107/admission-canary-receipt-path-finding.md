# Reject receipt parent symlinks before the admission canary

Independent read-only review of the #960 canary helper found that
`Path.absolute()` followed by `is_relative_to(consumer_root)` only checked the
lexical output path. An apparently external parent directory could be a symlink
into EdgeMech. Writing the receipt would then modify the consumer after the
helper reported that it was clean.

Reject traversal and symlinks in every output path component, require a new
receipt outside the verified consumer root, and recheck before opening the
output. A regression must exercise an external parent symlink pointing inside
EdgeMech and demonstrate that no receipt is written. Run the actual no-op sync
canary only after the reviewed implementation is committed, so its candidate
head names the implementation being exercised.
