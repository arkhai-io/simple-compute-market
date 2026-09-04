## MODIFIED Requirements

### Requirement: Provider-neutral conditional escrow client

The kit-owned settlement runtime MUST drive every settlement mechanism through one asynchronous conditional-escrow contract whose operations materialize an obligation, retrieve authoritative status, evaluate an immutable fulfillment reference, collect an authorized obligation, and reclaim an expired obligation. Results MUST expose only an opaque mechanism reference, public lifecycle status, safe normalized reason/deadline, optional transient buyer action, optional condition anchor, and opaque durable receipt. Mechanism input MAY contain one exact public funding profile and operation-scoped authorization reference but MUST NOT expose a stable payer/instrument or provider model to the runtime.

Reclaim MAY additionally carry mechanism-scoped options supplied by the
requesting participant for that one operation. The runtime MUST pass them to the
mechanism client without interpreting them, MUST NOT persist them, and MUST NOT
project them into any receipt, mechanism state, or public status. Because two
reclaims of one obligation naming different options are two different requests,
the reclaim reservation MUST bind the options it was given, so that a later
reclaim naming different ones is refused rather than silently reusing the first
reservation.

#### Scenario: Hosted materialization requires buyer action

- **WHEN** `fiat.stripe.v1` materialization or confirmation creates a hosted action
- **THEN** the runtime persists the opaque hosted reference and public action kind/expiry while the URL/client secret remains transient and service-owned

#### Scenario: Alkahest remains selected

- **WHEN** an `alkahest.v1` obligation is serviced
- **THEN** the existing Alkahest adapter, fields, SDK operations, and outcomes remain unchanged and no hosted-service call occurs

#### Scenario: A reclaim carries mechanism-scoped options

- **WHEN** a payer requests reclaim supplying options the selected mechanism understands
- **THEN** the runtime dispatches them to that mechanism's client unread and unstored, and the obligation's durable state gains no field naming them

#### Scenario: A second reclaim names different options

- **WHEN** a reclaim is requested for an obligation whose earlier reclaim reservation bound different options
- **THEN** the reservation is refused, and the refusal names a conflicting request rather than reaching the mechanism

#### Scenario: A mechanism that needs no options is unaffected

- **WHEN** a reclaim supplies no options, or supplies options to a mechanism that reads none
- **THEN** the operation proceeds exactly as it does today with no additional mechanism input

### Requirement: Mechanism clients own mechanism vocabulary
Alkahest-specific plan, status, arbiter, collection, and reclaim encoding MUST
live in the Alkahest kit behind the shared conditional-escrow client port. Where
a reclaim carries mechanism-scoped options, only the mechanism's own client MUST
interpret them; the buyer transport, storefront routes, and settlement runtime
that relay them MUST NOT name any option or condition its meaning on one.

#### Scenario: Runtime evaluates an Alkahest obligation
- **WHEN** it needs mechanism-specific status, readiness, collection, or
  reclaim behavior
- **THEN** it dispatches through the registered Alkahest client with the stable
  operation reference and prior durable mechanism state

#### Scenario: A hosted profile needs a payer return address

- **WHEN** a hosted obligation funded by push transfer is reclaimed and the
  authority requires somewhere to address the payer's return
- **THEN** the hosted client alone reads that address out of the reclaim's
  mechanism-scoped options and places it on its own request, and no relaying
  layer names it
