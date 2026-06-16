# arkhai-apitokens-middleware (Rust)

Seller-side gating middleware for the API-tokens domain — the Rust
sibling of the Python reference (`../python`) and the TypeScript port
(`../typescript`). It extracts the bearer key from the `Authorization`
header, verifies it against the tokens service (short-TTL cache), meters
each request by consuming credits (synchronously near exhaustion,
optionally batched above a low-balance threshold), and maps a drained
key to a 402 whose body carries a `purchase` pointer (the re-purchase
loop). All verification and accounting authority stays in the service.

The behavioral contract — status codes, machine-readable bodies, and
per-step service-call counts — is shared with the Python and TypeScript
middlewares and pinned by `../conformance/session.json`.

## Layout

- `src/config.rs` — `GateConfig` / `PurchasePointer` (+ `from_env`).
- `src/client.rs` — `TokensClient` over `reqwest`, and the `TokensApi`
  trait the gate depends on.
- `src/gate.rs` — framework-neutral `TokenGate` (verify cache, balance
  estimate, batched-charge accumulator), `parse_bearer`,
  `key_id_from_secret`, plus unit tests for the batched-charge path.
- `src/tower_layer.rs` — the tower/axum binding (`TokenGateLayer`),
  operating on `axum::body::Body` so it drops into any `Router`.

## Develop

```sh
cargo test       # unit + adapter + conformance suites
cargo clippy --all-targets
```

`tests/conformance.rs` is the reference harness: `tests/common/mod.rs`
stands up an in-process scripted tokens service with `axum`, and the
test drives the **real** `reqwest` client against it, replaying
`../conformance/session.json` step for step and asserting the decision
plus the per-step verify/consume call counts — mirroring the Python
runner at the HTTP layer. `tests/adapter.rs` exercises the tower layer
end to end (valid key → app, exhausted key → 402, excluded path, missing
key → 401).
