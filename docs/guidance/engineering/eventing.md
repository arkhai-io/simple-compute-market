---
tags: [engineering, eventing]
---

# Eventing

How a service tells others about its state changes: one eventing system per
service, each event recorded with the change it reports, delivered under stated
guarantees, and carried in an envelope whose evolution its readers can rely on. How
long the events and their delivery state are kept is
[Persistence, "State kept for notification or audit is retained by time"](persistence.md#state-kept-for-notification-or-audit-is-retained-by-time).

## A service has one eventing system

Each service has one eventing system. Producers record events in it, and every
outbox, notification, or delivery to a peer service is a consumer of it, never a
mechanism of its own per event type. An order service that sends a signed receipt
to a partner and tells its operators about a delayed shipment runs both as
consumers of one store of events, not as a receipts outbox beside a notifications
table. Adding an event type is one declaration and one call to record it; no
consumer, delivery code, or configuration schema changes for it.

A mechanism per event type repeats, each in its own way, what every delivery needs —
retry, ordering, pausing a destination and resuming it, a read of what is pending —
and the copies drift apart. One system states each of those once, and a reader
learns one status read for everything the service sends.

## An event is recorded in the transaction of the state change it reports

An event is written in the same database transaction as the state change it reports,
so the two commit or roll back together. An event recorded after the commit is lost
when the process stops between the two; one recorded before it reports a change that
may never happen. Work that must hold exactly when the event does — writing a signed
statement the event announces, say — runs in that transaction too, and its failure
rolls the state change back with it.

Where one component prepares an event and another owns the transaction that makes
the change, the prepared event is handed to the owner, which records it only if the
change is accepted: a transition the owner refuses records nothing.

## Delivery is at least once per destination, under a stable identity

Each destination receives each event selected for it at least once, in the order
the events were recorded, until that delivery is ended deliberately. A delivery whose
outcome was never recorded — the process stopped after delivering — is delivered
again, so every delivery carries the event's stable identity, and a receiver
deduplicates on it. A destination that fails holds up only its own later events,
never another destination's.

A delivery ends without receipt only by a stated rule: the destination refuses it
outright, it is given up after a bounded age, or the destination it is owed to is
removed. An ended delivery goes to a fallback recipient, never silently nowhere. A
destination paused by hand misses what is pruned before it resumes.

A consumer that tracks its position as the last event it has read relies on no event
committing behind that position. Events are therefore ordered so that none commits
with a lower position than one already visible to a reader; an identifier drawn
outside the recording transaction, which a slower transaction can commit after a
faster one has been read, would let a reader skip it.

At-most-once delivery is used only where it is chosen deliberately, for a stated
reason — a courtesy notice beside a durable record the receiver can always read,
where a duplicate does more harm than a loss — and the choice is written where the
delivery is. It is never the result of having no outbox.

## An occurrence is recorded once per its declared key

Each kind of event declares the fields that identify one occurrence of it: the
subject, say, and an attempt number. Recording the same occurrence again writes
nothing and returns the event already recorded. A producer that observes one state
change twice — a retried request, a second pass of a reconciling loop — therefore
reports it once, without keeping its own record of what it has reported.

## What a consumer acts on without knowing the kind is an envelope field

Anything a consumer does without knowing an event's kind — routing, filtering,
deduplicating, ordering, correlating — reads a first-class field of the envelope:
the event's identity, its kind and kind version, its source, its position, when it
occurred, its severity, its subject and related references, its correlation and
causation identities, its declared attributes, and a one-line summary a person
reads. `details` hold only what a reader of that particular kind wants. An envelope
that keeps everything else in `details` makes every router, filter, and cursor learn
every kind, and each kind declared changes all of them.

## Details hold only what may leave the service, already redacted

A consumer's destinations — a chat channel, a mail relay, a partner's endpoint —
receive the envelope whole, so `details` hold only what may leave the service, and
are redacted before the event is recorded, as its logs are. A secret, a credential,
or a raw tool output that may carry either stays in the service's own records, and
the event names where to find it.

## The envelope only gains optional fields

The envelope is a versioned contract
([Versioning, "A versioned contract is never changed in place"](versioning.md#a-versioned-contract-is-never-changed-in-place)),
and it evolves by addition. A field is only ever added, and added as optional. A
reader ignores a field it does not know, and keeps the envelope's extensions
unchanged in what it stores and passes on, without interpreting them. The envelope
version changes only with an incompatible change to the envelope itself, so a
reader built for one envelope version keeps reading every event that version
describes.

## A kind's details follow its kind version

A kind's `details` change incompatibly only with a higher kind version. A reader reads
the kind version before the details and decodes them only at a version it knows; an
event at another version is still routed and rendered from its envelope alone. A
consumer built for an older kind version thus keeps delivering a newer event rather
than failing on it.

## Attributes are scalars

An event's attributes hold scalars only — strings, numbers, booleans, and null —
each declared with its type by its kind, and one attribute name carries one type
across every kind that declares it. A router reads attributes as columns beside the
envelope's own fields, which a nested value, or a name typed two ways, would defeat.

## A kind's declaration never travels

A kind's declaration — its name, version, default severity, attributes and their
types, occurrence key, details model, and summary renderer — belongs to the producer
and never travels with an event. An event carries its envelope alone, so a reader
that has never seen the declaration still routes, stores, and renders it, and a
producer changes its declaration without coordinating with every reader.
