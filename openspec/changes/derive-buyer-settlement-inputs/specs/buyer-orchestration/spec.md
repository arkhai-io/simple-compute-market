## ADDED Requirements

### Requirement: The API-credit buyer derives its Alkahest inputs

The API-credit buyer's `buy`, `negotiate`, and `settle` commands MUST NOT accept an EVM address, signing key, chain, token, decimals, or escrow identity on the command line. They MUST take the wallet from the buyer's configuration; the chain from the configured chains a listing's accepted escrows name, prompting when several match and refusing under `--yes` with the listing and the candidates named; the token from the selected accepted escrow and its decimals from the chain; and, on settle, the chain and escrow identity from the accepted run. Explicit display prices MUST be scaled with the decimals of the selected option's token, and refused when the selected options' tokens disagree on decimals or the selected listings settle through more than one mechanism.

#### Scenario: A buyer passes a removed flag

- **WHEN** a buyer runs `market credits buy --chain anvil` or passes `--evm-private-key`
- **THEN** the command refuses the unknown option before doing anything

#### Scenario: A listing accepts several configured chains under --yes

- **WHEN** a non-interactive buy or negotiation meets a listing whose accepted escrows name two of the buyer's configured chains
- **THEN** it refuses, naming the listing and both chains

#### Scenario: A listing accepts one configured chain

- **WHEN** a listing's accepted escrows name exactly one configured chain
- **THEN** the buyer settles on that chain without asking

#### Scenario: Explicit prices in display units

- **WHEN** a buyer gives `--initial-price` and `--max-price` and the selected escrow's token reports two decimals
- **THEN** the opening and ceiling are those prices in the token's base units

#### Scenario: Explicit prices across mechanisms

- **WHEN** a buyer gives explicit prices and the selected listings settle through Alkahest and Arkhai payments
- **THEN** the buy refuses, naming both mechanisms, before negotiating
