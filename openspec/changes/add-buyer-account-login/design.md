# Design: add-buyer-account-login

## Context

The buyer CLI signs with the selected buyer profile's key, resolved through an OS
keyring, a strict owner-readable file, or an environment reference
([marketplace identity](../../../docs/development/ARCHITECTURE.md#marketplace-identity)).
A profile is created by generating or importing a key.

The registry admits writes openly, or by an operator-issued bearer key with `write`
scope (`core/registry/src/core_registry/api/api_key_auth.py`). A `write` key admits
listing publication.

The **buyer account service** is the service a buyer signs up to with an email login. It
holds the buyer's key and vouches for it. It is outside this repository, and it is where
role-based access and enterprise accounts will later live. This repository consumes it
and never implements it.

This change came from the review of pull request #401 on 2026-11-27, which replaced a
delegated account authority signing every RFQ operation with buyers signing their own
(`add-buyer-compute-rfqs`, D1). The review then asked how a buyer who knows only an email
login gets a key, and how a registry admits the keys of everyone who signs up.

## Decisions

Settled with the owner in the review of 2026-11-27.

### D1 — The CLI logs in through a browser with standard OAuth flows

`market login` opens a browser for the buyer account service's login, using OAuth 2.0
authorization code with PKCE and a loopback redirect (RFC 8252), as other command-line
tools do. On a machine with no browser it uses the device authorization grant (RFC 8628).
SCM depends on these standard flows and a configured issuer, never on a protocol of the
buyer account service's own.

### D2 — The buyer account service holds the key, and its administrators cannot use it

A buyer's key is held by the buyer account service in a way its administrators cannot use
to impersonate the buyer, and is written back to the CLI after login. The CLI stores it
through the profile's credential providers. How the service achieves this is the
service's design; open-source components are preferred to custom ones.

### D3 — Admission certificates bound to the buyer's key

The buyer account service signs a short-lived admission certificate stating that a buyer's
principal is admitted, until an expiry. The certificate names the principal's public key,
and a registry accepts it only on a request that key signed, so a copied certificate is
useless without the key. It uses a standard proof-of-possession format, such as a JWT with
a `cnf` claim (RFC 7800). The CLI refreshes it through its login session.

This is role-based access in its first form: later claims — roles, limits, an account an
operator can deny — go in the same certificate.

### D4 — The registry admits writes by a configured mode

The registry admits writes in one configured mode: open, an operator-issued key, or an
admission certificate from a pinned issuer. It verifies a certificate offline, against the
issuer's public key and the expiry, and stores nothing per buyer. Revoking a buyer at the
buyer account service takes effect when the certificate expires. The issuer pin is public
configuration, carried in a profile or chart value and never in a Secret.

Rejected:

- **A list of admitted principals on the registry**, maintained by the buyer account
  service as buyers sign up. It copies the service's users into every registry, grows with
  every sign-up, and two copies drift.
- **Asking the buyer account service on each write.** Revocation would be immediate, but
  every write would depend on that service's availability and pay a call.

### D5 — A double of the buyer account service

A double of the buyer account service sits beside the lane doubles and mirrors the contract
SCM consumes: the login flows, key writeback and certificate issuance and refresh. The CLI
login and certificate admission are tested against it.

### D6 — No custom security mechanism

SCM implements the OAuth client flows and certificate verification with existing
libraries, and adds no security mechanism of its own.

## Open Questions

### Q1 — The certificate's claims and format

The format and library, the claims a registry checks (subject, key binding, expiry,
issuer, audience), and whether it names the operations it admits.

### Q2 — What a certificate admits

Whether a certificate admits RFQ writes only, or any write the registry admits. Listing
publication is admitted by `write` keys today, and sellers are admitted separately.

### Q3 — Lifetime and refresh

The certificate's lifetime, how the CLI refreshes it, and what a command does when it
cannot.

### Q4 — Key writeback

How the key reaches the CLI and enters a profile — a new profile, or an import into an
existing one — and what `market login` on a machine with an existing profile does.

### Q5 — The configured issuer

How the CLI and the registry are configured with the buyer account service's issuer, and
how an issuer key change is rolled out.

### Q6 — Qualification against the hosted service

Repository tests run against the double. Qualifying the hosted buyer account service is
blocked on that service existing.

## Verification

Integration tests prove each admission mode at the registry, refusal of an expired,
foreign-issuer or unbound certificate, and the CLI login against the double. A lane runs a
buyer that logs in through the double and writes to a registry admitting certificates.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1–D3 | `openspec/specs/marketplace-identity/spec.md`; `docs/buyer-quickstart.md` |
| D4 | `openspec/specs/registry-discovery/spec.md` and `configuration.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md`; `docs/operator-handbook.md` |
| D5 | `docs/development/TESTING.md`; `docs/guidance/repository/lane-doubles.md` |
| The buyer account service | `docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities" |
| Goal 9 | `docs/development/ROADMAP.md`, Goal 9 |
