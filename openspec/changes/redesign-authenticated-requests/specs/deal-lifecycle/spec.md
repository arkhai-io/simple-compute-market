## MODIFIED Requirements

### Requirement: The end-delivery acknowledgement is signed by the Agreement's seller

The storefront MUST sign its response to `end_delivery` with the version 3 response signature, `arkhai.market-response-signature.v3`, under the Agreement's `seller` principal, binding the request identity, status, signing time and body, so that the buyer's signed request and that response verify against the Agreement alone. The end-delivery receipt each party keeps MUST hold the request's and the response's records with their exact bodies, and a receipt kept under version 2 MUST remain verifiable.

#### Scenario: A case export carries an acknowledgement

- **WHEN** the buyer exports its end request and the storefront's response
- **THEN** both signatures verify from their records and bodies against the Agreement's buyer and seller principals, and the response binds the storefront's receipt rather than a buyer-asserted historical instant

#### Scenario: A receipt kept before the cutover is verified

- **WHEN** a buyer verifies an end-delivery receipt its end journal kept under version 2
- **THEN** both envelopes verify by their protocol against the Agreement's buyer and seller principals

### Requirement: Each party keeps its commitment envelopes and authority records

The buyer MUST keep the seller's signed acceptance as its signed record and exact body before committing. The seller MUST keep the buyer's signed message the agreement rests on: the buyer's opening or counteroffer the seller accepted, or the buyer's acceptance of a seller counter; an administrative acceptance MUST be kept with its administrator as author.

#### Scenario: A buyer accepts

- **WHEN** a buyer verifies the seller's signed acceptance
- **THEN** it stores the acceptance's signed record and exact body before committing

#### Scenario: The seller accepts the buyer's opening

- **WHEN** a seller accepts a buyer's opening offer with no counter
- **THEN** the seller's store keeps the buyer's signed opening request as its signed record with its exact bytes

#### Scenario: An administrator accepts

- **WHEN** an administrator accepts a negotiation on the seller's behalf
- **THEN** the store keeps the buyer's signed message the acceptance answered and records the administrator as the accepting author

### Requirement: Envelopes are captured at the signed transport boundary

Each party MUST capture its commitment envelopes through an injected envelope-capture seam at the signed transport boundary, which carries the message's signed record, its exact body and the verification context to the party's evidence store before commitment. A storefront MUST receive the request's and the response's records from the admission that authenticated the request, not by reading the request beside it.

#### Scenario: The buyer's transport verifies an acceptance

- **WHEN** the buyer's signed transport verifies the seller's acceptance and returns its parsed payload
- **THEN** the seam has already passed the signed record, exact body and verification context to the buyer's store

#### Scenario: A storefront keeps the buyer's signed opening

- **WHEN** a storefront answers a buyer's `negotiate_new` that its admission core authenticated
- **THEN** its evidence store holds the buyer request's record and exact body as the admission handed them over, and no header

## ADDED Requirements

### Requirement: A lifecycle submit answers a recorded operation first

A seller's lifecycle submit whose `operation_key` is already recorded for its
negotiation with the same request MUST be answered from that record before the
Agreement authority's credential availability or any other check governing a new
submission is evaluated.

#### Scenario: A dispute submit is retried after its credential was removed

- **WHEN** a seller's dispute submit applies, its acknowledgement is lost, the
  Agreement authority's credential is then removed, and the submit's exact retry
  arrives
- **THEN** the storefront answers the recorded submission, and does not reject the
  retry as needing repair
