# Rotate registry account principals

## Why

Under `add-buyer-compute-rfqs` a buyer's marketplace principal owns its RFQs and responses
directly, so a changed key cannot carry them: a buyer whose key is compromised closes and
reposts. Publishers do not have this problem. The registry gives each publisher a stable
subject that its principals bind to, and moves it to a new principal only by a two-proof
rotation.

Buyers run no service of their own, so the registry is the only place a buyer's stable
identity at that registry can live. It needs the same stable subject and rotation for every
participant that signs its own requests, not only publishers.

## What Changes

- **A registry-local account subject** for any participant signing its own requests, to which
  its principals bind. RFQs and responses are owned by the account subject (design D1).
- **The account subject rotates by two-proof rotation**, using the dual-proof rotation
  `kit/identity` already provides, as publisher rotation does (D2).
- **The buyer CLI applies a rotation to the registries that hold its account**, through the
  buyer profile's rotation (D3).
- **Existing RFQs move from principal ownership to account subjects** (D4).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: registry account subjects and their rotation.
- `buyer-compute-rfqs`: ownership by account subject.
- `marketplace-identity`: applying a buyer profile's rotation at registries.

## Dependencies and Related Changes

- Depends on `add-buyer-compute-rfqs`.
- Builds on `add-persistent-buyer-profiles` (profile rotation) and `kit/identity`'s dual-proof
  rotation.

## Permanent documentation impact

- [ ] The repository's architecture document
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: registry account subjects to `registry-discovery` and `buyer-compute-rfqs`.
- D2: rotation by the publisher scheme to `registry-discovery`.
- D3: CLI-applied rotation to `marketplace-identity` and `docs/buyer-quickstart.md`.
- D4: the move of existing RFQs to `buyer-compute-rfqs`.
