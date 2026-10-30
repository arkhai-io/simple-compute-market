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
defaults MUST NOT refuse startup; a pool that resolves no lease bound its domain requires from
any tier MUST be held and reported per site, and a candidate whose pool resolves no settlement
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
- **THEN** that pool's listings are held and reported, and every other pool publishes

#### Scenario: A pool resolves no settlement clause

- **WHEN** a storefront has no `[pricing].settlements` and one pool's override and hint state
  no settlement clause
- **THEN** it starts, that pool's candidates are refused as having no settlement option, and
  an open listing among them closes as `no_settlement_option`
