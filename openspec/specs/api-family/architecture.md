# API Family Architecture

The [normative contract](spec.md) defines what the api family's packages own
and guarantee. This document explains how a domain selling prepaid bearer
access composes them, and why the family is cut where it is.

## Conceptual model

A domain of the api family sells access to a named service: a listing over a
quota resource, a negotiated quantity, a settled Agreement, and an issued or
topped-up bearer key that a gate admits requests against. Everything in that
flow that does not depend on what the service is lives once, in the family; a
domain contributes its listing schema, its label, and a handful of values.

`domains/api` (`arkhai_api`) is the vocabulary: the purchase shape and key
disposition, the issuance request and result, the fulfillment identity and
request digest, the signed secret-free issuance evidence and portable
fulfillment reference, and the issuance label those are spelled under. It
depends on pydantic and the identity kit alone, so it names no sibling's label;
each domain passes its own.

The family's kit is ten distributions beneath it, each installed only by the
side that needs it. Where they sit and why each is split is repository-wide
placement, in [Family kits](../../../docs/development/ARCHITECTURE.md#family-kits).

| Distribution | Installed by |
|---|---|
| `domains/api/contracts` | every side: the authority, the storefront, and the buyer through its domain's codecs |
| `domains/api/client` | the storefront, to call the authority |
| `domains/api/authority` | a domain's service root |
| `domains/api/selling` | a domain's storefront |
| `domains/api/selling-alkahest`, `selling-arkhai-payments` | a storefront whose seller table composes that mechanism |
| `domains/api/buying` | a domain's buyer plugin |
| `domains/api/buying-alkahest`, `buying-arkhai-payments` | a buyer plugin whose stage table composes that mechanism |
| `domains/api/gate` | an application that admits requests with a bearer key |

The negotiation and delivery carriers — message, terms, materialization,
receipt, and result — extend core schemas, so they cannot be vocabulary, and a
domain's codecs bind them to its kind literal. They live in `contracts`
(`arkhai_api_contracts.carriers`) rather than in `selling` because the buyer
plugin installs those codecs: placed in `selling`, they would bring the
storefront machinery onto every buyer's machine.

## Contribution bundles

A family kit never discovers or imports its domains, so each side takes one
frozen bundle from its composition root. `SellingContributions`
(`arkhai_api_selling.contributions`) is filled by a storefront and
`BuyingContributions` (`arkhai_api_buying.contributions`) by a buyer plugin.
Each lives in the library whose types it is written against, so neither is
typed as `Any` and neither is vocabulary. Every optional field's absence is
valid, so a domain supplies no placeholder.

| Field | API credits supplies |
|---|---|
| `label` | `api-credits`, with the grant prefix `api-credit-fulfillment.v1` |
| `kind` | `api_credits.v1` |
| `offering_mode`, `contribution_id`, `table_prefix` | `api_credits`, `apicredits`, `api_credit` |
| `listing_schema`, `publication_mapping` | the named-service listing over its quota resource |
| `issuance_projection` | service from `service_name`, resource from `resource_id`, endpoint from `base_url` |
| `publication_guards`, `acceptance_hook`, `public_result_extension` | none |
| `consumption_rule` | a fixed amount per request, configured at the gate |
| `refusal_noun` | `API-credit` |
| buying `schema_id`, `command`, `noun` | `api_credits`, `credits`, `API-credit` |
| buying `rendering` | the service name, description, and OpenAPI and base URLs |

The envelope kinds, the opening guard's name, and the private-credentials
reference are spelled from the kind's stem and the table prefix, which
reproduces the names API credits' recorded tables and envelopes carry. The
buyer's resource filters are the registry schema's, so the buying bundle
carries no filter vocabulary of its own.

A second domain would supply the same fields: its label and kind, a listing
schema and mapping from a quota resource, a projection naming the service and
resource it issues, and any publication guard, acceptance hook, or public
extension its product needs. Its values are its own design's.

## The accepted listing and the issuance projection

The projection maps a listing's resource to an `IssuanceSubject` — the
service identity and quota resource the authority's issuance command digests,
and an endpoint returned beside the key and never digested. `selling` adds the
quantity and key target from the accepted terms, which are the vocabulary's
purchase shape and the same for every domain. Publication uses the same
projection without terms, so `selling` reads a listing only through it and
names no domain field itself.

What a settled purchase issues must be what the buyer accepted. Before the
negotiation runtime records success, `selling` copies the listing's durable
binding to the thread and writes the listing, narrowed to the listing schema,
to core's per-negotiation artifact table under the `listing` slot
(`record_accepted_listing` in `arkhai_api_selling.quota_listing`). Settlement
verifies and issues from that record, so a listing republished or edited in
place after acceptance still issues the service and endpoint the buyer
accepted. A bound thread with no record, or one asked for another listing, is
refused. The record uses the existing artifact table because a new table would
change the schema baseline, and the Agreement's listing hash cannot stand in
for it: it covers the stored row's status and timestamps, which change after
acceptance.

## Negotiation, publication, and lifecycle

`selling` owns negotiation, publication, and the storefront's lifecycle, and
reads every domain-specific choice from the bundle:

- **Guards.** The opening guard registers under a name spelled from the kind's
  stem (`api_credits_round_zero_guard`); the quota and key guards keep their
  family names (`credit_quota_guard`, `key_owned_by_buyer_principal`), so a
  configured chain resolves as before. Refusal codes are the family's, shared
  with the authority's issuance re-check, except the one that names what is
  sold, which the table prefix spells (`api_credit_quantity_unavailable`).
  Messages name it through `refusal_noun`.
- **Configuration.** `selling` reads no configuration, so a refusal for a
  missing pricing floor or capacity site names the key the storefront passed
  in its own spelling.
- **Escrow handling.** `selling` knows no mechanism, so escrow
  canonicalization at opening, the `EscrowAcceptance` that offers and accepts
  an escrow, and the mechanism a listing's accepted escrows publish under are
  injected by the escrow stage.
- **Publication.** Publication guards run wherever a listing publishes:
  creation, resume, a reconciliation reopen, and a registry divergence repair.
  Reconciliation pages every listing by the core store's keyset over
  `(created_at, listing_id)`, which no write changes, so a pass visits each
  listing once.
- **Opening.** A thread takes its listing's binding when it opens. The opening
  is one transaction: the negotiation runtime's `open_negotiation` hook hands
  the thread, its opening message, and the binding to `selling`, which writes
  them with the purchase terms through the core client in one commit.
- **Lifecycle.** A mechanism's timer loops (`ContributedLoop`) and startup
  steps are contributed by its stage and registered by the storefront, so
  `selling`'s lifecycle names no mechanism.

## Service roots and the capacity profile

`authority` is a library: the key service, the prepaid ledger, quota as
capacity over the site and resource-pool kits, the models and in-process
migration chain, framework-free route services, the adapter from `contracts`'
plain route declarations to the site kit's route contracts
(`site_route_contracts`), and the runtime initialization that seeds the
profile's pool. It builds no application. Creating the app, installing the
site kit's authentication over the adapted declarations, and mounting routers
are composition, so each domain has its own service root; two domains never
share a process, so a shared family service would buy nothing and would need
a plugin group to reach its domains.

A root passes the authority an `AuthorityConfig` holding its issuance label
and one validated, immutable `CapacityProfile` (`arkhai_api_authority.profile`):
the offering mode, the seeded pool's provider, identity, and label, its
deliverable and advertisable modes, and its backing. The authority reads every
such value from the profile, so two domains' deployments differ only in what
their roots pass. The profile carries no resource type: the ledger does not
filter reservations by type, and a resource's type is what its registration
states. At startup the root runs the migration chain, then `initialize` seeds
the profile's pool when absent and refuses any stored pool without valid
declarations.

## Mechanism stages

Each selling-side mechanism stage takes every collaborator as a constructor
argument — the bundle, the capacity runtime, providers of the storefront's
settlement composition and persistence, its chain configuration and wallet,
its stage-event log — and supplies its negotiation step, loops, startup steps,
health checks, configuration checks, and servicing. A storefront's seller table
selects the stages; the storefront then registers exactly what those stages
contribute, so an Alkahest-only storefront registers no payment reconciliation
and a payments-only one runs no escrow backfill.

The Alkahest stage's attestation is a string obligation the chain does not
deduplicate, so the stage uses the settlement runtime's journal: the
submission is recorded before it is submitted, and the attestation's reference
before the obligation completes. An attempt that finds
a recorded submission with no reference, or an attestation whose outcome is
lost, cannot tell whether the chain holds one, so it parks the obligation for
an operator; the delivered credential is stored privately before the park
commits, and the grant stands. Only a definite refusal or non-submission
withdraws the submission and compensates the grant. Issuance whose outcome is
unknown is a `deferred` outcome, re-driven under the same fulfillment identity
with its hold kept. The rule is
[A fulfillment submission with an unknown outcome is never repeated](../settlement-servicing/spec.md#requirement-a-fulfillment-submission-with-an-unknown-outcome-is-never-repeated).

On the buyer side, every step that differs by mechanism is a method of the
stage the selected or accepted option names (`BuyerStage` in
`arkhai_api_buying.stages`): selection and negotiation pricing, the acceptance
check, a deal's enrichment, a listing's settlement rows, the buy session, resume
from a run log, the command-line options it reads, and the per-chain
configuration the negotiation guards read. A command's options are the union of
its stages' and reach only the stages. At most one stage supplies the escrow
codec core's negotiation client carries. A delivered bearer key is kept in the
buyer's private credential store (`arkhai_api_buying.credentials`), and the run
log records only a non-secret reference to it.

## The gate

`domains/api/gate` (`arkhai_api_gate`) is embedded in third-party applications,
so its runtime dependency is httpx alone, with the identity kit as an optional
extra for signed requests. It therefore keeps a local spelling of the verify
and consume routes it calls; a development-only parity test
(`domains/api/gate/tests/test_contract_parity.py`) holds that spelling equal to
`contracts`' declarations, and the published gate gains no dependency from it.

Its verify cache has three invariants:

- a cached verification authorizes only the exact secret that earned it,
  compared by fingerprint, because the key ID is public;
- a refused secret other than the cached one does not evict the cached
  credential;
- verifications install in the order they started, by ticket, so a late answer
  never replaces a newer one.

The Python, TypeScript, and Rust gates implement all three. The shared
conformance trace under `domains/apicredits/middleware/conformance/` pins the
first two for every gate, and each gate's own tests pin the ordering.

## Current limits

- The family's composability claim is scoped to prepaid bearer access. The
  purchase shape buys a quantity of credits, and `authority` keeps issuance and
  the prepaid ledger together. Splitting it into a ledger-free issuance half is
  deferred until a sibling domain sells access without a prepaid balance — by
  subscription, invoice, or rate limit alone; that domain's proposal is the
  trigger.
- A domain's issuance projection values — which identity enters the digested
  service and whether an endpoint is delivered — are that domain's design's.
  Only API credits composes the kit.
- The authority's migration chain carries API credits' history: its first
  identifier is `20260731_001_apicredits_schema_baseline`, and early steps
  normalize API-credits data such as wallet owners. A new domain's deployment
  starts at the same chain on its own database.
- `selling` depends on the core storefront, and `buying`, `buying-alkahest`,
  and `buying-arkhai-payments` on the core buyer, both role compositions. Each
  edge is an exception row in
  [`ARCHITECTURE.toml`](../../../docs/development/ARCHITECTURE.toml), owned by
  `kit-owned-storefront-auth-and-persistence` for `selling` and
  `kit-owned-buyer-orchestration` for the buying libraries.

## Related contracts

- [API family](spec.md)
- [API credits](../api-credits/spec.md)
- [Market composition](../market-composition/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Settlement configuration](../settlement-configuration/spec.md)
