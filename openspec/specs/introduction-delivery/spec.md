# introduction-delivery Specification

## Purpose
Define how a revealed introduction reaches the party that owns it: each side of an
introduction deal delivers the counterparty contact it already holds to
destinations its own operator configured, without the marketplace learning any
delivery protocol or the deal depending on delivery succeeding.

## Requirements

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

### Requirement: Delivery never gates the deal

A sink failure, timeout, or absence MUST NOT fail an introduction start, alter the
settlement obligation's servicing state, change the reveal response, or cause the
buyer command to exit non-zero. Failures MUST be reported to the local operator
identifying the sink, the obligation reference, and the failure class, and MUST NOT
include the contact payload or any sink secret.

#### Scenario: Every configured sink fails

- **WHEN** an introduction is revealed and all configured sinks raise
- **THEN** the reveal response is unchanged, the obligation still reaches its
  completed servicing state, and each failure is reported locally without the
  contact payload

#### Scenario: Buyer sink fails at the command line

- **WHEN** the buyer's configured sink fails while delivering a successful reveal
- **THEN** the command reports the failure on its diagnostic stream, still prints
  the revealed introduction, and exits successfully

### Requirement: Delivery stays off the reveal's critical path

Seller-side delivery MUST NOT extend the counterparty's reveal request. Every sink
invocation MUST be bounded by a configured or default timeout, after which the
invocation is abandoned and reported.

#### Scenario: A sink hangs during a seller-side reveal

- **WHEN** a configured sink blocks indefinitely while the storefront is serving an
  introduction start
- **THEN** the buyer's request completes within its normal bound and the blocked
  sink is abandoned at its timeout and reported locally

### Requirement: Delivery fires once per reveal and re-delivery is explicit

Delivery MUST occur on the operation that first reveals an introduction. An
idempotent replay of that operation, or a subsequent read of the durable reveal,
MUST NOT deliver again. Each side MUST offer an explicit operator action that
re-delivers an already-revealed introduction.

An introduction whose contact payloads have been deleted MUST NOT be delivered: an
introduction start that finds the payloads already deleted MUST NOT deliver, and an
operator's re-delivery request for such an introduction MUST be refused without
contacting any sink. Re-delivery reads the durable reveal rather than reconstructing
one, so once the payloads are gone there is nothing it may send. A first reveal that
persisted before the deletion committed preceded it, and its delivery belongs to it
even if the deletion commits before that delivery is dispatched.

#### Scenario: The reveal request is retried

- **WHEN** a buyer retries an introduction start and the retry is served as an exact
  replay
- **THEN** no additional delivery occurs on either side

#### Scenario: Operator re-delivers after a failed send

- **WHEN** an operator explicitly requests re-delivery of a revealed introduction
- **THEN** the configured sinks receive the same introduction again

#### Scenario: Deletion commits while the first reveal is completing

- **WHEN** a first reveal has persisted the introduction and a deletion of its payloads
  commits before the reveal's delivery is dispatched
- **THEN** the seller receives that one delivery
- **AND** no later start or re-delivery delivers again

#### Scenario: Operator re-delivers a deleted introduction

- **WHEN** an operator requests re-delivery of an introduction whose contact payloads
  have been deleted
- **THEN** the request is refused and no configured sink is contacted

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

A sink MAY declare the model of its settings beside its factory, and discovery MUST
make the declared models of installed sinks available. A deployment schema that types
delivery settings MUST take them from discovery and MUST NOT name a sink in code; an
installed sink that declares no model MUST be accepted with its settings left open.

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

#### Scenario: A deployment schema types the installed sinks

- **WHEN** a storefront generates its deployment schema with a sink installed that
  declares its settings model
- **THEN** that sink's instances are typed by the declared model, its secret settings
  are refused, and the storefront's code names no sink

#### Scenario: An installed sink declares no settings model

- **WHEN** an installed sink plugin provides only its factory
- **THEN** it can be enabled and configured, and a deployment schema leaves its
  settings open

