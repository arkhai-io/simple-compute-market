# Resize shape pricing — implementation first use

## Setup and reproduction

Nonvisual, fixture-backed library encounter; not independent acceptance or a deployed
system/e2e run. Slice B starts at `6f387f0b3` (`origin/resize-multiplier`). The current
encounter uses multiplier semantics; the prior slice-A reference observations
and its exit-pricing prerequisite `cbe5510dc` remain in Git history.

The required surface for this bounded slice is VM negotiation policy and seller
pricing, not a chain deployment. The prepared target is a fresh temporary SQLite
store created and removed by [first_use.py](first_use.py), owned by the invoking
checkout. It reuses the existing seller-hook suite's public development fixture
principals and listing setup. No secret or remote target selector is required.
The seller prices from what its registries last accepted, so the script records a
successful publication of the listing's family rates to the fixture's two test
registries (never contacted) whenever it stores them, and withdraws them the same
way: as a publication without rates.
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
| Open with two vCPUs, retaining the opening's omitted listing dimensions | Seller counters; effective shape is one H200 + two vCPUs, multiplier reference 10,000; derived quote 80, not the advertised 100 |
| Counter with grouped whole shape one H200 + six vCPUs | Multiplier reference 10,000; derived quote 120 |
| Reconstruct runtime, counter without a revision | Effective six-vCPU shape resumes from SQLite; multiplier reference remains 10,000 and derived quote remains 120 |
| Request nine vCPUs and the wrong GPU model | `shape_inadmissible` names CPU maximum 8; seller-hook calls added: 0 |
| Request the wrong GPU model within the envelope | `shape_commercially_infeasible` names GPU model; seller-hook calls added: 0 |
| Request a different region | `shape_commercially_infeasible` names region; seller-hook calls added: 0 |
| Revise to a whole storage-only shape with no priced family | `shape_price_unavailable`, not a quote from another asset or the advertised shape |
| Configure CPU maximum 5 while the pool hint states maximum 8, request seven | Policy reaches pricing with multiplier reference 10,000 and derived quote 130: the hint's stated bound overrides the configured default |
| Store override CPU maximum 6 over hint maximum 8, request seven | `shape_inadmissible` names maximum 6 |
| Replace override by one stating only the offer, request six | `shape_inadmissible` names configured-default maximum 5; hint maximum 8 does not leak through the override |
| Revise a continuation outside the envelope | Refused before the runtime's fallback reference can price it |
| Withdraw family rates, then exit the existing negotiation | `exit`; leaving does not require pricing the persisted shape |
| Open a different shape after removing the rate structure | `shape_commercially_infeasible`: flat-priced listing is shape-fixed |
| Authoritative requested-shape feasibility | **not checked**; owned by the separate feasibility-probe change |

The script is reproducible setup and an observational exercise, not a new permanent
acceptance-test suite. Slice B adds the specifically requested multiplier arithmetic,
floor/convergence and persistence regressions; slice A added no new tests. The two old regressions asserting
unconditional shape-mismatch refusal were removed deliberately; that intent is
replaced by evaluating and pricing admissible shape proposals, while flat-priced
listings remain fixed.

## Slice A validation (prior checkpoint)

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

## Slice B validation

- 121 focused VM cases pass (including 20 existing negotiation-thread cases): exact multiplier arithmetic and overflow (unit),
  shape-change/floor/convergence and large-payment SQLite round trip (library
  integration), the existing decoder/seller/reference/escrow/hold/controller cases,
  and the real buyer against the served storefront in both flat and shape-priced
  modes (application integration). The latter publishes from pool family rates;
  an unsourced database-only rate edit is not substituted for publication policy.
- 71 core buyer cases and 69 VM buyer cases pass, covering monetary Agreement and
  obligation comparison, client/orchestration, and resume. 49 existing policy and
  generic rate-helper cases pass unchanged, including truncation compatibility.
- The packet's one-command encounter passes after `make check-packaging` and the
  storefront's declared `reinit`, using refreshed wheels without ad hoc source
  overrides for internal packages.
- `make check-packaging` passes. `make check-change
  CHANGE=negotiation-driven-capacity-resize CHANGE_BASE=6f387f0b3` passes all twelve
  checks, including comment hygiene and pinned strict OpenSpec validation.

