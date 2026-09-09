# Two-sided contact-content delivery

## Problem and intended outcome

An explicitly finalized introduction should send each party the other party's
configured contact details and accepted deal/listing context at its own separately
configured route. Email is the first supported route. A routing address is not
implicitly a shared contact. A seller-only or status-only message does not meet
this outcome. Introduction settlement is neither proof of payment nor evidence
of off-platform commercial completion or physical provisioning.

This is a proposed transition, not current behavior. Current general composition
has optional seller-local/buyer-CLI-local best-effort delivery. The synthetic
file publisher and its signed no-outbound agreements forbid delivery. Preserve
both those historical terms and existing accepted/revealed records.

## Scope

Contact-owned explicit policy and review/finalize carriers; immutable two-sided
per-recipient intent/status; bounded verified-TLS SMTP; precise caller/config
ownership; additive persistence; explicit new-publication eligibility; optional
chart Secret hook; synthetic typed-client/restart/privacy tests. Buyer account
configuration is a client responsibility; seller configuration remains operator
owned. No new seller console, general notification framework, Slack/Telegram
connector, monetary policy change, physical supply authority or domain unification.

Related intake: #188 and #191 (delivery/disclosure), #219 (broader compute journey).
#167 remains off-platform attestation, not this introduction. #184 is a closed
historical inventory; #197/#203 retain retention policy/deletion scope. This change
does not claim to discharge their broader work or inherit unaccepted research.

## Acceptance and gate

The candidate [contract](contract.md) defines the exact wire and owner boundaries.
Local acceptance requires two distinct correct recipient messages after explicit
finalization, absent jobs before it, immutable snapshots, old-agreement safety,
honest ambiguous acceptance status, and no contact/route/credential leaks.
The exact contract and proposed normative deltas require final review before
implementation. They specify expiry/cancel fencing, terminal route cleanup and
new policy-bearing publication v2 without changing the identity envelope.
No issue publication, commit, release, remote publication or real mail follows
from this proposal. No private deployment coordinates belong in this change.

## Permanent documentation impact

After implementation and code review, promote behavior to
`openspec/specs/contact-exchange-settlement/spec.md` and companion architecture;
delivery lifecycle/TLS/privacy to `openspec/specs/introduction-delivery/spec.md`
and companion; new publication eligibility to `openspec/specs/storefront-publication/`;
configuration to `docs/development/DEPLOYMENT_AND_CONFIG.md`; owner boundaries to
`docs/development/ARCHITECTURE.md`. Update Goal 6 in
`docs/development/ROADMAP.md` and the active-change/capability indexes. No proposed
behavior is promoted to a permanent current-state contract in this docs stage.
