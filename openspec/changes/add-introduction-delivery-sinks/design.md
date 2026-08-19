## Context

See proposal.md — Why. The constraints that shape the approach are all existing
ones:

- `core_buyer` deliberately depends on no mechanism kit. The neutrality work
  recorded this explicitly when the Alkahest carriers moved: a core role package
  cannot import a mechanism kit, which is why core keeps tombstoned aliases rather
  than re-exporting the kit's models. Delivery must not be the exception that
  reverses that arrow.
- Both delivery points already exist and already hold the material. The seller's
  `IntroductionRouteService.start` persists both contact payloads, completes the
  obligation, and returns a viewer-scoped projection; the buyer's `introduce`
  receives that projection and writes a payload-free run-log event. Neither needs
  new state to deliver.
- The reveal is durable and idempotently re-readable by design — the route module
  states the inversion outright. That property is what makes best-effort delivery
  safe, and it is the reason this change can refuse to build a retry queue.
- The reveal projection is viewer-dependent: the same record yields the seller's
  contact to the buyer and the buyer's to the seller. Delivery must name its
  viewer rather than reuse the projection already built for the response.

## Goals / Non-Goals

**Goals:**

- One sink contract that both a long-running service and a short-lived CLI
  implement identically, so an operator learns one configuration shape.
- A destination set that grows by installing a package, not by editing the
  marketplace.
- Delivery that cannot make a deal fail, cannot slow a counterparty's request, and
  cannot leak the payload into logs.

**Non-Goals:**

- At-least-once delivery. This design is explicitly best-effort with explicit
  manual re-delivery; nothing durably queues an undelivered event.
- A delivery surface for mechanisms other than introductions. The seam is
  mechanism-neutral so a second producer costs one constructor, but no second
  producer is built here.
- Any operator-visible aggregation of delivery history beyond local reporting.

## Decisions

### A new kit package owns the contract

`kit/delivery` (`market_delivery`) holds the event, the `DeliverySink` protocol,
the configuration models, plugin discovery, and the built-in sinks. Both sides
depend on it: `core/buyer` directly, and `kit/contact-exchange` for the seller-side
dispatch injected into the route service.

Alternatives rejected: putting it in `kit/contact-exchange` would force
`core_buyer` to depend on a mechanism kit, reversing the dependency arrow the
neutrality change just established; putting it in `core` would place protocol
knowledge (SMTP, HTTP, subprocess) inside a schema-opaque orchestration package;
implementing it twice, once per side, would let the two configuration shapes drift
apart, which is precisely the operator-facing cost this change is trying to avoid.

### The event is mechanism-neutral; the introduction is its first producer

`market_delivery` defines a `DeliveryEvent` carrying an event kind
(`introduction.revealed`), the neutral obligation reference, the agreement
reference, the recipient's role, the counterparty principal, the opaque contact
entries, the agreed introduction context, and a rendered text form. It constructs
that event from the reveal projection's documented shape — plain mappings — so it
never imports the mechanism kit that produces the projection.

This is what lets `core_buyer` deliver without a mechanism dependency, and it means
a future producer (a settled hosted charge, a completed escrow) adds a constructor
rather than a second delivery system.

### The seller fires inside the route service, after the reveal is real

Dispatch is an optional callable injected alongside the existing
`IntroductionRouteCallbacks`, invoked by `start` after `persist` and `complete`
succeed, with a projection built for the seller as viewer. Only the route service
knows both that this is the *first* reveal and holds both payloads, so only it can
satisfy "deliver once, with the right half of the record".

Rejected: firing from the domain's `complete` callback. `complete` receives the
agreement and not the payloads, and it means "this obligation is serviced" —
hanging delivery there would make a convenience concern part of the settlement
lifecycle, which the specs forbid.

The replay branch returns the recorded outcome before reaching dispatch, so exact
retries deliver nothing without any additional bookkeeping.

### Seller-side delivery is dispatched, not awaited

The response is already determined when dispatch begins, so sinks run as a
supervised background task with a per-sink timeout: the task reference is retained
until completion and its exceptions are logged rather than discarded. A
counterparty's request never waits on the seller's mail server.

Trade-off accepted: a storefront that stops immediately after a reveal can drop an
in-flight delivery. Given a durable, re-readable reveal and an explicit re-delivery
command, that is a better failure than a reveal request whose latency is hostage to
a webhook.

### A sink is a synchronous callable run in a daemon thread

