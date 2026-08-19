## 1. The delivery kit

- [x] 1.1 Create `kit/delivery` (`market_delivery`) as `arkhai-kit-delivery` 0.1.0
      alongside the other kits: `pyproject.toml`, `py.typed`, `Makefile`, and the
      root `dist` wiring so its wheel builds into the shared `.dist` directory.
      No dependency beyond the standard library, `pydantic`, the shared identity
      kit, and the HTTP client already in use.
- [x] 1.2 `DeliveryEvent`: event kind, neutral obligation reference, agreement
      reference, recipient role, counterparty principal, verbatim opaque contact
      entries, agreed introduction context (option identity, profile, channel,
      terms, listing), and one rendered human-readable form computed on the event.
      Construct it from the reveal projection's documented mapping shape so the
      kit imports no mechanism package.
- [x] 1.3 `DeliverySink` protocol plus the configuration models: a `[Delivery]`
      section with `enabled` names and one `[Delivery.<name>]` table per sink,
      strictly validated, with credential fields secret-marked and excluded from
      representation.
- [x] 1.4 Sink discovery over the `market.delivery_sinks` entry-point group,
      mirroring `core_buyer.plugins`' domain discovery. An enabled name with no
      installed sink, or settings that fail validation, raises at construction; a
      distribution that fails to load is reported and skipped without preventing
      startup or the remaining sinks.
- [x] 1.5 Bounded dispatch shared by both sides: per-sink timeout, never raises to
      its caller, and captures each outcome as sink name, obligation reference, and
      failure class — never the contact payload and never a sink secret.
- [x] 1.6 Evidence: kit unit tests for event construction and rendering over
      unfamiliar contact keys; strict config validation and secret exclusion;
      discovery failure postures (unknown name, invalid settings, broken
      distribution); dispatch isolation, timeout, and payload-free reporting; and a
      third-party sink registered through the entry-point group receiving events
      with no marketplace change.
- [x] 1.7 Closeout: hygiene clean; the synchronous-sink-in-a-daemon-thread
      decision recorded in design.md. Suite: kit/delivery 42.

## 2. Built-in sinks

- [x] 2.1 `file`: append the event to a configured path, bounded and non-fatal.
- [x] 2.2 `command`: run a configured argument list with no shell, the event on
      standard input, no interpolation of event content into arguments, and a
      timeout.
- [x] 2.3 `webhook`: POST the event as JSON to one configured URL with a timeout;
      a failure status is a reported failure, not an exception to the caller.
- [x] 2.4 `smtp`: send one message to configured recipients over the standard
      library client, with the rendered form as the body.
- [x] 2.5 Evidence: per-sink unit tests, including contact content carrying shell
      metacharacters reaching the local program unevaluated on standard input, a
      rejecting HTTP destination, and each sink's timeout bound.
- [x] 2.6 Closeout: hygiene clean; the four sinks register through the same
      entry-point group a third-party sink uses, proven by the discovery suite.

## 3. Seller-side delivery

- [x] 3.1 `IntroductionRouteService` accepts an optional delivery dispatch and
      invokes it after `persist` and `complete` succeed, with a projection built
      for the seller as viewer. The replay branch returns before dispatch, so an
      exact retry delivers nothing.
- [x] 3.2 Bare-metal storefront composition: construct the configured sink set from
      `storefront.toml` at startup (failing fast on misconfiguration), inject the
      dispatch into the introduction route service, and run it as a supervised
      background task whose reference is retained and whose exceptions are logged.
- [x] 3.3 An explicit seller-side re-delivery action for an already-revealed
      introduction.
- [x] 3.4 Evidence: contact-exchange kit and bare-metal storefront tests — every
      sink failing leaves the reveal response unchanged and the obligation
      completed; a hanging sink does not extend the counterparty's request; an
      exact retry delivers nothing; a credentialed sink's settings appear in no
      readiness projection, published listing, or wire response; and re-delivery
      sends the same introduction again.
- [x] 3.5 Closeout: hygiene clean; one refinement recorded in design.md --
      "first reveal" is observed before persisting, because persist is
      idempotent and a repeat start with a fresh request id is not a replay.
      Suites: kit/contact-exchange 37, bare-metal storefront 122.

## 4. Buyer-side delivery

- [ ] 4.1 `core/buyer` depends on `arkhai-kit-delivery` (and on no mechanism kit),
      and constructs the buyer's configured sink set from the buyer configuration
      at command start.
- [ ] 4.2 `introduce` writes the revealed introduction to standard output first,
      then dispatches to sinks with bounded timeouts, reports each outcome on the
      diagnostic stream, exits successfully regardless, and records a run-log event
      carrying obligation reference and sink outcomes only.
- [ ] 4.3 Explicit re-delivery from the durable read command for an
      already-revealed introduction.
- [ ] 4.4 Evidence: `core/buyer` and bare-metal buyer tests — output precedes
      dispatch, a failing sink still exits successfully with the introduction
      printed, the run log holds no contact payload, and re-delivery re-sends.
- [ ] 4.5 Closeout.

## 5. Composition, documentation, and closeout

- [ ] 5.1 Verify the dependency boundary holds: the core buyer role package
      resolves sinks through the plugin contract while importing no mechanism
      package, and no composition root is required to reach a sink.
- [ ] 5.2 Permanent docs: record in `docs/development/ARCHITECTURE.md` that
      delivery of a revealed introduction is recipient-side, self-addressed, and
      non-authoritative, and that a delivered copy falls outside the introduction
      retention boundary — deletion governs marketplace persistence, not the
      recipient's own copy.
- [ ] 5.3 Closeout: comment hygiene clean, no change-ID references in production
      code, ROADMAP Goal 6 updated to record the delivery capability and close its
      gap row, promotion record complete.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Delivery is local, self-addressed, recipient-side, and never gates the deal | `openspec/specs/introduction-delivery/spec.md` (promote at synchronization) |
| Sinks are installed plugins discovered by entry point; core and kit import no concrete sink, and delivery never makes a mechanism kit a core dependency | `openspec/specs/market-composition/spec.md` (promote at synchronization) |
| The delivery event is mechanism-neutral and constructed from the reveal projection's shape, so a second producer costs one constructor rather than a second delivery system | `openspec/specs/introduction-delivery/spec.md` (promote at synchronization) |
| Seller delivery is dispatched off the request's critical path; buyer delivery is synchronous and prints before it sends | `openspec/specs/introduction-delivery/spec.md` (promote at synchronization) |
| A delivered copy falls outside the introduction retention boundary | `docs/development/ARCHITECTURE.md` |
