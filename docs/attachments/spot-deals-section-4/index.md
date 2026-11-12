# Seller notice — section 4 checkpoint

## Prepared first use

The target is an invocation-owned, in-process seller lifecycle API backed by the vendored payment authority and mediation contract doubles. It runs the production VM or bare-metal storefront CLI through its client factory seam. SQLite state is created and deleted by the invocation. No server, container, external deployment, secret or persistent fixture state is required. The identities and bearer token are deterministic public development fixtures.

From a clean checkout:

```sh
make dist-ci
make -C domains/vms/storefront reinit
cd domains/vms/storefront
uv run --find-links ../../../.dist python examples/preempt.py --domain vms
uv run --find-links ../../../.dist python examples/preempt.py --domain bare_metal
```

Each entry point directly invokes `deals preempt spot --operation-key fixture-notice --at <fixture-now-plus-one>`, then reads the pending stop. Both commands use the VM storefront development environment, which already includes the bare-metal storefront distribution. No browser surface or screenshots apply.

The committed fixture has paired on-demand/spot options, explicit authority entries, test mode, an in-process double selector and explicit setup opt-out. Its buyer explicitly accepts charged payee stops and term ends through `BuyerTermsPolicy(allow_unprotected_terms=True)`; default-buyer refusal is a separate observation. Its rate-servicing declaration exists only inside the fixture. Production publication and delivery remain closed without the rate hook. This proves commands and authority records, not delivered rate leases or teardown. Deployed lane-profile qualification remains open.

## Observations

The [VM record](vms-preempt.json) and [bare-metal record](bare-metal-preempt.json) show:

- lost stop response → unknown; seller read/list → verified pending stop;
- requested time below the notice minimum → authority time at now + 30 seconds;
- identical command retry → same authority stop and time;
- changed retry → rejected before another effect;
- on-demand notice → rejected with the actual non-delivery path named, no stop;
- buyer signing as administrator → HTTP 403;
- missing installed rate hook → refused;
- earlier payer stop → retained as the winner on seller retry.

## Validation

- Existing lifecycle contracts: 37 pass; typed lifecycle client: 2 pass; seller servicing: 70 pass; buyer lifecycle: 20 pass. Seller-servicing typing passes.
- Payments: 221 existing tests and typing pass.
- VM lifecycle acceptance/admin/ends/admission, lifecycle client parity and operator CLI: 126 pass.
- Bare-metal lifecycle ends/database execution and operator override/publication CLI: 29 pass.
- `make check-comment-hygiene check-packaging`: passes after refreshing the VM, bare-metal and end-to-end locks for the lifecycle client's runtime dependency.
- No permanent acceptance tests were added.
- The compose VM end-to-end run has not been attempted at this checkpoint.

## Restart

Seller command/read/CLI tasks 4.1–4.3 are implemented. Task 4.4 has committed in-process first-use fixtures; deployed lane-profile preparation is still open. The buyer priced-notice flow (4.5), foreground watchdog (4.5a), and foundation admin delegation/emergency classification (4.6) remain open. Permanent specification promotion and archival remain post-review closeout work.

The foundation admin route currently selects `stop` solely from accepted payee entitlement and otherwise uses `delivery_end`; it has no emergency/failure selector. The rate adapter requires explicit per-part stops and caller-persisted descriptors, so that bare admin stop is not a working rate notice. The foundation owner needs to delegate lawful notice to `notice` and distinguish seller-caused emergency failure, including spot hardware failure, through its existing cause classification. This slice adds no second classification switch.
