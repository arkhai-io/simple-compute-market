# Testing and Compatibility Specification

## Purpose

Define test-level ownership, shared contract fixtures, deterministic e2e staging, and client rollout behavior.

## Requirements

### Requirement: Layered behavioral verification
Unit, integration, smoke, and end-to-end tests MUST each defend the narrowest observable contract appropriate to their level and MUST NOT rely on e2e alone for component behavior.

#### Scenario: Service API behavior changes
- **WHEN** a route contract changes
- **THEN** focused unit/integration coverage pins the route behavior and e2e verifies only the cross-service flow

### Requirement: Shared contract fixtures
Cross-language or cross-package implementations of the same protocol MUST consume canonical fixtures that encode observable requests, responses, and state transitions.

#### Scenario: API-credit middleware port changes
- **WHEN** Python, TypeScript, or Rust middleware behavior is updated
- **THEN** each implementation reproduces the shared conformance session

### Requirement: Dependency-aware e2e stages
The end-to-end stage that violates an observable contract MUST fail; downstream stages MUST explicitly declare consumed prior state and skip with the exact missing state field rather than failing for an unrelated symptom.

#### Scenario: Required deal state is absent
- **WHEN** a downstream stage lacks a prerequisite produced by an earlier stage
- **THEN** the skip reason names the missing `DealState` field

### Requirement: Exact e2e state dependencies
Every staged e2e state field MUST use one exact producer/consumer name, and every field introduced for downstream behavior MUST have at least one explicit `require_state` consumer.

#### Scenario: Test author adds staged state
- **WHEN** a test adds a field to `DealState`
- **THEN** a downstream stage consumes that exact attribute name and coverage verifies the transition

### Requirement: Buyer profile compatibility is deterministic across domains

Focused tests MUST exercise versioned profile creation/import/selection/update/rotation/retirement/deletion, every exact credential provider, strict ownership and permissions, malformed and interrupted stores, missing secrets, principal mismatch, duplicate profile/principal, rotation overlap, run and binding blockers, and coordinated multi-run migration rollback.

The VM and API-credit plugins MUST run against the same selected-primary and retained-recovery matrix. Secret canaries MUST be absent from JSONL, TOML, stdout/stderr, exception and object reprs, Compose/Helm renders, ConfigMaps, images, wheels, and evidence.

#### Scenario: One plugin attempts legacy fallback

- **WHEN** an installed buyer plugin lacks the resolved-identity injection contract or reads direct identity configuration
- **THEN** conformance fails before the plugin performs discovery or an authenticated effect

#### Scenario: A migration candidate fails after an earlier replacement

- **WHEN** coordinated profile/run-log migration cannot validate or replace every candidate
- **THEN** tests observe complete profile and run-log restoration, no partial activation, and an actionable unresolved-manifest failure

### Requirement: Multi-domain storefront selection has focused compatibility coverage

Deterministic focused tests MUST cover frozen registry validation, immutable listing/thread binding, publication mode enforcement, domain-envelope matching, selected-site routing, settlement/fulfillment contexts, migration, restart recovery, result decoding, and teardown under both VM and bare-metal contracts. Duplicate, missing, unknown, unsupported, mismatched, and cross-swapped modes/identities/versions MUST fail before an unselected policy, persistence mutation, capacity call, provider call, or decoder runs.

#### Scenario: One and two registrations use the same shell

- **WHEN** focused composition runs with one explicit registration and with VM plus bare-metal registrations
- **THEN** both use the same common routes, repository, publication runner, and lifecycle carriers without a singleton or domain-specific control-flow copy

#### Scenario: Unknown binding is injected at a lifecycle boundary

- **WHEN** publication, opening, continuation, settlement, fulfillment, result, recovery, or teardown receives an unknown or mismatched binding
- **THEN** the owning boundary rejects it and its mutation/network spies remain untouched

#### Scenario: Installed-artifact deployment is inspected

- **WHEN** clean staged wheels render the combined image, Compose, and Helm configuration
- **THEN** both enabled contributions are discoverable, disabled domains leave no wait/source path, and signer/provider/SSH/private-result canaries are absent from public artifacts

