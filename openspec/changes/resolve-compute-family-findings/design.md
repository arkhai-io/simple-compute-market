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

That change's branch holds substantial unmerged work in files this change edits. Every
decision that shares a file with it is implemented in the second round, after it lands;
the first round shares none. The wait is partial, so it is recorded in the index's
`Notes`, not `Depends on`. Planning reads the branch so the plan cites what is already
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
| Two contracts claim the method and path | Unreachable: composing the route table refuses overlapping patterns |

Route resolution in both contracts packages reports which case failed through a typed
error rather than a bare `ValueError`. The answers stay unsigned. A response proof binds
the method, operation, resource, request identity, status, and body
(`_signed_response_headers`), and a client verifies against its own operation and
resource; the server knows no operation for the first two cases and no resource for the
third, and a request's headers carry a signature over its operation, not the operation.
The family client (`compute_provisioning_client/base.py`) and `kit/site-client` report a
refusal of an answer that carried no response authentication as such, naming its status,
following the wording `name-unverifiable-responses` gives storefront clients; they report
a malformed or wrong signature as they do today.

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
describes the `capacity_released` event provisioning sends. `docs/configuration.md`
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
remaining states.

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
imports without the adapters. `hollow-pre-floor-provisioning-migrations` removes the
legacy-backfill import with the data rewrite it serves.

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
   error, so a failing step is recorded with or without a callback.
2. **Deferred delivery.** Bare metal's ready hook defers while the lease is not yet
   active (`alkahest_lifecycle.py`); each deferral counts as an attempt, so the next try
   follows the error backoff, 30 s doubling to 30 minutes, and evidence publication, and
   with it the seller's collection, can lag activation by up to half an hour. In
   production nothing wakes it: the only wake is in the administrator's settle wait.
   `kit/settlement-runtime` therefore treats a deferral as not a failure: it does not
   count as an attempt, and a deferred obligation is rechecked on the next servicing
   cycle. Only bare metal defers today. The administrator wait keeps its wake, which a
   scenario holding the loops needs, so `storefront-publication`'s scenario is unchanged.
   This is distinct from `settlement-servicing`'s deferred fulfillment *outcome*, which a
   domain's own convergence finishes. `kit-owned-listing-and-fulfillment-lifecycles`,
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
completes, and skips delivery, so the seller is never told. The introduction store gains
a seller-delivery marker, set after dispatch, and the seller's side is told exactly once,
on whichever start completes the reveal. Operator re-delivery is unaffected.

Completing an interrupted reveal stays the buyer's retry. Completion is local, idempotent
bookkeeping, and the durable reveal record is what matters to either party; finishing it
without the buyer would hand the seller the buyer's contact while the buyer saw a 503.
The 503's detail says a retry completes the reveal, and the limit is documented.

Rejected: a sweep that completes and delivers without the buyer; handing completion to
`kit-owned-listing-and-fulfillment-lifecycles`.

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
chain. Every reader, storefronts and buyers, resolves a chain's book through one
`kit/alkahest` operation, which answers nothing for a chain using built-in addresses, so
no caller reads the map. `kit/config`'s `ChainSettings` loses the field. Both old keys are
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
scheduled resource's top-level `physical_host_id` and a `host_id` the schedule response
now carries, from the declaration. The e2e driver stops declaring the nested copies.

### D14. Mock-rule routes are typed

Response models for the shared rule route service sit in `compute_provisioning_contracts`,
since the mechanism is the family's. Each domain's client package (`vm_provisioning_operator`,
`arkhai_bare_metal.provisioning_client`) gains an extension client over any transport's
`authenticated_request`, after `kit/pool-overrides`. The e2e harness and the service's
integration conftest call them.

### D15. Worker controls are typed

`check-leases`, `run-cycle`, `advance-cycle`, and identity rotation return models in
`compute_provisioning_contracts/system.py`, beside `WorkerPauseResponse` from
`unbacked-bare-metal-listings`' branch. The e2e helpers read their attributes.

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

- **Round 1**, sharing no file with `unbacked-bare-metal-listings`' branch, in two
  sessions:
  - provisioning and the compute family: D6, D13, D14, D17, D20, D21;
  - storefronts and kits: D4 (all but its e2e stage), D7, D9, D16, D18, D22.
- **Round 2**, after `unbacked-bare-metal-listings` lands, in two sessions:
  - D3, D5, D8, D12, D15, D19, and D4's e2e stage;
  - D10 and D11.
- **Closeout**: promotion, the roadmap, the index, archive.

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
  its proposal records this. It is to be archived as delivered with `--skip-specs`, a
  move likewise made outside the design step; until then its row says so.
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
