# Design — compose-inference-domain-stack

## Context

### What exists

`add-inference-domain-contract` defines the vocabulary: the model-card listing
and its rate card, the `inference.v1` purchase shape bound from the `api`
family, the family's negotiation carriers bound under that kind, an
`InferenceMaterialization` that carries the accepted listing and refuses a card
other than its own, the usage record and charge derivation, secret-free usage
evidence, and the registry filter specification. The `api` family kit
(`compose-api-family-kit`, archived 2026-10-26) owns everything an API-selling
domain needs to sell against such a vocabulary, filled through one typed
contribution bundle per side: `SellingContributions` (label, kind, offering
mode, listing schema, publication mapping, issuance projection, publication
guards, public-result extension), `BuyingContributions` (schema identity,
provision terms, command, rendering), and the authority's `AuthorityConfig`
with its `CapacityProfile`. API credits fills each in a few dozen lines and is
the precedent every decision below copies the shape of.

Three facts about the kit decide more than the proposal assumed:

- The kit records the accepted listing artifact at acceptance and reads it back
  at fulfilment; it never constructs the family `Materialization` carrier in
  production. The accepted rate card is therefore pinned by the kit for every
  domain; what inference adds is surfacing it.
- The kit's negotiation prices from its own `extract_unit_price_from_order`
  with no contribution hook, so the contract's own pricing helpers are not on a
  kit-composed storefront's path; the listing codec's rate check at publication
  is the load-bearing rule.
- The kit's bearer gate admits or denies on the `Authorization` header and
  then calls the wrapped app, charging first; nothing in the repository
  proxies, streams, or reads a request body. The gateway is the one role with
  no precedent.

### What governs the design

`docs/development/ARCHITECTURE.md`'s package layers and family-kit rules, the
`api-family` capability's specification and architecture (a kit never imports
a domain; each domain composes the authority in its own service root; a
domain contributes through the typed bundles), `registry-discovery` (a buyer
compiles against the served filter specification), `test-compatibility` (one
end-to-end lane per domain), and `deployment-state` (Compose topology files
and development identities). Each decision names the rule that decides it
where one does.

## Decisions

### D1. The issuance projection names what the gateway serves

`issuance_projection(card)` returns `IssuanceSubject(service=card.served_model_name,
resource_id=card.resource_id, endpoint=card.endpoint.base_url)`. The digested
service identity is the served model name, so a grant is bound to what the
gateway admits in a request's `model` field, and the kit's existing connection
payload (`service_name`, `base_url`, `key_id`, `quantity`) already gives the
buyer a working first request. The gateway URL is delivery metadata, as API
credits' `base_url` is; it is not digested.

Rejected: `model_id` as the service. It names the convergent identity, but the
buyer would then need the served name delivered separately and could confuse
the two, and a seller could re-point a `model_id` at another served model under
the same grant. The convergent identity is not lost: it is in the accepted
listing the kit pins (D3). Rejected: a composite of both, which puts a
structured string in a field every domain uses as a plain name. Rejected: no
endpoint, which gains nothing since the endpoint is not digested and the kit's
credential store is built around `base_url`.

### D2. The gateway is a family library composed by an inference executable

The reverse proxy knows nothing inference-specific: it parses the request
body, refuses a `model` the deployment does not serve before any charge,
authorizes and charges through `TokenGate.authorize` inside the route, replaces
the buyer's `Authorization` with the deployment's own upstream credential from
a mounted secret, forwards to the model server with `httpx` streaming
pass-through (server-sent events when `stream` is set), serves `/v1/models`
listing only the configured model, and leaves `/health` ungated. API credits'
vLLM cookbook describes exactly this component and does not ship it. The
library therefore lives in the family as `kit/api/gateway`
(`arkhai-api-gateway`), depending on `arkhai-api-gate` and `httpx`, and
inference adds `domains/inference/gateway-service` (`arkhai-inference-gateway-service`),
a composition root the architecture check reads as an executable through the
hyphen rule, which reads the listing the gateway fronts (selected as plan
review 06 F1 records), validates it as an `InferenceListing`, and
projects it to the family's `GatewayOffering` (review 02, F3); the default
source is the storefront that published the listing, its origin, since a
registry's copy can lag a republication and the storefront and gateway are
deployed together; it also
supplies the upstream base URL and credential reference and the gate's
signing credential. The library understands only the offering.

