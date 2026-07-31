# API Credits Architecture

The [normative contract](spec.md) defines API-credit behavior. This document explains why market authorization, bearer usage identity, quota admission, and online request gating remain separate responsibilities.

## Market shape

API credits are prepaid finite units for a named service. A listing advertises a unit rate and available quota. The buyer negotiates a quantity, settles the resulting obligation, and receives either a new bearer key funded with that quantity or a top-up to an existing key.

```text
quota-backed listing
      ↓ quantity-priced negotiation
verified settlement
      ↓ idempotent issuance
API key balance
      ↓ online consumption
admit or reject request
```

Credits are not a replenishing liability limit. Issuance commits finite quota through an open-ended reservation; consuming a credit reduces the buyer's balance but does not make that unit sellable again.

## Authority boundaries

The API-credits domain owns versioned listing, provision-intent, pricing, terms, and result meaning. The storefront composes publication, seller policy, settlement verification, and fulfillment jobs. The credits service is authoritative for API keys, hashed secrets, balances, grants, consumption idempotency, and quota-ledger mutations.

The storefront's quota snapshot is advisory. It can prevent obviously infeasible negotiation and may place a temporary hold, but issuance must commit a live hold or reserve again at the authority. This repeats the same principle used by physical capacity: publication and negotiation views are not admission locks.

## Commercial and usage identity

A buyer wallet authorizes a market purchase or top-up. A bearer secret authorizes API use. These are deliberately different identities:

- wallet signatures prove who may negotiate and fund the purchase;
- key ownership determines who may top up an already owned key;
- the bearer secret admits an online request without requiring a wallet signature per call.

An active unowned key can receive an open top-up, while a wallet-owned key can be topped up only by its owner. The credits service repeats ownership and status checks during issuance because negotiation views may be stale and operator controls may bypass ordinary policy.

## Idempotency boundaries

Settlement `escrow_uid` identifies one credit grant. Retrying issuance under that identity must not reserve quota or increase balance twice. A newly issued but unused key may rotate its secret on retry, invalidating the earlier secret; after use, retries do not reveal a bearer secret.

Online consumption has an independent idempotency boundary scoped to the key and caller-supplied consumption key. This makes middleware retries safe without coupling request admission to settlement identity.

## Secret handling

The credits service stores only a hash of the bearer secret. The storefront persists buyer credentials needed for retrieval, while public fulfillment results omit the secret. A secret is formatted with public key identity plus random secret material so middleware can route verification without storing a plaintext secret index.

A newly issued secret is not guaranteed to be returned exactly once: an unused-key retry may rotate it, and the owning storefront may return persisted credentials through its authenticated status flow. Architecture and clients must therefore distinguish secret confidentiality from one-time-display semantics.

## Middleware role

Python, TypeScript, and Rust gates implement the same observable verification and consumption protocol. A gate parses credentials, asks the service to verify and consume a fixed configured amount, and maps authority results to HTTP admission outcomes.

Caching and batching reduce service calls but do not create another balance authority. Cached verification may delay observation of revocation for its configured TTL. Optional batching uses an optimistic local estimate and flushes to the service; authoritative balance and idempotency remain server-side.

## Failure and compensation

Settlement evidence is verified before issuance. If downstream on-chain fulfillment fails after credits were issued, the storefront attempts a compensating balance adjustment and revokes a key created solely for the failed operation. Compensation is best-effort recovery after a split authority transition, not proof that chain and database updates are one atomic transaction.

## Implementation composition

The storefront talks to the credits service through one domain-owned
HTTP client, `CreditsServiceClient` (`domains/apicredits/settlement/credits_client.py`),
constructed once at the storefront's composition boundary
(`apicredits_storefront/services/credits_service_client.py`'s
`get_credits_service_client()`) and reused by every settlement and
key-lookup caller, rather than each operation constructing its own
transient client. This mirrors the `kit/site` + `kit/site-client` split
used for the separate operator-facing capacity-administration surface
(`SiteCapacityAdminClient`): a typed client package, independently
versioned request/response models, and centralized authentication,
timeout, and error-translation behavior.

The service tracks its own schema evolution in a `schema_migrations`
table, applied in-process at application startup before the service is
ready to serve requests. The service has no separate deployment step
(no Kubernetes init container, no standalone migration CLI) to run
migrations ahead of the application process — in-process startup
migration is the current, non-provisional mechanism for the current
deployment topology, not a placeholder for a future one.

Every API-credit package resolves its internal dependencies from built
wheels, not repository-relative editable paths or `pythonpath`
fallbacks — see `docs/development/ARCHITECTURE.md#wheel-based-development`.

## Current limits

Current metering charges one fixed configured amount per admitted request; route-specific or variable-cost metering is not established. Possession-challenge protocols for existing keys are not implemented. Verification caching means revocation is not globally instantaneous, and optional batching must not be described as a strict zero-overdraft guarantee.

API credits intentionally has no compute-provisioning capability. A non-physical market does not acquire VM, lease-executor, or fulfillment-scheduler dependencies merely to conform to physical delivery architecture.

## Related contracts

- [Market composition](../market-composition/spec.md)
- [Negotiation protocol](../negotiation-protocol/spec.md)
- [Settlement servicing](../settlement-servicing/spec.md)
- [Site capacity](../site-capacity/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
