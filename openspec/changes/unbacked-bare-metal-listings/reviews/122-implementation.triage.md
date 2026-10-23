# Triage — 122-implementation — unbacked-bare-metal-listings

Reviewed commit: `e15a5b23e1db0889947ff6740e051aa5df8a59e6` (round 1's triage fixes), which
was `HEAD` at triage; the fixes are made against it. No validation record of `e15a5b2`
existed when the triage began: its validation had stopped on an invalid `GH_TOKEN`, and the
owner decided (workflow seq 190) that triage could proceed without it. During the triage
the owner ran a full validation of `e15a5b2` in their own environment, which passed all
three parts, and the validation step was writing its record from that evidence; it names
the same commit, so the records are one round and no waiver is needed. The owner has no
notes on `e15a5b2`'s diff.

Presented in the order F1, F2, F3, F6, F5, F4: F3's proposed fix depended on how F2 was
disposed of.

### F1 — Bounded client construction leaks a worker thread at every probe and can starve the storefront's default thread pool

- **Lens / basis / severity:** consistency / specification / should (as the reviewer's)
- **Position:** agree. Each probe of a chain missing its client started a new
  `asyncio.to_thread` construction, so a construction that never returns held one default
  executor worker per probe; the probe's own JSON-RPC work and the 64 `to_thread` call
  sites of `core_storefront/sqlite_client.py` share that executor, and no storefront sets
  its own. Proposed a daemon thread per construction rather than the reviewer's dedicated
  executor: with one per chain the count is bounded, and a pool's worker is joined at exit.
- **Proposed outcome:** fix — one in-flight construction per chain on a daemon thread,
  adopted when it finishes; the `settlement-configuration` delta amended; two kit unit
  cases.
- **Owner disposition:** agreed.
- **Result:** `AlkahestChainProbe` keeps each chain's pending construction
  (`_start_construction`, a daemon thread settling a loop future); a probe waits with
  `asyncio.wait`, so a timeout leaves it running, starts no other while it runs, and adopts
  its client, or builds again after a failure, once it finishes. The delta's requirement
  and the new scenario "A client's construction never returns"; decision 19's timeout
  bullet. Kit unit cases in `test_chain_probe.py`. Section 4's second-triage note.

### F2 — Release conditions under readiness are derived three ways in three domains

- **Lens / basis / severity:** direction / judgement / minor (as the reviewer's)
- **Position:** agree. VM (`demands_for_published_escrows`), API credits
  (`SettlementComposition.release_conditions`, `alkahest_ready`), and bare metal
  (`publication_release_conditions` over clauses) each write the readiness gate and the
  choice of chains; `design.md`'s decision 19 says all three call
  `publication_release_conditions`, which only bare metal does.
- **Proposed outcome:** fix — one `kit/alkahest` derivation over published escrows under
  readiness, called by all three storefronts, in this round's fix commit; D19's sentence
  corrected.
- **Owner disposition:** "I would prefer a Section 11 task for this."
- **Result:** task 11.9 added to Section 11, naming the kit function, its three callers,
  the removals, the tests, and D19's correction; 11.8's verification gains its suites.
  Ledger entry appended.

### F3 — The new trusted-oracle scenario tests only the SDK, not this repository's encoding of the condition

- **Lens / basis / severity:** testing / guidance / minor (as the reviewer's)
- **Position:** partly. The docstring remedy was already in place; building through the
  kit is the stronger one and cheap, and with F2 deferred it uses the kit's existing
  `release_conditions`.
- **Proposed outcome:** fix — the scenario derives its arbiter and demand through
  `kit/alkahest`'s `release_conditions` and the plan encoding, and its docstring states
  what it proves.
- **Owner disposition:** agreed.
- **Result:** `test_alkahest_trusted_oracle.py` derives the oracle-gated condition through
  `release_conditions` and encodes it with `encode_authorized_release_condition`; the
  arbitration request carries the condition's inner data. Unrun here: it runs in the VM
  lane's pipeline. Section 3's second-triage note.

### F6 — The exported low-level materializers don't hold an escrow to the listing's accepted entry, though the delta credits "plan materialization" with it

- **Lens / basis / severity:** consistency / specification / minor (as the reviewer's)
- **Position:** partly. The delta overstates; D18 already words it precisely. Dropping the
  exports does not fit: both buyers' escrow clients call
  `materialize_escrow_terms_from_proposal`, deliberately without accepted entries.
- **Proposed outcome:** edit — the delta's accepted-entry sentence names the seller's
  acceptance; the low-level materializer's docstring states that a seller goes through
  `authorize_escrow_proposal`.
- **Owner disposition:** agreed.
- **Result:** made in the `negotiation-protocol` delta and
  `materialize_escrow_terms_from_proposal`'s docstring. Section 8's second-triage note.

### F5 — D17 still says a resumed run derives from the Agreement's selected option

- **Lens / basis / severity:** documentation / evidence / minor (as the reviewer's)
- **Position:** agree. 85 F4's correction missed the bullet after the plan-check one.
- **Proposed outcome:** edit — rewrite the bullet to the recorded accepted proposal, the
  recorded conditions, the Agreement's exact amount, and the recorded seller plan.
- **Owner disposition:** agreed.
- **Result:** D17's bullet rewritten. Section 9's second-triage note.

### F4 — VM's chain-probe wiring is still proven only at the composition boundary

- **Lens / basis / severity:** testing / guidance / minor (as the reviewer's)
- **Position:** partly. Task 11.5 already plans VM's started-application degraded-start
  case with a stepped probe; it did not name the seams or record that it closes 85 F3's
  VM residue.
- **Proposed outcome:** task — amend 11.5: the app built through `build_vm_storefront_app`
  over `VmCompositionSeams` with a stub JSON-RPC and constructor, switched to answering
  before the stepped probe; the composition unit test stays.
- **Owner disposition:** agreed.
- **Result:** 11.5 amended.

The accepted fixes are committed as `9aa024e` ("unbacked-bare-metal-listings: round 1
second triage fixes"), on `e15a5b2`, not pushed. One ledger entry appended (122 F2).

## Next

Advance — "Advance."
