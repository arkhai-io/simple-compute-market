## ADDED Requirements

### Requirement: Hosted API-credit behavior has focused credential-free coverage

Focused tests MUST prove mechanism-neutral listing/selection, exact quantity pricing, canonical principal ownership, shared hosted authorization/transport, transient actions, delayed funding, shared operation journals, exact-once issuance, portable evidence verification, collect/reclaim exclusion, credential redaction, and Alkahest non-regression at the lowest owning level. Tests MUST inject deterministic hosted and credits-authority outcomes through production ports, use controllable clocks/events, and MUST NOT claim Stripe behavior.

#### Scenario: Default API-credit checks run

- **WHEN** no wallet, chain, hosted service, Stripe credential, browser, or external resolver is configured
- **THEN** domain, buyer, storefront, credits service/client, hosted adapter, runtime, migration, package, typing, redaction, and evidence tests complete without silently omitting the credential-free hosted contract

#### Scenario: Issuance acknowledgement is unknown

- **WHEN** a deterministic credits collaborator commits a grant then times out
- **THEN** restart proves one quota reservation, one grant/top-up, one fulfillment/evidence identity, and no duplicate collection

### Requirement: Wallet-free hosted API-credit E2E proves full domain value

A protected/release-qualified E2E scenario MUST use Ed25519 buyer and seller principals, one persistent buyer/payer profile, exact signed marketplace and hosted production artifacts, an ordinary API-credit storefront and credits service, and no wallet/chain/VM/bare-metal components. It MUST purchase a new key through an exact hosted profile, consume credits until the next request returns HTTP 402, top up the same key/profile through another accepted obligation, and prove admitted use resumes. Public reports MUST omit the bearer secret.

#### Scenario: New key purchase and top-up succeed

- **WHEN** authoritative hosted funding, exact-once issuance, evidence, and collection complete for both accepted obligations
- **THEN** the same canonical owner receives one usable key, reaches 402 at exhaustion, gains exactly the top-up quantity, and resumes use without duplicate grant or secret disclosure

#### Scenario: Another principal attempts top-up

- **WHEN** a different canonical Ed25519/EIP-191 principal funds an obligation naming the existing key
- **THEN** issuance is rejected with unchanged balance/quota/ownership, no satisfied evidence/collection, and eligible reclaim according to the accepted deadline

### Requirement: Hosted API-credit fault matrix preserves ordering

Credential-free integration and applicable protected tests MUST cover no issuance before funded, card/bank/ACH delayed states, off-session action fallback, restart before funding, restart after issuance before evidence/collection, terminal issuance failure then reclaim, unfunded expiry, funding/reclaim race, pre-collection return, post-collection loss, changed request conflict, evidence mismatch, and exact retry. Each assertion MUST name the owning boundary and exact mechanism/profile.

#### Scenario: ACH return precedes issuance

- **WHEN** authoritative hosted state reports a pre-collection return before a grant commits
- **THEN** no credits/evidence/collection are produced and recovery stays with the exact hosted obligation

#### Scenario: Issuance commits before restart

- **WHEN** the process stops after grant/evidence commit but before collect acknowledgement
- **THEN** restart recovers the same immutable identities and collects at most once without reissuing or revealing another secret

### Requirement: API-credit protected evidence separates authorities and secrets

A protected report MUST record exact marketplace consumer, hosted producer, credits authority/client, API-credit domain, evidence issuer/resolver, workflow/run, and source identities independently, plus selected profile, public lifecycle stages, attempts, timestamps, safe key ID/quantity/service outcomes, and sanitized API consumption results. It MUST exclude marketplace/hosted/credits credentials, provider/payer/instrument/customer/payment-method/mandate/bank/card data, raw actions/provider payloads, API bearer secrets, unrestricted logs, and source-bearing paths. Recursive canary/schema/signature validation MUST reject a violation before publication.

#### Scenario: Report contains bearer secret

- **WHEN** a full API key or secret fragment appears anywhere in the report/artifacts
- **THEN** validation fails before signing/publication and the run cannot qualify evidence

#### Scenario: External rail is unavailable

- **WHEN** Stripe test mode or the selected account cannot exercise a requested bank/ACH/return boundary
- **THEN** only that exact provider assertion is reported unavailable and deterministic/local evidence is not substituted

### Requirement: API-credit Alkahest evidence remains independent

Existing Alkahest API-credit unit, integration, and E2E scenarios MUST remain unchanged in authority claims and MUST run independently from hosted configuration. Hosted success MUST NOT satisfy an Alkahest regression, and an unavailable chain MUST NOT be reported as hosted failure.

#### Scenario: Alkahest regression lane runs

- **WHEN** existing chain prerequisites are configured
- **THEN** accepted escrow, issuance, credential delivery, compensation, and consumption behavior remain covered without a hosted call or profile requirement
