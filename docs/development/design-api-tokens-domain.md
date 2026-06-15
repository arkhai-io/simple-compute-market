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
- **Usage identity and market identity are separate concepts**, and
  **ownership enforcement is negotiation middleware** (decision
  recorded below in "Key ownership"): seller guards validate the
  buyer's existing-key claim per the key's recorded ownership scheme —
  the v1 default `key_owned_by_buyer_wallet` is free because the
  negotiation is already wallet-signed — and open top-up is simply a
  chain with no ownership guard, not a mode flag.
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
capacity snapshot: requested quantity ≤ available) and the ownership
middlewares for `existing` mode (key exists, is active, and the
ownership claim admits the buyer — reject reasons `key_not_found` /
`key_not_owned` / `key_proof_invalid`; see "Key ownership").

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

**Decision:** bearer usage keys, with a **scheme-tagged ownership
claim** on the key record — `owner: (scheme, identifier)`, the same
shape as the registry's publisher identity — and **enforcement
implemented as negotiation middleware**, the same way every other
dimension of a buyer message is validated (the architecture's rule:
price, escrow shape, duration, and now key ownership are all decided
by the chain against advertised data plus captured side inputs).

- `key_owned_by_buyer_wallet` *(seller default)* — a round-0 guard,
  structurally identical to `has_matching_inventory_guard`: consults a
  captured key→owner lookup (the tokens-service query, captured behind
  the round hook exactly like the inventory snapshot) and rejects with
  `key_not_owned` unless the key's `wallet` owner equals the
  negotiation's signing wallet. **Free**: no extra round, no buyer
  configuration, no new secrets — the wallet-signed negotiation *is*
  the possession proof. New keys auto-bind `owner = purchasing wallet`.
- `key_possession_challenge` — a seller middleware for asymmetric
  owners (`ed25519`): on an existing-key claim it *counters* with a
  nonce (`key_challenge` in the message — message content is schema
  vocabulary), then verifies the returned signature against the key's
  registered owner pubkey before deferring to the pricing middleware;
  `key_proof_invalid` rejects. The proof signs
  `(nonce, negotiation_id, terms hash)` so it cannot replay across
  negotiations. Costs one round trip. The buyer mirror,
  `answer_key_challenge`, ships in the buyer's default chain as a
  pass-through: `None` unless the seller's last message carries a
  challenge; when challenged it signs with the configured owner key
  and counters with otherwise-unchanged terms — and when challenged
  *without* an owner key configured it **exits with a clear reason**
  rather than passing (an unanswerable challenge must not surface as
  chain exhaustion). The owner keypair is buyer-generated at purchase
  time (kept by the CLI beside the run-logs); this is the
  wallet-decoupled mode — market identity and token identity coincide
  only if the buyer doesn't care.
- **Open top-up is the absence of an ownership guard** in the seller's
  chain — not a mode flag. A seller who wants gifting/team pooling
  omits the guard (per listing or per escrow kind via the existing
  `[negotiation.policies]` dispatch table), accepting the
  mistyped-key-id risk on their own terms.

Filing: `arkhai-kit-identity` owns the per-scheme signature
verification primitives; the domain middlewares are thin policy shells
over them; core chain mechanics are untouched.

**The guard is the interface, not the enforcement.** Negotiation-time
checks are advisory in this architecture (the inventory guard works
off a snapshot; reservation is authoritative), and ownership can
change between accept and fulfillment. The issuance job in the tokens
service re-checks the ownership claim authoritatively at grant time;
the middleware exists for early, well-reasoned rejection and to carry
the interactive challenge protocol.

Default rationale: wallet binding is the only scheme that costs
nothing, it is the safe default (a mistyped `key_id` rejects instead
of silently crediting a stranger), it makes the dominant flow — buy
more with the wallet you bought with — zero-ceremony, and it matches
the system's existing trust anchor: every other authorization (escrow
creation, reclaim) is already wallet-keyed, so a different default
identity would make wallet rotation the default UX problem rather than
an opt-in trade-off. The schema carries the claim from day one so
adding schemes is additive; `wallet` ships in v1, `ed25519` +
`key_possession_challenge`/`answer_key_challenge` are the planned
second scheme (the buyer pass-through middleware can ship from day one
— it is inert against v1 sellers).

## Work items

