# contact-exchange-settlement Specification

## Purpose

Define settlement by introduction: `contact-exchange.v1` puts buyer and seller
durably in authenticated contact, with no payment, escrow, or provisioning.
Acceptance, explicit contact capture, and party reads are separate operations.

## Requirements

### Requirement: An introduction completes a deal

Under `contact-exchange.v1`, the accepted plan MUST carry one non-financial
obligation. Explicit introduction start MUST persist the reveal before driving
materialization, check, and collection through the shared settlement runtime.
Completion MUST require neither payment nor provisioning and MUST NOT depend on
whether either party has read the reveal. Acceptance alone MUST NOT complete it.

#### Scenario: A contact-exchange deal settles

- **WHEN** the accepted buyer explicitly starts the introduction with its contact
- **THEN** both contacts and accepted context are persisted and the obligation
  completes without escrow, funding authorization, a chain client, or provisioning

### Requirement: Contact is revealed only after acceptance, only to the counterparty

Contact payloads MUST NOT appear in listings, options, or discovery responses.
Only the accepted buyer SHALL authorize introduction start. After start persists
the reveal, either authenticated party MUST be able to read the counterparty's
contact payload and agreed context through the introductions surface. Reads MUST
be idempotent and MUST NOT capture contacts or advance settlement. No other
principal may read either payload.

#### Scenario: Counterparty reads the introduction

- **WHEN** an authenticated party to a started contact-exchange deal requests its
  introduction
- **THEN** it receives the persisted counterparty payload and agreed context,
  and a repeat request returns the same result

#### Scenario: A non-party requests the introduction

- **WHEN** a principal that is not a party requests the reveal
- **THEN** the request is refused and no contact data is returned

### Requirement: The agreed context is durable

Start MUST capture the buyer-supplied contact, configured seller contact, and
introduction package from the immutable accepted plan. Reads MUST serve these
persisted artifacts, not reconstruct them from current configuration or mutable
negotiation state. Identical repeated starts MUST reuse the record; changed
contact payloads MUST be refused rather than overwrite it. If completion fails
after capture, the reveal MUST remain durable and the same start may retry
completion through the existing obligation.

#### Scenario: Reveal after restart

- **WHEN** the storefront restarts after contact capture, including after seller
  contact configuration changes
- **THEN** a party read serves the identical persisted introduction package

#### Scenario: Completion fails after capture

- **WHEN** lifecycle completion fails after the introduction is persisted
- **THEN** start returns temporary unavailability, the reveal remains readable,
  and an identical start can converge without replacing either contact

### Requirement: Contact payloads are bounded, deliberate PII persistence

Contact payloads MUST be size-bounded at configuration and introduction start,
MUST be persisted only for deals whose introduction has started, and MUST be
deletable without disturbing the settled obligation. A deal that never starts
MUST persist zero contact payloads. The deletion primitive does not imply an
automated retention scheduler or deletion of recipient-owned delivered copies.

#### Scenario: Unstarted deals hold no contact data

- **WHEN** a contact-exchange deal is accepted but the buyer does not start it
- **THEN** no contact payload is persisted for that deal

#### Scenario: Introduction teardown removes the payloads

- **WHEN** an operator invokes introduction deletion at the end of its retention
  window
- **THEN** both payloads are deleted while the settled obligation record remains

### Requirement: Bare-metal contact-only environment composition

The bare-metal environment factory SHALL derive introduction-only operation from
an enabled mechanism set containing only `contact-exchange.v1`. It SHALL construct
no site, capacity, provisioning, chain, or hosted financial runtime. Health SHALL
mark physical checks `not_applicable` and incomplete contact configuration
unavailable. Physical composition SHALL continue to require trusted sites.
Recipient-side delivery remains optional; the synthetic file-publication path
SHALL require no delivery callback, without disabling delivery in other contact
compositions.

#### Scenario: Wallet-free contact-only startup

- **WHEN** a seller supplies an Ed25519 identity, admin identities, public URL,
  database path, and ready contact-only settlement configuration with no delivery
- **THEN** the ordinary server starts with no physical, financial, or delivery
  runtime and no fabricated trusted site

#### Scenario: Contact readiness is incomplete

- **WHEN** the contact-only configuration has no seller contact payload or profile
- **THEN** health is degraded rather than claiming introduction readiness

### Requirement: Unbacked bare-metal contact admission

