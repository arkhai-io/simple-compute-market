## MODIFIED Requirements

### Requirement: Payment buyers approve and settle by negotiation

The buyer MUST supply its Arkhai account as `payer_account`, verify that the mandate is the mechanism's derivation of the negotiated Agreement, including its authorities, the dispute authority's account from the option, each part's holds and terms, validate it against local payment policy, approve with owner-scoped WorkOS credentials, and poll the deterministic transaction ID. On VM and bare-metal deals it MUST then send `commit` through the buyer half with the negotiation ID and transaction ID; on API-credit deals it MUST settle with `settle_agreement`. Marketplace requests MUST use the recorded profile signer and storefront trust, independently of payment credentials.

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

### Requirement: The buyer's end is backed by its own stop or a case

The buyer half's end command MUST issue the buyer's `stop` at the payment authority before it sends `end_delivery`. When the payment authority's answer is `unknown` or the authority is unreachable, it MUST still send `end_delivery` and MUST file `buyer_end(at)` with the agreement's dispute authority, carrying the signed request and the storefront's signed response as evidence; a filing the dispute authority cannot receive MUST be journaled and retried under its idempotency key.

#### Scenario: The payment authority is down

- **WHEN** a buyer ends a hosted VM deal while the payment authority is unreachable
- **THEN** delivery ends, and a `buyer_end` case at the request's time is filed with the dispute authority with both signed messages

#### Scenario: Both authorities are down

- **WHEN** a buyer ends a deal while neither authority is reachable
- **THEN** delivery ends, the filing is journaled, and it is filed once the dispute authority answers

#### Scenario: The stop is accepted

- **WHEN** the payment authority accepts the buyer's stop
- **THEN** the buyer half sends `end_delivery` and files nothing

### Requirement: Buyer lifecycle actions go through the buyer half

On VM and bare-metal deals, dispute filing, appending to a case, read, and any payment command the deal's parts offer the buyer MUST go through the buyer half of the lifecycle interface, dispatched by the domain's buyer stage table, without core buyer code binding the lifecycle kits. After a filed dispute the buyer client MUST send a `hint` to the seller.

#### Scenario: A buyer files a dispute on a hosted deal

- **WHEN** a buyer files a dispute on a hosted deal
- **THEN** the case goes to the agreement's dispute authority with the buyer's own credential and its case payload, not to the payments service; filing's outcome is the authority's answer, `accepted` with the case reference and each part's status; and a `hint` follows to the storefront
