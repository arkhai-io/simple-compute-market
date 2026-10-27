# Design: resolve compute family findings

## Context

`bare-metal-mock-provisioned-deal` (archived 2026-10-09) recorded, as it found them,
small defects and dead surfaces in the compute family and the kits around it. This
change takes them. Design checked each against the code at `421eeac` on `dev`, and
against the unmerged work on `unbacked-bare-metal-listings`' branch, which changes many
of the same files.

Four recorded items no longer hold:

- Bare metal's listing recheck and publication read held projections
  (`listing_source_check.py`, `publication.py`) since `share-site-projection-state`.
- The provisioning integration harness is file-backed with a connection per session
  (`provisioning/compute/service/tests/integration/conftest.py`).
- The bare-metal Compose wrapper mounts the operator's whole `storefront.toml`, and the
  chart passes `config` through, so an operator sets `negotiation.policies`; unset, the
  chain is the deliberate default. Running pipeline scenarios against the charts is
  `helm-e2e-pipeline-parity`'s.
- `terminate_vm_lease` is plumbing `vm-storefront-fulfillment` requires ("Early
  lease-termination client plumbing remains available"), added deliberately by
  `pools-7-storefront-fulfillment-cutover`.

Several recorded items were also stated wrongly. The unmatched-route answer is an
unsigned 404, not a 500; the 500 that remains is a route raising after authentication.
The family route contracts carry regexes, not path templates. Health, status, and
version are typed; only the worker controls and identity rotation are not. VM's mock-rule
routes are as untyped as bare metal's. The adapter bundle does not carry routers. The
`market-policy` CLI is broken as well as misplaced. The decisions below rest on the
corrected facts.

## Decisions

### D1. Scope: what this change keeps

Kept: every item below. Dropped as resolved: the four above. Handed to the change whose
subject each is:

- one opening-selection rule for both compute storefronts → `move-escrow-into-alkahest`,
  which redraws the settlement carriers (escrow fields as option parameters, the Agreement
  as the complete settlement input); fixing it here would choose a carrier rule that
  change replaces;
- reservation idempotency and release by escrow → `capacity-reservation-lifecycle-hardening`,
  which already adds a negotiation identity as `reserve()`'s key and modifies the same
  `site-capacity` requirement;
- a signed 500 for a route that raises after authentication → `unbacked-bare-metal-listings`,
  its decision 23;
- `kit/site`'s route surface (its own FastAPI router, its contracts declared in
  `kit/site/auth.py` and `kit/site-client` and held by a parity test) → a new change,
  `site-route-contracts`. It creates a contracts package, changes two composition roots
  and `ARCHITECTURE.md`'s route-contract section, and nothing else here depends on it.

The family route contracts keep regexes, with the client's paths, the controllers'
decorators, and the contracts held together by `test_route_binding.py`;
`ARCHITECTURE.md` already accepts a binding that repeats its contract's path under such a
test.

Rejected: keeping everything here, which would put two acceptance boundaries in one
change and edit a requirement `capacity-reservation-lifecycle-hardening` also modifies;
keeping `kit/site`'s surface as a round of this change.

### D2. Sequencing against `unbacked-bare-metal-listings`

That change's branch holds substantial unmerged work in files this change edits. A
decision is implemented in the first round only where its overlap with that branch is a
package's version line, a lock file, or a hunk that touches none of the branch's hunks;
every other decision waits for the second round, after the branch lands (35 F3). Version
lines are nearly unavoidable, since each incompatible change bumps its package and the
branch bumps most of the same packages; the branch's `RELEASING.md` resolves them, a
change bumping a package at most once against its target branch. Planning derives the
partition from the branch's diff against its merge base, not from this list, and names
each file a first-round section shares with the branch and why it merges mechanically.
The wait is partial, so it is recorded in the index's `Notes`, not `Depends on`. Planning reads the branch so the plan cites what is already
written there; in particular it types the worker pause and resume routes
(`WorkerPauseResponse`), wraps both middlewares' dispatch for a signed 500, and rewrites
`kit/alkahest/settlement_config.py`'s readiness blockers.

Rejected: gating the whole change on it, which would hold the independent fixes.

### D3. A request matching no route contract

`ProvisioningAuthMiddleware` resolves the route before authentication and answers every
resolution failure with the same unsigned 404 (`middleware/auth.py`), for four different
cases; `kit/site`'s middleware does the same for three of them. The answer becomes:

