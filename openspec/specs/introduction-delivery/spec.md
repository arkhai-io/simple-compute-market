# introduction-delivery Specification

## Purpose
Define how a revealed introduction reaches the party that owns it: each side of an
introduction deal delivers the counterparty contact it already holds to
destinations its own operator configured, without the marketplace learning any
delivery protocol or the deal depending on delivery succeeding.

## Scope

The local installed-plugin requirements below describe legacy recipient-owned
sink delivery. Agreements explicitly selecting the two-sided email delivery
policy instead use storefront-owned durable recipient intents and the
explicit-policy requirements below; they do not acquire legacy redelivery or
counterparty-destination behavior. Contact sharing and settlement completion are
owned by [contact exchange](../contact-exchange-settlement/spec.md). Both paths
reuse the mechanism-neutral event renderer.

## Requirements

### Requirement: Delivery is local, self-addressed, and recipient-side

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

#### Scenario: The reveal request is retried

- **WHEN** a buyer retries an introduction start and the retry is served as an exact
  replay
- **THEN** no additional delivery occurs on either side

#### Scenario: Operator re-delivers after a failed send

- **WHEN** an operator explicitly requests re-delivery of a revealed introduction
- **THEN** the configured sinks receive the same introduction again

### Requirement: Sinks are installed and configured, never enumerated in code

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

### Requirement: Explicit-policy delivery renders frozen recipient content

For the explicit two-sided email delivery policy, the storefront SHALL render
only each recipient's frozen counterparty contact and accepted introduction
package. Nested JSON context SHALL be readable plain-text fields, with scalar
strings preserved verbatim and no HTML, template, shell or header interpretation.
The buyer copy SHALL contain seller text; the seller copy SHALL contain buyer
text. Configured routes SHALL NOT enter shared content unless independently
authored in the shared blurb. No mutable listing or configuration lookup SHALL
supply finalized content.

#### Scenario: Whole text and accepted machine context reach both recipients

- **WHEN** an eligible introduction is reviewed, finalized and released for delivery
- **THEN** both copies include frozen listing identity, machine details and accepted
  terms, and each contains only its counterparty's whole blurb
- **AND** whitespace, combining Unicode and inert markup in that blurb remain intact

#### Scenario: Route-only addresses remain private

- **WHEN** a party configures a route separately from the shared blurb
- **THEN** the other party's message body contains no such route address
- **AND** each SMTP message addresses only its own recipient

#### Scenario: Restart does not rewrite or redeliver a terminal exchange

- **WHEN** delivery resumes after listing/configuration changes and restart
- **THEN** content and recipient routes come from the immutable capture
- **AND** terminal recipient intents are not resent and contain no route

### Requirement: Explicit-policy SMTP outcomes are conservative and bounded

Recipient attempts and terminal outcomes SHALL remain independent.
Explicit-policy delivery SHALL require verified STARTTLS before authentication
or DATA. A positive DATA acknowledgement SHALL remain accepted despite QUIT
failure. Unknown DATA acceptance SHALL enter needs-review, never automatic
resend. Temporary refusal retries SHALL be finite; attempt ownership and time
bounds SHALL fence stale senders. No redelivery API is supplied for this policy.

#### Scenario: One recipient temporarily refuses the message

- **WHEN** one finalized recipient receives positive DATA acknowledgement and the
  other temporarily refuses delivery
- **THEN** the accepted recipient is not resent while the other follows its own
  bounded retry state
- **AND** both eventual copies retain the same frozen context and only their
  respective counterparty contact; terminal routes are removed

#### Scenario: DATA acknowledgement is lost

- **WHEN** a connection fails after DATA without a known positive acknowledgement
- **THEN** the intent requires review, retains no route and is not retried blindly

#### Scenario: TLS verification or cleanup fails

- **WHEN** STARTTLS is missing or its certificate cannot be verified
- **THEN** authentication and message transmission are refused
- **AND** a later QUIT failure cannot reverse an already positive DATA acknowledgement

## Evidence

- `kit/delivery/tests/unit/test_events.py` proves readable deterministic nested
  context and verbatim inert text.
- `kit/delivery/tests/unit/test_smtp_attempt.py` proves verified TLS refusal,
  unknown DATA acknowledgement, positive DATA acknowledgement despite failed or
  blocked QUIT, and bounded process ownership.
- `kit/contact-exchange/tests/unit/test_delivery_state.py` proves durable retry,
  recovery fences and terminal route cleanup.
- `domains/bare_metal/storefront/tests/test_http_contact_source_exchange.py`
  drives signed HTTP, disposable SQLite, restart and both fake-SMTP recipient copies.

- `domains/bare_metal/storefront/tests/test_declared_contact_qualification.py`
  joins real signed publication/discovery to both frozen SMTP copies, including
  one temporary recipient refusal, independent retry and terminal restart.
