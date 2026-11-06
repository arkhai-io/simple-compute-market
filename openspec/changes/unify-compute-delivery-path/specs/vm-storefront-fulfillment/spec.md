## MODIFIED Requirements

### Requirement: A VM deal's lease begins at its reservation commit

The VM storefront MUST commit the deal's reservation with the Agreement's window before fulfillment begins, which begins the lease; afterwards only end service and the site's activation, through the guarded capacity effects, write to the lease. It MUST hold and commit site capacity under the deal's negotiation (`deal_ref.negotiation_id`) whatever the settlement mechanism, with a placement key naming the hold or the settlement placement, so a deal's site reservation is found by its negotiation and carries no settlement reference.

#### Scenario: A payments deal's capacity is held

- **WHEN** a VM storefront holds capacity for an Arkhai payments deal
- **THEN** the hold names the deal's negotiation ID and the `hold` placement and carries no settlement reference, and fulfillment begins only after the reservation is committed

#### Scenario: A ready VM's lease is activated

- **WHEN** a VM deal's fulfillment becomes ready after its Agreement start
- **THEN** the site records the lease's activation and the lease keeps its committed or truncated end

### Requirement: VM settlement stages own their mechanism's steps

The selected settlement stage MUST own mechanism-specific attestation, readiness and claim binding; the claims engine retains submission and collection, not physical recovery. Common delivery MUST consume the stage's evidence and MUST NOT compare mechanism IDs.

#### Scenario: An Alkahest deal is fulfilled

- **WHEN** physical fulfillment of an Alkahest VM deal reaches an active result
- **THEN** the Alkahest stage binds the fulfillment attestation and claim, the claims engine submits and collects, and common delivery records readiness without naming the mechanism or storing credentials

### Requirement: Full settlement convergence ownership

The VM storefront MUST own capacity reservation, physical fulfillment and listing/delivery progress through the compute family's delivery path, and MUST NOT store access material.

#### Scenario: An escrow-settled deal's reservation is looked up

- **WHEN** an operator or test looks up the site reservation of a VM deal settled through Alkahest
- **THEN** it finds the reservation by the negotiation its hold names, not by the escrow

#### Scenario: Physical success converges commercial delivery

- **WHEN** physical fulfillment reaches an active result
- **THEN** the delivery path activates the lease, starts billing through end service, records availability and updates listing/delivery progress, storing no credential
- **AND** the selected Alkahest continuation reconciles on-chain fulfillment, escrow readiness and settlement claims when applicable
- **AND** every step is safe to revisit after interruption

#### Scenario: Payment physical success requires no chain step

- **WHEN** verified payment evidence produces an active VM
- **THEN** common delivery returns the same domain result without creating an escrow claim or choosing a no-chain path by mechanism ID

#### Scenario: Terminal settlement ends a lease

- **WHEN** a VM deal's settlement reaches a terminal state before its lease end
- **THEN** the storefront requests end service, which truncates or terminates the lease

### Requirement: Physical fulfillment resumption

When durable fulfillment identity exists, recovery MUST query that fulfillment directly and MUST NOT schedule or begin a replacement. Nonterminal provider state remains pending; an active result MUST yield readiness and resource identities, never stored credentials; provider failure MUST enter the compute delivery path's end hand-off. Without fulfillment identity, recovery MUST reuse the persisted exact request and idempotent reservation/scheduling/begin contracts. Settlement evidence MUST be revalidated by its selected stage before protected effects.

#### Scenario: Recovery before fulfillment acceptance

- **WHEN** an unfinished delivery has persisted context but no fulfillment ID
- **THEN** recovery reuses the exact stored request and target
- **AND** reconciles reservation, scheduling and begin-fulfillment through their idempotent contracts

#### Scenario: Recovery after fulfillment acceptance

- **WHEN** an unfinished delivery has a durable fulfillment ID
- **THEN** recovery polls that fulfillment directly
- **AND** does not schedule a replacement resource or begin a second fulfillment

### Requirement: A step after physical fulfillment defers a VM deal, never fails it

Once physical fulfillment has produced a running VM, a failure of a later bookkeeping step (recording readiness, activating the lease when the site cannot be reached, starting billing, or publishing the fulfillment evidence) MUST NOT mark the deal's delivery failed. The foreground path MUST report the fulfillment as deferred and leave delivery unfinished, and restart convergence MUST complete the deal from the recorded fulfillment, without beginning a second one. The only lease writes after physical fulfillment are the site's activation and end service's truncation or termination. An activation the site refuses because the lease was released or expired MUST enter the end hand-off instead.

#### Scenario: Evidence publication fails after provisioning

- **WHEN** the VM is running and publishing its fulfillment evidence fails
- **THEN** the deal is deferred, and restart convergence publishes the evidence

#### Scenario: Restart convergence recovers a reservation never committed

- **WHEN** restart convergence resumes a deal whose reservation was never committed
- **THEN** it commits the reservation with the deal's Agreement window and negotiation before beginning
  the fulfillment, and a reservation committed earlier keeps the window its first commit
  recorded

#### Scenario: Activation loses to expiry

- **WHEN** a running VM's activation is refused and the lease reads as released
- **THEN** the deal goes to the end hand-off rather than being deferred again

### Requirement: A VM deal records only how to reach its VM

The connection details a VM storefront records for a deal MUST be the delivery's SSH endpoint (host, port, and tenant account), when access became ready, and the provisioned resource identities, and nothing else: no credential, guest name, address internal to a host, or key path. A record with no buyer-facing address MUST omit the host rather than name another. `settle` and `settle-status` MUST obtain credentials live through the compute delivery path's access check and MUST declare themselves credential-capable, so an exact retry reads again rather than replaying a recorded body.

#### Scenario: A VM becomes ready

- **WHEN** a VM fulfillment becomes active
- **THEN** the storefront records the delivered endpoint, readiness, and resource identities as the deal's connection details, and no credential

#### Scenario: The buyer polls settlement status

- **WHEN** the buyer reads `settle-status` for an available deal
- **THEN** the response's credentials come from a live read of the fulfillment result

#### Scenario: A former credential response is retried

- **WHEN** an exact retry of an earlier `settle-status` request arrives after a locally admitted end
- **THEN** it is refused, and no stored credential or recorded body is returned

#### Scenario: A storefront upgrades with recorded credential responses

- **WHEN** a VM storefront starts on a database whose replay records hold bodies carrying `tenant_credentials`
- **THEN** every recorded body loses its `tenant_credentials` member, whatever route wrote it, and each record keeps its status and remains a completed outcome