| Case | Answer |
|---|---|
| The path matches no contract | 404 |
| The path matches a contract under another method | 405 with `Allow` naming the contracts' methods |
| The route matches but its body resource is absent or not a string | 400 naming the field |
| Two contracts claim the method and path | Unreachable in the provisioning service: composing its route table refuses overlap between contributions |

Overlap is decidable because a route contract's pattern is restricted (35 F7): literal
path segments, `[^/]+` named captures, and finite alternations of literal segments, as
`identity/rotations/(?P<trust_role>admin|seller)` is, optionally ending in `/?`, an
optional trailing slash (55 F1). Building a contract from its declaration refuses any other
pattern. `ProvisioningRouteTable` compares contracts of different contributions segment by
segment when it is composed, a pattern ending in `/?` compared as both its forms, and
refuses two whose method and segments can match one request, before the service accepts
traffic; within one contribution the first matching contract still decides, in the order
its owner gave. The family's `jobs/?` and `hosts/?`, VM's `vms/?` and `relays/?`, and the
resource-pools contribution's `pools/?` use the slash, and the clients send the slashed
form, so no served path or signed operation changes. Every route pattern in the tree fits
the grammar once VM's two relay declarations drop a terminal `$`, which full matching
makes redundant. A unit test of the provisioning composition root builds the complete
table, the family's routes and every contribution the service ships (VM, bare metal,
resource pools, Ansible host import, capacity definitions), under the grammar and the
overlap check.

The grammar is written here only while it stays this small (55 F1). A route needing more
— a tail capture, a typed segment — does not extend it: the contracts adopt an
established path-template grammar and its matcher, imported rather than written here, and
the overlap comparison is rebuilt on it. Rejected: migrating the optional slashes to one
literal form, which would answer 404 to unslashed requests that authenticate today and
touch three owners' declarations for no gain in the comparison. `kit/site`'s middleware resolves first-match
over the one ordered table it is given, which the API-credits service extends with its own
routes, so it has no ambiguous case; whether it gains contributions is
`site-route-contracts`' question. Rejected: detecting ambiguity per request and answering it
as an unsigned 500 (a mis-composed service starts and fails on exactly the overlapping
requests).

Route resolution in both contracts packages reports which case failed through a typed
error rather than a bare `ValueError`. The answers stay unsigned. A response proof binds
the method, operation, resource, request identity, status, and body
(`_signed_response_headers`), and a client verifies against its own operation and
resource; the server knows no operation for the first two cases and no resource for the
third, and a request's headers carry a signature over its operation, not the operation.
The family client (`compute_provisioning_client/base.py`) and `kit/site-client` report a
refusal of an answer that carried no response authentication as such (35 F11): the report
names the status and that the answer was unauthenticated, and contains no part of the
response body, no header value, and no credential. It is the rule
`name-unverifiable-responses` states for storefront clients, stated here for these two.
They report a malformed or wrong signature as they do today.

The family client resolves its own table before sending, so it meets these answers only
when its table and the service's differ; the e2e harness's hand-built clients and an
operator's own requests meet them directly.

A request that names its operation in a header, so an authority can sign "operation not
served" over the caller's own claim, and binds its audience, so a request signed for one
authority is refused by another, belongs to the expanded `redesign-authenticated-requests`
(renamed from `redesign-authenticated-replay-state`), whose subject is every authority's
authentication. The answers above are what it would later sign.

Rejected: signing the answer now (a request-envelope change in `kit/identity` and every
client); changing only the clients' messages; leaving `kit/site`'s middleware for
`site-route-contracts` (the rule is one rule for both).

### D4. The VM storefront's senderless fulfillment callbacks are removed

`/api/v1/admin/fulfillment/events/{started,usage-started,release-started,failed}` have no
production sender: provisioning sends only `capacity_released`
(`services/deal_event_sink.py`). They are reached only by a site's service peer, through
the service-peer middleware, despite their administrator path. The first three close
listings that no longer fit, which the capacity-events and publication loops already do
on every capacity delta. `failed` runs the configured failure policy, which VM's pull
path already runs when it reads a failed fulfillment, and it takes the escrow from the
request body (`escrow_uid = body.escrow_uid or …`), so a site's service peer could name
another deal's escrow and, with `refund` configured, trigger its refund.

