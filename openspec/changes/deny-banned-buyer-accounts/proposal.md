# Deny banned buyer accounts

## Why

Under `add-buyer-account-login` a registry admits a buyer's writes on an admission certificate
from the buyer account service, and revoking a buyer there takes effect when the certificate
expires. A registry operator facing abuse — a buyer posting RFQs to harass or spam — can take
an RFQ down (`add-buyer-compute-rfqs`) but cannot stop the same buyer posting again, and a
new key from the same account would pass a ban on the old key.

## What Changes

- **A registry deny list overrides admission.** An operator denies a buyer account, and the
  registry refuses its writes whatever certificate or key it presents. A deny outranks an
  operator-issued key and an admission certificate, which outrank the registry's default
  posture (design D1).
- **The deny names the account, not only the key**: the admission certificate carries a stable
  account claim that the registry denies on, so a new key from a banned account is still
  refused (D2).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: the deny list and its precedence over admission.
- `marketplace-identity`: the admission certificate's account claim.

## Dependencies and Related Changes

- Depends on `add-buyer-account-login`.

## Permanent documentation impact

- [ ] The repository's architecture document
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- D1: deny precedence to `registry-discovery` and `docs/operator-handbook.md`.
- D2: the certificate's account claim to `marketplace-identity`.
