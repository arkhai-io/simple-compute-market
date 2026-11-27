# Design: add-buyer-compute-rfqs

## Context

The registry serves supply: sellers publish listings under their marketplace principal,
and buyers discover them with the listing filters of the installed filter specification.
Nothing lets a buyer publish demand.

Buyers already hold a marketplace principal. `add-persistent-buyer-profiles` gives the
buyer CLI a selected profile whose Ed25519 key is resolved through a credential
provider, and every buyer role signs version 2 requests with it
([marketplace identity](../../../docs/development/ARCHITECTURE.md#marketplace-identity)).
The registry already verifies such requests for listing discovery, and already admits
writes either openly or by an operator-issued key (`REGISTRY_REQUIRE_WRITE_API_KEY`).

The contact-exchange mechanism already introduces a buyer and a seller after an accepted
deal: `kit/contact-exchange` persists both contacts, redacts them one-way, sweeps them on
a retention window disclosed before commitment, and delivers them to each side's own
sinks ([contact-exchange settlement](../../specs/contact-exchange-settlement/spec.md)).

### Where this design came from

An earlier design of this change was implemented, closed out and archived on
`feat/buyer-compute-rfqs` (pull request #401). Its review on 2026-11-27 kept its purpose
and much of its lifecycle — independent introductions, two explicit consents,
withdrawal, closure ending pending responses, transactional deletion of contacts, partial
node counts, and anonymous browsing that follows supply visibility — and replaced the
rest:

- It admitted callers through a delegated account authority: an external service signed
  every RFQ operation, its namespace and account subject owned the records, and a
  `can_share_contact` flag it asserted authorized contact sharing. A buyer's key pair
  already identifies the buyer, so the delegation bought nothing a registry needs, and
  the flag was a role system without a goal behind it.
- It stored contacts with a custody stack of its own beside contact exchange's.
- It accepted free text (a 4,000-character description, free metadata, free region
  names) that anyone could read on a public registry.
- It reset every pending consent on any edit, including a deadline change, through
  terms revisions and a reconfirmation route.

The branch's code predates this design. Whoever implements it may iterate on that code
or start again; the review's findings against that code are recorded on the pull
request.

## Decisions

Settled with the owner in the review of 2026-11-27.

### D1 — Callers sign with their own marketplace principal

Every RFQ operation is a version 2 request signed by the caller's own principal and
verified as the registry verifies its other signed routes. The principal owns the RFQs
and responses it creates. There is no delegated signer, account namespace or permission
flag.

A changed key cannot carry its RFQs until `rotate-registry-account-principals` lands;
until then a buyer whose key is compromised closes and reposts. With keys held by the
buyer account service, a key changes rarely.

Rejected: a delegated account authority signing for users (see Context). A browser user
without a key pair is served by the buyer account service holding that user's key, which
the registry never sees.

### D2 — RFQ writes are admitted like the registry's other writes

Creating an RFQ and responding to one are writes. The registry admits them by its
configured admission mode — open, an operator-issued key, or an admission certificate
from a pinned buyer account service issuer — as `add-buyer-account-login` defines. An
open registry has chosen openness, as it has for listings. Reads by a signed caller need
only the read gate.

Rejected: admitting RFQ writes independently of the registry's write gate, which left an
operator who had closed publishing with open RFQ posting.

### D3 — Open RFQs are browsable where supply is

Where `REGISTRY_REQUIRE_READ_API_KEY` is false, anyone may search open RFQs and read one
by its identifier without signing. Anonymous results carry the published request and the
registry's identity and omit party references, responses and contacts. A closed or
expired RFQ is refused as an unknown one. A supplied proof that fails is refused, never
read anonymously.

### D4 — An RFQ requests what a listing offers

Anything a seller can list, a buyer can request. The registry validates an RFQ's shape
and commercial terms with the same listing schema and filter specification it loads for
listings, and adds only the demand's own fields: node count, regions, start window, term
and response deadline. No shape field has a special place; `gpu_model` is one categorical
attribute among those the listing schema declares. Sellers browse RFQs with the filters
buyers use on listings.

Rejected: a separate RFQ schema generated in the compute family, which the earlier design
used. It drifted from the listing vocabulary at once — a hand-picked subset of the shape,
and a `gpu_model` the registry accepted as any non-blank string.

### D5 — No free text is published

An RFQ carries no description and no free metadata. Commercial terms are typed, mirroring
the listing's terms. Regions are codes from an imported standard: ISO 3166-1 alpha-2
countries and UN M49 macro regions, matched hierarchically, so a request for Europe
matches supply in `DE`. A respondent's contact is free text, but only the buyer it
consented to reads it, after the buyer selects it.

Free text is not searchable in a way that helps a buyer and seller connect, and on a
public registry where buyers stake nothing it invites abuse. Private notes revealed with
the introduction, after both consents, are recorded as unowned work in Goal 9.

### D6 — Two consents, independent introductions

A respondent submits a chosen contact and consents to share it with this buyer if
selected. The buyer submits a chosen contact and consents when selecting that response;
selection completes the introduction with no further step by the respondent. The buyer
may select several respondents to one RFQ; each introduction is private to its pair, and
the RFQ stays open until closed or expired. Each contact-sharing request states the
opaque, RFQ-scoped reference of the party it shares with, and the registry refuses it
when that is not the current eligible party.

A respondent may withdraw a pending response; the buyer may dismiss one; selection and
withdrawal of one response are mutually exclusive. One response per respondent is
pending per RFQ. A response may state a node count up to the requested count, which
reserves nothing.

### D7 — Contacts live in the shared introduction custody layer

`unify-introduction-custody` generalizes `kit/contact-exchange` into one custody layer
for introductions: encrypted storage, one-way redaction, a retention window applied as
current policy and disclosed before commitment, early end by either participant,
operator sweep controls, and restore redaction. This change adds the stage before
selection: a respondent's contact held until selection, and deleted by withdrawal,
dismissal or closure in the same transaction. Selection turns it into an introduction.

The registry refuses an `indefinite` retention window by its own policy, since it holds
contacts as a party to neither side.

Rejected: a registry custody stack of its own, which duplicated contact exchange's
mechanism with different protection.

### D8 — Only the deadline is editable

A buyer may move the response deadline of an open RFQ; pending responses keep their
consent. Any other change is made by closing the RFQ and posting a new one, and closing
may name the replacement so respondents to the old one find it. A deadline that has
passed cannot be moved to reopen an RFQ.

Rejected: editing any field with terms revisions and a reconfirmation route. A
reconfirmation was a full new response, so revisions bought only a stable identifier, which
the replacement reference gives for far less.

### D9 — Records are bounded

The response deadline is at most a configurable horizon from the time it is set. Every
array and string an RFQ carries is bounded, the registry bounds request bodies, and
configurable caps limit the open RFQs and the pending responses a principal holds. The
caps catch runaway agents; admission (D2) is what makes abuse costly. Per-address rate
limiting is the hosting edge's, not the registry's.

### D10 — An operator can take an RFQ down

The registry's operator can take an RFQ down. Its shape is this design's open question.

### D11 — The flow ends at the introduction

No price, payment, reservation or provisioning follows from an RFQ or an introduction.

## Open Questions

### Q1 — Which listing terms an RFQ carries

D4 mirrors the listing's terms. Which of them a demand states — a target price in the
listing's rate form, a settlement mechanism, a maximum duration, an SLA, a deposit — and
how each is typed is open.

### Q2 — How the listing schema validates demand

Whether the RFQ body embeds a listing-shaped resource validated by the listing schema, or
the registry derives an RFQ schema from the listing schema at startup, and where the
demand's own fields are declared, is open. Test cases shared between packages ship in the
producer's package.

### Q3 — Region codes before listings carry them

Listings name their region as free text today. Whether this change moves listings to the
same codes, or RFQs carry codes first and `search-rfqs-in-the-database` aligns listings,
is open. The source of the code lists (a packaged library or vendored data) needs a
licence check.

### Q4 — The takedown

What a takedown does to pending responses and completed introductions, whether the RFQ
reads as closed or as removed, what reason is recorded, and who may see it.

### Q5 — Retries

Mutations keep principal-scoped replay. Reads of a contact must reauthorize on every
retry and store no body, as a route declared credential-capable does today. How this sits
with the envelope and retention `redesign-authenticated-requests` settles is open.

### Q6 — Bounds and caps

The horizon, the field bounds, the body limit, and the default caps.

### Q7 — What the branch's code keeps

Which of the branch's registry modules, migrations, clients, CLI and tests carry forward.
Its review findings against that code are recorded on pull request #401.

## Verification

Integration tests prove the lifecycle, consents, races, bounds and admission against the
real registry application, on SQLite and on PostgreSQL in a gate that runs both. A lane
scenario runs a buyer and two respondents from posting to introduction through the
buyer CLI.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D11 | The new `buyer-compute-rfqs` capability's specification and companion; `openspec/specs/README.md` |
| D2–D3 | `openspec/specs/registry-discovery/spec.md` |
| D1, D4 | `docs/development/ARCHITECTURE.md`, a section on buyer RFQs and "Shared vocabulary and identities" |
| D9 | `docs/development/DEPLOYMENT_AND_CONFIG.md`; `openspec/specs/registry-discovery/configuration.md` |
| D10 | `docs/operator-handbook.md` |
| Goal 9 | `docs/development/ROADMAP.md`, Goal 9 |
