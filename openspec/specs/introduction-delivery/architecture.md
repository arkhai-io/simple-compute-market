# Introduction Delivery Architecture

The [specification](spec.md) distinguishes local recipient-owned plugin sinks
from explicit-policy storefront-owned email intents. Both consume the same
mechanism-neutral `DeliveryEvent`; domain interpretation belongs to the accepted
package producer, not the delivery kit.

## Frozen recipient projection

Bare-metal delivery constructs each event from the immutable contact record:
buyer gets seller contact, seller gets buyer contact, and both get the same
accepted package. The envelope recipient comes from that party's captured route,
not a contact entry or current settings. Routes are absent from the rendered
context. SMTP credentials may rotate independently of captured content.

The renderer prints known top-level context fields first, then other fields in
sorted order. Nested mappings are sorted and indented; lists retain index order.
Strings remain literal, including whitespace and Unicode, so a contact blurb is
never turned into HTML, a template or an email header. This generic traversal
keeps the delivery kit independent of machine/declaration schemas.

## Durable intent boundary

Explicit finalization creates exactly two awaiting-completion intents with the
contact record in one transaction. The shared settlement journal must succeed
before either intent can send. A committed HTTP retry does not duplicate capture
or become a competing completion owner; the recovery worker converges unresolved
completion under the same obligation identity.

Each recipient has separate attempt ownership and terminal state. Verified
STARTTLS is mandatory. A positive DATA acknowledgement establishes acceptance
by the SMTP peer, not inbox arrival; QUIT failure cannot undo it. A lost DATA
acknowledgement requires review rather than blind retry. Finite temporary retries,
hard attempt bounds and stale-owner fences limit uncertainty, not eliminate it.
Terminal intents clear their routes and do not expose a redelivery API. Legacy
local sinks retain their separate explicit operator-redelivery contract.

Local SQLite/HTTP and fake-SMTP evidence does not establish deployment, recipient
inbox delivery or an exactly-once guarantee. Recipient-owned copies also remain
outside marketplace retention control.