An unbacked bare-metal listing SHALL contain only validated rateless
`contact-exchange.v1` options with asset `introduction`, no `bare_metal` physical
option facts, no accepted escrows, and exactly `access_methods: [none]`.
Negotiation in introduction-only composition or against an unbacked listing
SHALL refuse financial mechanisms, physical option facts, SSH keys, access
references, or an access method other than `none`. Descriptive machine/host
labels SHALL NOT confer site or provisioning authority.

Shared provenance belongs to [market composition](../market-composition/spec.md#requirement-unbacked-storefront-provenance);
file publication belongs to [storefront publication](../storefront-publication/spec.md#requirement-synthetic-contact-publication-validates-the-whole-file).

#### Scenario: An unbacked offer is accepted

- **WHEN** the buyer selects the exact advertised contact option with non-access
  `bare_metal.v1` terms
- **THEN** acceptance records no resource reservation or contact payload

#### Scenario: A financial or physical offer is unbacked

- **WHEN** an operator submits a financial option, physical access, or a pool or
  Physical Resource without a site
- **THEN** admission fails before writing the listing

### Requirement: Accepted introductions are resolvable before consent

New bare-metal contact acceptances SHALL commit their immutable accepted plan
and pending obligation bookkeeping atomically under the
[shared persistence contract](../market-composition/spec.md#requirement-accepted-plan-bookkeeping-shares-the-commit-transaction).
Registration SHALL create no contact record, mechanism invocation, settlement
operation, fulfillment binding, reservation, or completion. Re-registration
SHALL preserve existing lifecycle state.

#### Scenario: Authorized read before start and after restart

- **WHEN** the accepted buyer or seller signs a read for a registered obligation
  before explicit contact sharing, including after restart
- **THEN** the storefront returns request-bound signed HTTP 409 with detail
  `introduction has not been started`
- **AND** no contact payload or settlement operation is persisted by acceptance
  or the pending read

#### Scenario: A pending response is altered

- **WHEN** the response proof, body, status, principal, method, operation,
  resource, or request identity is altered
- **THEN** authenticated response verification refuses it
- **AND** unknown, nonparty, or unauthenticated requests do not receive authorized
  pending semantics; unsigned refusals retain their response bodies

#### Scenario: An older accepted plan lacks bookkeeping

- **WHEN** a read supplies only the opaque reference of an older unregistered
  acceptance
- **THEN** it remains unresolved with HTTP 404, without a scan or backfill
- **AND** authorized explicit start with the known negotiation ID can still
  capture contacts and register the obligation through the ordinary lifecycle

### Requirement: Literal configured contacts stay out of public artifacts

The contact kit SHALL recursively check decoded public string keys and values
for nonempty configured contact values at profile validation, option construction,
and accepted-obligation construction. Synthetic file publication SHALL use the
same check before local listing intent or registry calls. The check SHALL be
case-sensitive literal substring matching, not general data-loss prevention.

#### Scenario: A contact value requires JSON escaping

- **WHEN** a configured value appears literally in a decoded public string,
  including nested terms/context, arrays, Unicode, quotes, slashes, backslashes,
  or newlines
- **THEN** the owning boundary refuses the artifact
- **AND** a contaminated last offer blocks the whole file before listing/binding
  writes or registry calls

Synthetic publication diagnostics can include the supplied listing ID verbatim.
If that ID contains a configured contact value, the diagnostic echoes it even
though publication is refused. Artifact validation is not a universal diagnostic
redaction boundary.

#### Scenario: Private data is transformed or unconfigured

- **WHEN** public input contains a transformed value or other unconfigured
  private data
- **THEN** the literal guard makes no detection guarantee; it does not normalize
  case, Unicode, URLs, or arbitrary encodings

## Evidence

- Environment composition, health, admission, signed pending reads, explicit
  capture, party refusal, restart, rollback, and old unregistered references:
  `domains/bare_metal/storefront/tests/test_contact_only_runtime.py`.
- Shared start/read and persistence semantics:
  `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py` and
  `kit/contact-exchange/src/market_contact_exchange/migrations.py`.
- Decoded-string guard across profiles, options, and accepted terms/context:
  `kit/contact-exchange/tests/unit/test_contact_value_protection.py`.
- Whole-file escaped-value refusal before local intent or registry calls:
  `domains/bare_metal/storefront/tests/test_contact_publication.py::test_full_file_refuses_escaped_contact_before_intent_or_publication`.
- Optional recipient delivery composition:
  `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/delivery.py` and
  `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`.
