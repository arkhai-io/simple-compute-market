# Triage — 91-implementation-owner — unbacked-bare-metal-listings

Round commit: `da1929a6e5acbb5b976cabedd3c8267b4da3aad3`. The owner's note on validation's
local part, given while the round was read and routed to this triage. Its one point is
labelled O1 here. No review raised it: the review did not consider where the two
chain-backed tests sit, and the validation record noted only that no preflight checks
their toolchain.

### O1 — `make validate-local` should be able to skip the two Alkahest chain tests when their toolchain is missing, warning rather than failing

- **Lens / basis / severity:** testing / evidence / should (assigned)
- **Position:** partly. Failing six minutes into `make test` on a missing tool is a real
  cost. I first proposed an opt-in `validate-local` flag that warns at preflight and skips
  the two tests, failing fast without it. The owner then asked whether the tests are placed
  as `TESTING.md` says; they are not: `domains/vms/storefront/tests/integration/test_alkahest.py`
  spawns a chain through the SDK's `EnvTestManager` and drives a trusted-oracle settlement
  with no storefront code under test, which is a cross-process scenario, not an integration
  test of the storefront.
- **Proposed outcome:** decision — (a) move the trusted-oracle flow to one end-to-end core
  scenario against the lane's Anvil and delete the storefront tests, replacing the flag;
  (b) delete them; or (c) keep them and add the opt-in flag. I recommended (a).
- **Owner disposition:** "I do wonder if those two tests are correctly placed according to
  TESTING.md guidance. … Let's consider this alternate before designing the fix for O1."
  Then (a).
- **Result:** `e2e-tests/tests/e2e/roles/scenarios/core/test_alkahest_trusted_oracle.py`
  (marker `e2e_alkahest_trusted_oracle`, in the VM lane's module list, the README and the
  pytest markers) settles one ERC-20 escrow through the trusted-oracle arbiter against the
  lane's Anvil, with the funded buyer and seller and Anvil account #0, a deterministic
  development key, as the oracle; the CI workflow's deselects of the two tests are removed.
  Not added to the Helm `e2e` step's selection, whose release may not fund the seller.
  `domains/vms/storefront/tests/integration/test_alkahest.py` is deleted; the triage step
  could not delete it, so the orchestrating session ran the `git rm` on the owner's word,
  and the owner had the triage step's rules gain `git rm` on `dev`. Section 3's round-1
  note. Ledger entry appended.

Evidence for the round triaged in `85-implementation.triage.md`.
