# Introduction Delivery Architecture

The [normative contract](spec.md) defines where a revealed introduction is delivered and when. This document explains why seller-side delivery is dispatched at most once, how that is held, what it leaves to the buyer and the operator, and why its sinks serve a service's events too while its delivery stays its own.

## One seller-side dispatch per introduction

The durable reveal is what an introduction deal produces, and it is what either party relies on. Delivery is a best-effort courtesy beside it: it tells a party's own destinations about a contact that party already holds, and it never gates the deal. Seller-side delivery is therefore dispatched at most once per introduction, by the introduction start that completes the reveal.

Whether a record existed before a start cannot decide that. A start persists the introduction and then completes it, and a start whose completion fails leaves the record behind and answers 503; the buyer's next start finds the record, completes the reveal, and must still tell the seller. Two concurrent first starts can also both find no record. So once completion succeeds, the start claims the introduction's seller-side delivery with a write that succeeds for exactly one caller, and only the start that wins dispatches. Any other start, concurrent or later, dispatches nothing, and a claim write that fails answers the same 503 as a failed completion, so the buyer's next start claims it.

The claim records that a dispatch was scheduled, not that a sink received it. A dispatch lost to process exit before it ran, or failed at every sink, is recovered by the operator's explicit re-delivery, which reads the durable reveal, as any failed send is. A durable delivery outbox with sink-level idempotency would make delivery guaranteed, at the cost of a servicing loop and an idempotency duty on every sink, including third-party ones; it is not what best-effort delivery beside a durable reveal needs.

## No counterparty lever

Seller-side delivery is never something a counterparty can trigger. A buyer repeating starts, by mistake or deliberately, cannot make the seller's sinks send again: delivering on every start that completes the reveal was rejected for exactly that reason. Re-delivery stays the seller operator's own action, and the buyer's copy is sent by the buyer's own process from the reveal it received.

## The claim is its own table

The claim is a row in `contact_introduction_seller_dispatches`, keyed by the introduction's obligation reference, and taking it is an insert that succeeds for one caller (`claim_seller_dispatch` in `market_contact_exchange.migrations`, passed to `IntroductionRouteService` as its `claim_seller_dispatch` callback). It is not a column on `contact_introductions`: that table's `contact_introductions_redaction_only` trigger refuses every update but the one-way payload redaction, which is how a revealed row is kept from being rewritten or un-redacted, and the claim leaves that trigger untouched.

The table is created empty. That is correct only because no deployment holds an introduction revealed before the table exists: such an introduction would hold no claim, and the next start for it would announce it to its seller again.

## Completing an interrupted reveal is the buyer's

An interrupted reveal is completed by the buyer's new start. Completion is local, idempotent bookkeeping, and a new start carries a fresh request identity, as the buyer client gives every start, so it reaches completion; the 503 a failed start answers says that starting the introduction again completes it. An exact replay of the failed request answers its recorded 503 and completes nothing, as every route answers an exact replay: resuming completion on a replay would break that rule for a case a new start already handles. A sweep that completes and delivers without the buyer was rejected: it would hand the seller the buyer's contact while the buyer saw a 503.

## Deletion during a reveal

A start that completed the reveal from payloads it read before a deletion committed preceded that deletion, so the one dispatch it claims is still its own, sent from the record it holds. After the deletion no later start or re-delivery sends anything: re-delivery reads the durable reveal rather than reconstructing one, and once the payloads are gone there is nothing it may send.

## One sink layer

The sinks that deliver a revealed introduction also deliver a service's events, so an operator configures a mail relay, a webhook or an Apprise target in one way, and a sink installed as a plugin serves both. A sink takes a `Deliverable` and reads nothing else of it: `rendered`, the text a person reads; `payload()`, what a machine destination receives; and `reference`, what it is about. An introduction's `DeliveryEvent` is one, its reference its obligation reference. An event is one through `EventDeliverable`, with its summary as its rendering, its envelope as its payload, and its subject, `<type>:<id>` such as `lease:<reservation>`, as its reference. A sink contract and built-in sinks of the eventing component's own would duplicate every sink and Apprise's plugin. A third-party sink that reads `obligation_ref` keeps delivering introductions and fails an event's delivery, reported by its exception's class as any sink failure is.

A signing webhook signs as the composition that builds it says, never as constants. A storefront delivering an introduction signs as role `seller` and operation `introduction_delivery`, and the provisioning service delivering an event as role `service` and operation `operator_event_delivery`, each with its own identity, so a receiver verifies which service sent what. A signing instance built without a signer, or without the role and operation to sign as, is refused.

Events reach sinks through the event-sink consumer, `market_delivery.event_sinks`, under the distribution's `events` extra, so a buyer, which delivers introductions only, installs no eventing component. It is one consumer of the service's eventing system, `event-sinks`, with one destination per enabled sink instance. The deployment's routes, each an SQL condition over the envelope and the sinks it names, select the sinks an event goes to; each selected sink receives it at least once, under its stable identity, and its outcome is that destination's delivery state. A failing sink is retried with backoff and holds up no other sink. Once a delivery is older than the consumer's maximum age it is abandoned, and the event is handed to the finally sink: the log, unless an enabled sink instance is named for it. A route naming a sink that is not enabled, or a finally sink naming none, is refused when the consumer is built, so the service does not start on it. A sink added beside the others starts at the latest committed event. A sink that leaves the configuration is a departing destination whose routes are gone, so which of the events it had not yet read they would have selected is no longer known: every one of them is handed to the finally sink for it rather than lost, and the finally sink may therefore record an event the departed route would not have selected. See the [eventing architecture](../eventing/architecture.md).

Introduction delivery stays outside the eventing system. Its seller-side dispatch is claimed at most once ("One seller-side dispatch per introduction" above), no counterparty has a lever on it, a seller's delivery is routed by the origin of the listing so one site's destinations never receive another's buyer contact, and a buyer delivers with no database of its own. A consumer delivering at least once from a store of events holds none of those, so introductions share the sinks but not the delivery: they keep their claim, their origin routing and the operator's explicit re-delivery.

## Related contracts

- [Contact-exchange settlement](../contact-exchange-settlement/spec.md)
