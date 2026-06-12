# API tokens market domain — design + scope

The second market schema domain: **prepaid API credits** sold against a
token-gated service. A listing advertises a service (with an OpenAPI URL
describing what the tokens gate) at a unit price per token; the buyer
specifies a quantity and whether the credits land on a new API key or
top up an existing one; settlement is the existing escrow flow; the
deliverable is a credit grant in a seller-side tokens service, enforced
by drop-in middlewares (Python, TypeScript, Rust) in the gated service.

This is the trigger for every seam parked on "a second schema": the
second buyer schema plugin, the second domain-owned storefront, schema
identity for registries, the build_app invariants, non-per-hour price
scaling, and extraction of the site-authority ledger into a shared
package. `design-remaining-work.md` § 3's *pool-sharing* proof is **not**
claimed by this work — API credits are their own resource domain with
their own site authority, so the M storefronts × N sites topology is
exercised, but one pool selling through two market domains is not.

## Decisions

- **A token is a prepaid credit.** A key carries a balance; the gated
  service's middleware decrements it per request (or per request-cost).
  Quantity is the unit of purchase; price is per token.
- **Quota is capacity-managed through the existing contract.** The
  tokens service hosts a quota ledger behind `/api/v1/capacity/*`
  (`CapacityClient`): the seller configures sellable credit inventory,
  terms acceptance places a TTL hold for the quantity, settlement
  commits it, fulfillment issues the grant. Quota semantics in v1 are
  **sellable inventory** (a finite supply that selling decrements) —
  not an outstanding-liability cap that consumption replenishes; that
  is a later seller-policy upgrade.
- **Middlewares consume online.** Verify + decrement against the tokens
  service, with short-TTL validity caching and batched decrements for
  throughput (batching bounds a small overdraft window — flush
  threshold is the bound; documented per middleware). One source of
  truth; revocation is immediate; middlewares stay thin clients in all
  three languages.
- **Usage identity and market identity are separate concepts**
  (decision recorded below in "Key ownership"; the v1 default is
  wallet-bound top-ups, with ownership as a pluggable scheme-tagged
  claim so the coupling is a default, not a structural assumption).
- **Vocabulary:** the sold asset is an "API token" in listings and
  prose; the consumable count in code/DB/middleware vocabulary is
  **credits/balance** — "token" unqualified is already ERC20 vocabulary
  throughout this codebase, and the payment side of an API-token deal
  *is* an ERC20/native-token escrow, so the deliberate split avoids
  "token" meaning two things in one wire message.
- **Packaging mirrors the VM domain:** `domains/apitokens/` with
  concept modules + `buyer/` (plugin wheel `arkhai-apitokens-buyer`,
  no console script — publishes a `market.buyer_plugins` entry point),
  `storefront/` (`arkhai-apitokens-storefront`, domain-owned
  executable), `service/` (`arkhai-apitokens-service`, the tokens
  service), `middlewares/{python,typescript,rust}` (published as
  pip/npm/crates packages). The registry stays core + a new
  `filter-spec.yaml`.

## The market shape

**Listing.** `offer_resource` (opaque to the registry, schema-typed by
the plugin):

```json
{
  "kind": "api_tokens.v1",
  "service_name": "…",
  "description": "…",
  "openapi_url": "https://api.example.com/openapi.json",
  "base_url": "https://api.example.com"
}
```

`accepted_escrows` carries the unit price as a rate with a new `per`
unit: `{"field": "amount", "per": "token", "value": "<base units>"}`.
The buyer CLI renders `openapi_url` in listing detail so the buyer can
inspect what the tokens gate (fetching/summarizing the spec is a later
nicety; v1 renders the URL).

**Negotiation.** Same round/chain model. The plugin owns *what* is
bought: `--quantity N` and the key disposition
(`--new-key` | `--key-id <id>`), carried in
`ProvisionTerms{kind: "api_tokens.v1", payload: {quantity, key}}` —
fixed at round 0 exactly like VM duration. The policy owns *how it is
paid*: the negotiated scalar amount is `quantity × unit rate`, and the
**per-unit→absolute translation lives in the domain's policy surface**,
not the CLI bodies — this is the non-per-hour trigger that retires the
deferred remainder from the VM domain (the VM plugin's per-hour scaling
moves to the same seam as part of this work). `listed_price` is the
default and needs nothing new: the bound is quantity × advertised rate.
Seller-side guards: a quota guard (inventory-guard analog against the
capacity snapshot: requested quantity ≤ available) and a key guard for
`existing` mode (key exists, is active, and the ownership claim admits
the buyer — reject reasons `key_not_found` / `key_not_owned`).

