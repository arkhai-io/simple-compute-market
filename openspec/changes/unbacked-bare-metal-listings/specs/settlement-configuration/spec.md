## ADDED Requirements

### Requirement: An Alkahest section that cannot settle makes Alkahest unready

A configured `[Settlement.alkahest]` section that parses but under which no deal could be
settled MUST make the Alkahest mechanism unready, with a configuration blocker naming the
setting, and MUST NOT stop the storefront, whether or not the section is enabled. That
covers an oracle-gated section with no trusted oracle; a trusted or interruptible oracle
equal to the seller wallet; an interruptible section with no interruptible oracle; a
missing seller wallet address, whatever clients the storefront composes; a missing wallet
key or no configured chain where the storefront needs them to settle; and a release
model the storefront's domain cannot deliver. A release condition MUST NOT fall back to
the seller wallet as its oracle. A section that does not parse MUST stop startup, as any
configuration does.

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
  has no address
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

- **WHEN** Alkahest's seller wallet has no address
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

### Requirement: Alkahest probes its chains apart from readiness

A storefront composing Alkahest MUST probe each configured chain apart from readiness
evaluation, in its `alkahest-chain-probe` lifecycle loop, which the Alkahest kit supplies
and the storefront registers beside its other loops, with the pause and explicit step
every storefront loop has: reading the chain's identity and the code at each contract
address its address configuration requires, the loop's timer probing each chain once per
configured probe interval and an explicit step probing at once, with every call bounded by
a timeout. Alkahest readiness MUST read each chain's
last probe result and MUST NOT call a chain itself. A chain not yet probed since start
MUST read as a reachability blocker. A result MUST NOT expire while the loops are held. A
chain whose client could not be constructed MUST be probed at each probe until its
client's construction succeeds, a probe finding no construction running starting one and
waiting for it no longer than the same timeout; at most one construction per chain MUST
run at a time, a probe finding one still running MUST start no other, and a construction
finishing after its probe's wait MUST be adopted by a later probe; until it succeeds the chain MUST read as a reachability blocker whatever its RPC answers,
and every consumer of the storefront's Alkahest clients MUST read them through the map the
probe updates, so the storefront recovers without a restart. Readiness MUST judge the
chains a publication names, and with no publication input every configured chain; every
storefront's status MUST evaluate readiness with no publication input, and report each
chain's last result and when it was taken.

#### Scenario: Readiness is evaluated for many candidates

- **WHEN** a publication cycle evaluates Alkahest readiness for every candidate it builds
- **THEN** no chain is called more than its probe interval allows

#### Scenario: A storefront starts with its chain down

- **WHEN** a storefront starts while its chain's RPC is unreachable, and the RPC later
  answers
- **THEN** Alkahest is unready with a reachability blocker until a probe succeeds, then
  ready, without a restart

#### Scenario: A chain answers but its client cannot be built

- **WHEN** a chain's RPC answers the probe's calls but its client's construction fails or
  does not finish within the timeout
- **THEN** Alkahest is unready with a reachability blocker for that chain, and the next
  probe that constructs the client makes it ready, without a restart

#### Scenario: A client's construction never returns

- **WHEN** a chain's client construction never returns, across many probes
- **THEN** only that one construction runs, the chain reads as a reachability blocker at
  each probe, and the storefront's other work goes on

#### Scenario: A configured chain no listing publishes on stops answering

- **WHEN** a storefront configures two chains, its listings publish on one, and the other
  stops answering
- **THEN** status reports Alkahest unready with a reachability blocker, since servicing a
  deal accepted on that chain needs it, while publication on the answering chain goes on

#### Scenario: A scenario holds the loops

- **WHEN** a storefront's loops are held after a probe and its chain later stops answering
- **THEN** readiness keeps reporting the held result, with the time it was taken, until
  the `alkahest-chain-probe` loop is stepped or resumed

## MODIFIED Requirements

### Requirement: Priority orders choices but never changes accepted settlement

Storefront publication MUST emit options in configured priority order for every enabled and ready registration with a valid publication clause and a supported seller-stage entry. Buyer compatibility/selection MUST intersect registration compatibility with supported buyer-stage entries and MAY use priority as policy input. Accepted Terms MUST pin one exact option; configuration, readiness or priority changes MUST NOT switch an accepted or in-flight mechanism.

#### Scenario: One of two enabled mechanisms is unready

- **WHEN** one supported mechanism preflight fails and the other is ready
- **THEN** publication suppresses only the unready mechanism, reports its blocker and advertises the ready mechanism

#### Scenario: No enabled mechanism is ready

- **WHEN** every enabled mechanism fails preflight
- **THEN** publication derives no option and refuses the candidate, as storefront publication's "A compute candidate with no settlement option yields no listing" requires, without replacing existing accepted Terms or starting a settlement

#### Scenario: Registration lacks a domain stage

- **WHEN** an installed registration has no supporting entry for the publishing or selecting role
- **THEN** no fresh option for that role is published or selected, even if its configuration and preflight are valid
