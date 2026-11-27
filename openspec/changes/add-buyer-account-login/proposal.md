# Add buyer account login

## Why

A buyer's marketplace identity is a key pair, held through a buyer profile
(`add-persistent-buyer-profiles`). A person signing up for the marketplace knows an email
login, not a key file, and a registry that admits writes only openly or by an
operator-issued key has no way to admit the buyers who sign up without its operator
issuing each a key.

Buyers do not run a service of their own, so the marketplace needs a service that holds a
buyer's key and vouches that it belongs to someone who signed up: the **buyer account
service**. It is outside this repository. This change gives the repository's buyer CLI a
login to it and gives the registry a way to admit the keys it vouches for, without the
registry storing a copy of its users or calling it on every request.

Goal 9's RFQs need both (`add-buyer-compute-rfqs`), and every buyer command benefits from
the login.

## What Changes

- **`market login` signs a buyer in through a browser** with OAuth 2.0 authorization code
  and PKCE over a loopback redirect, or the device authorization grant on a machine with
  no browser. The buyer account service writes the buyer's key back to the CLI, which
  stores it through the buyer profile's credential providers (design D1, D2).
- **The buyer account service issues short-lived admission certificates** bound to the
  buyer's key, in a standard proof-of-possession format. The CLI refreshes them through
  its login session (D3).
- **The registry admits writes in one of three configured modes**: open, an
  operator-issued key, or an admission certificate from a pinned issuer. It verifies a
  certificate offline against the issuer's public key and stores nothing per buyer (D4).
- **A double of the buyer account service** sits beside the lane doubles, so the CLI login
  and certificate admission are tested in this repository (D5).
- **SCM adds no security mechanism of its own**: the flows and the certificate format are
  standards, implemented with existing libraries (D6).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `marketplace-identity`: buyer login and key writeback into a buyer profile; admission
  certificates and their verification.
- `registry-discovery`: write admission modes.

## Dependencies and Related Changes

- Builds on `add-persistent-buyer-profiles` (profiles and credential providers).
- `add-buyer-compute-rfqs` depends on it.
- `deny-banned-buyer-accounts` follows it.

## Permanent documentation impact

- [x] The repository's architecture document
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: CLI browser login to `marketplace-identity` and `docs/buyer-quickstart.md`.
- D2: key writeback into a buyer profile to `marketplace-identity` and `docs/buyer-quickstart.md`.
- D3: admission certificates to `marketplace-identity`.
- D4: admission modes to `registry-discovery`, `docs/development/DEPLOYMENT_AND_CONFIG.md`
  and `docs/operator-handbook.md`.
- D5: the double to `docs/development/TESTING.md` and
  `docs/guidance/repository/lane-doubles.md`.
- D6: no permanent destination — it constrains how this change is built, and the
  engineering guidance already prefers existing libraries.
- The buyer account service to `docs/development/ARCHITECTURE.md`, "Shared vocabulary and
  identities".
