# Triage — 132-implementation — unbacked-bare-metal-listings

Reviewed commit: `9aa024e2448b2758f71c23ee65a6021c8562369b` (round 1's second triage fixes),
`HEAD` at triage; the fixes are made against it. When the triage began the only untriaged
validation record, `131-validation.md`, named `e15a5b2`, the commit before it
(`git log e15a5b2..9aa024e`: the one commit `9aa024e`, the chain probe's single
construction, the kit-derived trusted-oracle scenario, and documents). The owner waived
the rule: "It's taking longer than expected due to queue. Waive and begin triage and I'll
bring the evidence when I'm able." During the triage the owner brought the validation of
`9aa024e`, saved verbatim as `134-validation.md`; it names the reviewed commit, passed, and
has no `V<n>`. `131-validation.md` is superseded by it. The owner has no notes on
`9aa024e`'s diff (workflow seq 207).

### F1 — `131-validation`'s observations on the Helm scenario list are untriaged, and one contradicts the recorded reason for leaving the trusted-oracle scenario off Helm

Merged with `131-validation.md`'s "About the validation" points 1 and 2, and, once it
arrived, `134-validation.md`'s points 1 and 2.

- **Lens / basis / severity:** testing / evidence / minor (as the reviewer's)
- **Position:** partly. The recorded reason, that the Helm release "may not fund the
  seller", was wrong: the `dev-env` chart runs the compose image's baked state
  (`dev-env/Dockerfile:12`, `dev-env/generate_state.py:31-42`), the seller needs only gas,
  and the Helm `e2e` step uses the same settings the served codec scenario already
  transacts with. Proposed correcting the note and keeping both `scripts/validate_slice.py`
  points out of this change; adding the scenario to `HELM_SCENARIOS` only on an
  all-scenarios pass, as `change-validate` admits one.
- **Proposed outcome:** fix — correct Section 3's round-1 note; the tooling points recorded
  for handling outside this change.
- **Owner disposition:** "I don't use Github issues. The section 3 note is approved. Add
  the pipeline marker variable fix. Helm validation still pending." Then, with
  `134-validation.md` showing `e2e_alkahest_trusted_oracle` passing on Helm under
  `HELM_ALL_SCENARIOS=1`, revised: add it to `HELM_SCENARIOS` with the matching note; the
  four other scenarios that passed on Helm recorded as an observation; the all-scenarios
  selection extended to keep the served list (`contracts`), as recommended.
- **Result:** `scripts/validate_slice.py`: `PIPELINE_MARKER_VARIABLES` reads
  `E2E_APICREDITS_MODULE`; `HELM_SCENARIOS` gains `e2e_alkahest_trusted_oracle`;
  `--all-scenarios` runs the pipeline's scenarios and then any served scenario outside
  them. `scripts/tests/test_validate_slice.py` updated (the fake's lanes include API
  credits; the default run's selection and `not_run` map; the real Makefile's API-credit
  marker; the all-scenarios selection). Section 3's round-1 note corrected and a
  third-triage note added; the round's evidence under Section 10. Two ledger entries
  (the commit waiver, F1).

  Recorded as observations on the validation tooling, with no action in this change: the
  four further scenarios that passed whole on Helm at `9aa024e` (`e2e_deal`,
  `e2e_deal_buyer_cli`, `e2e_compute_dynamic_listings`, `e2e_non_erc20_settlement`) could
  join the served list; `NOT_SERVED` gives one blanket reason for every unserved scenario.

The fresh-context check of the fix put the marker variables in lane order, narrowed the
selection's comment, and corrected `change-validate`'s all-scenarios instruction to match.
The accepted fixes are committed as `1df44f4` ("unbacked-bare-metal-listings: round 1
third triage fixes"), on `9aa024e`, not pushed.

## Next

Advance — "advance"
