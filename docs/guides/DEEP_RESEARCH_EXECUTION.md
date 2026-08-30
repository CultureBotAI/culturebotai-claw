# Deep-research execution contract

The fleet's executable provider boundary is the claw-governed standalone
artifact
`src/kg_microbe_governance/artifacts/scripts/deep_research_contract.py`.
Mechs consume it at `scripts/deep_research_contract.py` through the immutable
`scripts/.vendored_canon_ref` pin. Domain prompts, record lookup, output paths,
and promotion into curated data remain owned by each Mech.

## Native Codex lane

Codex research runs through the installed `codex` CLI, not through a
`deep-research-client` compatibility adapter. The contract invokes the
equivalent of:

```text
codex --search --ask-for-approval never exec --ephemeral --sandbox read-only \
  --cd <repository> --output-schema <schema> \
  --output-last-message <response> -
```

The rendered prompt is supplied on standard input. Explicit `--search` enables
web search, while read-only/ephemeral execution prevents repository mutation.
The response must satisfy the closed JSON schema and local semantic checks:
a non-trivial report, a configured minimum number of distinct HTTP(S) source
URLs, non-empty titles, and well-formed limitations. Only validated output is
rendered and atomically promoted; a timeout, failed command, invalid JSON, thin
report, or duplicate-source result cannot overwrite a prior report.

The Codex canary is non-billing. It checks that the CLI is present,
authenticated, and advertises web-search and structured-output flags; it never
submits a research prompt.

## OpenScientist lane

OpenScientist remains a first-class `deep-research-client` provider. Configure
credentials locally or in an approved secret store:

```dotenv
OPENSCIENTIST_API_KEY=<name>:<secret>
# OPENSCIENTIST_URL=https://...
```

The key uses the provider's `name:secret` form. Never commit the value. The
canary validates only its shape and runs `deep-research-client providers` to
confirm discovery; it neither prints the secret nor submits a job. Mechs may
use an isolated command such as
`uvx --from deep-research-client deep-research-client` for discovery and
execution.

## Safety boundary

Canaries and tests are offline/non-billing capability checks. A live provider
run is a separate action: it requires the Mech runner's explicit apply flag,
the repository's research-policy authorization, and any required usage or cost
approval. Provider output is evidence for review, never direct authority to
edit curated records.

The separate audit/result lifecycle is documented in
`docs/guides/DEEP_RESEARCH_RESULTS.md`.
