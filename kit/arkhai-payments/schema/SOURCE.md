# Payments wire contract source

`payments.schema.json` and `test-vectors/payments.json` are the Arkhai payments
service's published wire contract: its JSON Schema and conformance test
vectors. They are identified by content, not by where they were obtained.

- Published schema SHA-256: `da4ddc84e89b2144996e86f17dc260642d29943a2ed606c05eb63712b91da1db`
- Vendored schema SHA-256: `444f2a635e02af6e428053cad2bf83891244fd4567d030d7e6d67c42a457fd2a`
- Test-vector SHA-256: `e1a26e4c3fcde9724e5ec9bc606d20bebe49404554eca69a4cb78e4146215631`

The vendored schema differs from the published one only in its `$id`, which is
the neutral `urn:arkhai:payments:wire-contract`. The vectors are byte-identical
to the published ones.

Run `python scripts/generate_models.py` from this package to regenerate the
Pydantic models from the vendored schema. Updating the contract means replacing
both vendored files with a newer publication, setting the schema's `$id` back to
the neutral URN, recording all three hashes above, and regenerating the models.
Normal builds and client imports do not access the payments service or the
network.