The focused VM reproduction command above additionally includes
`tests/unit/test_vm_multiplier.py` and `tests/integration/test_vm_multiplier.py`.
The large exact monetary quote is derived identically by seller artifacts, the
persisted Agreement and the buyer codec; transcript scalars remain 10,000 bps.
No existing truncation assertion was changed. Shape-priced quotes round once in
`quote_from_multiplier`; `compute_rate_total` still serves legacy amount semantics.

## Slice C: agreed order and capacity claim

The accepted plan now records `service_terms["vm.v1"].order` with the whole
agreed quantitative/GPU shape. The publication stays unchanged. Both escrow
and hosted-payment delivery use the snapshot; a legacy plan without one derives
an order from its accepted provision terms. Acceptance holds use the same order
builder. No reservation resize is invoked.

After the setup above, open the changed surface with:

```sh
(cd domains/vms/storefront && uv run --frozen --no-sync pytest tests/integration/test_vm_multiplier.py -q)
```

This prepares temporary checkout-owned SQLite and an in-memory real site ledger,
mounts the actual site router, signs site responses, and drives the real
`SiteCapacityClient` over ASGI. No deployment, secret, chain, registry or resident
server is needed. It is library/wire integration, **not deployed e2e evidence**.

The smaller-shape cases start from one H200 + four vCPUs, negotiate a whole
revision to two vCPUs, accept at 10,000 bps, reconstruct SQLite, and observe:

| Case | Accepted order and fulfillment claim | Site reservation |
|---|---|---|
| `hold_ttl_seconds=900`, retaining one GPU | one GPU + two vCPUs | acceptance hold and committed lease both match |
| `hold_ttl_seconds=0`, omitting the GPU family | two vCPUs, no GPU | fresh settlement reservation and committed lease both match |

The listing still advertises four vCPUs after acceptance. The existing provider
sizing suite confirms that committed reservation dimensions override request and
pool defaults, and an omitted GPU count provisions no GPU. The fulfillment planner
and `encode_compute_lease` need no change.

Validation: 122 focused storefront tests and the packet's original encounter pass;
52 existing VM provider-plan tests pass. `make check-packaging`, all twelve
`make check-change` checks (including strict OpenSpec validation), and
`make check-architecture-change` pass. The first new regression attempt supplied
a double where composition requires a `CapacityRuntime`; composing the real
runtime over the signed site client fixed setup. An earlier implementation tried
to normalize durable `VmMessage` metadata as a provision payload; extracting only
its already-decoded shape fixed that mismatch. Neither failure remains.

Small payment-boundary repair: the existing successful receipt/delivery regression
now seeds a 10,000-bps transcript scalar beside a monetary Agreement of 100.
Hosted settlement validates the mandate bound to the exact stored Agreement,
rather than comparing that payment to `agreed_price`. Pending, verified,
idempotent delivery and mismatched-mandate refusal still pass; 31 focused payment,
lifecycle-admission and multiplier cases pass after this repair. The redundant
scalar/payment equality check was intentionally removed, not weakened into a
permissive amount comparison.

At the slice-C checkpoint, deployed e2e was unrun because `docker` was absent and
Podman selected an unconfigured provider shim. The final attempt configured the
native provider and built all fresh images, but startup failed before readiness
on included registry environment-file path resolution. Task 2.15 is explicitly
**unobservable**, not passed; no specs ran against a down service. See
[final-validation.md](final-validation.md) for the exact command, failure, cleanup,
and rebased focused validation. PR #349's registry carrier/seller-proof dependency
remains open; no deployed proof check is claimed. Promotion/archive remain after review.

## Boundaries

Slices B and C are not yet deployment-qualified shape negotiation. Shape-priced scalar
threads carry basis points; flat listings retain their absolute/truncating contract.
The repeated no-revision sub-floor counter in the encounter reaches the existing
bisection stale exit, so later refusal observations use a fresh thread. Accepting
the floor instead converges, as the focused persistence regression demonstrates.
Accepted artifact/claim propagation is covered by slice C above. No typing suite,
passing deployed pipeline, browser journey, registry seller-proof verification,
promotion or archival is claimed. Final PR preparation and validation are recorded
in [final-validation.md](final-validation.md).
The top-level `rate_structure` carrier is the documented PR #349 contract on
`registry-as-published`; registry storage/proof is not reimplemented here.
