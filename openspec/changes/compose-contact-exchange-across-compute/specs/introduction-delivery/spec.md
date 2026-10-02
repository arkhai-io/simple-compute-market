## ADDED Requirements

### Requirement: Delivery is available wherever the mechanism composes

Introduction delivery MUST be available in every domain that composes the
contact-exchange mechanism, not in one domain alone. Seller-side dispatch — running
delivery off the reveal's critical path, keeping each dispatch alive until it
finishes, reporting outcomes, and re-delivering an already-revealed introduction —
MUST have one implementation in the delivery capability. A composing domain MUST
supply only its configuration carrier and its operator command or route binding, and
MUST NOT carry a delivery implementation of its own.

Delivery MUST remain non-authoritative in every domain that gains it. That property
is what makes best-effort delivery safe: the durable, idempotently re-readable
reveal is what both parties can always fall back to. Re-delivery MUST read that
durable reveal rather than reconstructing one, so a re-send cannot invent contact
data that was never exchanged.

The delivery capability MUST NOT depend on a settlement mechanism, and a mechanism
MUST NOT depend on the delivery capability: dispatch reads the reveal and the
agreement by shape, and the mechanism receives dispatch as an injected callable.

#### Scenario: A newly composing domain delivers

- **WHEN** a compute-family storefront composes the mechanism and configures a sink
- **THEN** revealed introductions in that domain reach the configured sink through
  the delivery capability's seller-side dispatch
- **AND** the domain carries no delivery implementation of its own

#### Scenario: Re-delivery in a newly composing domain

- **WHEN** an operator re-delivers an already-revealed introduction in a newly
  composing domain
- **THEN** the sinks receive the material read from the durable reveal
- **AND** no contact data absent from that reveal is delivered

## MODIFIED Requirements

### Requirement: Delivery is local, self-addressed, and recipient-side

Each side of an introduction deal MUST deliver only to destinations configured by
that side's own operator, and MUST carry only the revealed material that side
already holds. The buyer's delivery MUST carry the seller's revealed contact
entries; the seller's delivery MUST carry the buyer's. Neither side MUST use a
counterparty-supplied contact entry as a delivery destination, and neither side
MUST deliver anything to the counterparty.

Where one storefront publishes listings originating at several seller sites,
seller-side destinations MUST be selectable by the origin of the listing the deal
was negotiated against. The seller's delivery carries the buyer's contact entries,
so dispatching to another origin's destinations would disclose the buyer's personal
details to a seller who was not party to the deal.

The seller-side configuration MAY carry a routing table naming, for each origin, the
configured sink instances that receive its reveals. Origins MUST be treated as
opaque identifiers supplied by the composing domain. A storefront with one origin
and no routing table MUST deliver every reveal to every enabled instance. A storefront
with more than one origin and any enabled seller-side instance MUST configure a
routing table, and MUST refuse to construct its sink set without one, whether or not
any mechanism producing delivery events is enabled: broadcasting every reveal to every
destination is the cross-seller disclosure this requirement exists to prevent. With a
routing table, an origin the table does not name MUST receive no seller-side delivery
rather than fall back to another origin's destinations, and re-delivery MUST route by
the introduction's origin through the same table.

A seller-side routing table MUST be refused when constructed if it names an instance
that is not enabled, if an enabled instance is routed for no origin, or if it names
an origin the storefront is not configured with. A buyer-side routing table MUST be
refused, because the buyer has no origin.

#### Scenario: Each side receives the counterparty's contact

- **WHEN** an introduction is revealed and both parties have configured sinks
- **THEN** the buyer's sinks receive the seller's contact entries and the seller's
  sinks receive the buyer's, each from its own process

#### Scenario: A counterparty address is not a destination

- **WHEN** a revealed contact payload contains an address that a configured sink
  could technically reach
- **THEN** delivery targets only the operator's configured destinations and never
  the counterparty's address

#### Scenario: Two origins publish through one storefront

- **WHEN** an introduction is revealed for a listing originating at one of several
  seller sites behind one storefront that routes deliveries by origin
- **THEN** the seller-side delivery reaches only the instances routed for that origin
- **AND** no instance routed only for another origin receives the buyer's contact
  entries

#### Scenario: An origin is not routed

- **WHEN** an introduction is revealed for a listing whose origin the routing table
  does not name
- **THEN** nothing is delivered seller-side and the reveal, its obligation, and the
  counterparty's request are unaffected

#### Scenario: A single-origin storefront configures no routing table

- **WHEN** a storefront with one origin configures sinks and no routing table
- **THEN** every enabled sink receives every reveal

#### Scenario: A multi-origin storefront configures no routing table

- **WHEN** a storefront with two origins enables seller-side sinks and configures no
  routing table
- **THEN** sink-set construction fails at startup, naming the configured origins
- **AND** no reveal is ever delivered to a destination chosen without its origin

#### Scenario: A destination is shared by every origin

- **WHEN** a multi-origin storefront routes one instance for every origin alongside
  each origin's own instance
- **THEN** that instance receives every reveal and each origin's own instance
  receives only its origin's

#### Scenario: A routing table is inconsistent

- **WHEN** a routing table names an instance that is not enabled, leaves an enabled
  instance unrouted, or names an origin the storefront is not configured with
- **THEN** construction fails with a message naming the offending entry, before any
  deal is negotiated

### Requirement: Sinks are installed and configured, never enumerated in code

A delivery sink MUST be discoverable as an installed plugin and selectable by name
in the local configuration, so that adding a destination requires no change to
core, kit, or domain packages. An enabled name that resolves to no installed sink,
or a sink whose configuration fails validation, MUST fail when the sink set is
constructed rather than when an introduction is revealed. A sink distribution that
fails to load MUST NOT prevent process startup or prevent other configured sinks
from delivering.

The configuration MUST enable named sink instances rather than plugins, so one
installed sink can serve several destinations. An instance MAY name the plugin it
instantiates; an instance that names none instantiates the plugin of its own name,
so a configuration written before instances existed keeps its meaning. Instance
names MUST NOT collide with the section's own reserved settings.

#### Scenario: A third-party sink is installed

- **WHEN** an operator installs a sink package and enables it by name
- **THEN** it receives revealed introductions with no change to any marketplace
  package

#### Scenario: A sink is misconfigured

- **WHEN** an enabled sink names an uninstalled plugin or carries invalid settings
- **THEN** construction fails with a message naming the sink, before any deal is
  negotiated

#### Scenario: One installed sink is broken

- **WHEN** one sink distribution raises while loading
- **THEN** the process starts, the broken sink is reported, and the remaining
  configured sinks still deliver

#### Scenario: One plugin serves two destinations

- **WHEN** an operator enables two instances naming the same installed plugin with
  different settings
- **THEN** each instance delivers to its own destination

#### Scenario: A configuration predates instances

- **WHEN** a configuration enables a sink by plugin name and its table names no plugin
- **THEN** it delivers exactly as it did before instances existed
