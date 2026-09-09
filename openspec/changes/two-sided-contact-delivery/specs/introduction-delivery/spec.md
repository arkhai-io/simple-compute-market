## MODIFIED Requirements

### Requirement: Delivery is local, self-addressed, and recipient-side

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

Each side of an introduction deal MUST deliver only to destinations configured by
that side's own operator, and MUST carry only the revealed material that side
already holds. The buyer's delivery MUST carry the seller's revealed contact
entries; the seller's delivery MUST carry the buyer's. Neither side MUST use a
counterparty-supplied contact entry as a delivery destination, and neither side
MUST deliver anything to the counterparty.

#### Scenario: Each side receives the counterparty's contact

- **WHEN** an introduction is revealed and both parties have configured sinks
- **THEN** the buyer's sinks receive the seller's contact entries and the seller's
  sinks receive the buyer's, each from its own process

#### Scenario: A counterparty address is not a destination

- **WHEN** a revealed contact payload contains an address that a configured sink
  could technically reach
- **THEN** delivery targets only the operator's configured destinations and never
  the counterparty's address

### Requirement: Delivery never gates the deal

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

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

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

Seller-side delivery MUST NOT extend the counterparty's reveal request. Every sink
invocation MUST be bounded by a configured or default timeout, after which the
invocation is abandoned and reported.

#### Scenario: A sink hangs during a seller-side reveal

- **WHEN** a configured sink blocks indefinitely while the storefront is serving an
  introduction start
- **THEN** the buyer's request completes within its normal bound and the blocked
  sink is abandoned at its timeout and reported locally

### Requirement: Delivery fires once per reveal and re-delivery is explicit

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

Delivery MUST occur on the operation that first reveals an introduction. An
idempotent replay of that operation, or a subsequent read of the durable reveal,
MUST NOT deliver again. Each side MUST offer an explicit operator action that
re-delivers an already-revealed introduction.

#### Scenario: The reveal request is retried

- **WHEN** a buyer retries an introduction start and the retry is served as an exact
  replay
- **THEN** no additional delivery occurs on either side

#### Scenario: Operator re-delivers after a failed send

- **WHEN** an operator explicitly requests re-delivery of a revealed introduction
- **THEN** the configured sinks receive the same introduction again

### Requirement: Sinks are installed and configured, never enumerated in code

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

A delivery sink MUST be discoverable as an installed plugin and selectable by name
in the local configuration, so that adding a destination requires no change to
core, kit, or domain packages. An enabled name that resolves to no installed sink,
or a sink whose configuration fails validation, MUST fail when the sink set is
constructed rather than when an introduction is revealed. A sink distribution that
fails to load MUST NOT prevent process startup or prevent other configured sinks
from delivering.

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

### Requirement: Sink configuration is local and carries secrets safely

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

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

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

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

This requirement applies to legacy local-plugin composition only. Explicit
`contact-delivery.v1` two-sided accepted policy uses the durable policy-gated
requirements below; absence of policy never enrolls historical work.

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

## ADDED Requirements

### Requirement: Explicit policy owns two recipient effects

For exact accepted `contact-delivery.v1` policy, the storefront SHALL own two
recipient intents, each using its recipient's separately configured own route
and only the counterparty contact plus immutable accepted context. The contact
kit SHALL own the mechanism carriers and durable worker; core remains opaque.
No contact entry SHALL imply routing authority. A signed buyer assertion SHALL
NOT be described as mailbox-ownership verification. Operator seller settings
remain independent of buyer account settings.

#### Scenario: Two recipient projections

- **WHEN** the buyer explicitly finalizes a valid new-policy introduction
- **THEN** one atomic capture freezes both contacts and exactly two unique intents
- **AND** each message contains the other contact, never the other route

### Requirement: Durable dispatch waits for settlement completion

New-policy intents SHALL remain awaiting_completion until materialize/check/
collect converges, then progress independently through pending/sending and bounded
retry_wait to accepted, failed or needs_review. Unique attempt claims SHALL be
durable before I/O. Provider failure SHALL NOT undo sharing. Acceptance, review,
GET, replay and historical records SHALL NOT generate delivery jobs. Recovery
SHALL examine only explicitly created new-policy intents.

#### Scenario: Capture commits before completion fails

- **WHEN** completion fails after atomic capture and the process restarts
- **THEN** the exchange remains readable and recovery converges completion before
  dispatch, without duplicate capture or recipient intents

### Requirement: SMTP outcomes preserve uncertainty and confidentiality

The new sender SHALL enforce the contract's ASCII single-mailbox grammar,
verified STARTTLS before auth/DATA, ten-second network operations, a hard
120-second attempt bound and a 150-second claim lifetime. It SHALL send one
recipient per SMTP transaction. At most three total attempts with 60/300-second
backoff SHALL occur only on demonstrably nonaccepted transient failures.
Abandoned sending or ambiguous acceptance SHALL stop at needs_review, not resend.
A positive DATA acknowledgement SHALL remain accepted despite QUIT failure;
accepted SHALL NOT claim inbox delivery. No manual resend exists in this mode.

#### Scenario: Acknowledgement is lost

- **WHEN** DATA may have been accepted but no definitive acknowledgement is known
- **THEN** the intent stops at needs_review and no worker resends it

#### Scenario: Positive acknowledgement precedes cleanup error

- **WHEN** final DATA succeeds and QUIT fails
- **THEN** the sender records accepted rather than retrying or reporting failed

#### Scenario: TLS or attempt ownership fails

- **WHEN** STARTTLS is absent, certificate/hostname validation fails, or a paused
  worker has exceeded its attempt deadline before initiating DATA
- **THEN** no plaintext/auth bypass or new DATA is performed
- **AND** expired claim recovery never assigns a second sender

### Requirement: New delivery copies have bounded-purpose retention

Route snapshots SHALL exist only for awaiting_completion/pending/sending/
retry_wait work and SHALL be cleared atomically on accepted/failed/needs_review.
Attempts SHALL retain opaque identities, bounded codes and timing, not route,
contact or rendered-body copies. Outcome reads SHALL reveal only the caller's
own recipient status, never a route address or raw provider error. Existing
exchange/replay retention and recipient-owned mail remain outside this cleanup.

#### Scenario: A stopped recipient intent is inspected

- **WHEN** a delivery enters needs_review or another terminal outcome
- **THEN** its route is cleared and diagnostics retain only bounded metadata
- **AND** neither settings changes nor legacy redelivery can resurrect its route
