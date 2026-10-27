## ADDED Requirements

### Requirement: A seller's wallet address and key name one account

A seller's Alkahest readiness MUST report `alkahest.wallet_address_mismatch` when its
configured wallet address is not the address its wallet key signs as, in every storefront.
A seller that states no address MUST use the key's. Alkahest's check that a release oracle
is not the seller MUST compare the oracle with the signing account as well as the address.

#### Scenario: The address names another account

- **WHEN** a storefront's `[Wallet].address` differs from the address its key derives
- **THEN** Alkahest is unready with `alkahest.wallet_address_mismatch`, the storefront keeps
  running its other mechanisms, and no Alkahest option is published

#### Scenario: The address is omitted

- **WHEN** a seller configures a wallet key and no address
- **THEN** the storefront uses the key's address wherever the seller's address is named

#### Scenario: The oracle is the signing key

- **WHEN** a seller configures as its release oracle the account its wallet key signs as
- **THEN** Alkahest is unready, whatever address is configured

### Requirement: Alkahest address books are named per chain in the Alkahest section

A role MUST name each chain's Alkahest address book only in `[Settlement.alkahest.address_books]`,
a table from configured chain name to book; a chain it does not name uses the SDK's
built-in addresses. Every reader of a chain's book MUST resolve it through that table. A
key naming no configured chain MUST make Alkahest unready. `[Chains.<name>].alkahest_address_config_path`
and `[Settlement.alkahest].address_config_path` MUST be refused with a diagnostic naming the
table, and migration MUST move either into it.

#### Scenario: A seller trades on two chains

- **WHEN** a seller names an address book for `anvil` and none for `base_sepolia`
- **THEN** publication, verification, and claim servicing use the book for `anvil` and the
  built-in addresses for `base_sepolia`

#### Scenario: A retired key is stated

- **WHEN** configuration states `[Chains.anvil].alkahest_address_config_path`
- **THEN** the role refuses it, naming `[Settlement.alkahest.address_books]`

#### Scenario: A configuration is migrated

- **WHEN** an operator migrates a configuration naming a book under either retired key
- **THEN** the book is named under `[Settlement.alkahest.address_books]` for its chain, and
  migration refuses two different books for one chain
