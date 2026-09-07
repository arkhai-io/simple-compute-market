# Compute introduction readiness

Dated research snapshot: 2026-09-07. Source baseline:
`ea54f296eaf83f9ad9186ebd8a9ab8b551094daa`.

Scope: the first compute-introduction increment selected in #193 under #179.
This is diagnostic evidence and a candidate epic boundary, not a normative
backlog, accepted implementation design, or release qualification. Subsequent
behavioral deltas and implementation tasks belong in OpenSpec changes.

## Selected outcome

A buyer discovers a compute offer, reviews its current terms, explicitly
authorizes contact disclosure, and retrieves an authoritative introduction.
The parties may continue off-platform. The introduction does not attest payment,
resource allocation, provisioning, or subsequent delivery.

Compute is the selected offer population, not a decision to restrict the market
to bare metal or to unify the current VM and bare-metal implementations.
API-credit introductions, hosted paid settlement, and off-platform completion
attestations are separate work. They do not gate this outcome by default.

### Agreed prospective-supply requirement

The first increment must support listing machines the seller does not yet have.
Restricting it to existing inventory would miss a central purpose of contact
settlement. The site authority owns the prospective supply declaration; extend
that authority where necessary rather than bypassing it. The storefront continues
to own commercial terms and contact settlement.

Prospective supply is not reservable capacity. A declaration must not require a
fabricated existing-machine binding, add allocatable capacity, or imply that the
machines exist. Completing an introduction neither changes those facts nor
attests later procurement or delivery. Existing capacity-admission guarantees
remain intact.

This is an agreed requirement and ownership direction for #219, not an implemented
capability. Its representation, lifecycle, and publication contract still need
OpenSpec design. It replaces the earlier choice between existing inventory and
seller declarations outside the site authority.

## Result

The contact mechanism, signed reveal endpoints, and durable completed-introduction
reads are reusable. The complete installed-buyer and production-publication path
is **not ready**. The material gaps are:

1. Rateless acceptance is not wired correctly through the installed buyer.
2. Production compute publication/startup still assumes existing physical inventory;
   prospective supply has no explicit supported representation.
3. Lost acknowledgements, interrupted completion, and concurrent retries lack a
   complete demonstrated recovery path.
4. Deletion is unexposed, and deleting the introduction row alone leaves contact
   copies in authenticated-response replay storage.

A new webhook service and the full hosted-payment redesign are not demonstrated
prerequisites. Authenticated pull remains a delivery choice. Site-owned prospective
supply is now required; its representation remains a design question.

## Evidence and limits

This was a read-only source/specification audit. **No behavioral tests were run.**
Test citations below describe assertions present in source, not successful runs.
No services, financial effects, or provisioning operations were exercised.

The earlier #184 inventory remains useful, with a terminology correction: direct
bare-metal introduction commands exist. That is different from registering
contact exchange in the generic buyer mechanism-selection registry. The latter
still excludes contact in the inspected VM composition.

### Discovery and production publication

The compute registry schema permits nonempty settlement options instead of legacy
escrows and filters on option mechanism. A schema-valid compute offer can
therefore advertise a rateless introduction without a funded rail. The schema
still requires its compute vocabulary; it does not accept arbitrary brokerage
prose as a compute offer.

- `core/registry/filter-spec.yaml:15-46,218-232`
- `core/registry/src/api/listing_routes.py:40-127,139-224`
- `core/registry/tests/unit/test_option_aware_filters.py:51-76`

`core/registry/filter-spec.introductions.yaml:15-40` declares a different schema,
`introductions.market`, with a smaller filter set. It is optional, not necessary
for introduction settlement and not an interchangeable profile inside a compute
registry. The bare-metal list command sends a virtualization filter absent from
that profile (`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:178-189`).

The bare-metal publication builder can construct a contact-only payload without
an escrow. However, the production runtime requires trusted site configuration
and creates capacity/fulfillment clients even when no financial mechanism is
enabled. The publication CLI obtains a live capacity snapshot; the domain schema
requires machine and physical-host identifiers.

- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py:116-168`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:325-430`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py:93-139,169-193`
- `domains/bare_metal/src/arkhai_bare_metal/schema.py:42-91`

These are publication/composition dependencies, not proof that revealing contacts
executes provisioning. The existing HTTP test injects a runtime without capacity
clients and inserts a listing before negotiating. Its builder test is not a
production publication path (`domains/bare_metal/storefront/tests/test_http_introductions.py:96-174,210-251`).

VM seller and buyer mechanism registries enumerate Alkahest and Stripe only;
VM does not inherit contact support merely by finding a contact option:

- `domains/vms/storefront/src/market_storefront/settlement_composition.py:264-270`
- `domains/vms/buyer/settlement_composition.py:121-134`

**Follow-up finding:** the site authority has operator-entered resource records,
but these are capacity buckets, not explicitly prospective supply. Registering a
resource writes a bucket with a backing-resource identity; its snapshot includes
enabled resources. The per-resource projection requires physical-resource identity,
and the grouped projection describes current capacity. The production inventory
adapter projects configured hosts. None of these inspected paths establishes a
prospective-supply contract.

- `kit/site/src/market_site/ledger.py:579-692`
- `kit/site/src/market_site/projections.py:88-195`
- `provisioning/compute/service/src/compute_provisioning_service/services/capacity_inventory.py:26-61`
- `openspec/specs/site-capacity/architecture.md#projection-boundaries`

The agreed direction is to extend site-owned declaration/publication for
prospective supply, keeping it distinct from admission of real capacity. An
arbitrary attribute or disabled bucket is not evidence of the required public
semantics. Exact representation and VM/bare-metal reach remain open; this does
not select domain unification (#196).

An adjacent defect is visible at publication: the mutation handler does not apply
the filter-schema validator used by the dry-run route
(`core/registry/src/api/listing_routes.py:40-127` versus
`core/registry/src/api/validate_routes.py:113-137`). A successful publish response
alone is therefore not evidence of schema eligibility. Track this as a registry
correctness finding; do not use it as permission to publish malformed inventory
or automatically expand the introduction epic into general discovery repair.

### Buyer review and acceptance

The bare-metal buyer contributes `request-introduction`, `introduce`, and
`introduction` commands. The first refreshes a signed registry listing and selects
an exact rateless contact option; the second supplies contact under an accepted
run; the third reads the persisted reveal.

- `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:633-742,777-834`
- `core/buyer/src/core_buyer/introductions.py:17-68`

There is a source-proven acceptance mismatch: the command calls
`negotiate_with_seller` without its advertised-option input. The shared client
compares the contact obligation's `amount=None` against the negotiated integer
amount and requires advertised semantics or an existing accepted plan. The
fresh-call amount fallback is zero for this command, not `None`.

- Caller: `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:683-700`
- Validation: `core/buyer/src/core_buyer/negotiation_client.py:403-415,773-782,970-985`
- Direct validator test supplies the missing inputs:
  `core/buyer/tests/unit/test_settlement_acceptance.py:130-189`

This is a bounded rateless-validation/caller-integration gap. Relaxing signature,
party, option, or plan validation would not be a valid repair.

The current command proceeds from refreshed listing to negotiation without a
separate interactive review checkpoint. Explicit `introduce --contact` is a
useful disclosure action, but the consumer must define what current offer/context
and contact content the human authorizes. Seller contact is taken from current
configuration at first start, not frozen at acceptance. The mechanism can carry
negotiated context; the bare-metal builder call does not supply that optional
context.

- `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py:168-187,255-260`
- `kit/contact-exchange/src/market_contact_exchange/settlement_config.py:319-340`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_service.py:554-563`

Registry-current review and an authenticated seller-preview requirement are
also different choices. The bare-metal seller's listing GET handlers do not
bind response authentication
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:317-360`;
`response_auth.py:71-88` in the same directory). Do not assume those reads supply
a signed preview or introduce a new preview API before deciding it is needed.

