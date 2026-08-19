## Why

An introduction deal's whole deliverable is a short opaque string — the
counterparty's contact details. Today that string is reachable only by reading
it back: the buyer sees it as CLI JSON on `introduce`, and the seller must go
look it up. Neither party is *told*. The mechanism made the reveal durable
precisely so nothing has to be delivered reliably, but "durable and idempotently
re-readable" is a safety property, not a convenience one, and a deal whose value
is being put in contact with someone should end with that contact where its
owner actually reads things.

Both sides already have a process running at the moment of reveal — the seller's
storefront serves the start request, the buyer's CLI issues it — and each side
already holds, legitimately, exactly the payload it would want delivered to
itself. So delivery is a local concern of each operator, configured by that
operator, about data they already have. It needs no wire change, no counterparty
cooperation, and no trust the mechanism does not already extend.

## What Changes

- A new kit package, `kit/delivery` (`market_delivery`), owns a mechanism-neutral
  delivery contract: a typed delivery event, a `DeliverySink` protocol, strict
  per-sink configuration, and construction of the configured sink set.
- Sinks are **installable**, not enumerated: a `market.delivery_sinks` entry-point
  group is discovered the same way buyer domain plugins already are, so a user
  can install a sink package and configure it without any change to core, kit, or
  a domain.
- Four protocol-thin built-in sinks ship with the kit — `file`, `command`,
  `webhook`, and `smtp` — chosen so the common destinations (a local file a bot
  watches, an arbitrary local program, a Slack/Discord/automation webhook, plain
  email) need no third-party dependency and no new protocol knowledge in the
  marketplace.
- The seller storefront delivers on a successful introduction start, from the
  introduction route service, off the request's critical path and never on an
  idempotent replay.
- The buyer CLI delivers on a successful `introduce`, and offers explicit
  re-delivery from `introduction` so a failed send is recoverable by hand.
- Each side configures its own sinks in its own config file with local-only
  secrets, validated eagerly at construction so a typo fails at startup rather
  than at the one moment delivery matters.
- Delivery is strictly non-authoritative: a sink failure MUST NOT fail the deal,
  the HTTP request, or the CLI command, and MUST NOT change obligation servicing
  or the settlement lifecycle in any way.

Explicit non-goals, stated so they are not read as deferred work:

- **No unattended delivery.** Nothing here starts an introduction on its own or
  watches for deals in the background; delivery happens in the process that is
  already handling the reveal. A daemon that introduces without a human is a
  separate capability that would consume this one.
- **No delivery to counterparties.** Each side delivers to itself. The
  marketplace never sends anything to an address a counterparty supplied.
- **No typed channels.** The contact payload stays opaque bounded strings and the
  option's `channel` stays a descriptive, filterable label. Sinks render what
  they are given; none of them interpret it.
- **No retry queue.** Bounded per-sink timeouts and manual re-delivery only. The
  reveal is durable, so an undelivered introduction is never a lost one.
- No change to any listing, option identity, obligation, negotiation, or reveal
  wire shape; no persistence change on either side.

## Capabilities

### New Capabilities
- `introduction-delivery`: local, recipient-side delivery of a revealed
  introduction — the sink contract and its failure isolation, sink discovery and
  configuration on each side, the built-in sink behaviors and their bounds, and
  the delivery points on the seller and buyer paths.

### Modified Capabilities
- `market-composition`: the dependency and plugin boundary for delivery sinks —
  core and kit assemble sinks without importing any concrete sink implementation,
  a mechanism kit does not become a core dependency to enable delivery, and a
  broken or failing sink cannot degrade market orchestration.

## Impact

- **New**: `kit/delivery` (`market_delivery`) — event, protocol, config models,
  entry-point discovery, four built-in sinks.
- **Modified**: `kit/contact-exchange` — `IntroductionRouteService` gains an
  optional injected delivery dispatch invoked after a successful, non-replayed
  start, with the seller's own viewer projection.
- **Modified**: `domains/bare_metal/storefront` — composes the configured sink set
  from `storefront.toml` and injects it into the introduction route service.
- **Modified**: `core/buyer` — `introduce` dispatches to the buyer's configured
  sinks; `introduction` gains explicit re-delivery. `core_buyer` gains a
  dependency on `arkhai-kit-delivery` only, never on a mechanism kit.
- **Modified**: `domains/bare_metal/buyer` — surfaces the delivery outcome in the
  CLI's own output and run log (obligation ref and sink outcome only; never the
  payload).
- **Configuration**: a new `[Delivery]` section on both the storefront and buyer
  sides, with the same shape on each. Absent section means no sinks and today's
  behavior exactly.
- **Dependencies**: no new third-party dependency — the built-in sinks use the
  standard library and the HTTP client already present.
- **Not broken**: no wire, database, deployment, or packaging break. Every
  existing deployment behaves identically until it configures a sink.
