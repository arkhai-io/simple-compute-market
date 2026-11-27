# Design: deny-banned-buyer-accounts

## Context

`add-buyer-account-login` admits writes by an open posture, an operator-issued key, or a
key-bound admission certificate verified offline (its D4). Revocation at the buyer account
service takes effect at certificate expiry, and the registry stores nothing per buyer.

The review of pull request #401 on 2026-11-27 settled that an operator's deny overrides that
delegated admission, keyed on an account rather than a key — an account-wide ban — and that it
follows the MVP.

## Decisions

### D1 — Deny overrides admission

Admission resolves in order: an operator's deny, then an operator-issued key or an admission
certificate, then the registry's default posture. A deny wins whatever the other tiers say,
unlike publication hints, where a higher tier wins only the fields it states.

### D2 — A deny names an account

The admission certificate carries a stable account claim, and the registry denies on it as well
as on a principal. The claim is used only for denial; ownership stays with the principal or
account subject.

The deny list grows only with abuse, unlike a list of admitted buyers.

## Open Questions

### Q1 — The operator interface

How an operator adds, lists and removes a deny, and whether a takedown can deny its poster in
the same call.

### Q2 — What a deny does to existing records

Whether a deny closes the account's open RFQs and ends its pending responses, or only refuses
new writes.

### Q3 — Reads

Whether a denied account may still read.

## Verification

Integration tests prove a denied account refused with a valid certificate, with a new key under
the same account, and with an operator-issued key.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D2 | `openspec/specs/registry-discovery/spec.md`; `openspec/specs/marketplace-identity/spec.md`; `docs/operator-handbook.md` |
| Goal 9 | `docs/development/ROADMAP.md`, Goal 9 |
