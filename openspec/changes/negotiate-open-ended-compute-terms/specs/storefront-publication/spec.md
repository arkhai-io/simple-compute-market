## ADDED Requirements

### Requirement: Compute listings carry two capacity bounds

Compute listings MUST carry resolved `max_duration_seconds` and MAY carry
`available_until_utc` as listing-level capacity facts. Resolution MUST prefer
storefront override, then pool hint, then configured default per offering mode.
The relative bound limits any deal's lifetime; the absolute UTC bound limits every
lease end. A later publication MUST NOT extend an accepted Agreement.

#### Scenario: Absolute date overrides a hint

- **WHEN** the pool and storefront override state different availability dates
- **THEN** the published listing uses the override while retaining the independently resolved relative bound

### Requirement: Compute product classes are derived options

Publication MUST retain existing capacity/shape listing identity while offering
separately priced billing/entitlement combinations. Reserved, on-demand and spot
MUST NOT be stored class fields. Recurring options MUST use shared early-termination
and adjudication terms; an on-demand option MUST grant no payee stop entitlement.
Unsupported lifecycle promises MUST NOT be synthesized for the Alkahest splitter.

#### Scenario: Three hosted products share capacity

- **WHEN** a pool offers prepaid, payer-only recurring and payer/payee recurring presets
- **THEN** one listing offers separately priced reserved, on-demand and spot options
- **AND** none creates independent capacity

#### Scenario: Existing splitter option

- **WHEN** an existing Alkahest splitter option is published
- **THEN** its accepted release condition and current service terms remain authoritative
- **AND** no unsupported lifecycle terms are invented to label it

### Requirement: Recurring presets expose the premature-stop penalty

Terms publication MUST resolve the penalty preset default and seller override before invoking the helper. An on-demand preset with no stated penalty MUST default to the quoted per-period price times the storefront setting `[pricing].default_premature_stop_penalty_periods`, which defaults to 24 and which the storefront MUST refuse at startup unless it is a positive integer; a penalty stated on the clause, including an explicit `"0"`, MUST win, and spot carries none by default. The injected helper MUST encode only the supplied early_termination.premature_stop_penalty through the foundation codec into candidate identity. A missing helper MUST omit recurring candidates with a named refusal rather than reconstruct mechanism params; reserved candidates MUST remain independent.

#### Scenario: A default on-demand preset is emitted

- **WHEN** the seller supplies no penalty override and the hosted preset helper is composed
- **THEN** its candidate carries 24 periods' price as the penalty, not a bond requirement

#### Scenario: A seller configures the penalty multiple

- **WHEN** `[pricing].default_premature_stop_penalty_periods` is 12 and an on-demand clause states no penalty
- **THEN** its candidate carries 12 periods' price, while a clause stating its own penalty keeps it

#### Scenario: A penalty multiple that is not a positive integer is refused

- **WHEN** `[pricing].default_premature_stop_penalty_periods` is 0, negative or fractional
- **THEN** the storefront refuses to start, naming the key

### Requirement: Unbounded recurring candidates close independently

A recurring candidate with no positive finite seller bound MUST yield no recurring
option and a derivation diagnostic. This absence alone MUST NOT hold a readable
pool or suppress a valid reserved candidate. In both domains no positive relative
maximum means no relative limit, so a reserved candidate MUST NOT be held for
lacking one; every reserved deal carries the buyer's explicit duration, checked at
acceptance against both bounds. When the buyer names no horizon and the limiting
bound is a fractional-second `available_until_utc`, the default horizon MUST be
floored to whole seconds at publication as at acceptance.

#### Scenario: Unbounded VM pool retains reserved sales

- **WHEN** a readable VM pool has no finite bound and has a valid reserved candidate
- **THEN** recurring options are omitted with a close reason and the reserved option remains

#### Scenario: A bare-metal pool states no maximum duration

- **WHEN** a bare-metal pool resolves no positive `max_duration_seconds` from any tier and has a valid reserved candidate
- **THEN** its reserved option publishes with no relative maximum, and a reserved deal's explicit duration is still checked against `available_until_utc` at acceptance

### Requirement: Recurring publication checks servicing

Publication MUST omit recurring candidates when composition does not declare
compatible rate servicing. It MUST derive the declaration from composition, not
listing terms; if no option remains it MUST use existing no-settlement-option
diagnostics. There MUST NOT be a bare-metal minimum-spend publication gate. A setup amount is
the seller's choice; a setup-bearing preset MUST publish only when the mechanism's helper declares
support for setup delivery end and the composition's declaration sets `setup` for that mechanism.

#### Scenario: Dark recurring product

- **WHEN** rate servicing is undeclared but a pool offers recurring and valid reserved candidates
- **THEN** only the reserved option publishes

#### Scenario: Bare-metal preset without minimum spend

- **WHEN** a bounded bare-metal recurring candidate has compatible servicing and no minimum-spend term
- **THEN** minimum-spend absence alone does not block publication

#### Scenario: A setup-bearing preset where setup is not declared

- **WHEN** a recurring clause states a setup amount and the composition's declaration for its mechanism has `setup = false`
- **THEN** that option is omitted with a diagnostic and the listing's other options publish

### Requirement: The composition supplies each compute option's delivery deadline

