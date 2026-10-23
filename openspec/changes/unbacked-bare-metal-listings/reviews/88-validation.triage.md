# Triage — 88-validation — unbacked-bare-metal-listings

Validated commit: `da1929a6e5acbb5b976cabedd3c8267b4da3aad3`, the commit `85-implementation.md`
reviewed, so the records are one round.

The record's environment entries are missing evidence, not findings. The sandbox's local
attempt lacked Node.js and Anvil, so `domains/vms/storefront`'s two chain-backed
integration tests failed there; the owner's attempt on another machine at the same commit
passed every local step, so the local part is judged from it. Those two tests are the
subject of 91 O1, which moves them to the end-to-end tier. The `gh` token's expiry meant
the pipeline run was the one `make round-view` dispatched, with logs the owner supplied;
it names the same commit. The Helm part ran only the contracts and codec scenarios, as the
record says, and is no evidence for the deal scenarios.

### V1 — e2e-vm `multi_registry` stages 06a and 06b raise `StopIteration` in `alkahest_opening`

- **Lens / basis / severity:** testing / evidence / blocking (assigned per the skill)
- **Position:** agree. The log (`.snapshot/e2e-logs/run-107609315856/2_e2e-vm.txt`) shows
  both stages failing in `_escrow_named_by` over `listing.demands`: the multi-registry
  listings were created with supplied escrows and no `demands`, so they advertised no
  release condition for the pinned opening to select.
- **Proposed outcome:** fix — fixed by F9's derivation: a VM create derives the condition
  for supplied escrows from the storefront's configuration, the four VM scenarios stop
  passing `demands=` at create, and the multi-registry creates stay as they are; the fix
  commit's validation shows whether 06a and 06b pass.
- **Owner disposition:** agreed.
- **Result:** F9's derivation is in the fix commit and the four scenarios no longer pass
  `demands=`. The multi-registry stages are unrun here; the next validation is the
  evidence.

Evidence for the round triaged in `85-implementation.triage.md`.
