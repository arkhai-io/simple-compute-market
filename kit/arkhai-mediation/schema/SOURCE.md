# Published mediation baseline

- Interface: `arkhai.mediation.v1`; schema identifier: `urn:arkhai:mediation:v1`.
- The exact schema and vector publication is identified by the SHA-256 digests in
  `market_arkhai_mediation/contract_data/publication.json`.
- Upstream artifact paths are `schema/mediation.schema.json` and
  `test-vectors/mediation.json`. Refresh both resources together from one publication.
- Exact copies ship inside `market_arkhai_mediation/contract_data/`.
  `contract.resource_bytes`, `schema`, `vectors`, `publication`, and `validate` work
  from installed wheels.
- `models.py` is generated from the transport definitions’ transitive closure in
  the canonical schema. Mapping and compatibility advertisements remain validated
  schema data, not payment-specific logic in this kit.
- After refreshing the resources and publication digests, run `make generate-models`,
  then `make test` and the repository packaging gate.
- Publication does not qualify a hosted deployment or enable setup-bearing presets.
- Vector signing seeds and the webhook key derived from 32 bytes of `0x09` are public
  deterministic development fixtures; never deploy them on a public network.
