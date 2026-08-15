## ADDED Requirements

### Requirement: Multi-domain storefront selection has focused compatibility coverage
Deterministic focused tests MUST cover registry validation, immutable listing/thread bindings, publication mode enforcement, domain-envelope matching, migration, restart recovery, result decoding, and teardown using the same shared control flow under VM and bare-metal contracts. The matrix MUST include duplicate, missing, unknown, unsupported, and mismatched modes/identities/versions and MUST assert that no fallback hook or physical effect is invoked.

#### Scenario: Unknown binding is injected at each lifecycle boundary
- **WHEN** focused tests present an unknown domain binding during publication, opening, continuation, settlement, recovery, result, or teardown
- **THEN** the owning boundary returns its declared compatibility/data-integrity error and every registered domain hook and remote mutation spy remains untouched

#### Scenario: A legacy population contains one ambiguous row
- **WHEN** migration tests include otherwise valid VM legacy state plus one contradictory or unclassifiable record
- **THEN** the entire migration rolls back with all pre-migration rows and identifiers unchanged

#### Scenario: The process restarts at each durable handoff
- **WHEN** tests restart after listing publication, thread creation, acceptance, plan persistence, reservation, fulfillment acceptance, active result, and teardown request
- **THEN** the next operation selects the same exact domain/site binding and neither repeats a completed effect nor crosses to the other domain

### Requirement: One storefront proves complete VM and bare-metal lifecycles
System integration evidence MUST run one storefront process with both exact domain registrations against accepted pool-mode and trusted-site/fulfillment authorities. It MUST complete one VM and one bare-metal path through publication, negotiation, settlement, Capacity Reservation, Physical Settlement scheduling, fulfillment, result observation, restart recovery, teardown, and capacity restoration. The proof MUST use real shared HTTP clients and durable repositories with controlled external provider boundaries, not route-internal calls, no-op fulfillment, success flags, or duplicated domain applications.

#### Scenario: Both domains complete through one process
- **WHEN** the scenario buys one VM slice and one bare-metal whole-host offer published by the same process
- **THEN** both produce their domain-correct Terms, plans, reservations, fulfillment results, and teardown outcomes while retaining distinct stable record and operation identities

#### Scenario: Cross-domain payload substitution is attempted
- **WHEN** the scenario swaps the two provision envelopes, result envelopes, listing IDs, settlement references, or teardown identities
- **THEN** each attempt fails at the first exact-binding boundary and neither domain's durable or remote state changes

#### Scenario: One domain fails independently
- **WHEN** a controlled VM fulfillment failure occurs while the bare-metal path is active
- **THEN** VM recovery/compensation proceeds without changing the bare-metal listing, negotiation, reservation, result, or teardown, and the inverse case is also covered

### Requirement: Pool mode and trusted site isolation are proven together
Integration coverage MUST prove that a pool's declared offering modes and a listing's operator-trusted site binding independently constrain the selected domain. Tests MUST cover a pool declaring both modes, one mode, no mode, and mode withdrawal; a second site with compatible capacity; unknown site trust after restart; and cross-mode physical conflict. No test MAY satisfy a refusal by falling back to another domain, site, pool mode, or executor.

#### Scenario: Selected site refuses while another can satisfy
- **WHEN** a listing-bound site refuses and another trusted site has compatible capacity for the same mode
- **THEN** the other site records no reservation, scheduling, provider, result, or teardown call

#### Scenario: Pool allows VM but not bare metal
- **WHEN** both domain publishers observe the same pool and only `vm` is declared
- **THEN** only the VM listing is eligible and a direct bare-metal attempt is rejected before a Capacity Reservation exists

### Requirement: Multi-domain package and deployment evidence uses staged artifacts
Packaging tests MUST install the shared storefront, VM domain, and bare-metal domain wheels from built artifacts into a clean environment, start the combined command, and inspect the image and Helm/Compose renders. Deployment tests MUST cover explicit one-domain and two-domain configurations, duplicate or absent contributions, persistent restart, migration preflight, public-status redaction, and disabled-domain removal without orphaned waits or service references.

#### Scenario: Clean wheelhouse starts the combined role
- **WHEN** only staged wheels and public configuration are available outside the repository layout
- **THEN** the combined storefront imports both exact contributions, reports the frozen registrations, and begins serving without editable source paths

#### Scenario: Rendered public configuration is inspected
- **WHEN** Helm and Compose fixtures enable both domains
- **THEN** registration and trust metadata are present while signer credentials, provider settings, SSH material, and domain result secrets are absent
