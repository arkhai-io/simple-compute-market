## MODIFIED Requirements

### Requirement: Delivery fires once per reveal and re-delivery is explicit

Seller-side delivery MUST be dispatched at most once per introduction, by the
introduction start that completes its reveal, whether that is the first start or a new
start after one whose completion failed. Once completion succeeds, the start MUST claim
the introduction's seller-side delivery with a write that succeeds for exactly one
caller, and only the start that claims it MUST dispatch; an exact replay, a subsequent
read of the durable reveal, or any other start, concurrent or later, MUST NOT dispatch
again. The claim records that dispatch was scheduled, not that a sink received it: a
dispatch lost before it ran, or failed at every sink, is recovered only by re-delivery.
Each side MUST offer an explicit operator action that re-delivers an already-revealed
introduction, and no counterparty request MUST cause a side's sinks to send again.

An introduction start MUST be declared `RERUN`, so its response body, which holds a
counterparty's contact, is never recorded for replay. An exact replay of a start whose
completion failed MUST complete the reveal as a new start does, dispatching the seller's
side once through the same claim. The failed start's answer MUST say that starting the
introduction again completes it.

An introduction whose contact payloads have been deleted MUST NOT be delivered: an
introduction start that finds the payloads already deleted MUST NOT deliver, and an
operator's re-delivery request for such an introduction MUST be refused without
contacting any sink. Re-delivery reads the durable reveal rather than reconstructing
one, so once the payloads are gone there is nothing it may send. A start that completed
the reveal from payloads it read before the deletion committed preceded the deletion, and
the one dispatch it claims belongs to it even if the deletion commits before that dispatch
is scheduled.

#### Scenario: The reveal request is retried

- **WHEN** a buyer retries an introduction start and the retry is served as an exact
  replay
- **THEN** no additional delivery occurs on either side

#### Scenario: A reveal's first completion failed

- **WHEN** a buyer's first introduction start persisted the introduction and answered 503
  because completion failed, and the buyer's next start, a new request, completes it
- **THEN** the seller's side is dispatched once, by that next start
- **AND** no later start dispatches again

#### Scenario: A failed start is replayed exactly

- **WHEN** a start whose completion failed and answered 503 is resent as an exact replay
- **THEN** the replay completes the reveal and answers it
- **AND** the seller's side is dispatched once, and no later start dispatches again
- **AND** no copy of the revealed contact is held for replay

#### Scenario: Two starts complete a reveal concurrently

- **WHEN** two starts with different request identities complete the same introduction
  at once
- **THEN** exactly one of them claims the seller-side delivery and dispatches it
- **AND** the other dispatches nothing

#### Scenario: A buyer repeats a completed start

- **WHEN** a buyer sends further starts for an introduction whose reveal already completed
- **THEN** each answers the durable reveal and no seller-side sink is contacted

#### Scenario: Operator re-delivers after a failed send

- **WHEN** an operator explicitly requests re-delivery of a revealed introduction
- **THEN** the same introduction is sent to the configured sinks again, and the action
  reports each sink's outcome

#### Scenario: Deletion commits while the first reveal is completing

- **WHEN** a start has read the introduction's payloads and completed its reveal, and a
  deletion of the payloads commits before that start dispatches the seller's delivery
- **THEN** that start claims and dispatches the one delivery from the payloads it holds,
  best-effort like every dispatch
- **AND** no later start or re-delivery delivers again

#### Scenario: Operator re-delivers a deleted introduction

- **WHEN** an operator requests re-delivery of an introduction whose contact payloads
  have been deleted
- **THEN** the request is refused and no configured sink is contacted

### Requirement: A webhook delivery can be authenticated by its receiver

A seller-side webhook instance MAY be configured to sign each request with the
storefront's marketplace signer, so the receiving API can verify the sender against
the storefront principal it already trusts rather than relying on the secrecy of its
URL. A signed delivery MUST cover the configured endpoint's target URI, so a delivery
signed for one receiver fails verification at another. Signing material MUST reach the sink from the storefront's composition, never
through sink settings, and a signing instance MUST be refused when constructed in a
process that has no marketplace signer.

#### Scenario: A seller's API verifies a delivery

- **WHEN** a signing webhook instance delivers a revealed introduction
- **THEN** the request carries a signature the receiver can verify against the
  storefront's public principal
- **AND** the request body is the same delivery event an unsigned instance sends

#### Scenario: A signed delivery is sent to another receiver

- **WHEN** a signed delivery made for one endpoint is replayed to a different receiver
- **THEN** that receiver's verification fails because the covered target URI is not its own

#### Scenario: A buyer configures signing

- **WHEN** a buyer-side webhook instance is configured to sign
- **THEN** construction fails naming the instance, because the buyer process holds no
  storefront signer

