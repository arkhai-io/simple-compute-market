# Seller notice and notice-preserving buyer end — section 4 evidence

## Prepared first use

The target is an invocation-owned, in-process seller lifecycle API backed by the vendored payment authority and mediation contract doubles. It sends the seller's notice through the typed seller lifecycle client, `SyncSellerLifecycleClient.notice`, which both storefronts' `deals preempt` verb delegates to; both domains' CLI wiring is proven by the VM storefront's `tests/integration/test_spot_notice.py`, which installs the bare-metal storefront and drives each domain's `deals preempt`. SQLite state is created and deleted by the invocation. The identities and bearer token are deterministic public development fixtures. No resident server or secret is needed.

From a clean checkout:

```sh
make dist-ci
make -C kit/deal-servicing reinit
cd kit/deal-servicing
uv run --find-links ../../.dist python examples/preempt_first_use.py
```

The default profile is [preempt.lane.toml](../../../kit/deal-servicing/examples/preempt.lane.toml); select another with --profile. It explicitly names the lane-only double, test mode, authority, paired on-demand/spot options, setup opt-out and the lane-only servicing declaration, which lists `returned` for the shipped presets' payee stop and term end beside the payer's `charged`. The options are the shipped presets and a default buyer approves them. A separate charged spot option is refused by a default buyer and approved by one that waives the charged term end and charged preemption by name, through `BuyerTermsPolicy`'s per-term waivers. `kit/deal-servicing/tests/integration/test_preempt_first_use.py` runs the entry point on this profile with the kit's suite.

The entry point sends notice for spot with operation key fixture-notice at <fixture-now-plus-one>, then reads the pending stop. No browser surface or screenshots apply.

The rate-servicing declaration exists only inside the approval/command fixture. Production publication and delivery remain closed without the rate hook. This proves commands and authority records; delivered rate leases and physical teardown await convergence qualification.

## Observations

The entry point asserts, and prints as its record:

- a default buyer approving both shipped options, and refusing the charged variant until each charged term is waived;
- lost stop response → unknown; read/list → verified pending stop;
- requested time below the notice minimum → authority time at now + 30 seconds;
- identical retry → same stop and time; changed retry → rejected;
- on-demand notice → refused before a payment effect;
- buyer signing as administrator → HTTP 403;
- missing installed rate hook → refused;
- earlier payer stop → retained as the winner on seller retry.

The [VM record](vms-preempt.json) and [bare-metal record](bare-metal-preempt.json) are the section's records from the entry point's first form, which drove each domain's `deals preempt` CLI on charged-term options a waiving buyer accepted; they are kept as that form's evidence and are not what the current entry point prints.

## Buyer and administrator behavior

The buyer half's durable end journal records the payer stop before I/O, then sends a stable-key hint. Ordinary rate end retains service through the priced notice. Unknown stop and hint outcomes are independent and restart under the original keys. Escalating to immediate surrender reuses the stop and enters the existing receipt/case path.

VM market end --from RUN and market bare-metal end --run-id RUN, one verb registered from the buyer half, select ordinary end for rate deals; market bare-metal teardown is its deprecated alias. --end-now-regardless explicitly surrenders service before paid notice expires. The output separates mode, payment records, hint, delivery acknowledgement and case progress. A failed delivery read cannot rewrite the stop outcome.

The admin interrupt body adds interruption_kind=preemption|failure beside its free-text reason, and both storefronts mount the route over the seller half's classification. A rate request omitting the kind refuses; once-only omission retains failure for existing callers. Preemption delegates the existing notice admission and journal. Failure ends delivery and files delivery_end for spot and on-demand. There is no automatic rate self-penalty. Both typed admin clients expose interruption_kind and operation_key.

## Permanent coverage and validation

- Payments: 277 tests, typing, published vector and generated-model checks pass. New cases cover exact rate/setup derivation, buyer re-derivation, authorization phases, activation/digest admission, refusal classification, stable money-operation keys, lost responses, verified stop observations and fixed settlement figures after held reversal.
- Servicing: 70; lifecycle contracts: 37; lifecycle client: 2; buyer half: 22. Servicing and buyer-half typing pass.
- VM storefront focused lifecycle, payment and operator suites: 157 pass. New signed-route cases cover both preempt CLIs, actor refusal, accepted permissions surviving listing edits, response loss/read/list and an earlier payer stop.
- Bare-metal storefront focused lifecycle, payment and operator suites: 46 pass, including its composed rate seller and buyer paths.
- Buyer suites: VM 259, bare-metal 35 pass, including canonical ordinary-end/explicit-surrender flags and failed-read outcome reporting.
- Comment hygiene, packaging, scoped documentation citations and pinned OpenSpec strict validation pass.
- Normal-end application cases use real SQLite and typed signed clients. At the authority's effective stop, watch records the end without a seller-fault filing. Kit recovery cases retain the original stop through both-authorities-down and hint loss; explicit surrender retains foundation receipt-time filing.
- Loopback runs clear ALL_PROXY, all_proxy, HTTP_PROXY, HTTPS_PROXY, http_proxy and https_proxy. An initial bare-metal buyer run inherited a SOCKS proxy without socksio; its clean-environment rerun passes. A buyer-half typing attempt in the servicing environment lacked typer; typing in the buyer environment passes.

## Compose VM run

The required invocation was:

```sh
PROVISIONING_MODE=mock mise exec -- make -C e2e-tests test-e2e-vm
```

Make exited 2 after seven minutes: 290 passed, 2 skipped, 1235 deselected and one failure. The sole failure was test_listing_shapes.py::TestStage07_ShapePricing::test_07a2_market_buy_buys_a_smaller_shape_and_reaches_ready, reporting retained pricing differs from seller publication: rate_structure. This is the maintainer-owned excluded base defect and was left unchanged.

The pipeline exercised the existing VM purchase, lifecycle and dispute scenarios against the local compose stack. It did not qualify rate delivery. The owned compose stack, volumes/network and leftover test Anvil were stopped with e2e-vm-down and the supervised process-group cleanup.

## Follow-up corrections

Horizon resolution and mandate derivation share minimum_rate_duration_seconds. Replaying the old mandate function reproduced admission of an 89-second duration starting one hour after acceptance; the shared calculation requires 90 seconds for a 30-second delivery deadline plus a 60-second period. Boundary regressions cover both early and late starts. Settlement-runtime's 182 tests pass.

The vendored ApiErrorCode enum defines every code D4 names. Rate command HTTP 409 request_id_reused and hold_not_reversible now explicitly require repair. Approval HTTP 409 insufficient_funds becomes exported PaymentApprovalInsufficientFunds with funding guidance and no receipt polling. Tests retain unknown outcomes for server errors. These two corrections are separate commits after the section 4 implementation.

## Deferred work

Installed rate delivery, automatic rate remedies, live authority qualification and permanent specification promotion remain the change's later sections and post-review closeout.
