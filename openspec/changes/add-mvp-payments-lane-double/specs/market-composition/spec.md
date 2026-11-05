## ADDED Requirements

### Requirement: The payments kit reads an account's own balance

`PaymentsClient` MUST offer `get_balance(account)`, calling the payments service's `GET /balances/{account}` and returning the published `Balance` model, with the account validated as an account identifier. The kit's `PaymentsAuthority` engine MUST offer the same view — `available` by asset, and one `held` entry per part where the account is the payee with held money, timed by its effective maturity or held until stop or lift — and `FakePaymentsClient` MUST serve it from that engine.

#### Scenario: A payer reads its balance

- **WHEN** a payer's client reads the payer's own balance
- **THEN** it receives the published `Balance`, whose `available` already excludes the payer's outgoing escrow

#### Scenario: A caller reads another account's balance

- **WHEN** a client reads a balance for an account other than its own
- **THEN** the service refuses it with 403 `caller_not_authorized`, and the client raises the refusal with that code

#### Scenario: A payee has held money

- **WHEN** the engine holds a once part's money for a payee until its hold matures
- **THEN** the payee's balance lists that part once, with its held amount and its effective `releaseAt`
