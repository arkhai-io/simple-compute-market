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

## Seller notice

`SellerLifecycleClient` and `SyncSellerLifecycleClient` wrap an async or sync
storefront client's `authenticated_request` transport. They use administrator
signatures and the shared lifecycle route contracts for `notice(negotiation_id,
operation_key=..., at=...)`, `read(negotiation_id)` and bounded `list(...)`.
Keep the operation key and optional requested Unix second unchanged on retry.
The accepted Agreement supplies payee rights and affected rate parts; today's
listing supplies neither. An accepted outcome contains verified controlling
stop records with the authority's effective time. Unknown remains unknown until
read/retry resolves it. Read exposes those records in `authority.parts`, and
seller list exposes the same per-part observations in each summary.

Both compute storefronts expose `deals preempt NEGOTIATION_ID --operation-key KEY
[--at UNIX_SECOND] [--storefront-url URL]` using their existing administrator
configuration. The command prints the authority outcome unchanged. It installs
no local stop timer. An on-demand refusal names `delivery_end` only as the path
for actual seller non-delivery; it does not file a case.
