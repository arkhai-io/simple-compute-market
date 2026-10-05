# API Credits Architecture

The [normative contract](spec.md) defines API-credit behavior. This document explains why market authorization, bearer usage identity, quota admission, and online request gating remain separate responsibilities.

## Market shape

API credits are prepaid finite units for a named service. A listing advertises a unit rate and available quota. The buyer negotiates a quantity, settles the accepted Agreement, and receives either a new bearer key funded with that quantity or a top-up to an existing key.

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

Only the storefront's selected seller stage verifies settlement sources and
owns delivery authorization. The credits service receives the existing
operator-authenticated issuance command, not raw receipts, mechanism IDs or
escrow/obligation references. It validates negotiation-derived fulfillment
identity, canonical owner, service/resource, quantity, key target and immutable
request digest, then repeats authoritative key and quota checks. Possession of
the operator credential is the issuance trust boundary; a second token or
mechanism-verification protocol is not introduced.

The storefront's quota snapshot is advisory. It can prevent obviously infeasible negotiation and may place a temporary hold, but issuance must commit a live hold or reserve again at the authority. This repeats the same principle used by physical capacity: publication and negotiation views are not admission locks.

## Commercial and usage identity

A canonical marketplace principal authorizes a market purchase or top-up. It
may be an Ed25519 identity in a wallet-free payment deployment or an EVM identity
for Alkahest. A bearer secret authorizes API use. These are deliberately
different identities:

- marketplace signatures prove who may negotiate and authorize the purchase;
- canonical principal ownership determines who may top up an existing key;
- the bearer secret admits an online request without a market signature per call.

An active unowned key can receive an open top-up, while an owned key can be
topped up only by its canonical marketplace owner. The credits service repeats
ownership and status checks during issuance because negotiation views may be
stale and operator controls may bypass ordinary policy.

## Idempotency boundaries

Every grant uses the same deterministic fulfillment identity derived from its
negotiation ID, irrespective of settlement mechanism. Negotiation and fulfillment
IDs are unique in `credit_grants`. The immutable canonical request digest binds
owner, service/resource, quantity and key target; changed reuse conflicts before
quota, key or balance mutation. An operational quota-hold reference is not part
of that digest: an expired hold can be replaced after authoritative rechecking
without changing purchase intent. Old grant adoption and old issuance payloads
are not accepted. A newly issued but unused key may rotate its secret on an
authorized retry; after use, retries do not reveal a bearer secret.

Online consumption has an independent idempotency boundary scoped to the key and caller-supplied consumption key. This makes middleware retries safe without coupling request admission to settlement identity.

## Secret handling

The credits service stores only a hash of the bearer secret. The storefront persists buyer credentials needed for retrieval, while public fulfillment results omit the secret. A secret is formatted with public key identity plus random secret material so middleware can route verification without storing a plaintext secret index.

A newly issued secret is not guaranteed to be returned exactly once: an unused-key retry may rotate it, and the owning storefront may return persisted credentials through its authenticated status flow. Architecture and clients must therefore distinguish secret confidentiality from one-time-display semantics.

## Middleware role

Python, TypeScript, and Rust gates implement the same observable verification and consumption protocol. A gate parses credentials, asks the service to verify and consume a fixed configured amount, and maps authority results to HTTP admission outcomes.

Caching and batching reduce service calls but do not create another balance authority. Cached verification may delay observation of revocation for its configured TTL. Optional batching uses an optimistic local estimate and flushes to the service; authoritative balance and idempotency remain server-side.

## Failure and compensation

Common issuance consumes verified validated purchase facts and a retry policy
supplied by the selected stage. Alkahest preparation verifies the source once
before reserving the delivery job; delivery reads the saved matching evidence
instead of repeating preparation inside terminal failure handling. That stage
owns signed issuance publication, on-chain attestation and compensation. If
attestation fails after issuance, it attempts balance adjustment and revokes a
key created solely for that operation. Compensation is best-effort recovery
across authorities, not an atomic chain/database transaction.

Failure/rollback context names `settlement_ref` and `negotiation_id`. Capacity
release retains the exact hold identity and correlates by negotiation, not a
payment transaction disguised as an escrow. Genuine Alkahest rows, public
legacy DTOs and the site ledger's existing correlation API retain escrow names.

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

## Payment composition and recovery

Buyer and seller compose immutable role tables for Alkahest and
`arkhai.payments.v1`. Registration/readiness admits fresh options only when a
matching role entry exists; accepted work dispatches from the exact Agreement,
not current priority, escrow presence or configuration keys. Alkahest and
`arkhai.payments.v1` are peer registrations. The payment path uses Ed25519 marketplace identity and owner-scoped payment credentials without constructing a wallet or chain client. Acceptance stores exact Agreement bytes and the seller-derived mandate in shared negotiation `settlement_data`.

Standalone `market credits negotiate` uses that buyer table for selection
preparation, accepted artifacts, price prerequisites and proposal construction.
Payment prices remain in their advertised asset units and the entry supplies
`payer_account`; no wallet or chain is needed. The entry projects advertised
rate fields into the scalar policy's opening shape; the policy still determines
the bid. The Alkahest entry retains
chain/token constraints, address and policy guards, token-decimal scaling of
explicit prices, and the existing escrow proposal shape. Derived prices use only
the selected option and are already in base units. Interrupted rounds recover
recorded selection, provision terms and scaled bounds, not current admission.

The buyer validates and approves the mandate, polls its deterministic transaction ID, then calls seller settlement with only the negotiation ID. The seller reloads accepted state and verifies the matching signed receipt before credit issuance. A pending transaction returns retryable pending without a grant.

`api_credit_settlement_evidence` stores negotiation-keyed
`api_credits.settlement-evidence.v1`: exact Agreement digest, mechanism, established
source reference and validated delivery inputs. Verified status/source/delivery
is immutable. `api_credit_issuance_progress` separately records delivery phases;
signed issuance evidence proves the later grant, and owner-only private results
retain credentials. A payment creates no escrow progress row.

Repeated settlement returns completed state or re-drives nonterminal issuance.
Recovery revalidates the stored signed receipt against the exact accepted
Agreement/mandate/reference without replacing verified evidence with pending or
requiring another payment poll. Authority lookup and immutable grant digests
reconcile acknowledgement loss under one fulfillment identity. Buyer credentials
remain in the private result channel, not public settlement evidence. Ledger,
fees, hold release, disputes and `reverse` remain payments-service operations.

### Explicit database reset

Quiesce settlement, issuance and recovery before resetting incompatible
disposable storefront and credits-authority databases. Confirm target ownership;
use new owned SQLite paths or delete only the confirmed disposable databases,
bootstrap current migrations, republish and renegotiate. Do not adopt historical
payment escrow rows or grant aliases. Startup rejects missing/current-marker
schema drift and old grant shapes instead of copying/translating them. Rebuild
`.dist` and reinit both producer and authority consumers together.
`docs/attachments/apicredits-dispatch/first_use.py` creates and cleans fresh
file-backed databases with controlled payment I/O and real typed credits HTTP;
it does not qualify a live payment ledger.
