## MODIFIED Requirements

### Requirement: Complete bare-metal seller lifecycle
A bare-metal storefront MUST validate listing, negotiation-message, agreed-terms, settlement materialization, receipt, and access-result artifacts through its installed domain contract. The listing binding MUST freeze the trusted `site_id`, Physical Resource identity, `bare_metal` offering mode, and contract identity/version; the accepted negotiation MUST copy that binding before persisting domain artifacts. Settlement and fulfillment MUST reload that binding and MUST NOT infer a site, executor, URL, credential, or domain from buyer payload data. Alkahest fulfillment MUST start when settlement verifies the escrow, through the kit settlement-servicing worker's ready hook, which the storefront composes whenever it has a settlement configuration, and MUST NOT wait for a buyer request to begin it or be retried by any other path. Arkhai payments MUST retain receipt-verified delivery and receipt-based reconciliation without creating conditional-escrow obligations. The storefront MUST refuse to start without its settlement configuration, and MUST build a configured mechanism's recovery resources whether or not the mechanism is enabled. An Alkahest fulfillment MUST publish on chain only its evidence's digest, and MUST NOT submit evidence again once a submission's outcome is unknown.

#### Scenario: Buyer accepts a bare-metal listing
- **WHEN** authenticated negotiation accepts valid terms for a trusted listing
- **THEN** the thread records the canonical buyer and seller principals and the exact listing/site/domain binding, and it is recorded as successful only after its agreement payloads and settlement plan are recorded
- **AND** no capacity is reserved or held until settlement starts fulfillment

#### Scenario: Acceptance is interrupted
- **WHEN** the storefront stops after an acceptance began but before the thread was recorded as successful
- **THEN** the thread is never settled, and it cannot be countered, accepted, or force-accepted again; the negotiation watchdog abandons it

#### Scenario: Settlement verifies the accepted plan
- **WHEN** a buyer settles an accepted bare-metal agreement
- **THEN** the storefront verifies and registers the settlement plan committed at acceptance, which the buyer funded, never a plan rebuilt from current configuration

#### Scenario: Accepted bare-metal agreement is fulfilled
- **WHEN** settlement verifies the escrow
- **THEN** the storefront wakes the settlement-servicing worker for that obligation, whose ready hook dispatches by mechanism to the bare-metal fulfillment, which reserves at the recorded site, commits the reservation with the agreed lease window, schedules the accepted Physical Resource, invokes the recorded bare-metal executor, and persists its reservation, settlement-resource, fulfillment, receipt, and result correlations
- **AND** the commit begins the lease with the window the site records, which the materialization and the delivered evidence state, and provisioning records the lease's target when the fulfillment becomes active, so lease expiry and termination find it

#### Scenario: Fulfillment start is interrupted
- **WHEN** settlement was verified but fulfillment did not start
- **THEN** the settlement-servicing worker's next cycle for that obligation starts it, without a second reservation or a buyer request

#### Scenario: An Alkahest fulfillment is evidenced and collected
- **WHEN** an Alkahest fulfillment's lease becomes active
- **THEN** the storefront stores the lease-ready evidence, bound to the accepted thread, the committed plan, and the escrow, and submits its digest on chain as a string obligation referencing the escrow, never its body
- **AND** it binds the attestation as the obligation's fulfillment, after which the worker checks the condition and collects the escrow

#### Scenario: An evidence submission's outcome is unknown
- **WHEN** an Alkahest evidence submission may have reached the chain but its attestation was not recorded
- **THEN** no later attempt submits again; the obligation waits for an operator with a reason, and the administrator's system status counts it

#### Scenario: The chain refuses an evidence submission
- **WHEN** the chain rejects an Alkahest evidence submission
- **THEN** the storefront retries it with backoff, and after a bounded number of rejections the obligation waits for an operator with a reason, which the administrator's system status counts

#### Scenario: Evidence is resolved
- **WHEN** a caller requests lease-ready evidence by its digest
- **THEN** the storefront serves it only on a signed request from a principal the evidence names as buyer or claimant, the seller's administrator
- **AND** the buyer's fulfillment status names the digest the storefront published, once it has published one

#### Scenario: A settlement ends uncollected after delivery started
- **WHEN** an Alkahest obligation reaches a terminal state other than collected after its fulfillment started
- **THEN** the storefront terminates the lease at the recorded site

#### Scenario: The storefront starts without its settlement configuration
- **WHEN** the bare-metal storefront starts with no settlement configuration, with a configured Alkahest section, enabled or not, that lacks its seller address, chains, or wallet key, or with any of those supplied and no Alkahest section
- **THEN** startup refuses with a clear error, and no mechanism is enabled implicitly

#### Scenario: Buyer supplies conflicting routing material
- **WHEN** a request or domain artifact asserts a provisioning URL, credential, different site, Physical Resource, machine, or physical-host identity
- **THEN** the storefront rejects the conflict before a state-changing authority call

#### Scenario: Storefront restarts during fulfillment
- **WHEN** a process restarts after reservation, scheduling, begin, result, or teardown acknowledgement
- **THEN** it reloads the same immutable binding and durable lifecycle references rather than reserving, provisioning, or releasing through another site

#### Scenario: Bare-metal result is returned
- **WHEN** the recorded fulfillment succeeds
- **THEN** the storefront records one buyer-safe `BareMetalReceipt` and `BareMetalResult` (the tenant account, when access became ready, and the lease end) without an endpoint, a private key, provider payload, authority URL, or credential
- **AND** where to connect is served only live, through the access route, while the lease is active