The gate middleware cannot be used as-is: it authorizes on headers alone, so
an unlisted model would be charged before refusal. The route calls
`TokenGate.authorize` after the model check.

Rejected: everything under inference. Less to design now, but API credits
copies it the moment the cookbook's gateway ships, which the family exists to
prevent. Rejected: adding `gateway` to the architecture's role words; the
hyphen rule already classifies `gateway-service`, and a new role word is a
repository-wide vocabulary change this change does not need.

### D3. The delivery's public result carries the contract's materialization

`public_result_extension(listing_resource, result, delivery)` returns, under
one key, `InferenceMaterialization` built from the accepted listing the kit
hands it and that listing's rate card, with the issuance's `fulfillment_id`
and the delivery's settlement mechanism and reference. The contract's model
refuses a card other than the listing's, so the public record cannot show a
buyer a rate they did not accept.

The third input is new to the kit (planning found the gap): the issuance
result carries neither the mechanism nor the settlement reference, and the
materialization requires a reference with its mechanism and fulfillment id.
The kit's `fulfill` already holds both on the settlement evidence it issues
from, so the selling library passes a frozen `DeliveryContext(mechanism,
settlement_ref)` as the extension's third argument. The context names what
the kit knows — the agreed mechanism and the stage's reference, which for the
Alkahest stage is the escrow uid — and the domain maps it onto its own shape;
inference places the reference as the materialization's `escrow_uid`. API
credits supplies no extension, so its delivery and wire bytes are unchanged.

Rejected: a slimmer public record without the settlement reference, which is
not the contract's materialization and so not what the buyer plugin and
metering read. Rejected: building the materialization in the Alkahest selling
stage, which knows the reference but would put a domain shape into mechanism
code the family keeps domain-neutral. The accepted terms then exist in three places, each with one role
and all bound by the same digest: the storefront's accepted-listing artifact,
recorded by the kit at acceptance, is the issuance input and the seller's
audit record; the authority's `grant_terms` row (review 03 F3, review 04) is
the copy consumption charges against and `meter-inference-usage` prices
against; and this public materialization is the buyer's and an auditor's
copy. No acceptance hook is needed, since the kit records the artifact
itself.

Rejected: nothing public, which leaves the buyer unable to see the rate bought
at. Rejected: a card-only extension, which saves little since the listing is
small and loses the model identity beside the card.

### D4. Retries are charged as the kit charges them

The gateway passes no idempotency key to `authorize`, so a retried request is a
second charge, as it is for API credits today. The gate's contract is pinned
by a cross-language conformance trace, and metering's hold-and-settle replaces
this charge path. The seam is recorded for `meter-inference-usage`.

Rejected: honouring a client `Idempotency-Key` header now. Cheap in the
gateway, but it changes the family gate's pinned contract for API credits too,
for a path metering retires.

### D5. The deterministic model server is a test image

The stub lives under `e2e-tests/` beside the end-to-end image, outside the
architecture check, because it knows no market: an OpenAI-style server
answering `/v1/models`, `/v1/chat/completions`, and `/v1/completions` with
responses keyed on the prompt, streamed when asked, so the scenario asserts
exact text. A Compose profile `vllm` swaps in the CPU vLLM image and small
instruct model the API-credits cookbook already names.

Rejected: `domains/inference/model-stub`, which would need an architecture
override row for a project that is neither a role nor a library of the domain.

### D6. Contribution values follow API credits' pattern

Label `IssuanceLabel("inference")`, whose fulfilment prefix defaults to
`inference-fulfillment.v1`; kind `inference.v1`; offering mode, contribution
id, and pool provider `inference`; table prefix `inference`; key prefix `ik`;
pool id `default`; backing `BACKED`, the only value the contract admits.
`AuthorityConfig` names the distribution `arkhai-inference-service` and the
authority's own database. The storefront's seed and quota lookup name the same
pool and mode.

### D7. The publish request carries the model card

The domain's publish request extends the kit's `PublishFromQuotaRequest` with a
`model_card` object; the storefront's `[seed.model_card]` table reaches it as
`request["model_card"]` through the kit's `ListingSeed`, which passes fields it
does not own through. `publication_mapping(request, quota)` validates the card
as `InferenceModelCard` with `resource_id`, `capacity_site_id`, and
`offering_mode` filled from the `QuotaSource`, so a seller's card cannot name
another resource than the one its quota backs.