#### Scenario: A configuration predates instances

- **WHEN** a configuration enables a sink by plugin name and its table names no plugin
- **THEN** it delivers exactly as it did before instances existed

### Requirement: Sink configuration is local and carries secrets safely

Delivery configuration MUST live in each side's own configuration, carried the way
that side already carries its settlement configuration, and MUST use the same
section shape on the seller and buyer sides. Sink settings, including
credentials, tokens, and destination addresses, MUST NOT appear in a published
listing, a settlement option, an accepted obligation, readiness details, any wire
response, a run log, or ordinary command output. A side with no delivery
configuration MUST behave exactly as it did before delivery existed.

#### Scenario: A seller configures a credentialed sink

- **WHEN** a storefront configures a sink carrying a token
- **THEN** the token appears in no published listing, option, readiness projection,
  or wire response, and readiness is unaffected by delivery configuration

#### Scenario: No delivery is configured

- **WHEN** a side has no delivery configuration
- **THEN** introductions reveal and complete exactly as before and nothing is
  delivered

### Requirement: The delivered event carries the introduction without interpreting it

A delivery event MUST identify the settlement obligation by its neutral reference,
the agreement it belongs to, the recipient's role, and the counterparty principal;
MUST carry the counterparty's contact entries verbatim as opaque keys and values;
MUST carry the agreed introduction context, including the option identity, the
advertised profile, channel, and terms; and MUST carry a human-readable rendering
of the same material. No sink MUST be required to interpret a contact key, and the
advertised channel MUST remain a descriptive label that selects no delivery
behavior.

#### Scenario: An unfamiliar contact key is revealed

- **WHEN** a revealed payload uses contact keys the marketplace has never seen
- **THEN** every configured sink receives them verbatim alongside a readable
  rendering, and no sink dispatch depends on the advertised channel

### Requirement: Built-in sinks are protocol-thin and bounded

The delivery capability MUST provide built-in sinks covering a local file, a local
program, an HTTP endpoint, and electronic mail, each requiring no third-party
dependency. The local-program sink MUST pass the event on the program's standard
input, MUST invoke an explicit argument list without a shell, and MUST NOT
interpolate event content into arguments. Every built-in sink MUST bound its own
execution and surface a failure through the same non-fatal reporting as any other
sink.

#### Scenario: Contact content contains shell metacharacters

- **WHEN** a revealed contact entry contains shell metacharacters and the local
  program sink is configured
- **THEN** the content reaches the program on standard input with no shell
  evaluation and no argument interpolation

#### Scenario: An HTTP destination rejects the event

- **WHEN** the configured endpoint returns a failure status
- **THEN** the failure is reported locally and the introduction, its obligation, and
  the counterparty's request are unaffected

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

### Requirement: A webhook delivery can be authenticated by its receiver

A seller-side webhook instance MAY be configured to sign each request with the
storefront's marketplace signer, so the receiving API can verify the sender against
the storefront principal it already trusts rather than relying on the secrecy of its
URL. Signing material MUST reach the sink from the storefront's composition, never
through sink settings, and a signing instance MUST be refused when constructed in a
process that has no marketplace signer.

#### Scenario: A seller's API verifies a delivery

- **WHEN** a signing webhook instance delivers a revealed introduction
- **THEN** the request carries a signature the receiver can verify against the
  storefront's public principal
- **AND** the request body is the same delivery event an unsigned instance sends

#### Scenario: A buyer configures signing

- **WHEN** a buyer-side webhook instance is configured to sign
- **THEN** construction fails naming the instance, because the buyer process holds no
  storefront signer

### Requirement: An instance's name does not misname its sink

A sink instance whose name is an installed sink's name MUST instantiate that sink. An
instance naming one sink and stating another MUST be refused when constructed.

#### Scenario: A table named for one sink states another

- **WHEN** an instance named `webhook` states `sink = "file"`
- **THEN** construction fails naming the instance