Removed: the four routes, their request models, `notify_usage_started` and
`notify_fulfillment_failed` in both typed clients, their entries in the service-peer
operation map and the OpenAPI callback set, their tests, and the e2e stage that tests
`usage-started` itself. Kept: the failure policy, its unit and pull-path tests, and
`capacity-released`. `compute-provisioning-contract`'s "Deal-scoped lifecycle events"
describes what provisioning sends and what crosses the wire (35 F4): the `LifecycleEvent`
model is the provisioner's internal record and is never sent; the provisioner calls the
storefront's capacity-released callback, a `service`-role signed request carrying the
reservation ID, the site ID, and the release time when known, under a request identity
derived from the release's stable event identity, and retries it from its durable outbox
until acknowledged. The requirement states the sender's obligation and names the callback
as its target; the route itself is the storefront's. The callback stays under an
administrator path, which the argument below applies to as well; moving it is a known
limit left to `replace-polling-with-authenticated-push`. `docs/configuration.md`
describes the failure policy as the pull path's.

Push delivery (`replace-polling-with-authenticated-push`) would not reuse these: it
delivers capacity deltas, projection invalidation, and fulfillment status from an outbox,
each with a stable event identity the requirement demands and these bodies lack, and an
authority-to-storefront channel does not belong under an administrator path.

Rejected: keeping them as the push surface; keeping `failed` as an operator lever (an
operator-driven failure path would be an administrator route keyed by negotiation,
designed as one).

### D5. Reservation states nothing writes are removed

`ReservationState.provisioning` and `provisioning_failed` (`kit/site/src/market_site/db.py`)
are never assigned, yet held-state sums, the lease transitions, the terminal sets, the
lease-state projection, VM's interrupt and release code, and API credits all decide about
them. Both members go, with every reader, the lease contract's
`LeaseState.PROVISIONING_FAILED`, and the mapping entries. `site-capacity` states the
remaining states. Removing a lease state changes the compute provisioning contract, so it
is part of that contract's major 3 (D13).

The column is a plain string, so no schema change is needed, but a stored row in either
state would change behaviour silently: a `provisioning` row would stop counting as held,
and a lease read of either would raise. The provisioning service's and the API-credits
service's migration chains convert any such row:

- `provisioning` becomes `unmanaged`, whose capacity stays held until an operator repairs
  it, with a failure reason naming the legacy state;
- `provisioning_failed` becomes `force_released`, whose capacity stays free as it is now,
  with a failure reason naming the legacy state.

Each conversion keeps the row's capacity effect exactly. Where no such row exists the
migration changes nothing.

`CapacityLedgerService.update_reservation_state` and its authority-protocol entry go: a
generic state writer is the one way a reservation can enter a state its lifecycle
forbids, and only tests call it. Tests reach a state through the real transitions or seed
the row, which `TESTING.md` permits for state no API expresses.