### D8. The request-priced guard is one removable entry

`publication_guards` holds one function refusing a card whose prompt,
cached-prompt, completion, or image rate is non-zero, naming the field, while
the gate charges `request_credits` per request. `meter-inference-usage` deletes
that one entry. The guard is the withdrawn branch's `rate_card_guard.py`,
adapted to the kit's signature. The predicate itself — is this card
request-priced — lives in the contract package, `arkhai_inference.listings`,
because the gateway executable applies the same rule to the listing it fronts
and two composition roots cannot import each other; the guard and the
gateway's projection both call it. The same predicate bounds the request
charge (plan review 06 F3).

### D9. Alkahest only, refused at startup

The storefront's `SettlementStageTable` and the buyer's hold one stage,
Alkahest. Startup compares the configured settlement priority against the
table and refuses any mechanism the table lacks, naming it. Resolving the
seller settlement registry also refuses a mechanism it does not register
(implementation found this; the plan assumed it was ignored), so the
storefront's refusal adds the named heading beside its other startup
problems rather than the only refusal. Neither inference wheel declares the
fiat payments distribution.

The issuance label and the accepted-terms payload live in the domain package
(`arkhai_inference.label`, `arkhai_inference.listings.accepted_terms`), not in
the storefront root: the service root composes the same label and the gateway
executable hands the same current terms to its verification hook, and two
composition roots cannot import each other (implementation, section 5).

### D10. Compose files, identities, and env targets mirror API credits

`domains/inference/compose.yml` carries topology only: the inference registry
(the packaged image with `REGISTRY_FILTER_SPEC_PATH=/app/filter-spec-inference.yaml`,
no bind mount, since the image already carries the specification), the
authority, the gateway and model stub, and the storefront, with named volumes.
`compose.inference.yml` is the standalone wrapper over `compose.dev.yml`;
`compose.inference-local.yml` binds development credentials, signer
identifiers, and a one-shot buyer; `compose.inference-lane.yml` adds the
lane-only compute and API-credits registries; the root `docker-compose.yml`
includes the domain file. Identities: `inference-registry.ed25519`,
`inference-service.ed25519`, `inference-gateway.ed25519`, an
`inference.identity.env` and `inference.wallet.env` on an Anvil account no
other storefront uses (the storefront signs toward the authority, which has
no admin key), and a buyer configuration pinning
the inference registry, all derived by the identities README's rule and pinned
where they are consumed. Root targets `e2e-inference-stack-env` and
`e2e-inference-dev-env` print them; `e2e-dev-identities-env` gains the stack.

*Amended 2026-11-09, on merging `dev`.* `dev` moved every lane from printed
environment files to committed overlays, registry profiles, and secret
overlays, and removed the `e2e-*-dev-env` targets. The inference stack follows:
`compose.inference-local.yml` binds the committed credential files by path; the
registry loads `dev-env/registry/config-inference-registry.env` by
`ACTIVE_PROFILES`; the storefront's wallet key moves from
`inference.wallet.env` and an environment variable to
`dev-env/identities/inference.storefront.secrets.toml`; and the lane's compute
and API-credit registries run the committed `compute-registry` and
`api-credits-registry` profiles with their descriptors pointed at the lane
network. The lane layers the payments and mediation lane doubles, as every
lane does (D20), though inference settles through Alkahest alone. Promotion of this to the testing and identity documents is
already in `dev-env/identities/README.md`; `docs/development/TESTING.md`'s lane
list still needs the inference lane at closeout.

### D11. The scenario runs in its own lane

`test-e2e-inference` builds the inference images and every registry its
scenarios read, brings the inference wrapper up with the lane overlay, and runs
`e2e_inference_deal` on the lane's network, with its own job in the end-to-end
workflow and its own `e2e-inference-down` and `-logs` targets. The compute and
API-credits registries are present only for the schema-filter scenario, through
`compose.inference-lane.yml`. The scenario is written over the domain-neutral
helpers (`DomainDealState`, `ordered_events`, `create_profiled_buyer_cli`); the
inference-specific parts are the `market inference buy` invocation, the
model-card resource filter, the credential shape, and the model calls. A
missing lane setting fails, as the lane rule requires.