#### Scenario: Bare-metal lease is torn down
- **WHEN** the buyer requests teardown for the completed fulfillment
- **THEN** the storefront terminates the lease at the recorded site, the site's lease lifecycle converges teardown through the recorded fulfillment and releases the capacity reservation exactly once after authoritative teardown success, and the storefront records the release only on the site's capacity-released callback

### Requirement: The seller's inventory guard checks a listing against its own source

Before every seller decision in a negotiation round, and before a buyer's or an
administrator's acceptance, the storefront MUST recheck every published field of the
listing that is sourced from its declaration or pool against that source: the listing's
own site and pool or Physical Resource, never a resource elsewhere. A categorical field
MUST equal its source and a quantity MUST fit the declared capacity. Fields whose
authority is the storefront are not rechecked. A buyer's exit MUST NOT be rechecked.

The storefront MUST additionally check that the listing's published quantity is
available only for a capacity-backed listing. For an unbacked listing it MUST NOT
consult availability or contact a site authority.

A declared-match failure MUST be reported with a reason distinct from an availability
failure, so a buyer and an operator can tell a shape the seller no longer declares
from capacity that is temporarily taken. A source the storefront cannot confirm MUST be
refused as retryable, distinct from both, for a seller decision that would counter or
accept and for any acceptance; a seller decision that independently rejects or exits
keeps its own reason.

#### Scenario: An unbacked listing matches its declaration

- **WHEN** a buyer negotiates against an unbacked listing whose published fields match its enabled source declaration
- **THEN** the declared match passes without any availability read or site call

#### Scenario: A declaration no longer supports its listing

- **WHEN** a buyer negotiates against a listing whose source declaration has shrunk below, or been disabled beneath, its published shape
- **THEN** seller policy rejects with a declared-match reason rather than an availability reason

#### Scenario: Matching capacity exists only elsewhere

- **WHEN** a listing's own source no longer supports it but another pool or site holds matching available capacity
- **THEN** seller policy rejects the listing

#### Scenario: A backed listing matches but capacity is taken

- **WHEN** a capacity-backed listing matches its declaration but its published quantity is not available
- **THEN** seller policy rejects with the availability reason

#### Scenario: A fungible listing matches one member

- **WHEN** a buyer negotiates against a listing derived from a fungible pool whose enabled members declare different counts
- **THEN** the declared match passes only if some single enabled member has equal categorical attributes and declares at least the published quantity

#### Scenario: A dry-run evaluation applies the same checks

- **WHEN** a seller evaluates a proposal against a listing without opening a negotiation
- **THEN** the evaluation applies the same declared match and, for a capacity-backed listing only, the same availability check as a negotiation round

#### Scenario: An acceptance follows a change at the source

- **WHEN** a buyer accepts a seller's counter, or an administrator force-accepts, after the listing's source stopped supporting it or its capacity was taken
- **THEN** the acceptance is refused with the declared-match or availability reason and nothing is recorded

#### Scenario: The source cannot be confirmed

- **WHEN** the listing's site cannot be reached, does not verify, or has not supplied the projection the storefront reads
- **THEN** an opening or round the seller would counter or accept, and any acceptance, is refused as retryable and nothing is recorded

#### Scenario: A buyer exits while the source cannot be confirmed

- **WHEN** a buyer exits a negotiation whose listing's site cannot be reached
- **THEN** the exit is recorded without a site call

### Requirement: Bare-metal opening rechecks its listing against its source

Whenever a bare-metal storefront rechecks a listing against its source, it MUST
re-derive the listing's shape and region from its own site's live resource-pool
projection, at its bound pool and Physical Resource. It MUST refuse with a declared-match
reason when any of these hold:

- the shape digest differs from the binding's;
- the region differs from the published region;
- the Physical Resource is absent or disabled.

It MUST refuse with the availability reason when the site's capacity snapshot shows the
Physical Resource taken, and as retryable when the site cannot be reached or does not
verify, or no site authority is configured.

#### Scenario: A declaration shrinks beneath its listing

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource now
  declares fewer GPUs than it published
- **THEN** the opening is refused with a declared-match reason

#### Scenario: The Physical Resource is taken

- **WHEN** a buyer opens a negotiation on a bare-metal listing whose Physical Resource is
  reserved by another deal
- **THEN** the opening is refused with the availability reason

## ADDED Requirements

### Requirement: The bare-metal storefront reports its deal readiness

The bare-metal storefront's administrator status MUST report its registry's reachability, its seller chain's viability, its configured Alkahest chains, and the provisioning contract version it speaks, and MUST admit a configured site authority under the `service` role. When it records a site's capacity release, it MUST record a `fulfillment/capacity_released` stage event.

#### Scenario: A site checks its link to the storefront

- **WHEN** a configured site authority reads the storefront's status under the `service` role
- **THEN** the storefront answers, signed; any other service principal is refused

#### Scenario: Readiness is read before a deal

- **WHEN** an administrator reads the storefront's status
- **THEN** it reports `registry`, `negotiation_strategy`, and `alkahest` checks, judged per key as VM's are, and `provisioning_contract_version`, while the `/health` probe makes no registry call

#### Scenario: A site releases a deal's capacity

- **WHEN** the storefront records a capacity release from the reservation's site
- **THEN** its stage-event log carries a `fulfillment/capacity_released` event for the deal
