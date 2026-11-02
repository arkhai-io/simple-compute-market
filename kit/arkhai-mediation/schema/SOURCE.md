# Published mediation baseline

- Producer: https://github.com/arkhai-io/arkhai-payments
- Revision: `b98fed26ef373045124b3e89bf14c7c1552b46bd` (main); paired payments baseline `3be127e4`.
- Upstream files: `schema/mediation.schema.json` and `test-vectors/mediation.json`.
- Exact copies and SHA-256 metadata ship inside `market_arkhai_mediation/contract_data/`.
  `contract.resource_bytes`, `schema`, `vectors`, `publication`, and `validate` work from installed wheels.
- `models.py` is generated from the transport definitions' transitive closure in the canonical schema.
  Mapping and compatibility advertisements remain validated schema data, not payment-specific logic in this kit.
- Refresh the two resources together from a published revision, update `publication.json`,
  run `make generate-models`, then `make test` and the repository packaging gate.
- The baseline retains `exceptional_end` and `buyer_end` exactly as published, including in historical records.
  The lifecycle adapter must not emit either request kind.
- Delivery-end claims, concurrence, ruling basis, respondent reads, their signature vectors,
  and setup-bearing presets are unsupported until a coherent revision is published.
- The fixture seed is public deterministic development material from the vectors; never deploy it.