#### Scenario: Full live proof is requested

- **WHEN** the production bare-metal contribution or selected-site POOLS-7 lifecycle is unavailable
- **THEN** the real multi-domain E2E remains explicitly blocked rather than recording fake publication, fulfillment, teardown, or capacity-restoration success

### Requirement: Per-domain end-to-end deal path

Every market domain intended for deployment MUST have an end-to-end scenario
proving discovery, negotiation, settlement, delivery, and domain-defined
teardown against running services. Scenarios MUST use the shared
domain-neutral state, profile/config, event-order, and client helpers rather
than copying a VM scenario or interpreting another domain's listing,
fulfillment result, private authority state, or teardown carrier.

#### Scenario: A domain is deployed

- **WHEN** a market domain is intended for deployment
- **THEN** its release-qualified scenario observes one complete deal through the ordinary public buyer and seller boundaries

#### Scenario: Another domain needs a deal path

- **WHEN** its listing, result, or teardown semantics differ from VM
- **THEN** the scenario supplies domain codecs and assertions to shared helpers without adding a domain guess, default route, or copied orchestration

#### Scenario: An external authority is unavailable

- **WHEN** a live seller, site/provisioning authority, chain, payments authority, credential, or real access target required by the selected scenario is absent
- **THEN** that exact live assertion remains blocked or unavailable and static composition is not reported as end-to-end success

### Requirement: Payment evidence is attributed at its owning boundary

Credential-free SCM tests MUST prove generated wire contracts, JCS hashes, mandate policy, signed-receipt rejection, exact Agreement and settlement-data persistence, selected-mechanism dispatch, retryable pending, and idempotent domain delivery through deterministic ports. They MUST NOT claim live ledger or provider behavior, which remains producer-owned evidence.

#### Scenario: Local payment smoke uses controlled collaborators

- **WHEN** a local VM smoke drives pending to provisioning to ready with controlled HTTP and delivery
- **THEN** its evidence establishes SCM receipt gating and one delivery, not live payment-service or hardware acceptance

#### Scenario: API-credit payment is retried

- **WHEN** seller progress is nonterminal after an issuance acknowledgement is lost
- **THEN** focused domain tests use the same transaction and grant identity and assert no duplicate balance or quota mutation

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision, check readiness before mutations, and report unavailable prerequisites rather than substitute another mechanism. A payment scenario MUST report itself blocked only when no payments target is configured or the configured target is not ready; once a target is configured, a missing setting the scenario itself supplies — its parties' accounts and credentials, or the service policy it pins — MUST fail the scenario rather than block it. Payment-service ledger, hold release, fees, disputes, top-ups, payouts, and provider recovery remain the payments service's evidence.

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

#### Scenario: A configured payments run lacks a buyer credential

- **WHEN** a payments target is configured but the buyer's marketplace credential is not
- **THEN** the payment scenario fails naming the missing setting, rather than reporting itself blocked

### Requirement: Signed receipts in tests come from the kit fixture

A test that needs a signed receipt over its own Agreement MUST sign it through the payments kit's receipt fixture with an injected signer. The fixture ships no key material, and a kit unit test reproduces the published receipt vector byte for byte.

#### Scenario: A storefront test needs a verified receipt

- **WHEN** an integration test settles a payments deal
- **THEN** it builds the receipt with the kit's fixture and a test signer, and the vector test proves the fixture signs what the service signs

### Requirement: A deployable domain's deal runs on every end-to-end run

Every market domain intended for deployment MUST have a complete-deal scenario that runs
on every run of the end-to-end pipeline, against running services using that domain's
ordinary local or test authorities. A domain whose delivery crosses compute provisioning
MUST run provisioning in its mock profile. The scenario MUST hold every storefront loop
it depends on, preview each transition it advances through that loop's or route's dry
run where one exists, and advance it explicitly. That scenario proves the services
compose into a working deal. Mocked delivery MUST NOT be reported as evidence of real
delivery: where a domain's release acceptance requires a real external resource, that
remains a separate protected lane.

#### Scenario: Bare metal runs its deal in the pipeline

