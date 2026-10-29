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

The buyer half MUST dispatch payment stops through the payment adapter. If payments is unknown/unreachable, it MUST send receipt-only end_delivery and file buyer_end(at) with its kept request and any seller acknowledgement. It MUST use acknowledged receipt when available, otherwise retain its observed time as a contested claim, and MUST NOT claim automatic adjudication. Rate stop sequencing and notice behavior belong to rate servicing.

#### Scenario: The payment authority is down

- **WHEN** a buyer requests an end while payments is unreachable
- **THEN** the buyer sends end_delivery without at, retains the signed receipt if obtained, and files a buyer_end case for human triage without claiming the seller's billing action or case has completed

#### Scenario: Both authorities are down

- **WHEN** the storefront acknowledges surrender while both authorities are unreachable
- **THEN** the buyer retains receipt evidence and journals its case for retry; seller cooperative payment progress remains distinct

### Requirement: A buyer end filing survives an absent dispute authority

A `buyer_end` filing the dispute authority cannot receive MUST be journaled and retried under its idempotency key.

#### Scenario: A retry after restart

- **WHEN** the buyer half restarts with a journaled, unacknowledged `buyer_end` filing
- **THEN** it files under the same idempotency key and the authority records one case

### Requirement: Compute buyers end delivery through the canonical lifecycle client

The VM and bare-metal buyer end commands MUST use the lifecycle client's `end_delivery(negotiation_id)` through the buyer half, with the accepted buyer's profile signer and storefront trust. `market bare-metal teardown` MUST remain the bare-metal verb over this shared client, not a domain-only transport.

#### Scenario: A bare-metal buyer tears down

- **WHEN** the buyer runs `market bare-metal teardown` for its committed deal
- **THEN** it uses the same authenticated lifecycle client method as the VM end verb and keeps the signed response

#### Scenario: A buyer leaves a reserved deal

- **WHEN** a buyer ends delivery on a `once`-only hosted deal or a current Alkahest deal without a lifecycle payment adapter
- **THEN** it sends `end_delivery` without trying an unsupported payment stop or claiming a refund

#### Scenario: The storefront is down

- **WHEN** a buyer's rate-part stop is accepted but the storefront cannot receive the hint
- **THEN** the command reports the accepted stop and unacknowledged hint separately and does not claim the resource was torn down

#### Scenario: The buyer obtains a site report

- **WHEN** the buyer's lifecycle read returns a site-signed `lease_ended` report
- **THEN** the buyer stores its exact bytes and proof even if it has no independently trusted site identity to verify it, without treating it as a payment authority record

### Requirement: The buyer client keeps and reports its end evidence

The client MUST verify signed responses and keep exact request and acknowledgement envelopes and any site-signed reports returned by lifecycle reads. Progress MUST distinguish delivery acknowledgement, payment-stop outcome and any case.

#### Scenario: An end with an unknown stop

- **WHEN** the storefront acknowledges `end_delivery` and the payment stop's answer is `unknown`
- **THEN** the buyer sees delivery acknowledged, the stop unknown and the filed case, and keeps both signed envelopes

### Requirement: Buyer lifecycle actions go through the buyer half

On VM and bare-metal deals, dispute filing, appending to a case, read, and any payment command the deal's parts offer the buyer MUST go through the buyer half of the lifecycle interface, dispatched by the domain's buyer stage table, without core buyer code binding the lifecycle kits. After a filed dispute the buyer client MUST send a `hint` to the seller.

#### Scenario: A buyer files a dispute on a hosted deal

- **WHEN** a buyer files a dispute on a hosted deal
- **THEN** the case goes to the agreement's dispute authority with the buyer's own credential and its case payload, not to the payments service; filing's outcome is the authority's answer, `accepted` with the case reference and each part's status; and a `hint` follows to the storefront
