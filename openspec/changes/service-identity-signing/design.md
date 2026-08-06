# Design

## Context

Verified by inspection 2026-08-06; re-verify before implementing.

- `provisioning/compute/service/.../settings.toml`: `storefront_admin_key` is
  "Dual purpose: signs the outbound lease-watchdog callback to the storefront, and gates
  every inbound request (the storefront presents it as X-Admin-Key)."
- `middleware/auth.py` compares the presented header to the configured key with
  `secrets.compare_digest`. There is no caller identity beyond "holds the secret."
- `kit/identity` exposes an `IdentityVerifier` protocol (`name`,
  `verify_signature(identity, message, proof)`), a registry rejecting duplicate scheme
  registration, and an `Identity` model of `scheme` + `identifier`. Its docstring
  anticipates non-wallet schemes: DIDs, OIDC `sub` claims, "any other scheme-defined
  identifier."
- `Eip191Verifier.verify_signature` calls `Account.recover_message` and compares the
  recovered value to `identity.identifier`. That recovered value is an **address**, not
  a public key: an address is the last 20 bytes of the keccak-256 hash of the public
  key, and the derivation is one-way. Verification is pure ecrecover — offline, no RPC,
  no chain configuration. `kit/identity` depends only on `eth-account` and `pydantic`.
- `core_storefront.auth.verify_signed_identity` already parses `X-Signature` and
  `X-Timestamp`, enforces `DEFAULT_MAX_TIMESTAMP_SKEW`, resolves the verifier by scheme,
  and verifies over a canonical (operation, resource_id, timestamp) message. Every buyer
  request uses it.
- The storefront already configures sites through `[capacity.sites]`, so the registry
  extends an existing shape rather than introducing a new configuration channel.

## Goals / Non-Goals

**Goals:** no party holds material that lets it sign as another; rotation without
downtime; a site identity that is also a wallet.

**Non-Goals:** collateral, admin site management, many-to-many ownership, a second
scheme, buyer-side changes.

## Decisions

### Reuse `verify_signed_identity`, do not write a second signed-request format

The buyer path already solves canonical message construction, replay bounding, and
scheme dispatch, and it is exercised on every buyer request in production. A separate
service-to-service format would be a second thing to get right, a second thing to
review, and a second place for a skew or canonicalization bug to hide.

Whether the (operation, resource_id) pairing transfers unchanged needs checking against
the real callback and admin surfaces rather than assuming — a projection poll or a
capacity-release callback may not have a natural `resource_id`. If it does not, the
right move is extending the canonicalization once, not forking it.

### `eip191`, chosen for where it leads rather than for reuse

A plain Ed25519 scheme would be cleaner in isolation: no chain semantics, no address
derivation, no wallet vocabulary on an infrastructure boundary. It was rejected, and the
reason is not that the eip191 verifier already exists.

Pairing a site identity with a wallet is what makes site-owner collateral expressible as
a registration prerequisite without a second identity mapping — the address that signs
requests is the address that can hold a stake. Under a bare signing key, collateral would
need a wallet bound *to* the key, which is a second mapping that can drift, and drifting
is exactly what an identity binding must not do.

The objection that this drags chain dependencies into infrastructure does not hold:
verification is ecrecover, entirely local.

### The registry holds an `Identity`, not an address or a public key

Three candidate field shapes were considered and the distinction matters enough to
record, because two of them are subtly wrong.

`wallet_address` is correct for eip191 and wrong as a contract: it names one scheme's
identifier form in a registry meant to outlive that scheme.

`public_key` is scheme-neutral but **factually wrong for eip191**: an address is a hash
of a public key, not the key, and the recovery path yields the address. A field named
`public_key` would either hold something that is not one, or hold something the verifier
cannot compare against.

`Identity(scheme, identifier)` is scheme-neutral *and* correct, and it is already the
repository's vocabulary for exactly this. The registry entry is
`(site_id, url, identity)`.

### The registry is an interface, config-backed for now

Site management moves to storefront admin later. If callers read configuration directly,
that move is a rewrite; if they read a registry that happens to be configuration-backed,
it is a second implementation behind an unchanged interface.

This is the same lesson as `capacity-shape-envelope`'s predicate interface, and it costs
nothing now.

### Cardinality follows the topology instead of fighting it

The shared secret forced two relationships with different cardinality through one
mechanism. Asymmetric identity lets each be what it is: a storefront holds many site
identities, because it aggregates many sites; an authority holds one storefront
identity, because it serves one storefront.

This is worth stating because "a registry of identities" reads like multi-tenancy. It is
not — the many side is sites-per-storefront, which already exists and is unchanged.

### Rotation is overlapping acceptance, not a coordinated flip

A verifier accepts a set of counterparty identities rather than one, so a new key can be
introduced, adopted, and the old one retired in three independent steps. Under the shared
secret, both sides had to change in the same instant, which is why rotation has never
been operationally possible.

### Retire the shared key by freeze-then-redirect

`storefront_admin_key` stops being the authentication primitive but is not deleted in
the same change, matching the pattern the POOLS campaign uses. Removing it abruptly makes
rollback a coordinated redeploy of two services rather than a code revert.

## Risks / Trade-offs

- **[Private key material is mishandled in deployment]** → The sensitive surface shrinks
  — one secret per service, identities in ordinary configuration — but private keys are
  now per-service rather than shared, which the infrastructure repository must generate
  and distribute. Placement rules belong in `DEPLOYMENT_AND_CONFIG.md`, not in this
  change's documents.
- **[Canonicalization does not transfer to every service call]** → Named above; check
  before assuming, extend once rather than forking.
- **[Wallet vocabulary confuses an infrastructure boundary]** → Accepted, and the reason
  is recorded so a future reader does not "simplify" it back to a bare key and silently
  remove the collateral path.
- **[Signature verification cost per request]** → ecrecover is local and cheap, but it is
  not free and now runs on every inter-service call including projection polls. Worth
  measuring rather than assuming, and an argument for replacing polling with push
  independently of this change.
- **[Both directions are signed but the middleware still accepts the shared key]** →
  Intended during the freeze window, and the window must be closed deliberately rather
  than left open indefinitely.

## Migration Plan

1. Registry interface and identity configuration, both directions, unused.
2. Sign and verify storefront-to-authority calls; shared key still accepted.
3. Sign and verify authority-to-storefront calls; shared key still accepted.
4. Overlapping-identity rotation.
5. Freeze the shared key as an authentication primitive.

Steps 2 and 3 are independently deployable because the shared key remains accepted
throughout. Step 5 is the boundary: after it, an unsigned caller is refused.

## Open Questions

- **Does the service-to-service canonical message need an operation vocabulary distinct
  from the buyer path's?** Buyer operations are named per endpoint; service calls may
  want coarser or finer granularity. Deferrable — it changes the message construction,
  not the requirement that calls be signed and replay-bounded.
- **Should a site's identity be verifiable against on-chain state at registration?**
  That is the collateral path, and it is deliberately not built here. Deferrable, and
  this change is what makes it possible without a second mapping.
