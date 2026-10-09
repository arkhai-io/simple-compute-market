# Payments wire contract source

`payments.schema.json` and `test-vectors/payments.json` are the Arkhai payments
service's published wire contract: its JSON Schema and conformance test
vectors. They are identified by content, not by where they were obtained.

- Published schema SHA-256: `a978f81926aa268c41a3989339bf1ca90372c13e90b97e468f7da04a5a66c454`
- Vendored schema SHA-256: `e0bf3dd2e41815082c8e939bd8cf02578d17cf1c5a64da11f05461555da20010`
- Test-vector SHA-256: `8d39d794dde2500738b7ceb3ac1729e4c68a69cca7a35a12cbf21edc1a8b7e1e`

The vendored schema differs from the published one only in its `$id`, which is
the neutral `urn:arkhai:payments:wire-contract`. The vectors are byte-identical
to the published ones.

Run `python scripts/generate_models.py` from this package to regenerate the
Pydantic models from the vendored schema. Updating the contract means replacing
both vendored files with a newer publication, setting the schema's `$id` back to
the neutral URN, recording all three hashes above, and regenerating the models.
Normal builds and client imports do not access the payments service or the
network.