Sinks block by nature — writing a file, running a program, opening a socket — so
asking sink authors to be async would buy nothing and cost every third-party
author an event loop. Instead a sink is a plain synchronous callable, and the
dispatcher owns concurrency: one daemon thread per sink, joined against a shared
deadline so the whole dispatch costs the slowest sink rather than their sum.

The threads are daemons deliberately. A timed-out sink is abandoned, not killed —
a thread cannot be interrupted — so a non-daemon worker would hold up interpreter
exit and a hung webhook would hang the buyer's CLI after it had already reported
the timeout. A pooled executor has the same defect, since its shutdown joins its
workers.

### Buyer-side delivery is synchronous, and prints before it sends

A CLI has no supervisor to outlive it, and the operator is present and waiting, so
sinks run inline with bounded timeouts. The revealed introduction is written to
standard output *before* dispatch, so a slow or failing sink can never delay or
obscure the answer the operator came for; sink outcomes follow on the diagnostic
stream, and the command exits successfully regardless. Re-delivery is a flag on the
existing read command rather than a new verb — the durable re-read and the re-send
are the same operator intent.

### Discovery mirrors buyer domain plugins, with the opposite failure posture

Sinks resolve from a `market.delivery_sinks` entry-point group, name to factory,
exactly as `core_buyer.plugins` resolves `market.buyer_domains`. Configuration is
`[Delivery] enabled = [...]` plus one `[Delivery.<name>]` table per sink, identical
on both sides, with each sink validating its own settings strictly at construction.

The deliberate divergence: a buyer domain that fails to load is a broken market and
raises; a sink that fails to load is a lost convenience and is reported, skipped,
and survived. Construction happens at process or command start, so an unknown name
or a bad setting fails long before a deal exists.

### Built-in sinks stay protocol-thin

`file` appends the event, `command` runs a local program, `webhook` POSTs JSON, and
`smtp` sends one message — covering a bot-watched file, an arbitrary local tool, a
chat or automation endpoint, and plain email with no third-party dependency. None
of them interprets a contact key or the advertised channel; anything richer belongs
in an installed plugin.

`command` is the general escape hatch and so carries the sharpest constraints: an
explicit argument list, no shell, the event on standard input, never interpolated
into arguments, and a timeout. It executes what the operator configured, which is
the operator's own trust boundary — the same one their shell profile occupies —
and the documentation says so plainly.

### Rendering belongs to the event

The human-readable form is computed once, on the event, and carried to every sink.
Third-party sinks stay trivial, output stays consistent across destinations, and a
sink that wants structure still has every field.

## Risks / Trade-offs

- **Delivered copies escape the retention posture.** The mechanism persists contact
  payloads only for started introductions and supports lifecycle deletion; a
  delivered copy sits in the operator's own mailbox or file and no deletion recalls
  it. → The boundary is documented where retention is documented: deletion governs
  marketplace persistence, not the recipient's own copy. Delivery is opt-in and
  self-addressed, so an operator only ever exports data to themselves.
- **Background dispatch can be lost on shutdown.** → Never described as
  at-least-once; explicit re-delivery is a first-class command on both sides.
- **A local-program sink executes configured commands from a long-running
  service.** → argv-only, shell-free, stdin-fed, timed out, opt-in, and documented
  as the operator's own trust boundary.
- **Two configuration surfaces could still drift.** → One package owns the models
  and the discovery; both sides construct through the same entry point, and the
  section shape is identical by construction rather than by convention.
- **Sink secrets are a new class of local secret in two config files.** → Sink
  settings are validated by strict models with secret-marked fields, excluded from
  every published, wire, log, and command-output surface, and never included in
  failure reports.

## Migration Plan

Purely additive. A side with no `[Delivery]` section behaves exactly as it does
today, which is also the rollback: remove the section, or uninstall the sink
package. No persistence, wire, or option-identity change, so no coordinated
deployment between buyer and seller is required — either side can adopt delivery
alone.

Packaging follows the existing local flow: `kit/delivery` publishes as
`arkhai-kit-delivery` at `0.1.0`, is added to `core/buyer`,
`kit/contact-exchange`, and the bare-metal storefront and buyer, and its wheel is
built into the shared `.dist` directory before the consuming environments are
re-synced.

## Open Questions

- Whether other mechanisms should produce delivery events — a settled hosted charge
  or a completed escrow are natural second producers. Deferrable: the event seam is
  mechanism-neutral, so answering it later adds a constructor and changes nothing
  here.
- Whether the storefront should expose recent delivery outcomes on an operator
  status surface rather than only in logs. Deferrable: local reporting satisfies
  the specs, and a status surface is additive.