### D12. The buyer plugin's contributions

`BuyingContributions(schema_id="inference", provision_terms=InferenceProvisionTerms,
command="inference", noun="inference", ...)` with a rendering whose summary is
the model identity and whose columns are quantization, context length,
provenance, and the request charge; one `AlkahestBuyerStage`. Discovery
filters compile from the served specification, which already pairs each rate
bound with `rate_card_asset`, so the plugin encodes no pairing rule.

The one stage is a plugin-local subclass of `AlkahestBuyerStage` that carries
the purchase-time hook (D16), with a subclass of its buy session, because the
buying library proposes from both: `buy` through the session's `propose`,
`negotiate` through the stage's `prepare_selection`. The subclasses rely on the
Alkahest stage's constructor and `propose` signature, which that library does
not declare as an extension contract (implementation, section 7). The served
model name reaches the buyer in the delivery's `connection_details`; the
buying library copies its `service_name` onto the delivered credential and the
credential panel shows it under the domain's `summary_header`, so a completed
purchase shows the key, the base URL, and the model name (implementation
review 08 F6).

### D13. The withdrawn modules are recovered, not rewritten

`model_card.py`, `rate_card_guard.py`, and `materialization.py` are recovered
from the withdrawn storefront branch and adapted to D7, D8, and D3; the
withdrawn authority is not reused, since the service root is configuration
over the kit.

### D14. The gateway signs as the service role

The gateway holds its own development credential and signs toward the
authority as the `service` role, which the authority trusts by role, as the
API-credits sample application does.

The inference service has no shared-secret gate behind its signed
authentication: it refuses to start without a signing credential and a trusted
role. The API-credits service's `X-Admin-Key` fallback serves deployments
provisioned before identities and admits every caller when no key is set,
which the bearer-credential requirement cannot admit (implementation, section 6).

### D15. The authority's database starts on the family chain

The inference service's database is built by the family authority chain, on
its own database, through `inference-service-migrate` (D20). The chain is one
for every domain: its authority baseline is identified
`v0_3_0_baseline_apicredits_service` in the inference database too, followed
by the site ledger's migrations and `20261109_001_grant_terms`, and it names
no floor. The two authorities' tables are identical by design, so the
API-credits name in the baseline's identifier is the family's recorded limit
and costs nothing here.

### D16. Forward compatibility with privacy proofs

The contract already fixes where a proof attaches: the model card's attestation
envelope and the usage evidence's attestation reference. This change adds the
seams a first proof format would need, each a no-op in version 1: a
per-request verification hook in the family gateway library and a
purchase-time verification hook in the buyer plugin, called before settlement
is proposed; both take the listing's attestation envelope and return a refusal
or nothing. The gateway's hook receives the offering's complete current
canonical terms (the rate card and the attestation), the key's accepted terms
as `verify` returns them, and their digest (reviews 02–04), so it can both
detect a change since acceptance and verify against the accepted envelope
itself; it runs after the key is verified and before it is charged
(F3), so a refused proof costs the buyer nothing. The inference
gateway image is built reproducibly from a digest-pinned base and compose, so
it can later be measured. No proof `kind` is defined. The first `kind`'s
input is the verification chain a comparable open-source market already
ships, whose published claim carries the image digest, the compose digest,
the platform measurements, and the build provenance, and whose verification
runs at session open and per prompt; its own documentation records that such
a claim attests the software, not that the listed model is the one answering,
which is the gap a listing-level claim must close.

Rejected: no seams now. Zero cost today; the first proof format then becomes a
gateway rewrite rather than a plugin.

### D17. Forward compatibility with a three-party arrangement

No royalty field is added. `model_owner` on the card and `provenance`, with
`hosted-for-owner` reserved under a version bump, stand as the contract left
them. The constraint this change holds is that the inference storefront's
settlement composition is the kit's obligation list unmodified, so a second
claimant in one deal is a later addition to that list, not a new mechanism;
and D1 keeps the grant bound to the host's served name, so a model owner's
identity lives in the pinned listing rather than in the grant.

Rejected: a declared-but-unpaid royalty number. It encodes a direction of
money that the hosting domain has not decided.

### D18. Implementation cadence