**Settlement.** Unchanged machinery: scalar escrow for the absolute
amount, RecipientArbiter immediate settlement by default (oracle-gated
opt-in works as-is), claims engine collects (the degenerate
single-collect case). Fulfillment is an issuance job against the tokens
service: commit the quota hold, create the key (new mode) or locate it
(existing mode), write the credit grant. Credentials return to the buyer
through the existing settle-status/run-log channel:
`{key_id, secret?}` — the bearer secret only for new keys, delivered
once. The fulfillment failure policy reuses the storefront's configured
action list with a domain action that revokes partial issuance and
releases the quota hold.

**No lease tail.** Credits do not expire in v1, so committed
allocations carry no `lease_end_utc` and the ledger's expiry/watchdog
machinery is dormant for this domain. Credit expiry, if a seller wants
it later, maps onto lease truncation naturally — that is why the shared
ledger is reused rather than a bespoke quota table.

## Components

**Tokens service (`arkhai-apitokens-service`).** FastAPI + SQLite, the
same shape as the VM provisioning service. Owns:

- `api_keys(key_id, secret_hash, owner_scheme, owner_id, status,
  created_at)` — bearer secrets hashed at rest; `owner_*` is the
  scheme-tagged ownership claim.
- `credit_grants(id, key_id, escrow_uid UNIQUE, quantity, granted_at)`
  — one grant per deal; `escrow_uid` uniqueness makes issuance
  idempotent under job retry.
- a balance per key (grants − consumption) and an append-only
  consumption log (batched decrements land here).
- the quota ledger (`site_resources`/`site_allocations`/
  `capacity_events`) behind `/api/v1/capacity/*` — **reused, not
  reimplemented**: the ledger + capacity API currently live inside the
  VM provisioning service and are lifted into a shared package both
  services mount (work item 2). This is the "second domain shows what
  is invariant" criterion firing for the site-authority scaffold.

API surfaces: market-facing (`/api/v1/capacity/*`, issuance job),
middleware-facing (`POST /api/v1/keys/{key_id}/consume` with amount +
idempotency key → remaining balance or 402; `GET …/verify`; a batch
variant), admin (list keys/grants/usage, revoke, adjust). Middlewares
authenticate to the service with a seller-side service credential —
they are trusted seller components, not buyer-facing.

**Middlewares (Python, TypeScript, Rust).** Thin clients with identical
behavior: extract the API key from the Authorization header, verify
with a short-TTL local cache, consume with batched flush (synchronous
consume below a low-balance threshold so the overdraft window stays
bounded), map exhaustion to 402/429 with a machine-readable body
pointing at the listing (the re-purchase loop). All
verification/accounting logic stays in the service; a middleware is
~one file per framework adapter (ASGI; Express/Fetch handler;
tower/axum layer).

**Storefront (`arkhai-apitokens-storefront`).** Domain-owned executable
over `core_storefront` (sync negotiation, stage log, auth, publication,
claims engine, heartbeats all reused). Listing import/publish is
quota-backed: a listing derives from a quota resource the way VM slices
derive from pool members, and closes on exhaustion via capacity deltas.
Negotiation hooks as above. Settlement jobs submit issuance instead of
VM provisioning.

**Buyer plugin (`arkhai-apitokens-buyer`).** Registers the schema
plugin (entry-point discovery, same as `vms.compute`): filter
vocabulary for the new registry schema, `--quantity`/key-disposition
flags, listing rendering (unit price, service name, OpenAPI URL),
credentials delivery to the run-log. The policy surface registers
nothing new — the scalar policies gain the unit-scaling hook and
`listed_price` stays the default.

**Registry.** A second registry deployment with the api-tokens
`filter-spec.yaml` (axes: `service_name` contains, plus the existing
escrow-token projection; price-range filtering can wait). This makes
**schema identity** load-bearing for the first time: with two
registries configured, the buyer plugin must select the ones speaking
its schema. v1 is the minimal sharp version of the parked item: the
filter-spec gains a `schema: {id, version}` header; a plugin declares
the schema id it implements; the fan-in offers each plugin only
matching registries.

## Key ownership — usage identity vs market identity

*(Open decision — recommendation below; everything else in this doc
stands under any of the variants.)*

Two operations, only one of which ever touches the marketplace:

- **Usage** (every request to the gated service) is authenticated by
  the API key alone, under every variant. The buyer's wallet never
  appears in a web client's secrets; a web client holds an API key
  exactly as it would for any SaaS.
- **Top-up** (assigning purchased credits to an existing key) is a
  marketplace negotiation, which is already wallet-signed — the buyer
  CLI necessarily holds the wallet because it creates escrows. So
  binding top-up rights to the purchasing wallet adds **zero** new
  key-management burden in the purchase path.

