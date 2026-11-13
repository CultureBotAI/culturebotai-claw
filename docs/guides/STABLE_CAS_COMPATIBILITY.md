# Retaining existing CAS mapping candidates

Stable MIM generation preserves an existing canonical `skos:exactMatch cas:`
row when the registered current owner corroborates that same CAS identity
(#1192). Promoting an ontology identifier to the primary `identifier` does not
silently retire a different, still valid registry assertion.

The input must already contain the exact CAS row. Metadata alone never creates
a new assertion. The canonical subject must resolve to one current registered
owner through the existing stable-ID or unambiguous historical-alias contract.
The CAS must have ordinary ASCII syntax and a valid check digit. It must agree
with the current primary CAS or `chemical_properties.cas_rn`; conflicting
identity-bearing values, a non-mapped owner or an unsupported current mapping
stop generation for explicit review. Procurement-only `supplied_form` metadata,
synonyms, matching labels and shared external identifiers do not establish this
identity.

This is candidate preservation, not scientific approval. The regenerated row
has an empty validation stamp. MIM's separate native publication review retains
the complete original row, provenance and historical stamps and decides the
actual canonical action. Ordinary release review separately retains or resolves
each SUPPORTED/WITHHOLD decision. The four observed rows motivating this fix
were WITHHOLD; restoring their presence does not remove those holds.

CAS assertions can coexist with a curated kgmicrobe identity without being
competing kgmicrobe namespaces. Conflicts between `kgmicrobe.compound:` and
`kgmicrobe.ingredient:`, numeric MIM suffixes used as registry slugs, ambiguous
owners and malformed canonical rows remain refused. The explicit #1189 local
registry retirement proposal cannot retire a CAS row.

Regression fixtures retain the exact four adopted owner files and extracted old
rows, with acquisition hashes in
`tests/resources/cas_preservation1192/ORIGIN.json`. They are scientific evidence
inputs to tests, not a new reviewed release or a complete mint registry.
