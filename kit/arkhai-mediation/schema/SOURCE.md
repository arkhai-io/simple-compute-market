# Published mediation baseline

- Producer: https://github.com/arkhai-io/arkhai-payments
- Revision: `da93a544ab106be19d4d52a866f1887d8dee3447` (main); paired payments baseline `3be127e4`.
- Upstream files: `schema/mediation.schema.json` and `test-vectors/mediation.json`.
- Exact copies and SHA-256 metadata ship inside `market_arkhai_mediation/contract_data/`.
  `contract.resource_bytes`, `schema`, `vectors`, `publication`, and `validate` work from installed wheels.
- `models.py` is generated from the transport definitions' transitive closure in the canonical schema.
  Mapping and compatibility advertisements remain validated schema data, not payment-specific logic in this kit.
- Refresh the two resources together from a published revision, update `publication.json`,
  run `make generate-models`, then `make test` and the repository packaging gate.
- The published revision defines delivery-end claims, per-scheme marketplace identities/proofs,
  concurrence, ruling basis, respondent reads and both signature-scheme vectors.
  It removes `exceptional_end` and `buyer_end`; neither is emitted by the adapter.
- Publication does not qualify a hosted deployment or enable setup-bearing presets.
  The hosted service must first deploy this coherent revision; no live evidence is claimed.
- The fixture seed is public deterministic development material from the vectors; never deploy it.