### Acceptance, reveal, and recovery

The seller HTTP tests perform signed negotiation from a seeded listing, then
start the introduction and read both parties' projections. This is stronger than
seeding an accepted agreement, but it bypasses the installed buyer and normal
publication. Core introduction-transport tests stub the signed HTTP seam.

- `domains/bare_metal/storefront/tests/test_http_introductions.py:132-207,254-348`
- `core/buyer/tests/unit/test_introductions.py:21-76`

POST start admits only the accepted buyer; GET admits either accepted party and
selects the contact half by authenticated principal. An integrating consumer can
use signed pull separately under each party's authority. It does not gain both
halves merely by knowing an obligation reference or changing a role label.

- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:191-272`
- `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py:216-243,306-331`

The local contact adapter already completes an amountless obligation through the
current runtime. Its synthetic introduction reference does not dispatch physical
provisioning. Escrow-shaped method names alone therefore do not establish a
required dependency on hosted-payment implementation.

- `kit/contact-exchange/src/market_contact_exchange/client.py:16-95`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/introduction_routes.py:117-149`
- `kit/settlement-runtime/tests/unit/test_non_financial_obligation.py:38-104`

Recovery is less complete than the happy path:

- Contact insertion and obligation registration/completion are separate commits.
  GET resolves the obligation before loading contacts; an interruption before
  registration can leave persisted contacts without a retrievable result.
- After registration, GET can return persisted contact without advancing an
  interrupted completion. The completion callback ignores returned operation
  outcomes, including a possible `busy` result.
- Contact-only composition creates no settlement worker. The hosted worker is
  not a safe drop-in: its ready callback invokes hosted fulfillment.
- Buyer recovery refreshes the original registry listing and authority binding;
  persisted server contact is not proof of recovery during listing removal or
  registry outage.

Evidence: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/introduction_routes.py:81-149`,
`kit/contact-exchange/src/market_contact_exchange/introduction_routes.py:255-269,306-331`,
`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:333-350,522-541`,
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:432-490`,
and `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:104-150`.

The existing restart assertion covers a completed start followed by GET, not
those interruption windows. Acceptance acknowledgement loss and the buyer's
pre-log window also need focused proof. #211 should settle any necessary shared
port boundary without turning the entire financial redesign into a gate or
silently approving a conflicting temporary abstraction.

### Delivery and deletion

Authenticated pull is available without a webhook service. Local sinks are
optional copies: the seller forwards the buyer half to the seller's own
configured destinations; the buyer forwards the seller half to theirs. The
webhook sink is an operator-configured POST, not a signed marketplace event
protocol (`kit/delivery/src/market_delivery/builtin/webhook_sink.py:22-78`).
A consumer choosing pull still owns its user-to-principal authorization and
notification behavior. Signatures do not replace confidential transport.

