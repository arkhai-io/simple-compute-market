# Implementation Tasks

## 1. Change the shipped defaults

- [x] 1.1 Re-verify the exposure before changing anything: no funds, escrow, or chain
      interaction gates hold placement; no rate limiting exists in the storefront; no
      per-buyer negotiation concurrency limit exists. Confirmed 2026-08-06.
- [x] 1.2 Set `capacity.hold_ttl_seconds = 0` in
      `domains/vms/storefront/src/market_storefront/settings.toml`.
- [x] 1.3 Set the same default in
      `domains/apicredits/storefront/src/apicredits_storefront/settings.toml`. The
      apicredits storefront carries the identical pattern against its quota ledger.
- [x] 1.4 Replace the comment framing 0 as a contention trade-off with the security
      justification, stating why shortening the window is not a mitigation and naming
      billing as the condition for raising it.

## 2. Preserve coverage of the two-phase path

- [x] 2.1 Leave `storefront.bob.toml` and `storefront.credits.toml` at a non-zero value
      and annotate both with why they deliberately override the default, so a future
      reader does not align them to it.
- [ ] 2.2 Confirm `domains/vms/storefront/tests/unit/test_two_phase_reserve.py` still
      exercises the hold path — it parameterizes the TTL, so it should be unaffected,
      but this needs checking rather than assuming.
- [ ] 2.3 Run the VM and apicredits e2e suites and confirm the two-phase reserve path is
      still covered through the local profiles.

## 3. Operator-facing guidance

- [x] 3.1 Correct `docs/cookbooks/vllm-apicredits-seller.md`, which instructed sellers
      to set 900.
- [ ] 3.2 Search the remaining docs and quickstarts for any other guidance that enables
      pre-settlement holds.

## 4. Validation

- [ ] 4.1 Run the storefront unit suites for both domains and the e2e suites. Any suite
      asserting a hold exists after acceptance under default configuration is a real
      finding, not a test to relax.
- [ ] 4.2 Confirm settlement's fresh-reserve fallback is exercised, since it is now the
      normal path rather than the exception.
- [ ] 4.3 Run `openspec validate --all --strict` against the baseline current at
      implementation time.

## 5. Closeout

Per `openspec/README.md#plan-closeout-requirements`.

- [ ] 5.1 **Comment hygiene.** Run `make check-comment-hygiene`. Read
      `_place_capacity_hold`'s docstring directly: it describes the hold as closing the
      window where the escrow settles but capacity is gone, which is now the accepted
      residual risk rather than a solved problem.
- [ ] 5.2 **Import placement.** Not applicable; configuration only.
- [ ] 5.3 **Documentation compliance.** Confirm the shipped-default rule landed in
      `openspec/specs/negotiation-protocol/spec.md`, that `ARCHITECTURE.md` states when
      capacity becomes exclusive, and that the why-shortening-fails reasoning stayed in
      `design.md`.
- [ ] 5.4 **Narrative compression.** Compress completed-task notes to final behavior and
      validation evidence.
- [ ] 5.5 **Roadmap currency.** Update Goal 5's current-state description in
      `docs/development/ROADMAP.md` — the vector is closed by denying the capability, and
      the goal is what buys it back.
- [ ] 5.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Uncompensated pre-settlement holds are not a shipped default; the setting documents its exposure and the condition for enabling it | `openspec/specs/negotiation-protocol/spec.md` — "Unfunded exclusivity is not a shipped default" |
| When capacity becomes exclusive in a deal's lifecycle | `docs/development/ARCHITECTURE.md`, capacity reservation |
| The security justification an operator reads before raising the value | `domains/vms/storefront/src/market_storefront/settings.toml` and the apicredits equivalent |
| Why shortening the hold window is not a mitigation, and why the paid-buyer race is the smaller risk | This change's `design.md` |
