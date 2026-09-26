## ADDED Requirements

### Requirement: Bare-metal buyer commands use the generic role

An installed bare-metal buyer domain MUST register one `bare-metal` command namespace on the core-owned `market` executable and MUST compose schema-driven listing discovery, demand construction, negotiation, exact settlement selection, settlement, status, resume, result/evidence/access retrieval, and teardown through the generic buyer orchestration and authenticated storefront client contracts. The domain plugin MUST NOT call a site or provisioning authority, import a seller or provisioning package, or replace generic persistence with a domain-local run store.

#### Scenario: Buyer completes an ordinary lease

- **WHEN** an installed bare-metal plugin discovers a compatible listing and the buyer invokes `market bare-metal buy` with a valid lease demand
- **THEN** the core role records discovery, accepted negotiation, the exact settlement selection and plan, and later lease lifecycle state under one run identity while domain hooks encode and decode only `bare_metal.v1` payloads

#### Scenario: Provisioning route is offered to the buyer

- **WHEN** a listing, response, configuration value, or command argument attempts to make a provisioning URL, site credential, provider identifier, or direct executor operation authoritative
- **THEN** the buyer rejects it and uses only the accepted storefront authority and agreement references recorded by the core run

### Requirement: Bare-metal demand is exact and buyer-bounded

A version-1 bare-metal buyer demand MUST contain exactly lease duration, one access method supported by the advertised listing, and the method-specific buyer input; SSH MUST require one syntactically valid public key and MUST reject private-key material. The buyer MUST NOT submit an `access_ref`, site, Resource Pool, Physical Resource, physical-host, executor-machine/provider, seller/claimant, price, condition, or deadline override. Negotiation and resume MUST reject any seller response whose immutable domain terms conflict with the selected listing, original demand, canonical parties, or selected settlement option.

#### Scenario: Buyer requests SSH access

- **WHEN** the selected listing supports SSH and the buyer supplies a positive duration within the listing bounds and a valid SSH public key
- **THEN** the buyer emits the canonical `bare_metal.v1` provision envelope with no seller-owned routing or resource fields

#### Scenario: Buyer tries to select a physical host

- **WHEN** buyer input names or changes a site, Physical Resource, physical host, machine, executor, or buyer-issued access reference
- **THEN** demand construction fails before negotiation and no run event or remote mutation records that invalid demand

#### Scenario: Accepted terms change the resource

- **WHEN** a negotiation response binds different immutable resource, listing, party, access-method, or settlement values than the authority-authenticated listing and buyer selection permit
- **THEN** the buyer rejects the response and does not settle it

### Requirement: Bare-metal settlement choice and recovery are immutable

The buyer MUST select exactly one advertised settlement alternative using the shared settlement registry, persist its canonical mechanism, option and obligation identities, and recover from those recorded identities rather than current priority or readiness. Fresh commands MUST resolve the selected active buyer profile exactly once; every `--from <run_id>` mutation or authenticated retrieval MUST resolve the exact profile UUID and retained canonical principal recorded by that run. A hosted action MUST use the shared transient-action policy: only allowlisted metadata is durable, the action URL is fetched when needed and never persisted, and resume re-retrieves authoritative state. No settlement failure MAY switch mechanisms, funding profiles, options, parties, amount, or operation identity.

#### Scenario: Buyer resumes after profile rotation

- **WHEN** a lease run was signed by a retained predecessor principal and another principal is now the selected profile primary
- **THEN** `settle`, `status`, `access`, and `teardown` recovery use the run-recorded predecessor signer and reject use of the new principal for that run

#### Scenario: Hosted materialization needs interaction

- **WHEN** the recorded hosted obligation requires a transient buyer action and command policy permits it
- **THEN** the buyer obtains and handles the current action through the shared adapter, persists only safe action kind/expiry metadata, and resumes the same operation after interaction

#### Scenario: Selected mechanism becomes unready

- **WHEN** current configuration priority or readiness differs from the accepted run
- **THEN** recovery addresses the recorded mechanism and operation or fails closed; it does not choose another advertised alternative

### Requirement: Public lease result and private access retrieval are separate

The buyer MUST accept only an authority-authenticated, versioned, allowlisted lease result and portable evidence projection from the recorded storefront. Public result/evidence MAY identify the agreement, settlement obligation, fulfillment, Physical Resource, allocation or lease, canonical buyer, access method, readiness, and expiry, but MUST NOT contain connection endpoints, usernames, SSH private material, passwords, bearer tokens, arbitrary provider/executor details, provider identifiers, or raw result payloads. Buyer-specific SSH access MUST be retrieved through a separate authenticated operation and MAY expose only the connection host, port, username, host-key fingerprints, validity window, and an opaque grant reference; the buyer supplies its own private key. Access data and transient retrieval URLs MUST NOT enter the run log, profile store, configuration, portable evidence, diagnostics, reprs, or default status output.

#### Scenario: Lease becomes ready

- **WHEN** the storefront reports authoritative whole-host access readiness for the recorded agreement
- **THEN** the buyer verifies the storefront response and exact run binding, decodes the strict lease result/evidence, and can retrieve its separate SSH connection view without accepting an arbitrary `details` or `access_ref` dictionary

#### Scenario: Public evidence contains a credential

- **WHEN** signed evidence includes a password, bearer token, private key, connection endpoint, raw executor result, provider field, or unrecognized property
- **THEN** the buyer rejects the evidence rather than displaying or persisting it

#### Scenario: Access response is signed by another authority

- **WHEN** access data is returned without a valid response proof from the exact storefront authority recorded by the run
- **THEN** the buyer rejects it and does not reveal, cache, or use the data

### Requirement: Buyer teardown is authenticated and idempotent

`market bare-metal teardown --from <run_id>` MUST request teardown from the recorded storefront for the recorded agreement and exact buyer principal; it MUST NOT invoke provisioning directly or represent request acceptance as access revocation. Exact retries MUST return or resume the same teardown operation. Status MUST distinguish requested, running, complete, failed/operator-action, and lease-already-expired outcomes, and completion MUST be based on authoritative revocation/teardown state. Physical teardown remains independent from financial reclaim and MUST NOT alter a completed collection.

#### Scenario: Response is lost after teardown acceptance

- **WHEN** the storefront accepts a teardown request but the buyer loses the response
- **THEN** repeating the command for the same run resumes or returns the same operation without issuing a second physical teardown

#### Scenario: Teardown is still running

- **WHEN** the physical authority has accepted but not completed revocation
- **THEN** the buyer reports a nonterminal teardown state and does not claim that access is revoked or that capacity is available

#### Scenario: Buyer attempts teardown for another agreement

- **WHEN** the run principal or recorded agreement does not authorize the requested teardown
- **THEN** the storefront response is rejected or authorization fails and the buyer does not retry through another authority