A compute option whose mechanism has a lifecycle adapter MUST publish
`lifecycle.delivery_deadline_seconds` from its composition: the pool port's value when the
port gives one, else the payments clause's configured `delivery_deadline_seconds`. A compute
option with neither MUST publish without the term and with the diagnostic "a default buyer
refuses this option: no delivery deadline". On such an option the adjudication's
`dispute_window_seconds` MUST be at least the delivery deadline plus the authority's advertised
minimum window, and derivation MUST refuse an option whose window is shorter.

#### Scenario: A clause states a deadline and the pool port gives none

- **WHEN** a payments clause configures `delivery_deadline_seconds` 1200 and the composition's pool port returns none
- **THEN** the published compute option carries `lifecycle.delivery_deadline_seconds` 1200

#### Scenario: The pool port gives a deadline

- **WHEN** the pool port returns 900 and the clause configures 1200
- **THEN** the published option carries 900, so the site and the published term agree

#### Scenario: The dispute window ends before the deadline can be filed on

- **WHEN** a compute option's deadline is 1200 seconds, the authority's minimum window 3600 and its `dispute_window_seconds` 4000
- **THEN** derivation refuses the option with "the dispute window ends before the delivery deadline can be filed on"

### Requirement: Compute settlement clauses resolve from one shared source

Both compute domains MUST resolve settlement clauses and listing terms field by field through
one shared resolver: storefront override, then the pool hint per GPU model
(`pricing.gpu.<model>`), then the pool hint for the pool (`pricing.settlements`), then the
configuration per model (`[pricing.defaults.gpu.<model>]`), then the flat configuration
(`[pricing]`). Each field resolves whole from the highest tier that states it: a settlement
clause list still replaces lower tiers' lists whole and is never merged across tiers. Capacity
bounds keep their own order, with `capacity_bounds.<mode>` ahead of the model hint. A
configuration or hint an earlier release accepted MUST keep its meaning.

#### Scenario: A pool-level hint below a model hint

- **WHEN** a pool's hint states `pricing.settlements` and, for one GPU model, `pricing.gpu.<model>` settlement clauses
- **THEN** that model's listings use the model hint's clauses and the pool's other listings use the pool-level clauses

#### Scenario: A bare-metal pool states pool-level clauses

- **WHEN** a bare-metal pool's hint states `pricing.settlements`
- **THEN** its listings publish those clauses, as a VM pool's would

## MODIFIED Requirements

### Requirement: A storefront that cannot publish refuses to start

A storefront that derives listings from site projections MUST refuse to start, naming each
problem, when publishing is impossible for the whole storefront: it has no registry to publish
to, or a registry without its authority pin; it has no enabled settlement mechanism; or it has
no configured site, a site not bound to exactly one service peer, or a site whose authority URL
is not an HTTP(S) origin: a URL the WHATWG URL standard parses, with an `http` or `https`
scheme and no credentials, path, query, or fragment. A refusal names the site and never echoes
its URL. A storefront that only
services deals already accepted is not a supported deployment. Settlement clauses and a lease
bound MAY come from a pool's override or hint instead of the storefront's defaults, so missing
defaults MUST NOT refuse startup; a pool that resolves no lease bound from any tier MUST publish
with no relative limit, and a candidate whose pool resolves no settlement
clause from any tier MUST be refused as "A compute candidate with no settlement option yields no
listing" requires.
A bare-metal storefront MUST also refuse to start when a registry pin or a `[registry.auth]`
token names no configured registry, or when two `[registry.auth]` entries name one registry
after URL normalization; the refusal names that registry's URL and the table, and never
echoes a token.

#### Scenario: A bare-metal storefront has no registry

- **WHEN** a bare-metal storefront starts with no `[registry].urls`
- **THEN** it refuses to start, naming the missing registry, and starts no loop

#### Scenario: A bare-metal registry pin or token names no configured registry

- **WHEN** a bare-metal storefront starts with a `[registry.authorities]` pin or a
  `[registry.auth]` token naming a URL that is not one of its `[registry].urls`, or with two
  `[registry.auth]` entries that name one registry once normalized
- **THEN** it refuses to start, naming the table and the registry's URL, and the refusal
  carries no token

#### Scenario: A site's authority URL is not an origin

- **WHEN** a VM or bare-metal storefront starts with a `[capacity.sites]` URL that states a
  path, credentials, a query, a fragment, or a port that is not a number
- **THEN** it refuses to start, naming the site, without echoing the URL

#### Scenario: No settlement mechanism is enabled

- **WHEN** a VM storefront starts with no enabled settlement mechanism
- **THEN** it refuses to start, naming the missing mechanism

#### Scenario: A storefront's terms live in its pools

- **WHEN** a VM storefront starts with an empty `[pricing].settlements` while its pools'
  overrides or hints state settlement clauses
- **THEN** it starts and publishes those pools' listings

#### Scenario: A bare-metal pool resolves no lease bound

- **WHEN** a bare-metal storefront has no `[pricing].default_max_duration_seconds` and one
  pool's override states no maximum duration
- **THEN** that pool's listings publish with no relative maximum, and every other pool publishes

#### Scenario: A pool resolves no settlement clause

- **WHEN** a storefront has no `[pricing].settlements` and one pool's override and hint state
  no settlement clause
- **THEN** it starts, that pool's candidates are refused as having no settlement option, and
  an open listing among them closes as `no_settlement_option`
