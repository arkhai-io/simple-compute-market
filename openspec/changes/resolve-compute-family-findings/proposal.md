## Why

Moving provisioning execution into the compute family kit, composing bare metal
onto the kit negotiation runtime, and running a bare-metal deal in the pipeline
surfaced defects and dead surfaces that were outside that work's scope. Each is
small; together they are the compute family's known debt.
`bare-metal-mock-provisioned-deal` (archived) recorded them as it found them.

Design checked every recorded item against the code. Some had been resolved since,
some belong to other changes, and the rest are below. The design also found defects
the record missed: a reveal whose first completion failed never reaches the seller's
delivery sinks, a deferred bare-metal fulfillment is rechecked on a backoff that grows
to thirty minutes, a single Alkahest address book is applied to every chain when
claims are serviced, and the configuration-migration tool retires the address-book key
everything else still reads.

The substantive gaps the record found — host-secret protection, failure
classification, guest network isolation, disabled-host admission, a relay lane, the
administrator stance, lease start policy, and pricing an escrow that names no
contract — are roadmap gaps rather than part of this change.

## What Changes

`design.md` records each decision; the labels below are its.

Route answers and typed surfaces:

- A request matching no route contract is answered unsigned by what failed to match:
  404 for an unknown path, 405 with `Allow` for a known path under another method, 400
  for a route whose body resource cannot be bound; overlapping route patterns are
  refused when the table is composed. Both the provisioning service's middleware and
  `kit/site`'s do this, and the family client and the site client report an
  unauthenticated answer as such, naming its status (D3).
- Bare metal's and VM's mock-rule routes return typed responses and each domain gains
  an extension client; the remaining worker controls return typed responses (D14,
  D15). VM binds pool overrides at `POOL_OVERRIDES_PATH` (D16).

Dead or senderless surfaces removed:

- The VM storefront's four fulfillment callbacks with no production sender —
  `started`, `usage-started`, `release-started`, `failed` — with their models, client
  methods, operation-map and OpenAPI entries, and tests; the lifecycle-events
  requirement describes the `capacity_released` event provisioning sends (D4).
- `ReservationState.provisioning` and `provisioning_failed`, which nothing writes, from
  every reader and the lease contract, with an upgrade conversion of any stored row,
  and the guard-free `update_reservation_state` (D5).
- `find_active_lease_by_vm_target` and the `vm_target` payload key (D21); the VM
  storefront's unread `[provisioning] mode` from settings, the chart, the runbook, and
  the quickstart (D22).
- `kit/policy`'s broken `market-policy` RL training CLI and its training dependency
  settings, carried into `repair-rl-training-tooling` (D7).

Behaviour that answers wrongly:

- A bare-metal status or result read whose site reports a delivery other than the
  recorded one answers a typed 409 rather than a 500 (D12).
- Bare-metal begin reads the scheduled resource's own physical identity, and the
  schedule response names its host, so a declaration that does not repeat them in its
  publication settings can be fulfilled; the compute provisioning contract becomes major
  3, accepted alone, carrying the host and the removed lease state (D13, D5).
- VM's operator `create_vm` refuses a guest name provisioning's rules reject (D17).
- The policy kit's refusals name `[negotiation].policies` and where built-ins come
  from (D18); fulfillment convergence prints its counts (D19).
- Bare metal's servicing worker reports its events, every scheduled retry is logged, a
  deferred delivery, recorded as such in the operation journal, is rechecked every
  servicing cycle, and the settle wait polls through a failed status read (D8).
- An introduction's seller-side delivery is dispatched at most once, claimed by the
  start that completes the reveal, and no buyer request makes it send again; a new
  start completes an interrupted reveal (D9).
- A seller's wallet address and key name one account, as an Alkahest readiness rule;
  the address is derived when absent (D10).
- Alkahest address books are named per chain in `[Settlement.alkahest.address_books]`,
  for storefronts and buyers (D11).

Placement:

- The VM-owned relay, port, pool-configuration, and codec suites move into the VM
  adapter, with the relay port-lease index declared on its model (D20).
- The provisioning service's migration modules keep naming VM's tables, with the
  reason documented (D6).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: reservation states; the site middleware's unmatched-route answer and
  the site client's report.
- `physical-provisioning`: the provisioning middleware's unmatched-route answer and the
  family client's report; operator guest names; the typed worker-control and mock-rule
  models and the domains' client extensions.
- `compute-provisioning-contract`: the lifecycle event provisioning sends; the schedule
  response's host and physical identity; contract major 3.
- `market-composition`: the mock rule routes' typed answers.
- `storefront-publication`: the bare-metal delivery conflict and begin.
- `settlement-servicing`: deferred delivery, retry reporting, and the settle wait.
- `introduction-delivery`: at most one seller-side dispatch, claimed by the completing
  start; an interrupted reveal completed by a new start.
- `settlement-configuration`: wallet address and key; Alkahest address books.

## Non-Goals

- The roadmap's substantive gaps listed under Why.
- Separate payout accounts (a multisig or treasury receiving Alkahest settlement apart
  from the signing key): an unowned Goal 6 gap. This change states the current rule,
  that the published recipient and the signer are one account.
- Signing an unmatched request's answer, binding a request's audience, and naming its
  operation in the request: `redesign-authenticated-requests`.