Two rounds, each one session, reviewed after each. Round 1: the family gateway
library with its unit tests, and the storefront, service root, and buyer
plugin, which are configuration over precedent. Round 2: the inference gateway
executable, the model stub, the Compose stack and identities, and the
end-to-end lane. The gateway and the stack are where the risk is, and they get
their own review. The campaign's first seller, first paying buyer, and settlement
option (review 01, F6) are, for this change, the team's own development
stack: the inference storefront the stack composes is the seller, the
end-to-end buyer is the paying buyer, and Alkahest on the development chain
is the settlement option. The Alkahest-only development-chain scenario is
therefore this change's proof, not only its cheapest one, and the plan's
sections assume it; a third-party seller or buyer, when one appears, is
`package-inference-seller`'s and `qualify-inference-market`'s to answer.

### D19. The storefront starts without its dependencies

*Added 2026-11-10, on merging `dev`.* The storefront follows the API-credits
storefront wherever inference's market does not require a difference, which
`ARCHITECTURE.md` asks of two domains handling one concern, and the
deployment-state requirement "A deployment does not wait on a service's
dependencies" governs its startup. Four outcomes of implementation reviews 08,
09, and 12 are replaced, at the owner's direction:

- **No authority preflight.** Startup no longer waits for a signed probe of the
  inference authority. The listing seed waits for the authority and each call
  to it is retried. `credits.fail_on_unreachable` and
  `credits.preflight_timeout` are removed, and a configuration still stating
  either is refused at startup by name, since ignoring it would change
  behaviour silently.
- **Configuration is still refused.** What waiting cannot repair stops startup
  before the database opens: an unset `[credits].service_url`, a missing
  signing credential, a missing authority trust set, an unreadable capacity
  configuration, and a settlement priority naming another mechanism.
- **The chain probe owns the chain clients.** The storefront composes
  `AlkahestChainProbe`; no client is built at startup, and readiness reports a
  chain that does not answer. The `publish` and `listings` commands are
  therefore clients of the running storefront, since a service set composed
  for one command reaches no chain.
- **The seller is one account.** `[wallet].address` is optional and defaults to
  the account the key signs as. An address naming another account does not
  refuse startup; Alkahest readiness reports
  `alkahest.wallet_address_mismatch` and no Alkahest option publishes.

No dispute policy is composed: inference settles through Alkahest alone, and
nothing on that path reads one.

### D20. Migrations, lane doubles, and the sweep follow `dev`

*Added 2026-11-18, recording the decisions taken on merging `dev` on
2026-11-11 (implementation review 23 F1, F2, F4).* The merge brought the
repository's migration policy, every lane's doubles, and the family selling
library's sweep onto this change's services. The owner decided each as
follows; where an earlier entry said otherwise, this one supersedes it.

- **Migration policy.** The deployment-state requirement "Service-owned
  migration history" governs the four API-family stateful services. Each
  migrates through a packaged command in a deployment phase before its
  application starts: `apicredits-service-migrate`, `inference-service-migrate`,
  `apicredits-storefront-migrate`, and `inference-storefront-migrate`. The
  application only checks its database, issues no DDL, and refuses an
  incompatible one. The family libraries own the chains, `kit/api/authority`
  the services' and `kit/api/selling` the storefronts', and each root composes
  its chain behind its own command. Neither chain names a floor, so a database
  a chain did not build is refused, and an image whose chain lacks a recorded
  migration refuses that database as ahead. This replaces the in-process
  migration at startup that D15 and review 03 F3 assumed.
- **No rollback over a migrated database.** The API-credits upgrade and
  rollback end-to-end scenario (`e2e_credits_service_rollback`), its pre-kit
  image, and the requirement they proved are removed: under the policy the
  previous image against a migrated database is a refusal, not a supported
  path. The guarantee that replaces it is the refusal itself — a release
  either starts on a database its chain built or does not start — with
  recovery by the pre-upgrade backup or by rolling forward, proven at the
  library level by `kit/api/authority/tests/integration/test_migrations.py`
  (a behind database and an ahead one are refused unchanged) and stated in
  the api-family delta's scenarios for the terms table.
