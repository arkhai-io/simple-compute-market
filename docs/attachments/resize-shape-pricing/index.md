# Resize shape pricing — implementation first use

## Setup and reproduction

Nonvisual, fixture-backed library encounter; not independent acceptance or a deployed
system/e2e run. Start revision: `9490b81d4` (`origin/resize-multiplier`). The evidence
applies to this packet's containing implementation commit and its exit-pricing
prerequisite `cbe5510dc`.

The required surface for this bounded slice is VM negotiation policy and seller
pricing, not a chain deployment. The prepared target is a fresh temporary SQLite
store created and removed by [first_use.py](first_use.py), owned by the invoking
checkout. It reuses the existing seller-hook suite's public development fixture
principals and listing setup. No secret or remote target selector is required.
The script loads a fake site's pool projection before starting negotiation and
injects a matching **advertised listing** source verdict. It does not authenticate
a real site response or demonstrate authoritative requested-shape feasibility.
No server, container, tunnel, or browser remains running.

From the repository root, prepare verified wheels and the normal storefront environment:

```sh
make check-packaging
make -C domains/vms/storefront reinit
```

Then this one command lands directly on the negotiation surface and prints the
encounter, including fresh setup and cleanup:

```sh
(cd domains/vms/storefront && PYTHONPATH=src:. uv run --frozen --no-sync python ../../../docs/attachments/resize-shape-pricing/first_use.py)
```

## Observations

The listing advertises one H200 GPU and four vCPUs, with family rates 60 per GPU
and 10 per vCPU in its selected asset. A deliberately different USD GPU rate is
also present; it does not contaminate the selected-asset reference.

| Action | Observed result |
|---|---|
| Open with two vCPUs, retaining the opening's omitted listing dimensions | Seller counters; effective shape is one H200 + two vCPUs, reference 80, not the advertised 100 |
| Counter with grouped whole shape one H200 + six vCPUs | Reference 120 |
| Reconstruct runtime, counter without a revision | Effective six-vCPU shape resumes from SQLite; reference remains 120 |
| Request nine vCPUs and the wrong GPU model | `shape_inadmissible` names CPU maximum 8; seller-hook calls added: 0 |
| Request the wrong GPU model within the envelope | `shape_commercially_infeasible` names GPU model; seller-hook calls added: 0 |
| Request a different region | `shape_commercially_infeasible` names region; seller-hook calls added: 0 |
| Revise to a whole storage-only shape with no priced family | `shape_price_unavailable`, not a quote from another asset or the advertised shape |
| Configure CPU maximum 5 while the pool hint states maximum 8, request seven | Policy reaches pricing with reference 130: the hint's stated bound overrides the configured default |
| Store override CPU maximum 6 over hint maximum 8, request seven | `shape_inadmissible` names maximum 6 |
| Replace override by one stating only the offer, request six | `shape_inadmissible` names configured-default maximum 5; hint maximum 8 does not leak through the override |
| Revise a continuation outside the envelope | Refused before the runtime's fallback reference can price it |
| Withdraw family rates, then exit the existing negotiation | `exit`; leaving does not require pricing the persisted shape |
| Open a different shape after removing the rate structure | `shape_commercially_infeasible`: flat-priced listing is shape-fixed |
| Authoritative requested-shape feasibility | **not checked**; owned by the separate feasibility-probe change |

The script is reproducible setup and an observational exercise, not a new permanent
acceptance-test suite. No new tests were added. The two old regressions asserting
unconditional shape-mismatch refusal were removed deliberately; that intent is
replaced by evaluating and pricing admissible shape proposals, while flat-priced
listings remain fixed.

## Validation

- 94 existing VM cases passed: revision decoder, seller hook, reference amount,
  escrow normalization, hold cap, negotiate controller, and loopback buyer-selection
  integration. The controller/loopback cases use their existing readiness/setup.
- 62 existing negotiation-runtime cases passed.
- `make check-packaging` passed after `make lock` refreshed the three consumer
  locks affected by the VM negotiation package's two direct imports.
- `make check-change CHANGE=negotiation-driven-capacity-resize CHANGE_BASE=origin/resize-multiplier`
  passed all twelve checks, including comment hygiene and pinned strict OpenSpec validation.

Focused reproduction after preparation:

```sh
(cd domains/vms/storefront && uv run --frozen --no-sync pytest tests/unit/test_vm_revised_terms.py tests/unit/test_sync_negotiation_seller_round_hook.py tests/unit/test_extract_initial_price.py tests/unit/test_sync_negotiation_escrow_normalization.py tests/unit/test_sync_negotiation_hold_cap.py tests/integration/test_negotiate_controller.py tests/integration/test_buyer_selection_negotiation.py -q)
(make -C kit/negotiation-runtime reinit && cd kit/negotiation-runtime && uv run --frozen --no-sync pytest tests/unit -q)
```

Corrected implementation encounters: a first test invocation used the nonexistent
plural `hold_caps` filename and collected nothing; the corrected suite above passed.
A first focused run exposed raw SQLite JSON/model adaptation errors (26 failed,
68 passed); normalizing the listing for policy while retaining its top-level rate
structure repaired those failures. Early exercise runs needed fixture API/setup
corrections and a buyer bid inside the existing bisection policy's reasonable range;
the final encounter above completes. No failing check is carried forward.

## Boundaries

This is slice A, not deployment-ready shape negotiation. The scalar remains an
absolute base-unit amount with existing truncation. Tasks 2.7–2.11 still own basis
points, upward rounding, floor/convergence and the payment-consumer audit. Accepted
artifact/claim propagation remains 2c. No typing suite, deployed pipeline, browser
journey, registry seller-proof verification, promotion, archival, or PR is claimed.
The top-level `rate_structure` carrier is the documented PR #349 contract on
`registry-as-published`; registry storage/proof is not reimplemented here.
