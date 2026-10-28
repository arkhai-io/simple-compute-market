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

## MODIFIED Requirements

### Requirement: An Alkahest section that cannot settle makes Alkahest unready

A configured `[Settlement.alkahest]` section that parses but under which no deal could be
settled MUST make the Alkahest mechanism unready, with a configuration blocker naming the
setting, and MUST NOT stop the storefront, whether or not the section is enabled. That
covers an oracle-gated section with no trusted oracle; a trusted or interruptible oracle
equal to the seller wallet's address or to the account its key signs as; an interruptible
section with no interruptible oracle; a seller wallet with neither an address nor a key,
whatever clients the storefront composes; a missing wallet key or no configured chain
where the storefront needs them to settle; and a release model the storefront's domain
cannot deliver. A release condition MUST NOT fall back to the seller wallet as its oracle.
A section that does not parse MUST stop startup, as any configuration does.

#### Scenario: An oracle-gated section names no oracle

- **WHEN** a storefront starts with an oracle-gated Alkahest section that lists no trusted
  oracle
- **THEN** it starts, Alkahest is unready with a configuration blocker naming the missing
  oracle, and its other mechanisms publish

#### Scenario: The oracle is the seller's own wallet

- **WHEN** a storefront's Alkahest section names the seller wallet as its trusted oracle
- **THEN** Alkahest is unready with a configuration blocker, and no candidate is refused
  per cycle for it

#### Scenario: The seller wallet has no address

- **WHEN** a VM or API-credit storefront composes Alkahest clients but its seller wallet
  states no address and has no key to derive one from
- **THEN** Alkahest is unready with a configuration blocker, and no listing advertises a
  release condition with no recipient

### Requirement: Readiness blockers state their kind

Every mechanism's readiness blocker MUST carry a kind: `configuration`, which the
storefront's own configuration causes and only an operator can clear, or `reachability`,
raised because a dependency the mechanism needs could not be reached, or has not yet been
probed, to determine readiness. The kind MUST be set on every blocker: by each
mechanism's preflight on the blockers it reports, and by the settlement runtime on the
`not_configured` and `disabled` blockers it builds itself, which are configuration
blockers. Status MUST report it. A mechanism whose readiness contacts nothing reports only
configuration blockers. A disabled section's readiness MUST list, after `disabled`, the
configuration blockers its mechanism's preflight reports for it.

#### Scenario: A chain cannot be reached

- **WHEN** Alkahest's chain probe cannot reach a configured chain
- **THEN** its blocker is the reachability blocker `alkahest.chain_unreachable`

#### Scenario: A required contract is not deployed

- **WHEN** Alkahest's chain probe reaches a chain that has no code at an address its
  address configuration requires
- **THEN** its blocker is the configuration blocker `alkahest.contract_missing`

#### Scenario: A wallet is missing

- **WHEN** Alkahest's seller wallet states no address and has no key to derive one from
- **THEN** its blocker is a configuration blocker

#### Scenario: A mechanism is disabled

- **WHEN** a mechanism's section is absent or disabled
- **THEN** the settlement runtime's `not_configured` or `disabled` blocker is a
  configuration blocker

#### Scenario: A disabled section could not settle

- **WHEN** a seller's Alkahest section is disabled and lacks its wallet key, or names a
  release model its domain cannot deliver
- **THEN** its readiness reports `disabled` followed by the configuration blocker naming
  the problem, and no reachability blocker