- A signed answer to a route that raises after authentication:
  `unbacked-bare-metal-listings`.
- Reservation idempotency and release by escrow: `capacity-reservation-lifecycle-hardening`.
- One opening-selection rule for both compute storefronts: `move-escrow-into-alkahest`.
- `kit/site`'s route surface: `site-route-contracts`.
- Repairing RL model training: `repair-rl-training-tooling`.
- Per-adapter migration chains in the provisioning service; see `design.md`'s open
  question.
- Should anything come to act on a reservation's recorded executor target, a
  deliberate operation to resolve a reservation whose recorded target differs from its
  fulfillment's is needed with it; nothing does today.

## Dependencies and Related Changes

- Follows `bare-metal-mock-provisioned-deal` (archived), which recorded the items.
- Its second implementation round waits for `unbacked-bare-metal-listings`, whose
  unmerged work changes the same files: both authentication middlewares, bare metal's
  deal controls and servicing composition, `kit/alkahest/settlement_config.py`, the
  worker controls, VM's admin controller, and an e2e scenario. The first round does not
  wait.
- Coordinates with `hollow-pre-floor-provisioning-migrations` (the legacy-backfill
  import; the relay port-lease index), `kit-owned-listing-and-fulfillment-lifecycles`
  (the deferral cadence its pending outcome inherits), and `pools-7-storefront-fulfillment-cutover`
  (`terminate_vm_lease` stays as that change's required plumbing).
- Opens `site-route-contracts` and `repair-rl-training-tooling`; expands
  `redesign-authenticated-requests` (renamed from `redesign-authenticated-replay-state`);
  finds `service-identity-signing` delivered and archives it as such.

## Impact

`provisioning/compute/` (contracts, client, service middleware, migrations, worker
controls, convergence), `kit/site`, `kit/site-client`, `kit/policy`, `kit/alkahest`,
`kit/config`, `kit/settlement-runtime`, `kit/contact-exchange`, `kit/storefront`,
`core/storefront-client`, `domains/vms/` (storefront, provisioning adapter and client,
buyer, training README), `domains/bare_metal/` (storefront, domain package, buyer),
`domains/apicredits/` (storefront, buyer), e2e scenarios and harness, the storefront and
bare-metal Helm charts' values, and the seller and buyer quickstarts.

Wire: removed VM callback routes and client methods; reservation states and
`LeaseState.PROVISIONING_FAILED` removed; `host_id` on the schedule response; compute
provisioning contract major 3, accepted alone, so provisioning and its storefronts
upgrade together; typed
mock-rule and worker-control responses; unmatched-route statuses. Configuration:
`[Settlement.alkahest.address_books]` replaces two keys; `[Wallet].address` becomes
optional for a seller. Persistence: a reservation-state conversion in the provisioning
and API-credits services' migration chains; a seller-delivery marker on introductions.
Each is a minor bump of its package under the repository's pre-1.0 versioning policy.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Unmatched-route answers and the clients' report of an unauthenticated answer →
  `openspec/specs/physical-provisioning/spec.md`, `openspec/specs/site-capacity/spec.md`;
  why an unroutable request is unsigned →
  `openspec/specs/physical-provisioning/architecture.md`, "Canonical requests, durable
  replay, and signed responses" (D3).
- The lifecycle event provisioning sends; the schedule response's identities; contract
  major 3 → `openspec/specs/compute-provisioning-contract/spec.md` (D4, D13, D5).
- Typed worker-control and mock-rule models owned by the contracts distribution, and the
  domains' client extensions → `openspec/specs/physical-provisioning/spec.md`, "Compute-owned
  caller contract"; the rule routes' typed answers →
  `openspec/specs/market-composition/spec.md`, "Compute mock executors share one
  compute-family mechanism" (D14, D15).
- Reservation states and their upgrade conversion → `openspec/specs/site-capacity/spec.md`
  and `architecture.md` (D5).
- The service's migration history names the tables its database holds →
  `openspec/specs/physical-provisioning/architecture.md`, "Compute composition" (D6).
- Deferred-delivery cadence and its journal record, retry reporting, the settle wait →
  `openspec/specs/settlement-servicing/spec.md` (D8).
- At-most-once seller dispatch by claim, and no counterparty-triggered re-send →
  `openspec/specs/introduction-delivery/spec.md`; the buyer-retry limit and why a new
  start, not a replay, completes a reveal → a new architecture companion for
  `contact-exchange-settlement` (D9).
- Wallet address and key; address books → `openspec/specs/settlement-configuration/spec.md`,
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, the seller, bare-metal seller, and buyer
  quickstarts (D10, D11).
- Bare-metal delivery conflict and begin → `openspec/specs/storefront-publication/spec.md`
  (D12, D13); operator guest names → `openspec/specs/physical-provisioning/spec.md` (D17).
- Before 1.0, an incompatible change to anything a package publishes is a minor bump,
  and a versioned contract is versioned rather than changed in place →
  `docs/development/RELEASING.md`, "Versioning policy"; a pointer in
  `docs/development/ARCHITECTURE.md`, "Operators"; one sentence in
  `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration".
- The roadmap: Goal 1's row for this change; Goal 6's unowned payout-account gap →
  `docs/development/ROADMAP.md`.