- **Lane doubles.** Every end-to-end lane layers
  `compose.payments-double.yml`, the inference lane included, and the
  inference lane's registries layer the `payments-lane` profile so they
  recommend the mediation double. Inference still settles through Alkahest
  alone (D9). The lane's runner takes a profile of its own,
  `docker,payments-lane,inference-lane`, as the lane-profile requirement
  states for every lane. This supersedes D10's amendment of 2026-11-09.
  The lane also runs every party on injected lane time, as the lane-time
  requirement states for every Compose lane: the storefront from a lane
  configuration (`storefront.inference.lane.toml`), the inference service and
  the gateway from the environment `compose.inference-lane.yml` gives them,
  and the three registries and both doubles from the shared lane profile and
  overlay. The service and the storefront take the signed time route the
  API-credits ones do, the service trusting the lane's operator as `admin`;
  the gateway, whose gate signs toward the service at the process's time
  source, serves a time route and status on the lane doubles' control wire
  behind a control token under injected time alone, bound from the time
  component's route service so the published gateway imports no test tool;
  the harness drives it through the doubles' typed client. The
  lane's profile names every one of them in its `lane_time` section. The model
  stub signs nothing and reads no time a party checks, so it has no time
  source. The full local stack stays on wall time.
- **A baseline ID per family storefront.** Each family storefront root names
  its own family baseline migration ID: API credits
  `v0_3_0_baseline_apicredits_storefront`, inference
  `v0_3_0_baseline_inference_storefront`. Compatibility is the exact set of
  recorded IDs, and the two chains create differently prefixed tables, so one
  shared ID let either storefront accept the other's database and fail at its
  first write; with its own ID each refuses the other's. The two authority
  services keep one chain and one baseline ID (D15), because their tables are
  identical.
- **The sweep is kept for inference.** After each reconcile the family selling
  library closes, at each registry, the open listings of the storefront's own
  offering mode published under its own identity that it does not hold open.
  The inference storefront keeps it. It assumes one seller identity per
  storefront: two inference storefronts sharing an identity and a registry
  would close each other's listings. A listing of another offering mode under
  the same identity is left alone.
