# Triage — 134-validation — unbacked-bare-metal-listings

Validated commit: `9aa024e2448b2758f71c23ee65a6021c8562369b`, the commit
`132-implementation.md` reviewed. The owner's record, numbered `02-validation.md` in their
checkout, saved here verbatim. Its links name
`.snapshot/validation-9aa024e-20261022T185347Z/`; in this checkout the evidence is unpacked
at `.snapshot/owner-validation-9aa024e/`.

Checked: every file in `SHA256SUMS` verifies; `results.json` names the commit before and
after; `pipeline.json` is run 39835301963, `headSha` the commit, all three jobs `success`,
the run's own status still `in_progress`; the VM job log shows the kit-derived
`test_an_escrow_released_by_a_trusted_oracle_is_collected` `PASSED` (line 4471) and 135
passed (line 5505). The Helm per-scenario counts, `e2e_alkahest_trusted_oracle` among them,
come from `helm-scenario-observations.json`, the validating session's reading of a log that
was later lost; `validate-helm.log` keeps the totals (112 passed, 5 failed), which those
counts sum to.

No `V<n>`: nothing to dispose of as a failure. Its "About the validation" points:

1. The served list can grow — presented with 132 F1: `e2e_alkahest_trusted_oracle` joins
   `HELM_SCENARIOS`; the other four are recorded as an observation.
2. The all-scenarios selection omits `E2E_APICREDITS_MODULE` and drops `contracts` —
   presented with 132 F1 and fixed in this round.
3. The raw Helm `e2e` step fails when an unserved scenario fails; 4. the evidence directory
   `.snapshot/validation/9aa024e2448b/` vanished, cause unknown; 5. the standard fetch waits
   on the run's aggregate status — observations on the validation tooling, presented, no
   action in this change.

Evidence for the round triaged in `132-implementation.triage.md`.
