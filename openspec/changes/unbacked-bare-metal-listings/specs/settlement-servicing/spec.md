## ADDED Requirements

### Requirement: Settlement verifies against the accepted plan

Every storefront that settles Alkahest deals MUST verify a buyer's escrow, register its
obligations, and settle against the settlement plan committed when the deal was
accepted, and MUST NOT re-derive the plan, its release condition, or its escrow terms
from the listing as currently stored or from current settlement configuration. Every
other reader of an accepted deal's settlement terms — an administrator's preview of its
verification, its oracle evidence's heartbeat interval, and an administrator's interrupt
deciding whether it is interruptible — MUST read the same plan. A seller's change to its
release policy, wallet, or chain address book after acceptance MUST NOT change how an
accepted deal is verified.

#### Scenario: The seller changes its release policy after acceptance

- **WHEN** a VM, bare-metal, or API-credit deal is accepted under the recipient release
  model, the seller then configures another model, and the buyer settles an escrow funded
  under the accepted plan
- **THEN** settlement verifies the escrow against the accepted plan and proceeds

#### Scenario: An escrow does not match the accepted plan

- **WHEN** a buyer settles an escrow whose arbiter, demand, token, or contract differs
  from the accepted plan's obligation
- **THEN** settlement refuses it, whatever the listing now states

#### Scenario: An administrator previews verification after a policy change

- **WHEN** a seller changes its release policy after acceptance and an administrator
  previews verification of the deal's escrow
- **THEN** the preview checks the escrow against the accepted plan and agrees with
  settlement's verification
