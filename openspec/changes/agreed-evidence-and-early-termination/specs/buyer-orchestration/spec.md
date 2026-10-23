## MODIFIED Requirements

### Requirement: Payment buyers approve and settle by negotiation

The buyer MUST supply its Arkhai account as `payer_account`, verify that the mandate is the mechanism's derivation of the negotiated Agreement, including each part's event authorities and terms, validate it against local payment policy, approve with owner-scoped WorkOS credentials, and poll the deterministic transaction ID. On VM and bare-metal deals it MUST then send `commit` through the buyer half with the negotiation ID and transaction ID; on API-credit deals it MUST settle with `settle_agreement`. Marketplace requests MUST use the recorded profile signer and storefront trust, independently of payment credentials.

#### Scenario: Payment and marketplace credentials stay separate

- **WHEN** a payment buyer approves a VM mandate and then sends `commit`
- **THEN** the approval uses the owner's WorkOS credential, and the `commit` is signed by the recorded profile signer

#### Scenario: A mandate grants the seller an unentitled stop

- **WHEN** a mandate lists the payee as a stop authority while the selected option entitles only the payer
- **THEN** the buyer refuses to approve it

### Requirement: The typed client settles Agreement deals apart from EVM deals

The typed storefront client MUST settle an Agreement-settled deal with `settle_agreement(negotiation_id)` only where the domain has no buyer lifecycle route, which sends only the negotiation ID and the signer's principal; where the route exists the lifecycle client's `commit` replaces it. EVM settlement is the separate `settle_evm`, so EVM arguments never appear on the agreement path. Both settle calls use the settle route contract, and the storefront dispatches on the accepted Agreement's mechanism.

#### Scenario: A buyer settles a payments deal through the typed client

- **WHEN** a buyer settles an accepted Arkhai payments API-credit deal with `settle_agreement`
- **THEN** the request carries the negotiation ID and the buyer's principal and no EVM fields

#### Scenario: A buyer commits a VM payments deal

- **WHEN** a buyer has approved the mandate of a VM deal
- **THEN** it sends `commit` through the lifecycle client, not `settle_agreement`

## ADDED Requirements

### Requirement: Buyer lifecycle actions go through the buyer half

Buyer stop, dispute, and read MUST go through the buyer half of the lifecycle interface, dispatched by the domain's buyer stage table, without core buyer code binding the lifecycle kits. After an accepted stop the buyer client MUST send a `hint` to the seller.

#### Scenario: A buyer files a dispute on a hosted deal

- **WHEN** a buyer files a dispute on a hosted deal
- **THEN** the dispute goes to the payments service with the buyer's own credential and its case payload, and a `hint` follows to the storefront
