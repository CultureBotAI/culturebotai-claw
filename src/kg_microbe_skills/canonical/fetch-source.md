---
name: fetch-source
description: "Add or harden a `fetch-<source>` recipe that downloads an upstream bulk release into {{ display_name }}'s raw data tree. Routes the download through a helper that validates before it promotes and replaces atomically, so a truncated or error-page response cannot become the release. Use when adding a new source download, or when an existing recipe is flaky, unvalidated, or can leave a partial file behind."
category: workflow
requires_database: false
requires_internet: true
version: 1.0.0
tags: [sources, download, provenance, validation]
---

# Fetch a source release

- Repository: `{{ github }}`
- Records this feeds: {{ record_globs }}

## The rule

<!-- canonical:begin the-rule -->
**Do not put a bare `curl -o` in a `fetch-*` recipe.** Route the download
through a helper that owns retries, validation, atomic replacement, and
provenance.

A bare `curl -o` writes straight to the destination. That means the two
failures that actually happen in this fleet both land as a corrupt release
rather than as an error:

- **A transfer that dies mid-body.** curl exits 18 on an early close and 56 on
  a reset, and neither is in its transient set — so `--retry` does not retry
  them. The truncated bytes are already at the destination, and every
  downstream step treats them as the release.
- **A 200 carrying an HTML error page.** `-f` only catches a 4xx/5xx *status*.
  A host that answers 200 with a login or maintenance page passes `-f`, and the
  HTML is installed as data.

Neither is hypothetical and neither is loud. The seeding step fails later,
somewhere else, on malformed content — which is the expensive way to find out.

The helper downloads to a sibling `.part`, validates, and only then calls
`os.replace`. An existing good release survives a failed transfer, because the
destination is never opened until the bytes have been checked.
<!-- canonical:end the-rule -->

## Choosing validation

<!-- canonical:begin choosing-validation -->
Validation is the whole point of the route, so choose it deliberately rather
than accepting defaults:

- **Always set a credible minimum size.** A token value like 1 byte passes for
  a truncated release and tells you nothing. Size it to the real release.
- **Check the magic prefix** for a compressed or binary format — `1f8b` for
  gzip, `504b` for zip. This is what catches an HTML error page cheaply.
- **Check for a stable marker string** in a text format: a header line, a
  column name, a format declaration. Something the real file always has and an
  error page never does.
- **Use a published digest when the publisher supplies one.** Do not compute an
  "expected" digest from the same untrusted download and then check the
  download against it — that asserts only that the bytes equal themselves.

Every success writes a provenance sidecar beside the file: requested and
resolved URL, UTC fetch time, size, SHA-256, and whatever `ETag`,
`Last-Modified` and `Content-Type` the server exposed. Read a file back against
its sidecar to detect a torn promotion, rather than assuming one did not
happen. Sidecars live beside gitignored raw data and are not committed.

Dry-run first. Printing the transport, destination, and validation contract
without touching the network or the filesystem is free, and it is the step that
catches a wrong path or an unquoted URL before a large download does.
<!-- canonical:end choosing-validation -->

## Scope boundary

<!-- canonical:begin scope-boundary -->
This is for **one fixed URL and one destination**, fetched once per release.

An API that needs pagination, authentication, dynamic file enumeration, or
source-specific post-processing is not a `fetch-*` recipe. It belongs in an
ingestion script in the language the rest of the pipeline is written in, with
checkpointing and partial-failure semantics of its own — a paginated pull that
dies on page 40 of 200 has a different recovery story than a single file, and
forcing it through shell interpolation loses that.

For a source that is several fixed files, invoke the helper once per file
rather than looping. Each invocation keeps its own timeout budget, and each
failure stays explicit and independently retryable instead of sharing one
deadline across an unknown number of files.
<!-- canonical:end scope-boundary -->

## How this repository fetches

This section is {{ display_name }}'s. Record the route this repository actually
uses — the helper or script a `fetch-*` recipe calls, its real arguments, and a
worked example against a source this repository genuinely downloads. Keep the
established recipe names and destination paths.

Name the checks to run after adding or migrating a recipe: the helper's own
tests, a `just --dry-run fetch-<source>`, and whatever source-catalogue or
registry gate this repository enforces. A `fetch-*` recipe that no gate knows
about is one nobody will notice has rotted.

## Related

- `kg-microbe-sources check --mech {{ mech_key }}` validates this repository's
  `download.yaml` source catalogue: a source's licence and seeder obligations,
  and each file block's own URL and status.
- The shared implementation lives in claw as `kg_microbe_sources.fetch`
  (`FetchPlan`, `fetch()`, `verify()`), with an injectable transport so the
  interesting behaviour is testable offline. `curl` is only the default.