1. **Schema identity in the filter-spec + second registry.**
   *(Mechanics done.)* `schema: {id, version}` header in
   `filter-spec.yaml` (shipped spec declares `vms.compute`; etag
   participation only when declared), surfaced by the registry client;
   `resolve_indexer_urls_for_schema` drops registries declaring a
   *different* id (lenient on undeclared/unreachable; singleton lists
   skip the fetch); VM plugin discovery verbs resolve through it.
   Remaining: deploy the api-tokens registry in compose/e2e — rides
   with the domain (items 4/6). (Retires TODO item 4's minimal core.)
2. **Site-authority ledger extraction.** *(Done.)* `arkhai-core-site`
   (`core/site/`, import `core_site`): ledger, tables (own metadata),
   and a `make_capacity_router(get_ledger)` factory replacing the
   container-coupled controller; the VM provisioning service mounts
   tables + router and re-exports the model names through `db.models`.
   Pure move otherwise — payload shapes byte-identical, ledger unit
   tests moved to `core/site/tests`.
3. **Tokens service.** *(Done.)* `arkhai-apitokens-service`
   (`domains/apitokens/service/`, provisioning-service shape: FastAPI +
   SQLite + dynaconf + X-Admin-Key gate, router factories instead of a
   DI framework). Keys/grants/balance/consumption schema; the quota
   ledger mounted from `core_site` (which grew the generic `units`
   claim key, per-host `required_attributes`, and open-ended commits
   for it); `POST /issuance` idempotent on `escrow_uid` with the
   authoritative ownership re-check at grant time (deterministic
   new-key ids per escrow; secret rotation on retry of an unused key so
   a lost response can't strand the buyer); consume/verify/batch API;
   admin surface; `GET /keys/{id}` is the seller guards' key→owner
   lookup. Dockerfile/compose wiring rides the e2e topology (item 6).
4. **Concept modules + storefront.** *(Done.)* Landed in two layers.
   First, the domain-neutral storefront glue the second root would
   otherwise have duplicated was hoisted: market-state SQLite
   persistence + versioned migrations (`core_storefront.sqlite_client` /
   `sqlite_migrations`, with `_ensure_domain_tables` /
   `_domain_migrations` subclass hooks the VM client now uses for its
   inventory tables), registry fan-out (`multi_registry_client`),
   settle-time escrow verification, refund + ERC-20 transfer, the
   remote capacity client + event poller
   (`core_storefront.capacity_remote`, with the domain's listing
   reconcile injected), and the alkahest claim hooks
   (`market_alkahest.claim_hooks`). Then the domain:
   `domains/apitokens/{listings,negotiation,settlement}` (offer schema +
   per-token pricing, `api_tokens_round_zero_guard` /
   `token_quota_guard` / `key_owned_by_buyer_wallet` + the seller round
   hook with quantity×rate reference amounts, issuance client +
   fulfillment orchestration with inline rollback) and
   `arkhai-apitokens-storefront` (`domains/apitokens/storefront/`,
   import `apitokens_storefront`): quota-backed publish/reconcile
   (listings derive from a quota resource, close on exhaustion and
   reopen on release via the capacity event feed), sync negotiation
   persisting `token_deal_terms` per thread, settlement jobs submitting
   issuance with the negotiation-time hold and returning
   `{key_id, secret?}` once through `tenant_credentials`, claims-engine
   collection, and a `serve`/`publish`/`listings` CLI. The scalar
   policies and `SellerRoundResult` were imported from
   `domains.vms.negotiation` as a documented leftover; item 5 relocated
   them to the kits. Dockerfile/compose rides item 6.
5. **Buyer plugin.** *(Done.)* Landed in two layers, like item 4.
   First the relocations the second plugin forced: the alkahest-scalar
   negotiation vocabulary left `domains.vms` for the kits
   (`market_policy.scalar_policies` / `.seller_round`,
   `market_alkahest.proposals` — retiring item 4's documented
   leftover), and the schema-invariant buyer machinery was hoisted to
   `core_buyer` (negotiation client, scalar policy surface —
   registered once, since two plugins re-registering `listed_price`
   would silently shadow each other — settle/escrow clients,
   aggregation, run-log, deal recovery). The per-unit→absolute seam
   moved with it: `negotiate_with_seller` scales per-unit prices by an
   explicit `unit_count`; the VM shim supplies `duration_seconds/3600`
   and the tokens plugin the requested quantity. Then the plugin:
   `arkhai-apitokens-buyer` (`domains/apitokens/buyer/`) publishes the
   `api_tokens` schema plugin with its verbs namespaced under one
   `market tokens …` group (buy/negotiate/settle/listing) so both
   plugins compose in one binary without shadowing the VM plugin's
   bare verbs (bare-verb dispatch by listing schema is item-7
   territory); `--quantity` + key disposition (`--new-key` |
   `--key-id`) fixed at round 0 in the `api_tokens.v1` provision
   terms; listing rendering (service name, per-token unit price,
   OpenAPI URL); `answer_key_challenge` rides the default chain as the
   pass-through (inert vs v1 wallet-bound sellers; clean
   `key_challenge_unanswerable` exit when challenged — signing lands
   with the ed25519 scheme); issued credentials land once in the
   run-log (`credentials_delivered`, the buyer's durable copy of the
   secret). The wheel ships the apitokens concept modules without
   `domains/__init__.py` (vms-buyer owns the file; alone, the
   namespace-package fallback resolves it). Dockerfile/compose rides
   item 6.
6. **Middlewares + e2e.** *(Done — all three middlewares + the full
   e2e.)* The Python gating middleware landed first:
   `arkhai-apitokens-middleware` (`domains/apitokens/middleware/python/`)
   — a framework-neutral `TokenGate` (verify cache, per-key balance
   estimate, synchronous-near-exhaustion / optionally-batched charging)
   behind a one-file ASGI binding; a drained key gets a 402 whose body
   carries a `purchase` pointer (the re-purchase loop). The behavioral
   contract — status codes + machine-readable bodies + per-step
   service-call counts — is recorded in
   `domains/apitokens/middleware/conformance/session.json`, the shared
   fixture the TypeScript and Rust middlewares will satisfy (their
   harnesses mirror the Python reference runner at the HTTP layer).
   `arkhai-apitokens-sample-app` is the one-endpoint gated service.
   The e2e topology (`docker-compose.yml`): a second registry serving
   the `api_tokens` filter-spec (the shared registry image +
   `REGISTRY_FILTER_SPEC_PATH`), the tokens service, the tokens
   storefront (self-seeds one quota-backed listing on startup from a
   `[seed]` config block), and the sample app. The full deal is green
   under the `e2e_tokens_deal` marker: discover (the buyer's schema
   filter picks the api-tokens registry, skips vms.compute) → negotiate
   a new key → settle → consume to 402 → buy again into the existing
   key → consume succeeds. Two settlement bugs surfaced and were fixed
   bringing it up: the storefront must stamp its wallet as the escrow
   recipient in the accepted artifacts, and the service image must
   `--refresh-package arkhai-core-site` (a stale same-version wheel
   predated the generic `units` capacity claim). The TypeScript
   (`middleware/typescript/`, npm) and Rust (`middleware/rust/`, crate)
   middlewares then followed, each reproducing the same
   `conformance/session.json` over a real HTTP client against an
   in-process scripted service (Node `node:http` / Rust `axum`) —
   `TokenGate` + a `TokensClient`/`TokensApi` seam in every language,
   with framework adapters (Connect/Express + Web-fetch in TS, a
   tower/axum layer in Rust). All three conformance suites are green.
7. **Core consolidations that ride along** *(Done — the second plugin
   made the invariants showable.)* On the buyer side, `core_buyer.cli`
   now owns the two things every schema plugin's `buy`/`negotiate` was
   re-declaring: `assume_yes_option()` (the shared `--yes/-y` flag, with
   per-verb help kept) and `register_policy_verb()` (the
   inject-then-register pairing — core applies `inject_policy_cli_params`
   so the policy flag surface is identical across plugins). The four
   domain verbs (VM + api-tokens × buy/negotiate) call these instead of
   spelling the flag and the injection out themselves. On the seller
   side, the one piece the two storefront composition roots genuinely
   shared — the admin-key OpenAPI customization (the `X-Admin-Key`
   security scheme + the gateway `servers` block) — moved to
   `core_storefront.openapi.install_admin_key_openapi`; both `server.py`
   roots call it, their domain-specific lifespan and router wiring left
   alone.

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
