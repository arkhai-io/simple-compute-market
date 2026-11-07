# Lifecycle client

`market_deal_lifecycle_client.LifecycleClient` is an async buyer transport for
`commit(CommitMessage)`, `hint(HintMessage)` and `read(negotiation_id)`. The shared
lifecycle route declarations supply the methods, paths and semantic operations.
No payment or dispute request is relayed through the storefront.

Construct it with the accepted buyer's marketplace signer and a pinned
`TrustedIdentitySet` of storefront publishers; use it as an async context manager
or call `aclose()`. An optional envelope capture sink receives exact verified
response bytes and their signed outgoing requests. JSON is canonicalized before
signing and sending. Signed errors are verified before their content is reported;
unsigned, wrong-context, stale, untrusted and tampered responses fail closed.
Transport/HTTP/authentication failures raise `LifecycleClientError`; they are not
an authority's rejection of a lifecycle command. Retry an operation with the same
message operation key. An optional HTTP `request_id` cannot be reused with changed
request content.

First use, with deterministic public development signers and an in-process signed
storefront seam (no accounts, secrets, server or seed required):

```sh
make dist
make -C kit/deal-lifecycle-client reinit
(cd kit/deal-lifecycle-client && uv run --find-links ../../.dist python examples/first_use.py)
```

This exercises peer messages, delivery reads, exact-envelope capture and refused
responses. It is not a deployed lifecycle-route qualification. End-delivery is a
separate canonical method, not an extra field on commit or hint.