- **WHEN** the bare-metal end-to-end lane runs
- **THEN** a whole-host deal completes through discovery, negotiation, Alkahest
  settlement, mock-provisioned delivery, lease expiry, and teardown, observed through
  typed clients, with every dry-run stage VM's deal runs
- **AND** the site releases the Physical Resource's reservation, the storefront receives
  the capacity-released callback, and the next publication pass reopens the listing

#### Scenario: Buyer teardown is repeated

- **WHEN** the bare-metal lane's second deal requests teardown twice
- **THEN** both requests return the same lease release operation and the site releases
  the reservation once

#### Scenario: Real access is required

- **WHEN** release acceptance requires observing real access and its revocation
- **THEN** the mock-provisioned deal does not satisfy it, and the protected lane's
  requirement stands

### Requirement: The canonical compute deal's shared stages are defined once

The compute family's canonical complete deal, settled through Alkahest, MUST take each
stage its lanes run identically from one shared definition, whether the lane delivers
through the provisioning mock profile or through a real host. A lane MUST subclass a
shared stage without replacing its body and MUST supply its differences through
fixtures and a per-domain driver. A lane MAY insert stages of its own; a stage whose
body differs between lanes is not shared.

A shared stage MUST NOT depend on the mock profile. Holding a provisioning job before
its result, releasing it, and evaluating a mock rule are mock gates: they are stages of
their own, run only by lanes that deliver through the mock profile, and are supplied by
a driver part that only mock drivers implement. A stage that would call a gate is split
at the gate, and its gate-free part stays shared.

#### Scenario: A shared stage changes

- **WHEN** a shared stage's preview, advance, or assertion changes
- **THEN** every compute lane that runs the canonical deal runs the changed stage without
  a per-domain edit

#### Scenario: A domain's part of a shared stage

- **WHEN** a shared stage needs supply seeding, provision terms, the lease view,
  settlement-preview expectations, the settlement's dispatch, result and access
  assertions, or the claim that re-reserves released supply and its release
- **THEN** the domain's driver supplies it and the stage's body is unchanged

#### Scenario: A mock lane holds a job

- **WHEN** a lane that delivers through the mock profile holds its create or teardown
  job before the result, or evaluates the mock rule for it
- **THEN** it does so in a mock-only stage, through its driver's mock-gate part, between
  the shared stages it surrounds

#### Scenario: The preflight before settlement fails

- **WHEN** the lane's last stage before settlement — the mock rule's evaluation in a
  mock lane, the check of the previewed host in a real lane — fails
- **THEN** the shared settlement stage skips and submits nothing

#### Scenario: A real lane runs the canonical deal

- **WHEN** a lane delivers through a real host
- **THEN** it runs every shared stage, none of which calls a mock gate, and its driver
  implements no mock-gate part

#### Scenario: A deal outside the canonical deal

- **WHEN** a compute scenario settles another way, or a domain outside the compute family
  runs a complete deal
- **THEN** it keeps its own stages

#### Scenario: A compute domain differs in negotiation

- **WHEN** a compute domain would need its own negotiation stage
- **THEN** the difference is resolved in its storefront composition, not in the stage

### Requirement: Each domain runs in its own lane

The end-to-end pipeline MUST run each market domain's scenarios in a lane of its own, as
a pipeline job separate from every other domain's lane, so a failure in one domain's
lane cannot hide or stand in for another's evidence. Each lane MUST build the images its
own stack runs and compose only its own services, including every registry its
scenarios read.

#### Scenario: The pipeline runs

- **WHEN** the end-to-end pipeline runs
- **THEN** the VM, bare-metal, and API-credit lanes each build their own stack's images
  and run their own stack and scenarios, in parallel
- **AND** the VM lane's stack does not include the API-credit services

#### Scenario: A scenario reads a registry of another schema

- **WHEN** a lane's scenario discovers across registries of more than one schema
- **THEN** the lane deploys each of those registries in its own stack, and the scenario
  reads them from that lane's settings

#### Scenario: A compute lane provisions through the mock profile

- **WHEN** a compute lane runs
- **THEN** its provisioning services run their mock profile because the run selects mock
  provisioning, not because the lane's local overlay or stack hard-codes it
- **AND** no storefront in the lane carries a provisioning mode