What asymmetric (public/private) API keys would add, against that
baseline: (1) wallet-independence of a key's commercial lifecycle —
any wallet can fund a key whose possession it can prove, so wallet
rotation or org changes don't strand keys; (2) buyer-generated keys
whose private half never transits the wire or rests with the seller;
(3) possession-proof top-ups with no stored binding. What they cost:
if *usage* requires request signing, every customer of every gated
service needs signing tooling instead of a bearer header — an adoption
killer for arbitrary HTTP clients — and the three middlewares grow
signature verification, replay windows, and clock handling. Note that
gains (1) and (3) attach to *ownership*, not usage: they don't require
signed requests, only an asymmetric claim on the key record. And the
at-rest security delta of public keys over bearer secrets is small
when secrets are high-entropy and hashed (a leaked table of hashes of
256-bit random keys is not crackable); the residual advantage is
secret transit at issuance.

**Recommendation:** bearer usage keys, with ownership as a
**pluggable scheme-tagged claim** on the key record —
`owner: (scheme, identifier)`, the same shape as the registry's
publisher identity and resolved through `arkhai-kit-identity`'s scheme
registry:

- v1 ships scheme `wallet`: bound automatically from the signed
  purchase; top-up requires the same signing wallet (one equality
  check at the key guard). Zero UX, zero new secrets.
- `ed25519` is the planned second scheme: the buyer supplies an owner
  public key at purchase (the CLI can generate and keep it beside the
  run-logs); top-ups prove possession by signing the negotiation
  payload. This is the wallet-decoupled mode — market identity and
  token identity coincide only if the buyer doesn't care.
- `open` is a seller-policy mode (anyone may credit any key id —
  gifting/team pooling), explicitly opted into per listing, with the
  mistyped-key-id risk on the seller's terms.

The schema carries the claim from day one so adding schemes is
additive; only `wallet` ships in v1.

## Work items

1. **Schema identity in the filter-spec + second registry.**
   `schema: {id, version}` header in `filter-spec.yaml`, surfaced by
   the registry client; plugins declare their schema id; buyer fan-in
   matches plugins to registries. Deploy the api-tokens registry in
   compose/e2e. (Retires TODO item 4's minimal core.)
2. **Site-authority ledger extraction.** Lift the quota/allocation
   ledger + `/api/v1/capacity/*` controller out of the VM provisioning
   service into a shared package; the VM service re-mounts it
   unchanged (pure move, gated on its suites + canonical e2e before
   any tokens code exists).
3. **Tokens service.** Keys/grants/balance/consumption schema, quota
   ledger mount, issuance job (idempotent on `escrow_uid`),
   consume/verify/batch API, admin surface, ownership-claim check.
4. **Concept modules + storefront.** `domains/apitokens/{listings,
   negotiation,settlement}` hooks (quota guard, key guard, issuance
   submission, failure action), quota-backed publish/reconcile,
   `arkhai-apitokens-storefront` composition root.
5. **Buyer plugin.** Schema plugin + verbs/flags/rendering;
   per-unit→absolute scaling in the policy surface (and the VM
   plugin's per-hour scaling moves to the same seam); credentials to
   run-log.
6. **Middlewares + e2e.** Python middleware first (it gates the e2e's
   sample service), then TypeScript and Rust to the same behavioral
   spec (shared conformance fixtures: a recorded consume/verify
   session each implementation must satisfy). e2e topology: second
   registry, tokens storefront, tokens service, a sample gated app;
   full deal: discover → negotiate (new key) → settle → consume to
   402 → buy again into the existing key → consume succeeds.
7. **Core consolidations that ride along** (each parked on "second
   plugin shows what is invariant", now showable): hoist `--yes` and
   `inject_policy_cli_params` into core `build_app`; extract whatever
   the two storefront composition roots actually share.

Items 1–2 are pure-infrastructure and land first, each gated green on
the existing suites; 3–5 are the domain; 6 proves it end to end; 7 is
cleanup the second instance finally justifies.

## Non-goals / deferred

- **Usage-metered / postpaid billing** — v1 is prepaid credits only;
  metered billing is a settlement-plan shape (spot-instance track).
- **Outstanding-liability quota** (consumption replenishes sellable
  quota) — a seller-policy upgrade over the same ledger.
- **Credit expiry** — maps to lease truncation when wanted.
- **Offline/self-verifying tokens** — revisit only if the per-request
  hop is a demonstrated bottleneck a cache can't fix.
- **Scopes/products per key, per-route pricing** — one product per
  listing in v1.
- **Secondary transfer of credits between keys/buyers.**
- **Fiat payment for token purchases** — separate track
  (`design-remaining-work.md` §§ 1–2); nothing here blocks it, since
  the payment side is untouched escrow machinery.

## References

- `ARCHITECTURE.md` — "Organizing Principle" (plugin inversion, one
  storefront process per market domain), "Buyer negotiation policy
  surface", "Capacity and the Site Authority"
- `design-remaining-work.md` § 3 — what this work does and does not
  prove for the multi-domain capacity plan
- `core/registry/filter-spec.yaml` — the schema-injection surface the
  second registry instantiates
