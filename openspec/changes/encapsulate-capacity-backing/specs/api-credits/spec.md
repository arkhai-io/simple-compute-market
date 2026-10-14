## ADDED Requirements

### Requirement: An API-credit listing is rechecked against its source

Before every seller decision in a negotiation round, and before a buyer's or an
administrator's acceptance, the API-credit storefront MUST recheck the listing
against its source: that its quota resource is still declared in its pool, that the
pool is enabled and advertises `api_credits`, and that the pool's backing equals the
listing's bound backing. For a capacity-backed listing it MUST also require at least
one available unit. A source it cannot confirm MUST be refused as retryable. A
buyer's exit MUST NOT be rechecked.

#### Scenario: The pool stops advertising API credits

- **WHEN** a buyer negotiates against a listing whose pool no longer advertises `api_credits`
- **THEN** the seller rejects with a declared-match reason

#### Scenario: Quota is exhausted

- **WHEN** a buyer negotiates against a capacity-backed listing whose quota resource has no available unit
- **THEN** the seller rejects with the availability reason

#### Scenario: The credits service cannot be reached

- **WHEN** the listing's source cannot be confirmed
- **THEN** a seller decision that would counter or accept, and any acceptance, is refused as retryable

## MODIFIED Requirements

### Requirement: Quota-backed publication
An API-credits listing MUST identify a named service and an authoritative quota resource. Publication from quota MUST require that resource to exist with available capacity, and MUST resolve the backing the resource's pool declares from the credits service's resource-pool projection, which carries each pool's declarations. Listing creation MUST record the listing's immutable durable binding — site, offering mode, quota resource, pool, domain identity and version, and backing — and every capacity effect, reconciliation, and recheck MUST build the listing's binding from that record, never from the published listing. A pool whose backing leaves no settlement option the domain may publish MUST yield no listing. Reconciliation MUST close an open capacity-backed listing when authoritative availability reaches zero and MAY reopen it when availability later becomes positive; an unavailable authority MUST preserve the last complete listing state rather than be interpreted as zero. The storefront MUST refuse to start against a database holding a listing with no durable binding, naming that a fresh database is required.

#### Scenario: Quota is exhausted and later replenished
- **WHEN** reconciliation observes zero available units for an open capacity-backed listing and later observes at least one available unit
- **THEN** it closes the listing and subsequently republishes it from the new authoritative view

#### Scenario: Quota authority is unavailable
- **WHEN** reconciliation cannot obtain an authoritative availability view
- **THEN** it neither closes nor reopens the listing based solely on that failure

#### Scenario: A listing is created
- **WHEN** an operator creates a listing for a quota resource in a backed pool
- **THEN** the listing and its durable binding, recording the pool's declared backing, are stored together before registry publication

#### Scenario: A database predates listing bindings
- **WHEN** the storefront starts against a database holding a listing with no durable binding
- **THEN** it refuses to start and names the listing and the fresh-database remedy

### Requirement: Advisory negotiation checks and authoritative issuance
Negotiation-time quota and key checks MUST be advisory guards over captured views. The quota check MUST compare a requested quantity with captured availability only for a listing whose backing is bounded by availability, and MUST report itself not applicable otherwise. Existing-key negotiation MUST reject known revoked keys, keys owned by another wallet, and unavailable keys while allowing an active unowned key to receive an open top-up. Issuance MUST recheck key status and ownership at the credits service and MUST commit a live quota hold or atomically reserve fresh quota before granting credits.

#### Scenario: Captured quota cannot satisfy the request
- **WHEN** the captured availability is two units and the buyer requests three
- **THEN** negotiation rejects the request without placing a quota hold

#### Scenario: Negotiation view is stale at issuance
- **WHEN** accepted terms reach issuance after their hold expired or key state changed
- **THEN** the credits service repeats authoritative quota and key checks before changing the balance