### Requirement: Bare-metal storefront restart recovery is proven at integration level

Bare-metal storefront restart recovery MUST be proven by integration tests that rebuild
the production application over the same database. After a rebuild following settlement
commit or teardown acceptance, the buyer MUST retrieve the same operation without a
second obligation, mechanism selection, or physical teardown, and duplicate polling and
result reads MUST be idempotent. The end-to-end lane starts from empty state and does
not restart services.

#### Scenario: Process stops after settlement commit

- **WHEN** the settlement authority committed the recorded operation but the buyer did not receive its response
- **THEN** after the rebuild, resume retrieves the same operation and continues without a second obligation or mechanism selection

#### Scenario: Process stops while the lease is active

- **WHEN** the storefront is rebuilt while a delivered lease is active
- **THEN** repeated status, result, access, and settlement-status reads return what they returned before, with no second reservation or fulfillment start

#### Scenario: Process stops after teardown acceptance

- **WHEN** teardown was accepted before the response was lost
- **THEN** after the rebuild, a repeated teardown returns the same lease release operation and the site releases capacity once

### Requirement: A configured bare-metal payment purchase is qualified end to end

With a ready payments target configured, the bare-metal lane MUST qualify one fixed-term whole-host purchase settled through `arkhai.payments.v1`: discovery, negotiation, payment approval, receipt-gated mock delivery, re-drive of the original run's settlement, seller refund, and physical teardown, with the refund and the teardown as separate operations. Mock access is evidence of composition, never of real SSH access or revocation. The scenario MUST leave no payment hold, allocated host, mock rule, or held loop behind, whether it passes or fails, except a payment it cannot refund, which it MUST report by its negotiation and transaction together with any host its seller may still deliver for it, and a host whose fulfillment it cannot read or tear down, which it MUST report as a failed cleanup step. Without a configured, ready target it MUST report a named blocked prerequisite, never fall back to Alkahest or count as qualification.

#### Scenario: Bare-metal payment purchase is qualified

- **WHEN** the bare-metal payment scenario runs with a ready configured payments target
- **THEN** three ordered calls discover a distinct backed whole-host listing, negotiate
  and approve one hourly payment option with a wallet-free profiled Ed25519 buyer,
  and observe receipt-gated durable mock delivery
- **AND** recovery reads the original run and resolves its retained signer, re-drives
  the same negotiation through `SyncStorefrontClient.settle_agreement`, and requires
  the original transaction, fulfillment identity, and durable result
- **AND** the pinned seller refunds the held payment and the buyer separately
  requests physical teardown, converging mock reclaim and selected-site capacity release

#### Scenario: A stage fails after the payment is approved

- **WHEN** a stage of the bare-metal payment scenario fails after the buyer approved the payment
- **THEN** the scenario's cleanup refunds the deal's payment if it is not already refunded,
  then reads the deal's fulfillment and tears down a host it finds not yet torn down,
  reading the deal's identifiers from the original run when the purchase command failed
- **AND** a host delivered while the refund was being requested is found and torn down,
  and one whose fulfillment cannot be read or torn down is reported as a failed step
- **AND** a refund the seller refuses because the payment is not yet verified, or the
  payments service or storefront is unavailable, is retried for a bounded time, and a
  refund that still fails fails the scenario naming the negotiation and transaction
- **AND** a failed cleanup step is reported without preventing the later ones, and the
  held loops are resumed whatever an earlier step did

#### Scenario: No payments target is configured

- **WHEN** the bare-metal payment scenario runs with no payments target configured, or an unready one
- **THEN** it reports a named blocked prerequisite and makes no purchase

### Requirement: Scenarios hold shared services for the whole module

An end-to-end scenario that needs a shared service's timer held — a storefront's
lifecycle loops, provisioning's fulfillment convergence, or its lease watchdog — MUST
take its lane's hold fixture for the whole module, built on one shared helper per pause
kind. A hold MUST be taken before the module's first stage, MUST wait until each held
loop reports itself paused at its gate, and MUST be released in a finaliser whatever the
module's outcome, after the module's other cleanup. A stage MUST assert a hold and MUST
NOT pause or resume a service itself, and a source check MUST refuse a scenario or stage
that calls a pause route directly. Every lane MUST use the same mechanism.