The current deletion helper removes only `contact_introductions`; its production
adapter and public route/CLI surfaces expose no deletion operation (#203).

- `kit/contact-exchange/src/market_contact_exchange/migrations.py:91-98`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py:35-40,88-117`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:253-272`
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py:37-103`

Exposing that helper alone would not satisfy removal of marketplace-held contact:

- Response middleware persists full reveal bodies in authenticated replay
  outcomes, independently of the introduction row.
- Exact semantic retries return that stored body before loading the introduction
  row. A retry still requires a valid current proof and allowed party principal;
  this is not anonymous access. Timestamp freshness does not limit storage
  retention because the same request can be re-signed.
- The completed replay lifecycle has no result-expiry/cleanup transition.
- After deleting only the row, fresh GET says the introduction has not started;
  fresh authorized POST can recreate it. No deletion marker distinguishes erased
  from never-started work.

Evidence: `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/response_auth.py:54-76,102-130`,
`core/storefront/src/core_storefront/sqlite_client.py:807-818,2580-2796`,
`core/storefront/src/core_storefront/auth.py:189-239`,
and `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py:236-269,306-331`.
These are source-traced consequences, not an executed deletion reproduction.

#197 needs a chosen retention trigger/window, deletion authority, and post-delete
read/start/retry/history contract. A deletion promise must distinguish stored
contact, replay copies, configuration, backups, and recipient-controlled delivered
copies. It cannot recall contact already disclosed. Preserve required settled
history and anti-replay protection rather than clearing the replay database as a
shortcut. No particular TTL, double opt-in rule, or durable delivery queue is
selected here.

## Candidate epic and decision gates

**Candidate:** complete one honest compute-introduction journey, reusing the
contact kit and signed discovery/reveal primitives. Its enabling changes can be
sequenced separately, but the usable outcome includes publication, buyer
acceptance, authorized disclosure, durable result access, and the selected
recovery/deletion contract.

Before writing implementation tasks:

| Gate | Choice to record | Existing decision owner |
|---|---|---|
| Prospective supply | Required and site-owned; design its representation, lifecycle and publication without creating reservable capacity; exact VM/bare-metal reach remains open | #219 and #191, with #196 only if an actual dependency is established |
| Review and disclosure | Authoritative reviewed context, drift handling, seller contact authorization, and when each party authorizes disclosure | #191 |
| Consumer delivery | Signed pull as the initial integration, or additional delivery requirements | #191 |
| Retention and deletion | Trigger/window, caller authority, post-delete history/retries, storage-copy boundaries | #197; implementation defect #203 |
| Shared lifecycle | Smallest coherent rateless acceptance/completion/recovery boundary consistent with the intended composition model | #211 |

An existing-inventory-only increment does not satisfy the selected requirement.
The site authority remains the owner even when supply is prospective; deployment
requirements for that mode still need design. No implementation readiness or new
dependency edge follows from this table.

## Validation needed for a usable increment

Follow `docs/development/TESTING.md`, not the current directory labels of older
tests. Pure option/amount validation belongs at unit level. Real client-to-app
acceptance, signature verification, state transitions, privacy, and deterministic
interruption/retry/delete races belong at application integration level.

A final installed-wheel, cross-service scenario must publish a real eligible
compute offer for machines the seller does not yet have, discover it through the
registry, negotiate through the installed buyer, reveal and re-read under the
intended principals, and exercise the accepted end-of-retention behavior. Prove
that neither declaration nor introduction creates reservable capacity or a false
physical-machine binding. Assert the absence of payment/provisioning effects;
do not substitute injected listing rows for publication evidence. Detailed race
permutations stay in integration tests rather than multiplying system lanes.

Readiness checks must cover both parties and outsider refusal, retained identity,
lost acknowledgements, changed/removed listings, leased operations, re-signed
replays after deletion, restart, and any accepted delivery mode. Build internal
wheels into `.dist` and explicitly reinstall changed consumers before attributing
results. No editable sibling imports or fabricated physical bindings.

The owning permanent homes are already
`openspec/specs/contact-exchange-settlement/spec.md`,
`openspec/specs/introduction-delivery/spec.md`,
`openspec/specs/buyer-orchestration/spec.md`,
`openspec/specs/settlement-configuration/spec.md`, and
`openspec/specs/marketplace-identity/spec.md`. Prospective-supply design must also
name promotion into `openspec/specs/site-capacity/spec.md`, its companion
`openspec/specs/site-capacity/architecture.md`, and
`openspec/specs/storefront-publication/spec.md`, with repository-wide composition
rationale in `docs/development/ARCHITECTURE.md` as applicable. Future accepted
changes must name any additional domain owners, exact companion-architecture promotion,
roadmap/campaign impact, and the closeout required by `openspec/README.md`.
This snapshot does not promote unimplemented behavior into those documents.