- **The inference buyer is in the `market` binary.** *Added 2026-11-20
  (pre-closeout review 24 F5).* The released `market` binary bundles
  `arkhai-inference-buyer` (`core/buyer/market-binary/pyproject.toml`,
  `manifests/release-components.json`), because the release rule requires the
  binary's project to depend on every declared buyer domain
  (`docs/guidance/repository/images.md`, "The `market` binary"). The inference
  lane is not among the lanes a release candidate is validated against
  (`docs/release-handbook.md`, "Running the lanes on a release candidate's
  images") until inference is meant to ship: the owner's decision of
  2026-11-19.
- **Each inference party's time is normative in `inference`.** *Added
  2026-11-20 (pre-closeout review 24 F4).* The inference service's time
  setting and `admin`-only status and time routes, the storefront's, and the
  gateway's setting and token-guarded control are a requirement of the
  `inference` delta, since `injected-time` gives each party's setting, route
  and status to its own capability and the gateway is a published service,
  not test apparatus. The lane's composition stays in the `test-compatibility`
  delta, whose lane-time requirement now names the inference service and
  gateway among a lane's parties.

Rejected: one storefront baseline ID with a startup check that the bundle's
tables exist, which leaves `--check` and the migrate command reporting the
other family storefront's database compatible. Rejected: one ID with the
consequence recorded as a limit, which leaves a migration ID naming two
schemas. Rejected: a floor that adopts an API-credit database from before the
baseline, as the compute services adopt theirs, which would keep rollback but
departs from the policy `dev` states for API credits, where no deployment
holds such a database. Rejected: a sweep each domain opts into, with inference
left out, which would leave a listing the storefront no longer holds on sale
at a registry.

### F4 (design review 01). A key is scoped to its first grant

The family authority binds a key to the `(service, resource_id)` of the grant
that created it, and to its accepted terms digest (review 02, F1), and
refuses an existing-key issuance whose subject or terms differ, with a named
error. A key's balance is one number, so without this a buyer
could top up a key for one model from the same seller's cheaper listing for
another and spend the pooled balance through the first model's gateway. The
grant row already records both values, so the rule is a comparison against
the key's prior grants and no schema change; it holds for API credits too,
where one deployment serves one service and nothing crosses it today. The
buyer plugin surfaces the refusal rather than retrying.

Rejected: balances per grant with the gate consuming from the matching
entitlement. The right shape if a key is ever meant to span models, but it
changes the ledger, the verify payload, and the gate's pinned conformance
contract, and nothing in the campaign asks for a multi-model key.

### F1 (design review 01, amended by review 02 F1). The gateway charges the key's accepted terms

The inference gateway root reads the listing it fronts at startup and projects
it to the family's offering: its `served_model_name` is the one model the
gateway admits, its `rate_card.request_credits` is the offering's default
charge, and its storefront and registry are the purchase pointer. Readiness
refuses a card that is not request-priced or a listing that cannot be read.
But the charge a request pays is the one the buyer accepted, not the one the
listing shows today: the issuance projection fills the family subject's
optional **accepted terms** (the canonical JSON of the accepted card's
`rate_card` and `attestation`), their **terms digest**, and the **request
charge** (`request_credits`); the authority stores all three beside the grant
(review 04, F1 and F2) and pins them on the key at its first grant, `verify`
returns them, and the gateway charges the verified charge,
falling back to the offering's default only when verification returns none.
A republished price therefore reaches new keys only; an existing key's top-up
under different terms is refused (F4), so one balance never mixes two prices.
API credits leaves both values unset, so its issuance digests, verify
responses, and gate behaviour are byte-identical, which the pins prove.

Rejected: a gateway-global charge read from the current listing, which
reprices credits already bought when the seller republishes. Rejected:
grant-scoped balances with an entitlement chosen at consumption, the right
shape if a key is ever meant to span terms, but a ledger, verify, and gate
contract change nothing in the campaign asks for.

### F3 (design review 01). Verification precedes the charge

The family gate gains a separable verify step beside `authorize`, so the
gateway orders a request as: model check, key verification, proof
verification (D16's hook, a no-op now), charge, forward. The split is additive
and produces the same authority exchanges as `authorize`, so the gate's
conformance trace is unchanged. The hook's input is the attestation envelope
of the listing the gateway loaded under F1.

### F2 (design review 02). The proof hook binds to the accepted attestation

The accepted terms digest pinned under F1 covers the card's rate card and
attestation envelope, so the gateway's verification hook receives the
offering's complete current canonical terms together with the key's accepted
digest and the accepted terms payload from `verify` (review 03 F2, review 04
F3). A first proof format can therefore refuse a credential whose seller
changed the attestation or the price since the buyer accepted them, or verify
against the accepted envelope the authority holds; nothing reaches into the
storefront's records. In this version the hook admits everything.

### F3 (design review 02). The family gateway consumes a domain-neutral offering

The family gateway library understands one value, `GatewayOffering`: the
service name it admits in a request, the key scope it enforces (service and
resource), the default per-request charge, the purchase pointer, the upstream
base URL and credential reference, and the current canonical terms as
verification input. Each domain's executable validates its own listing
and projects it: inference from `InferenceListing` (`served_model_name`,
`request_credits`, the storefront and registry, the attestation envelope), API
credits from its resource (`service_name`, its configured charge, no
verification input). The library imports no domain, and the two-domains
scenario holds through the projection.

Rejected: the library reading a listing itself, which made it interpret
inference's fields and contradicted the family's import rule.

### F1 (design review 03). A key is enforced against the gateway it is used at

The gateway sends its offering's service and resource with every `verify` and
`consume`, and the authority refuses a key whose first grant's scope differs,
uncharged, with a named status the gateway answers as `403 key_out_of_scope`.
The fields are optional on both requests, so API credits' requests, the
authority's responses, and the TypeScript and Rust gates are unchanged.
Enforcement is authoritative: a gateway cannot forget the check, and no scope
leaves the authority.

Rejected: `verify` returning the key's scope for the gateway to compare,
which adds fields to the pinned verify response for every key and trusts the
gateway to compare.

### F3 (design review 03, amended by review 04 F1 and F2). Accepted terms persist and travel compatibly

- **A separate table.** A migration step creates `grant_terms`: the grant's
  id, the accepted terms as canonical JSON, their digest, and the request
  charge. `credit_grants` is unchanged. The step is appended to the family
  authority chain as `20261109_001_grant_terms` and applied by the migrate
  command; an image whose chain lacks it refuses the migrated database as
  ahead, so recovery from an upgrade is the pre-upgrade backup or rolling
  forward, never the previous image against the same file (D20). No key column: a key's pinned values are its
  first grant's row. A grant with no row is unpinned, so a key whose first
  grant is unpinned accepts only unpinned top-ups and is charged the
  offering's default, which is today's API-credits behaviour; inference has
  no such keys.
- **The payload, not only the digest.** The authority keeps the full accepted
  terms because `meter-inference-usage` prices usage server-side against the
  grant's accepted card, which a digest cannot recover; the digest is the
  integrity check the authority verifies on write and returns with the
  payload.
- **Validation ordering.** The application checks the database's recorded
  migrations against its chain and issues no DDL; the migration that creates
  `grant_terms` runs in the chain as any step does, through the migrate
  command.
- **Wire bytes.** The subject's terms, digest, and request charge, where they
  appear in the issuance request digest, the signed evidence, and the verify
  and consume exchanges, are omitted when unset, never serialised as `null`;
  the API-credits pins prove byte identity, and the pin fixture gains an
  inference case with the fields present. The request digest and the evidence
  carry the digest, not the payload, so neither grows with the card.

### F1 (plan review 06). The gateway discovers the listing it fronts

The gateway executable selects its listing by what identifies its offering:
it is configured with the storefront URL, the quota `resource_id`, and the
served model name, lists the storefront's open listings through the kit's
listing route — every page of them, at the route's largest page size, until
a short page, since a match or a duplicate may sit past the first (plan
review 07 F3) — and takes the one whose card names both. Zero or several
matches refuse readiness, naming the count, and the executable retries the
read at startup until the storefront has published, because the development
seed publishes after the storefront starts and mints the listing's id at
that moment. A configured `listing_id` remains an optional override that
replaces the search for a deployment that has one.

Rejected: a deterministic listing id in the seed table handed to both
services, which changes the kit's publish request for a development
convenience and stops matching after the seller republishes. Rejected: an
id written to a shared volume or by an initialization job, which adds a
filesystem contract between two services for one value.

### F3 (plan review 06). The request charge is positive and ledger-bounded

The contract's `request_credits` is uint256-domain and admits zero; the
authority's ledger charges integers from one to the signed 64-bit maximum,
`consume` refuses an amount below one, and the charge enters the issuance
digest through canonical JSON, whose integer domain (RFC 8785) ends at
`2^53 - 1` (plan review 07 F1). The request-priced predicate (D8) therefore
also refuses a card whose `request_credits` is zero or above `2^53 - 1`,
naming the field, so a listing that publishes is one every request against
it can be digested and charged; the family's `request_charge` is declared
with the same bounds. The uint256 domain stays for the per-token rates that
metered consumption will price.

Rejected: carrying charges as decimal strings through the issuance subject,
the authority, the gate, and its cross-language conformance trace, with a
zero-cost admission that calls no `consume`: it reaches every family package
for a charge path metering replaces.

### F2 (design review 01). A top-up is admitted after the gate's verification TTL

The gate remembers an exhausted key until its verification entry expires, so
a request immediately after a top-up answers `402` until the TTL passes. The
API-credits lane already handles this: a three-second TTL in the stack and a
scenario that polls through it. Inference does the same, and the requirement
says so. The gate is not changed: forcing re-verification on an exhausted key
would alter behaviour the cross-language conformance trace pins, for a charge
path metering retires.

## Risks / Trade-offs

- **A second consumer of a young family.** A gap the kit left for API credits
  surfaces here (the gateway, the public-result key set). Mitigated by placing
  what is domain-neutral in the family, once.
- **A retried request is charged twice** until metering replaces the charge
  path. Accepted; recorded as metering's seam.
- **A republished price reaches new keys only** (F1); an existing key keeps
  its accepted charge and refuses a top-up under other terms. Accepted for
  flat per-request charging, which metering replaces.
- **The stub proves the plumbing, not a model.** The `vllm` profile exists for
  a contributor to run a real server; the lane does not.
- **Quota as a sales cap.** A seller whose declared quota reaches zero leaves
  discovery while the model server is fine; the seed defaults it large.

## Open Questions

- **The first attestation `kind`.** Trigger: a seller who can produce a
  measured image and a buyer who will verify it. Input: the verification chain
  D16 names.
- **The hosting domain** (owner pays host to serve, or host pays owner a
  share). Trigger: a model owner who is not a seller. D17 keeps the door open.
- **Charge idempotency on retries.** Trigger: `meter-inference-usage`, whose
  hold-and-settle path replaces the per-request charge.
