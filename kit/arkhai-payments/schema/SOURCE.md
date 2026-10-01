# Payments wire contract source

`payments.schema.json` and `test-vectors/payments.json` are copied from
[`arkhai-io/arkhai-payments`](https://github.com/arkhai-io/arkhai-payments)
at source commit `f16b1ebdca4e0977dae45bebe7b57cce9c1a08c2`.

- Schema SHA-256: `a978f81926aa268c41a3989339bf1ca90372c13e90b97e468f7da04a5a66c454`
- Test-vector SHA-256: `8d39d794dde2500738b7ceb3ac1729e4c68a69cca7a35a12cbf21edc1a8b7e1e`
- Schema source: `schema/payments.schema.json`
- Vector source: `test-vectors/payments.json`

Run `python scripts/generate_models.py` from this package to regenerate the
Pydantic models from the vendored schema. Updating the upstream contract means
selecting and recording a new source commit, replacing both vendored files, and
regenerating the models; normal builds and client imports do not access the
payments repository or the network.
