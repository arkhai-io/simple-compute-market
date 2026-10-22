## MODIFIED Requirements

### Requirement: Payment buyers approve and settle by negotiation

The buyer MUST supply its Arkhai account as `payer_account`, verify that the mandate is the mechanism's derivation of the negotiated Agreement, including the start and stop authorities its `early_termination` clause implies, validate it against local payment policy, approve with owner-scoped WorkOS credentials, poll the deterministic transaction ID, and send `commit` through the buyer half with the negotiation ID and transaction ID. Marketplace requests MUST use the recorded profile signer and storefront trust, independently of payment credentials.

#### Scenario: Payment and marketplace credentials stay separate

- **WHEN** a payment buyer approves a mandate and then sends `commit`
- **THEN** the approval uses the owner's WorkOS credential, and the `commit` is signed by the recorded profile signer

#### Scenario: A mandate grants the seller an unentitled stop

- **WHEN** a mandate lists the payee as a stop authority while the selected option's clause gives the payee no entitlement
- **THEN** the buyer refuses to approve it

## ADDED Requirements

### Requirement: Buyer lifecycle actions go through the buyer half

Buyer stop, dispute, and read MUST go through the buyer half of the lifecycle interface, dispatched by the domain's buyer stage table, without core buyer code binding the lifecycle kits. After an accepted stop the buyer client MUST send a `hint` to the seller.

#### Scenario: A buyer stops a hosted deal

- **WHEN** a buyer stops a hosted deal it is entitled to stop
- **THEN** the stop goes to the payments service with the buyer's own credential, and a `hint` follows to the storefront