#### Scenario: A deal scenario fails part-way

- **WHEN** a VM or bare-metal deal scenario fails in a stage after its storefront's loops
  and the lease watchdog were held
- **THEN** both are resumed when the module ends, and the next module finds them running

#### Scenario: The Helm deal test passes

- **WHEN** the in-cluster deal test completes against a persistent Helm release
- **THEN** the seller storefront's lifecycle loops report running afterwards

#### Scenario: A stage pauses a service

- **WHEN** a scenario module or stage calls a storefront or provisioning pause route
  directly
- **THEN** the source check fails, naming the call

### Requirement: A real-provisioning VM scenario proves delivery on a real host

A VM scenario MUST exist that runs the canonical compute deal against a provisioning
service outside its mock profile and a real KVM host, and proves what the mock profile
cannot: that the service's VM execution is not mocked; that the create and teardown
jobs ran and succeeded; that the buyer, with the key it negotiated, reaches the VM with
the delivered access as the delivered user and finds the listing shape's vCPU count,
memory within a stated tolerance, and at least its disk; that an unrelated public
key is refused for the delivered user; and that once the lease expires and its
capacity is released the host's VM list no longer names the guest and the delivered
access no longer connects. It makes no claim about the guest's other configured
credentials.

The scenario MUST run under either access mode its target names. Under relay access it
MUST require the delivered address to be the relay's and the port the leased one. In
either mode, between its first deal's access checks and that deal's expiry, it MUST
hold an established session to the first guest while a second deal on the same listing
is created and torn down, and MUST fail if that session ends or stalls beyond a stated
bound; it MUST check the host's connectivity through the provisioning service before
and after each create and teardown; and under relay access it MUST read the relay's
holdings to show the second deal's port released and held by no other lease.

The scenario MUST register the pool, executor host, and capacity declaration it deals
on from its target description, publishing the target's listing shape, and MUST be able
to deal on a shape that declares no GPUs. It MUST keep every worker hold and explicit
advance that exists outside the mock profile, and MUST wait for a real job, found
through its fulfillment's capacity reservation, by reading its state, within a stated
bound, where a mock lane would release a gate. It MUST register the host with the
connection its target describes, replacing the connection of a host an earlier run left
behind, and MUST write nothing to the stack before its target is validated, its VM
execution is found real, and, under relay access, its relay is found enabled with a
token and an active grant key. It MUST NOT submit settlement unless the settlement
preview chose the target host. When it fails after a fulfillment is dispatched and
before its own teardown completes, it MUST truncate each of its live deals' leases so
the provisioning service tears the guests down, and MUST fail naming the fulfillment,
reservation, jobs, guest, and host where removal is not confirmed; it MUST NOT release
reservations beyond its own. It MUST generate the buyer's key for the run and MUST trust
the guest's host key on first use for the run only, failing if a later connection in the
run presents another. It belongs to no default lane and MUST skip, naming the profile
it needs, when its target names no VM host.

#### Scenario: A real deal is delivered

- **WHEN** the scenario runs with a target describing a prepared KVM host
- **THEN** the create job runs on that host, the fulfillment reaches `active`, and the
  buyer's connection with the delivered access shows the delivered user, the listing
  shape's vCPU count, memory within tolerance, and at least its disk

#### Scenario: A relayed deal is delivered

- **WHEN** the target describes the host with relay access
- **THEN** the delivered access names the relay's address and the port leased for the
  guest, and connects

#### Scenario: A session survives a second deal

- **WHEN** a session to the first guest is open while a second deal's guest is created
  and then torn down
- **THEN** the session stays established throughout, the second guest is reached at its
  own port, and its port is shown released afterwards

#### Scenario: An unrelated key is refused

- **WHEN** the scenario connects to the delivered VM as the delivered user with a public
  key it did not negotiate
- **THEN** the connection is refused

#### Scenario: Teardown removes the VM and its access

- **WHEN** the lease is expired and the watchdog and convergence cycles are advanced
  until its capacity is released