Rejected: refusing the upgrade while such rows exist (an upgrade stopped on data an
operator may not understand); keeping both as legacy states nothing writes; keeping
`provisioning` for starting a lease on activation (Goal 5's unowned gap), which is not
near and would define its own state.

### D6. The service's migration modules keep naming VM's tables

`db/database.py` creates VM's metadata, and `db/migrations.py` creates and evolves
`ansible_pool_configs` (`20260713_002`, and `_migrate_vm_pool_playbook_optional`, which
rebuilds it from VM's current model) and runs VM's legacy lease conversion
(`20260724_001`). `deployment-state`'s "Service-owned migration history" requires the
migration entrypoint to receive only its database. The service's database holds VM's
tables, and its migration history is the record of how they were created and evolved, so
it names them. This change documents that allowance in `physical-provisioning`'s
architecture companion and corrects the comment at `database.py` claiming the module
imports without the adapters. The closeout of `pools-7-storefront-fulfillment-cutover`,
which landed on `dev` (`1e5ba29`) after this design, already moved those imports to
module level and removed the comment, so implementation only confirms it is gone.
`hollow-pre-floor-provisioning-migrations` removes the legacy-backfill import with the
data rewrite it serves.

Rejected: injecting VM's schema from the entry point (it relocates the import and amends
a requirement promoted days before); per-adapter migration chains now (one domain owns
provisioning-side tables; see Open Questions).

### D7. The RL training CLI leaves `kit/policy`

`kit/policy`, a published foundation kit, ships `market-policy`, which shells out to
`domains/vms/training/`. It cannot run: `REPO_ROOT = parents[3]` resolves to `kit/`, its
default models directory does not exist, and from a wheel no repository path resolves.
Nothing in a Makefile, CI, or image calls it, and `domains/vms/training/README.md`
describes directories and targets that no longer exist.

This change removes from `kit/policy` the console script, `cli.py`, the `training`
dependency group, the `[tool.uv]` pufferlib build settings and CPU torch index, and the
CLI clause in the package description, and drops `market-policy` from `RELEASING.md`'s
console-script examples; `typer` stays, for `buyer_policy.py`. The training README is
cut down to what exists. The removed material is carried verbatim, as Markdown, in a new
change, `repair-rl-training-tooling`, which is expected to give the training scripts a
runnable, unpublished tooling project. Neither change depends on the other.

Rejected: moving the CLI into the published `arkhai-vms-negotiation` (the same defect in
a new place); deleting the training tooling outright.

### D8. Bare-metal settlement servicing

Three parts.

1. **Reporting.** Bare metal composes an `on_event` for its servicing worker, writing the
   `claims` stage events VM's composition writes (`settlement_composition.py`). The kit's
   worker logs every scheduled retry at warning, naming the obligation, operation, and
   error, so a failing step is recorded with or without a callback. The API-credit
   storefront composes the same worker with no callback, so it composes one too:
   `settlement-servicing`'s "Every failing servicing step is reported" requires a callback
   of each storefront that composes the worker.
2. **Deferred delivery.** Bare metal's ready hook defers while the lease is not yet
   active (`alkahest_lifecycle.py`); each deferral counts as an attempt, so the next try
   follows the error backoff, 30 s doubling to 30 minutes, and evidence publication, and
   with it the seller's collection, can lag activation by up to half an hour. In
   production nothing wakes it: the only wake is in the administrator's settle wait.
   `kit/settlement-runtime` therefore treats a deferral as not a failure: it does not
   count as an attempt, and a deferred obligation is rechecked on the next servicing
   cycle. Only bare metal defers today.

   The operation journal records the wait (24 F4). A ready hook whose delivery is not yet
   active calls `SettlementRuntime.defer_fulfillment`, which in one journal write releases
   the fulfillment lease, returns the attempt `reserve_fulfillment` counted, marks the
   operation *awaiting delivery*, and makes it due at once. After the hook returns without
   a fulfillment reference, the worker reads the operation, as its scheduling already
   does: an operation awaiting delivery keeps its due time and takes no backoff; any other
   operation still pending takes the error backoff as today, and a hook that raises
   stays on the error path.

   The mark is a flag on the operation, `awaiting_delivery`, added to
   `settlement_operations` by the runtime's own migrations, and the operation's state
   stays `pending` (35 F5). The worker's due query, `schedule_settlement_retry`, and
   `wake_settlement_obligation` all select `pending` operations, so they are unchanged,
   and only `defer_fulfillment`'s write and the worker's post-hook read learn the flag;
   any later write that leases the operation clears it. A release that predates the flag
   ignores it and reads an ordinary pending operation, due now with its attempt returned,
   and backs it off as today: rollback degrades to today's cadence and never strands an
   obligation. Rejected: a new state value, which an older release's due query would
   never select again, so every deal awaiting delivery would stall after a rollback. The hook's signature is unchanged, and `service_obligation`
   behaves as a sweep does. Rejected: a typed outcome returned by the hook, which is a
   second signal that must agree with the lease it released and still needs a journal
   write to return the attempt. The administrator wait keeps its wake, which a
   scenario holding the loops needs, so `storefront-publication`'s scenario is unchanged.
   This is distinct from `settlement-servicing`'s deferred fulfillment *outcome*, which a
   domain's own convergence finishes and for which servicing is not woken; the journal
   mark has its own name so the capability uses one word per concept, and the
   deferred-outcome requirement says which of the two wakes servicing. `kit-owned-listing-and-fulfillment-lifecycles`,
   whose proposed start path has a domain answer "pending", inherits the cadence.
3. **The settle wait.** `SettlementAdminRouteService.wait` treats a failure of its status
   read as a non-terminal poll, keeps polling until its deadline, and returns the last
   error beside `ready: false`, for VM and bare metal alike.

Rejected: moving the wake into `BareMetalFulfillmentService.status` (it helps only when
someone reads status); handing the cadence to `kit-owned-listing-and-fulfillment-lifecycles`
with this change depending on it (that change is undesigned and behind
`kit-owned-storefront-shell`).

### D9. An interrupted introduction reveal

`IntroductionRouteService.start` judges a first reveal by whether a record existed before
the call, and delivers to the seller's sinks only then. A first call that persisted the
record and then failed completion answers 503 before delivering; a retry finds the record,
completes, and skips delivery, so the seller is never told.

The introduction store gains a seller-delivery claim (24 F1). Once completion succeeds,
the start claims it with a conditional write that succeeds for exactly one caller, and
only the start that wins schedules the seller's delivery; any other start, concurrent or
later, skips it. Each introduction therefore has at most one seller-side dispatch, made by
the start that completes the reveal. The claim records that dispatch was scheduled, not
that a sink received anything: a dispatch lost to process exit, or failed at every sink,
is recovered by the operator's re-delivery, as a failed send is today, consistent with
delivery being best-effort beside the durable reveal. A claim write that fails after
completion succeeded answers 503, and the buyer's next start claims it. The claim also
closes the race in which two concurrent first starts both find no record and both deliver.

The claim is a row in its own table, keyed by the introduction's obligation reference, and
taking it is an insert that succeeds for one caller (35 F6). It is not a column on
`contact_introductions`, whose `contact_introductions_redaction_only` trigger refuses every
update but the one-way payload redaction; that trigger is how a revealed row is kept from
being rewritten or un-redacted, and the claim leaves it untouched. No deployment holds an
introduction revealed before the claim exists, so the migration creates the table empty.

Seller-side delivery is never a counterparty's lever: a buyer repeating starts, by mistake
or deliberately, cannot make the seller's sinks send again. Re-delivery stays the seller
operator's explicit action, and the buyer's own copy is sent by the buyer's own process.

Completing an interrupted reveal stays the buyer's, by a new start (24 F2). Completion is
local, idempotent bookkeeping, and the durable reveal record is what matters to either
party; finishing it without the buyer would hand the seller the buyer's contact while the
buyer saw a 503. A new start carries a fresh request identity, as the buyer client gives
every start, and reaches completion. An exact replay of the failed request answers its
recorded 503 and completes nothing, as every route answers an exact replay; resuming
completion on a replay would break that rule for a case a new start already handles. The
503's detail says to start the introduction again, and the limit is documented.

Rejected: delivering on every start that completes the reveal, which hands the buyer a
way to make the seller's sinks send again; a durable delivery outbox with sink-level
idempotency, which would make best-effort delivery guaranteed at the cost of a servicing
loop and an idempotency duty on every sink; a sweep that completes and delivers without
the buyer; handing completion to `kit-owned-listing-and-fulfillment-lifecycles`.

### D10. A seller's wallet address and key name one account

The address is what published release conditions name as the recipient, and the key
signs every chain transaction: the fulfillment attestation, `collectEscrow`, reclaim,
arbitration requests, VM's oracle decisions, and refunds. Under the `recipient` model a
mismatch makes collection revert after delivery; under `oracle_gated` collection pays the
key's account, not the named one; and the oracle-is-not-the-seller check compares only
the address. No storefront refuses a mismatch: API credits' check
(`resolve_evm_wallet`) has no caller.

A mismatch is an Alkahest readiness blocker, `alkahest.wallet_address_mismatch`, in
`kit/alkahest`'s wallet blockers, for every storefront; an absent seller address is
derived from the key with `kit/config`'s `derive_wallet_address`; the oracle check
compares the oracle with the signing account as well as the address. API credits passes
its wallet to readiness, and `resolve_evm_wallet` goes. This follows
`unbacked-bare-metal-listings`' decision 19: configuration under which Alkahest cannot
settle makes Alkahest unready and leaves the storefront running.

The rule states what holds today, that the published recipient and the signer are one
account. A seller paid to a separate account (a multisig or treasury) needs a payout
setting, attestations naming that recipient, and refunds from it; that is an unowned
Goal 6 gap. Buyers keep their deliberate tolerance of a mismatch.

Rejected: a startup refusal (the wallet serves only Alkahest); a warning, as buyers have.

### D11. Alkahest address books are named per chain in the Alkahest section

An address book is one deployment's contract addresses, overriding the SDK's built-ins
for a chain such as Anvil. `[Chains.<name>].alkahest_address_config_path` is read by
client construction, publication, release conditions, escrow verification, VM's refunds
and escrow CLI, and every buyer; `[Settlement.alkahest].address_config_path` is read by
the conditional-escrow client, which applies one path to every chain when servicing
claims, and by readiness. A seller on two chains has claims serviced against the wrong
book. The configuration-migration tool moves the per-chain key into the section key and
refuses the per-chain key, which everything else reads.

Configuration:

```toml
[Settlement.alkahest]
enabled = true

[Settlement.alkahest.address_books]
anvil = "/etc/arkhai/alkahest/anvil.json"   # a chain not listed uses the SDK's built-in addresses

[Chains.anvil]
rpc_url = "http://anvil:8545"
chain_id = 31337
```

The map is Alkahest-owned and per chain, so `[Chains]` holds only chain resources, as
`settlement-configuration` requires. Readiness refuses a map key naming no configured
chain. A chain's book is resolved through one `kit/alkahest` operation, which answers
nothing for a chain using built-in addresses, so no caller reads the map. Only composition
roots, the storefronts and buyer CLIs, call it (35 F9): they pass the resolved
chain-to-book mapping as data to the negotiation, policy, and codec packages, which keep
their current `chain_config_paths` parameters and gain no `kit/alkahest` call.
`arkhai-kit-policy`, `arkhai-vms-negotiation`, and `arkhai-kit-storefront` reach
`kit/alkahest` through scope exceptions `move-escrow-into-alkahest` owns, and no new
dependency of that shape is added while they stand. `kit/config`'s `ChainSettings` loses the field. Both old keys are
refused with a diagnostic naming the map, and the migration tool moves either into it: a
per-chain key to its chain, and the section key to the one configured chain, or to the
chains whose per-chain keys name the same book; where it cannot tell which chains it
served, migration refuses and names both keys.
`[Settlement]` is strict, so a release that predates the map refuses it; under the
pre-1.0 policy the change is a minor bump of each package that reads it.

Rejected: per-chain only (it keeps mechanism data in the shared chain table, against the
rule); one section path (it cannot express two chains); both keys required to agree (the
section path still covers every chain).

### D12. A bare-metal delivery conflict answers 409

When the site reports a delivery that differs from the write-once recorded result, the
store raises `StorefrontDomainBindingError`, which no handler maps, and the status read
answers 500; no restart is needed. The status, result, and access routes answer a typed
409, `delivery_conflict`, and the recorded result stands. The servicing ready hook keeps
retrying, now logged (D8).

### D13. Bare-metal begin reads the scheduled resource's own identity

Begin requires a nested `bare_metal_publication` repeating the terms' host and physical
machine, which `site-capacity`'s "Cross-mode physical accounting" forbids a declaration's
publication settings to repeat; a conforming declaration fails begin. Begin compares the
scheduled resource's `physical_host_id`, read from its top-level attributes, and a
`host_id` the schedule response now carries, from the declaration. The e2e driver stops
declaring the nested copies.

The response's `host_id` is optional, absent when the declaration names no host (35 F8).
`SettlementResource.host_id` and the stored assignment's host are optional, and the
scheduler places a hostless declaration, and returns a hostless assignment unchanged, in a
pool whose provider needs no host; a required field would fail the response's validation
on exactly those resources, an idempotent repeat of an older assignment included. Bare-metal
begin refuses an absent or different `host_id`, or a different `physical_host_id`, as a
conflict with its terms.

The response is a versioned contract, so it is versioned rather than changed in place
(24 F3). The compute provisioning contract becomes major 3, carrying the schedule
response's `host_id` and D5's removed lease state, and every party accepts only
major 3, as major 2 replaced major 1. A major-2 schedule response names no host, which
bare-metal begin would otherwise refuse as a conflict with its terms rather than by
version; versioning makes a mismatched pair a refusal that names the cause. The provisioning service, the storefronts, and the
family and domain clients of a deployment upgrade together, and roll back together; a
mismatched pair refuses each request, naming the supported major, as "Explicit contract
incompatibility" requires, rather than failing begin on a missing field. Rejected: a minor
2.1 with a new minor-version check where bare metal needs it, which allows a mixed rollout
of the schedule response but adds a check the contract has no machinery for and leaves
D5's enum removal unversioned.

### D14. The mock mechanism's routes are the family's, typed and mounted by each domain

The rule routes and the evaluate-job route are the compute family's mock mechanism, which
each adapter binds under its own `/test` prefix, so the family owns their pieces of the
route-contract pattern (`ARCHITECTURE.md`, "Route contracts and their HTTP binding") and a
domain supplies only where it mounts them (35 F1):

- **Route contract:** `compute_provisioning_contracts` gains `MockRouteMount`, a frozen
  value of a `prefix` and an `operation_prefix` whose `route_declarations()` yields the
  five declarations (rule add, rules list, rule delete, rule resume, job evaluate) under
  that prefix and those operation names. VM mounts `("/test", "provisioning_test")` and
  bare metal `("/test/bare-metal", "provisioning_test_bare_metal")`, which reproduce
  today's paths and signed operation names exactly, so the wire is unchanged.
- **Wire models:** the rule route service's response models sit in
  `compute_provisioning_contracts`.
- **Route service:** `MockRuleRouteService`, unchanged in the family kit.
- **Typed client:** `compute_provisioning_client` gains `MockRuleClient` and
  `SyncMockRuleClient`, constructed over the family client's transport with a
  `MockRouteMount`; each method signs from the mount's declarations and returns the
  family's models.
- **HTTP binding:** each domain's adapter, as today, contributing its mount's
  declarations to the provisioning service's table.

VM's `routes.py` replaces its hand-written test entries with its mount's declarations.
`arkhai_bare_metal.provisioning_client`, which holds bare metal's hand-written copy of the
contract and is no client, is reduced to bare metal's two mount values and renamed
`provisioning_routes`, so `arkhai-bare-metal` gains no compute dependency; the bare-metal
adapter and callers construct the mount from those values. The e2e harness and the
service's integration conftest call the family client. A third compute domain mounts the
mechanism by stating two values.

Rejected: an extension client in each domain's client package, which would write the same
client once per domain and place bare metal's in its vocabulary library; one family client
fed each domain's hand-written declarations, which needs the declarations restructured to
name each operation and still a prefix to build concrete paths from patterns, at which point
the declarations are redundant.

### D15. Worker controls are typed

`check-leases`, `run-cycle`, `advance-cycle`, and identity rotation return models in
`compute_provisioning_contracts/system.py`, beside `WorkerPauseResponse` from
`unbacked-bare-metal-listings`' branch. The e2e helpers read their attributes.

D14's and D15's ownership is normative (24 F5, 35 F1): `physical-provisioning`'s
"Compute-owned caller contract" names the mock-rule and worker-control response models
among those the contracts distribution owns, the mock mechanism's route-contract template
among its route contracts, and the mock-rule client among the family client's operations,
a domain contributing only its mount; `market-composition`'s mock-executor requirement
says the rule route service answers with those models and each adapter mounts it through
the family's template. Their fields stay in code, held by
the contract tests, and their failures are answered as every provisioning route's are.

### D16. VM binds pool overrides at `POOL_OVERRIDES_PATH`

On an unprefixed router, as bare metal does, rather than literal paths under the admin
router's prefix.

### D17. Operator guest names are checked

VM's operator `create_vm` checks the guest name with `check_guest_name`, which
provisioning's own names satisfy, in the adapter's service, and answers 422; the IaC
README stops saying operator names are unchecked.

### D18. The policy kit's refusals name the right things

The empty-chain refusal names `[negotiation].policies`; the unknown-name refusal says
built-ins are always registered and extensions come from the
`market_policy.negotiation_middlewares` entry-point group.

### D19. Convergence counts reach the log text

The recovery-diagnostics line carries its counts in the message, as other workers'
lines do, and keeps `extra` for the test that reads it.

### D20. VM-owned suites move into the VM adapter

The relay administration (except `TestTheDigestGate`, which tests the service's
importer), port allocator, port lease, Ansible pool-configuration, and VM codec suites
move into the VM adapter with a VM schema fixture. The partial unique index
`uq_relay_port_leases_active_owner`, which keeps two concurrent retries from taking one
relay port and which only service migration `20260901_001` creates, is declared on VM's
`relay_port_leases` model first, so the fixture keeps it; the migration still creates it
where absent. The codec suite gains `pyyaml` in the adapter's dev group.

### D21. The site ledger's VM target lookup is removed

`find_active_lease_by_vm_target` has only test callers and its docstring names a retired
route; nothing reads the `vm_target` payload key. Both go; `executor_target` stays.

### D22. `[provisioning] mode` is removed and ignored

Nothing reads it. It goes from the VM storefront's settings, its `config init` template,
the umbrella chart's values and their render test, the validation runbook, and the seller
quickstart, which says it selects mock or live. `[provisioning]` is untyped, so a
deployment that still states it starts unchanged.

### D23. Deltas

`skip_specs` is removed; the deltas are under `specs/`.

### Pre-1.0 incompatible changes (stated by the owner)

Before 1.0, a package's incompatible change to anything it publishes — its API, a wire
format it sends or accepts, or the meaning of a configuration key it reads — takes a
minor bump, and its users are expected to update. A contract carrying its own version (a
`VersionedEnvelope`'s `(kind, schema_version)`, a contract version, a protocol
identifier) is never changed in place: a new version is defined, and each party states
the versions it accepts and refuses others; before 1.0 the release introducing one may
stop accepting the one before. Persisted state keeps its own rules. The guidance does not
apply at or above 1.0.0. It is promoted to `RELEASING.md`'s "Versioning policy", with a
pointer from `ARCHITECTURE.md`'s "Operators" and one sentence in
`DEPLOYMENT_AND_CONFIG.md`. Signalling is semver and versioned contracts; no
per-release list of incompatible changes is kept.

## Implementation cadence

Two rounds, each reviewed before the next, then closeout.

- **Round 1**, overlapping `unbacked-bare-metal-listings`' branch only as D2 allows, in
  two sessions:
  - provisioning and the compute family: D6, D14 (all but its e2e callers), D17, D20, D21;
  - storefronts and kits: D4 with its e2e stage, D7, D9, D16, D18.
- **Round 2**, after `unbacked-bare-metal-listings` lands, in two sessions:
  - D3, D5, D8, D12, D13, D15, D19, D22, and D14's e2e callers;
  - D10 and D11.
- **Closeout**: promotion, the roadmap, the index, archive.

D13 and D5 together make the compute provisioning contract major 3, so both are in round
2 (35 F2): `dev` never holds a major-3 contract that must not be released, and no release
can carry half of it. Bare-metal begin's fix waits for the branch; the pipeline does not
meet the defect meanwhile, since its driver still declares the nested copy begin reads.
D22 waits because its template and settings edits sit beside the branch's own, and D14's
e2e callers because the branch rewrites the files they are in (35 F3). Planning confirms
the rest of the partition against the branch's diff, as D2 says.

Planning's derivation, from the branch's diff against its merge base `968a4a9`, placed
D4's e2e stage in round 1, beside the routes it tests. The stage is
`test_03_usage_started_keeps_oversized_listings_closed` in
`e2e-tests/tests/e2e/roles/scenarios/vms/test_compute_dynamic_listings.py`. It calls
`notify_usage_started`, which D4 removes. Removing the stage means removing that method,
the `usage_started` field and the requirement on it in `test_04`, and the docstring's step
naming it. None of those hunks touches the branch's: the branch edits the module's imports,
`pytestmark`, the head of `DynamicListingState`, and `test_00`/`test_00a`. Leaving the stage
for round 2 would leave round 1's pipeline calling a client method that round 1 removed.
D14's first round changes no path or signed operation, so the e2e harness's hand-built
mock-rule client keeps working until its callers move in round 2.

Planning re-derived the partition once the branch had merged `dev` and moved on, from
the branch at `c6e2108` against its new merge base `73d3760`, with `dev` at `1e5ba29`.
It holds: every first-round file the branch also edits overlaps it only in a version
line, a floor raised to the same bump, a lock, or a hunk with unchanged lines between.
One shared line is adjacent rather than separated: `kit/policy`'s description, which D7
edits, follows the version line both sides raise to `0.6.0`, so Git reports one
conflict whose resolution keeps that version and D7's description; it is a version-line
overlap, which D2 admits.

## Edits to other changes

Made with this design's recording:

- `site-route-contracts` and `repair-rl-training-tooling` are proposed, with index rows.
- `redesign-authenticated-requests`'s proposal is expanded: a version 3 request
  envelope that states its operation and binds its audience, motivated by independently
  operated sites and storefronts and several sites per storefront, and what
  `service-identity-signing` left undone. The change was renamed from
  `redesign-authenticated-replay-state`; the directory move, with its index row and
  `retain-authenticated-request-outcomes`' dependency, was made outside the design step,
  which cannot move directories.
- `service-identity-signing` is found delivered: its requirements are already in the
  permanent specifications and most of its tasks were carried out by
  `add-nonchain-marketplace-identities`; its remainder moves to the expanded change, and
  its proposal records this. It was archived as delivered with `--skip-specs` on
  2026-10-27, a move likewise made outside the design step.
  `replace-polling-with-authenticated-push` no longer depends on it.
- Recorded in the proposals of `move-escrow-into-alkahest` (the opening rule),
  `capacity-reservation-lifecycle-hardening` (release by escrow and the repurposed
  `escrow_uid`), `kit-owned-listing-and-fulfillment-lifecycles` (the deferral cadence),
  and `hollow-pre-floor-provisioning-migrations` (the legacy-backfill import; the index
  declaration).

## Open Questions

- **Per-adapter migration chains.** The provisioning service's single migration chain
  names VM's tables (D6). Revisit when a second compute domain needs provisioning-side
  tables: each adapter would then own its chain, run in an order the contributions
  declare, which amends `deployment-state`'s "Service-owned migration history".