- **THEN** the teardown job has succeeded, a VM list job on the host succeeds without
  naming the guest the create job reported, and the delivered access fails to connect
  within the stated bound

#### Scenario: The run fails with a guest on the host

- **WHEN** a stage fails after a fulfillment is dispatched and before the scenario's
  own teardown of it completes
- **THEN** the scenario truncates that deal's lease so the provisioning service tears
  the guest down, and fails naming the fulfillment, reservation, jobs, guest, and host
  where it cannot confirm the guest's removal

#### Scenario: The settlement preview chooses another host

- **WHEN** the settlement preview chooses a host other than the target's
- **THEN** the scenario does not submit settlement

#### Scenario: The service's VM execution is mocked

- **WHEN** the provisioning service reports no VM executor, or reports it mocked
- **THEN** the scenario fails at its first check, before any registration or deal
  mutation, rather than reporting mock delivery as real

#### Scenario: No target is present

- **WHEN** the run does not select the target profile, its file is absent, or it names
  no VM host
- **THEN** the scenario skips with a message naming the profile and file it needs,
  having written nothing to the stack

### Requirement: A real-provisioning target is a typed, versioned settings section

The real-provisioning scenarios' target MUST be read from a versioned settings section
loaded from a profile file the repository ignores, beside a committed example whose
values are visibly fictitious. The section MUST be validated before any stage runs: a
missing or misspelled field MUST fail naming the field, an unknown version MUST be
refused, and a field that does not belong to a host's domain or access mode MUST be
refused. Version 2 describes a list of hosts, at most one per domain, each with its
domain, its identity, the connection the provisioning service reaches it at (address,
user, port, and the path at which the service reads its key), its access — a relay
named by its identifier, or direct access with a tenant address — and the capacity it
sells; a VM host also states the listing shape its scenario publishes, which MUST fit
twice within its capacity, and a bare-metal host its physical machine identity and its
SSH host public key. A relay named by a host is resolved in the provisioning service
that host's scenario runs against. The section MUST NOT carry the private key the
provisioning service reaches hosts with, nor any relay token or key.

#### Scenario: A field is misspelled

- **WHEN** the target section names a field the model does not define, or omits one it
  requires
- **THEN** the scenario fails before its first stage, naming the field

#### Scenario: A newer target reaches an older reader

- **WHEN** the section's version is one the scenario does not know
- **THEN** the scenario refuses it rather than interpreting it

#### Scenario: Relay access is requested under version 1

- **WHEN** a section states version 1, whatever access mode it names
- **THEN** it is refused with a message naming the version 2 profile and how its fields
  map

#### Scenario: A listing shape does not fit twice

- **WHEN** a VM host's listing shape exceeds half its capacity on any dimension
- **THEN** the target is refused, naming the dimension

#### Scenario: Relay access names a tenant address

- **WHEN** a host under relay access states a tenant address, or one under direct access
  names a relay
- **THEN** the target is refused, naming the field

### Requirement: A real-provisioning bare-metal scenario proves relay access on a real host

A bare-metal scenario MUST exist that runs the canonical compute deal against a
provisioning service outside its mock profile and a real host reached through a relay,
and proves: that the service's bare-metal execution is not mocked; that the grant and
reclaim jobs ran on the target host and succeeded; that the buyer, with a key generated
for the run and negotiated in the deal, reaches the host as the delivered tenant at the
relay's address and the leased port; that an unrelated key is refused; that after the
lease expires and its capacity is released the delivered access no longer connects and
the relay's holdings show the port released; and that the host's connectivity through
the provisioning service holds before and after the grant and the reclaim. It MUST
register its pool, host, and declaration from its target, MUST write nothing before its
target, its execution, and its relay are checked, MUST NOT submit settlement unless the
settlement preview chose the target host, MUST pin the host's key from its target, MUST
truncate its lease on a failure after dispatch so reclaim runs and name what it cannot
confirm, and belongs to no default lane, skipping when its target names no bare-metal
host.

#### Scenario: A relayed bare-metal deal is delivered

- **WHEN** the scenario runs with a target describing a prepared bare-metal host under
  relay access
- **THEN** the grant job succeeds and the buyer connects as the delivered tenant at the
  relay's address and the leased port, while an unrelated key is refused

#### Scenario: Reclaim ends the relayed access

- **WHEN** the lease is expired and the cycles are advanced until its capacity is
  released
- **THEN** the reclaim job has succeeded, the delivered access no longer connects, and
  the relay's holdings show the lease released

#### Scenario: The service's bare-metal execution is mocked

- **WHEN** the provisioning service reports no bare-metal executor, or reports it mocked
- **THEN** the scenario fails at its first check, before any registration or deal
  mutation

### Requirement: Real-lane SSH access goes through one helper

Every end-to-end scenario that opens SSH to a delivered resource MUST do so through one
shared helper, which offers a key generated for the run, trust on first use for a run or
a pinned host key, a session held open with a liveness check, and the classification of
a refused connection.

#### Scenario: A scenario opens SSH

- **WHEN** any end-to-end scenario connects to a delivered guest or host
- **THEN** it uses the shared helper, and no scenario builds its own SSH command

### Requirement: Arkhai physical qualification uses ordinary buyer settlement

Arkhai real-hardware qualification MUST use the shipped buyer and external payments authority, correlate each signed TEST payment to its physical delivery, and keep buyer credentials separate from operator observations. It MUST report unrun prerequisites and MUST NOT label an unexecuted payment-specific pytest driver passed.

#### Scenario: A real Arkhai rental is qualified

- **WHEN** a configured campaign executes a VM or bare-metal rental using `arkhai.payments.v1`
- **THEN** the buyer negotiates and pays through the shipped client, verifies pinned delivered SSH and the negotiated shape, and observes ordinary teardown, fresh access denial and restored capacity with correlated payment, reservation and job identities

#### Scenario: An operator supplies independent physical observations

- **WHEN** qualification needs host inventory, management continuity or cleanup observations unavailable to the tenant
- **THEN** those observations use a separate operator authority and neither its key nor its management route is available to the ordinary buyer

#### Scenario: A prerequisite or driver is unrun

- **WHEN** a payment, physical target or required observation is missing or a named alternative driver was not executed
- **THEN** qualification records that observation as unproven and does not substitute mock, native component or historical evidence for the missing real lifecycle

#### Scenario: An operator supplements finite host network-policy evidence

- **WHEN** an operator probes the paid deployment's shared host network policy from a separate CPU guest bound to the same pinned guest base, default bridge, virtio NIC, and loaded policy structure
- **THEN** the recorded result is limited to the finite network paths and rules exercised; it does not replace paid-buyer evidence for customer identity, credentials, privilege, grant, GPU work, payment, delivery, teardown, access revocation, or restored capacity, and it does not establish universal network isolation

### Requirement: Equivalent physical proof preserves lifecycle invariants

An alternative payment-specific qualification method MUST retain the original physical acceptance observations: relay and direct VM access, concurrent-deal and management continuity, lease expiry, repeat registration/adoption, bare-metal cleanup and refusal recovery. It MUST recover only its own rentals and preserve relay quarantine and consumed tenant identities.

#### Scenario: Two VM deals share a host

- **WHEN** the second CPU-only VM is created and torn down while the first buyer session is active
- **THEN** the first session and management connection remain usable, both delivered shapes match their agreements, an unrelated key is refused, and ordinary expiry removes each guest and ends access

#### Scenario: Direct access is qualified

- **WHEN** the equivalent VM cycle uses direct access
- **THEN** it runs in a drained controlled pool without exposing host management or rebinding a pool that retains active reservations or relay holdings, and its result is distinguished from external relay acceptance

#### Scenario: Bare-metal cleanup refuses an unsafe descendant

- **WHEN** an ordinary reclaim encounters the nonce-scoped foreign-owned test descendant
- **THEN** capacity remains unavailable, retry and actionable notification are observed, and fixture-only repair permits the same nonterminal job to complete without resetting tenant identity history or bypassing cleanup

#### Scenario: A campaign is repeated

- **WHEN** registrations and listings are reconciled for another qualified cycle
- **THEN** canonical identities are retained, no duplicate allocator is created, and consumed UIDs and unexpired relay quarantine remain protected
