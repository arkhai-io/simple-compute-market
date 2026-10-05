# Joined settlement closeout — independent audit

Tested production revision: `66d83b9f` (`settlement-dispatch-campaign`), in checkout-owned `closeout-verify`. Mode: auditing; this assignment explicitly includes production control-flow inspection and named test surfaces. No product repairs or new permanent tests were made. This is backend/CLI/library evidence, not a rendered journey.

## Predictions, recorded before execution

| Prediction | Outcome |
|---|---|
| Clean wheels and consuming reinstalls expose declared stage/evidence exports without editable sibling sources | Met; own project editable installs remain normal, cross-project dependencies are wheels |
| Core and VM accepted-run recovery preserve exact mechanism despite stray proposals/current priority changes | Met in existing public CLI/library replay |
| VM first use: pending/0 → provisioning → ready/1, zero payment escrows | Met |
| Bare-metal controlled settlement/introduction/recovery preserves one physical identity and refuses unverified payment effects | Met in existing HTTP entry suites |
| API-credit pending/lost-ack/reopen/top-up: 0 → 1 → 2 grants, final balance 5, owner-only private result, zero payment escrows | Met |
| All domains persist versioned validated delivery inputs with immutable binding, separate progress/private results | Not fully met: VM repository accepts unsupported verified delivery payload (F3) |
| Selected stage revalidates authoritative sources before every protected recovery effect | Not fully met: bare-metal Alkahest revalidation accepts reclaimed journal state (F1) |
| Literal inventory and generic control flow contain no leftover orchestration switch | Not met: standalone VM negotiation branches on config key and proposal choice (F2) |
| Domain payment doubles remain compatible with typed client; published vectors pass | Met on methods/fields exercised by controlled paths; not a full private-service qualification |
| Complete-deal lanes run only on owned ready payment/site/provider/auth deployment | Unobservable: no owned ready deployment; live lanes not run |

## Findings, ranked

### F1 — P1: bare-metal Alkahest recovery authorizes from stale local materialization

`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_stages.py:386–405`, `revalidate_alkahest`, reads `settlement_runtime.get_status` and checks reference/materialization/obligation identity plus absence of fulfillment reference. It does not recheck chain evidence or inspect `reclaim_state`/`mechanism_status`. `BareMetalSettlementService.verified_evidence` invokes this gate before common begin/status/access/teardown, so invoking a callback is not itself proof of source revalidation.

The selected installed stage's isolated library diagnostic [`reclaimed_gate.py`](reclaimed_gate.py) supplies a matching materialized journal record with `reclaim_state='succeeded'`, `mechanism_status='reclaimed'` and no fulfillment reference. Observed: `reclaimed_journal_authorized_by_revalidation=True`. No chain or hardware effect was attempted; the observation is gate acceptance, not a demonstrated live unauthorized allocation.

Replay: `domains/bare_metal/storefront/.venv/bin/python docs/attachments/route-settlement-closeout/reclaimed_gate.py`. Acceptable result: refusal before protected effects, with selected-stage authoritative source revalidation. Reviewer should encode coverage at the production recovery surface; 6.2 cannot yet be confirmed.

### F2 — P2: standalone VM negotiation still chooses mechanism behavior outside its entry

`domains/vms/buyer/negotiate_cli.py:381–417` directly calls payment `payer_selection`, then branches on `registration.config_key == 'alkahest'` to parse escrow, validate policy, resolve chain/wallet and scale token prices. At `:541–551`, `picked_entry is None` chooses selection versus escrow construction. The stage already exposes selection/proposal hooks, but this CLI bypasses them. This is a control-flow finding, not a failed existing CLI test or a carrier-only projection. The original ID grep misses the config-key branch. See the [full inventory](inventory.md).

Replayable check: inspect fresh `market negotiate` selection/prerequisite/proposal construction for each supported entry; require all mechanism-owned behavior to be selected through the declared buyer stage, preserving existing pricing/wallet guards. 8.2's branch-removal acceptance is not satisfied.

### F3 — P2: VM evidence persistence does not validate delivery envelope or accepted digest shape

`domains/vms/storefront/src/market_storefront/payment_repository.py:81–135` checks only the top-level schema string and a truthy `agreement_sha256` before accepting a first verified record. Fresh installed-library diagnostic [`inspect_vm_schema.py`](inspect_vm_schema.py) successfully persisted/reloaded a `verified` record with digest `diagnostic-digest`, no authoritative source, and delivery `{kind: 'not-a-vm-payload', schema_version: 999}`. Observed: `unsupported_delivery_persisted=` followed by that payload.

The common planner rejects unsupported delivery facts, so this is **not** evidence of a delivery bypass. It is a repository contract/poisoned-state gap: verified payloads become conflict-frozen without the promised versioned validated delivery data. Pending records legitimately have incomplete facts; validation must distinguish pending from verified. 6.1 cannot yet be confirmed.

Replay: `domains/vms/storefront/.venv/bin/python docs/attachments/route-settlement-closeout/inspect_vm_schema.py`. Acceptable result: verified malformed source/delivery/digest refused without a stored authoritative record; supported pending and exact valid retries remain usable.

## Setup and preparation

- Required/prepared controlled target: this checkout's installed library/CLI and in-process ASGI apps. No inherited deployment selectors, external credentials, shared writable database or existing service was reused.
- `make dist-clean && make dist`: passed; entire joined wheel set rebuilt, not worker wheel leftovers.
- Reinit passed for `core/buyer`, `core/storefront`, VM buyer/storefront, bare-metal storefront, API-credit buyer/storefront/service, payments kit and `e2e-tests`. Bare-metal buyer has no reinit target: `uv sync --dev --find-links ../../../.dist --reinstall` used. Core/domain test environments were also synced/reinstalled from `.dist` before checks.
- Bare-metal own role wheels were explicitly installed non-editably for its committed inspection. Other consumers' own project editables are local to their project, never sibling paths. All eleven inspected consumer environments import both core exports and see `market_core/py.typed`.
- Wheel inspection found stage modules in each changed role wheel; core owns dependency-light carriers (only Pydantic dependency), with `py.typed`; payments kit also has `py.typed`. Core role and domain/API-credit packages have no typing markers or declared static targets. Credits-service runtime wheel depends on site/resource-pools/identity, not settlement kits; its test-only domain client dependency is not production authority coupling. Carrier/import-boundary suites passed, including `TYPE_CHECKING` boundaries.
- Static checks: `make -C core typecheck-core` passed (6 files); payments-kit typecheck passed (9 files), generated model check current.
- Reinit modified five existing locks (`core/buyer`, `core/storefront`, API-credit domain/service, e2e-tests). Restored only those generated lock changes after all execution; fresh installed environments were retained. Existing owner: [#257](https://github.com/arkhai-io/simple-compute-market/issues/257).

## Suites on joined wheels

Counts are per executed suite group; separate integration/storage rows below are repeat measurements, not additional unique coverage. All final runs passed with no xfails/skips reported.

| Suite group | Passed |
|---|---:|
| Core carrier purity/domain contract/domain boundaries | 15 |
| Core buyer orchestrator/acceptance/policy/priceless/identity recovery | 52 |
| Core storefront registry/lifecycle/publication fixtures | 24 |
| VM buyer focused selection/dispatch/CLI recovery/config/pricing/plugin group | 101 |
| VM storefront focused planner/fulfillment/recovery/failure/evidence/composition/publication/migrations plus all integration files | 244 |
| Bare-metal buyer composition | 9 |
| Bare-metal 15 named storefront selection/negotiation/evidence/migration/physical/HTTP/contact/composition suites | 80 |
| API-credit buyer five focused suites | 17 |
| API-credit storefront seven focused suites | 58 |
| API-credit domain typed client/HTTP/issuance evidence | 25 |
| Credits authority key/API/migration suites | 35 |
| Payments kit tests | 7 |

**667 passing checks in the primary groups.** Exact focused file sets are the committed owner packets' reproduction commands, with these joined additions: VM includes `test_settlement_publication.py` as well as the delivery packet's named set; bare-metal includes `test_app_composition.py` in its 15-suite set. [`replay.sh`](replay.sh) contains the actual joined preparation/focused/integration/storage/first-use commands.

| Required isolated integration/storage slice | Passed |
|---|---:|
| VM integration `test_settle_controller.py`, `test_negotiate_controller.py`, `test_storefront_client.py` | 29 |
| Bare-metal HTTP settlement/negotiation/introductions | 15 |
| API-credit typed-client `test_credits_client_http.py` | 4 |
| Credits-service real typed-client `src/tests/unit/test_api.py` | 3 |
| VM migrations/fulfillment resume runtime | 12 |
| Bare-metal migrations/persistence | 6 |
| API-credit storefront settlement fulfillment | 12 |
| Credits-service migrations | 13 |

VM runs used `ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS=''`, as declared. An initial verifier command accidentally named nonexistent `test_fulfillment_publication.py`: pytest collected no storefront tests, exit 4. Corrected immediately to the existing publication suite; final 244-pass run and isolated 29-pass integrations are the evidence, not the failed command. No fixture/import/wheel-version repair was needed.

## Controlled first use and storage observations

### VM

Replayed the committed `examples/payment_smoke.py` using the documented installed VM buyer/payments wheels. It owns fresh temporary SQLite, synthetic Ed25519 buyer/seller/payment-service personas, controlled payment HTTP and physical delivery. Real typed payment client/receipt models and VM planner are exercised. Successful signed in-process settlement establishes controlled readiness, not deployed health.

Observed: `before approval: pending deliveries: 0`; `after approval: provisioning`; `retry: ready deliveries: 1`; `payment escrow rows: 0`. The existing buyer focused group also replays actual `market settle --from <run>` under changed priority/enablement and both stray-proposal variants. No second accepted Agreement/operation is substituted.

Fresh introducing-table SQL diagnostic bootstrapped/reran VM evidence/delivery definitions. Evidence columns: negotiation PK, mechanism, Agreement digest, unique opaque ref, status, JSON. Delivery separately contains context/phase/claims/physical identity/private credentials. Cleanup printed `temporary_database_removed=True`. F3 limits the validated-payload claim despite those correct columns.

### Bare metal

Replayed the committed HTTP settlement/introduction entries and named recovery/physical suites (15 HTTP checks; 80 focused). These create fresh temporary SQLite and synthetic canonical identities; payment polling/site/provisioning are controlled, not hardware. Signed receipt tamper/pending checks and restart/result/access/teardown/contact paths hold under the existing coverage.

Installed role inspection ran `docs/attachments/baremetal-dispatch/inspect_wheels.py buyer|seller`: exact declared stages and six codecs conform. Fresh/rerun SQL shows evidence columns `negotiation_id, mechanism, agreement_sha256, settlement_ref, status, evidence_json, created_at, updated_at`; lifecycle independently has `settlement_ref`, capacity/fulfillment identity, state/failure and selected-site/resource binding. Old evidence/lifecycle schema shapes refused explicit reset; temporary schema removed. F1 limits Alkahest authoritative recovery qualification.

### API credits and credits authority

Replayed committed `docs/attachments/apicredits-dispatch/first_use.py` with installed storefront/domain wheels in the service environment (`PYTHONPATH=src`, explicit `--project .`). Owned file-backed temporary storefront/authority databases; seeded 100-unit `svc-quota`, two synthetic accepted Agreements; ephemeral operator key at the declared admin-auth seam. Credentials are not published. `/health=200` before effects.

Observed: pending grants **0**, lost-ack grants **1**, final grants **2**, balance **5**, payment escrows **0**, source revalidations **4**. Owner-only new-key secret retrieval and secret-free top-up/exact retry assertions held. Actual typed CreditsServiceClient/ASGI authority is used; only payment I/O is controlled. Databases reopened during recovery; final cleanup reported true.

Fresh storefront SQL: negotiation PK evidence, Agreement digest, unique established ref, constrained status and independent issuance-progress table with credentials reference. Actual common `credit_delivery` validation and repository conflict checks guard accepted delivery payloads. Signed issuance/private storage remains separate.

Fresh authority diagnostic [`inspect_credits_schema.py`](inspect_credits_schema.py) uses public bootstrap twice and schema check: `credit_grants` has unique fulfillment/negotiation, key FK, immutable owner/service/resource/quantity/key target/digest snapshot plus operational hold hint; no mechanism/escrow columns. Engine disposed and temporary database removed. Initial manual diagnostic used only authority Base metadata and omitted site ledger tables; bootstrap correctly refused it. Replayed with actual `run_migrations` (which initializes site/resource-pool metadata) and passed; not a product defect.

## Payment double conformance (9.1)

`make -C kit/arkhai-payments typecheck check-vectors check-generated test-unit` passed: **4 published vectors**, **7 tests**, current generated models. VM controlled HTTP goes through the actual typed `PaymentsClient.approve/poll` and generated signed-receipt/snapshot parsing, not a copied service implementation. Bare-metal polling double accepts current `poll(transaction, timeout=..., interval=...)`, returning the consumed `snapshot.receipt` with a real typed SignedReceipt. API-credit controlled boundary matches `poll`, `ensure_agreement_attached`, `reverse` arguments used by the storefront; receipt verification uses the installed kit and exact mandate/Agreement. These narrow doubles do not pretend to reproduce full snapshot/event/attachment behavior they do not exercise. VM buyer CLI approval double tests dispatch rather than ledger authority; the separate smoke supplies typed HTTP qualification. No private payments repository/service was used.

## Live complete-deal readiness

No checkout-owned live deployment or explicit payment/site/provider/auth target was handed off. No inherited `ACTIVE_PROFILES`, `CONFIG_DIRECTORY` or compose project selector was present. The committed generic local profile addresses are not proof of ownership and were not seeded or mutated. Read-only readiness probes at its storefront `/health`, registry `/api/v1/system/status`, provisioner `/api/v1/system/ansible/readiness` returned curl HTTP **000** (connection failure). Podman could not connect to its local machine socket. No owned ready live lane exists; no private payments service/account or hardware access was established by this setup.

Stopped before scenario execution, including state-changing readiness seeds. VM `test_full_deal_buyer_cli.py`, API-credit `test_credits_deal_buyer_cli.py`, bare-metal `test_bare_metal_deal.py` are **unavailable/unqualified**, not failed product journeys or mocked successes. Live payment complete-deal ownership remains `scm-complete-deal-e2e` in private `arkhai-io/arkhai-payments`; physical live qualification remains the domain roadmap's existing release gate. Public controlled qualification does not close those owners.

## Frictions and replayable checks

- Reinit lock churn: [#257](https://github.com/arkhai-io/simple-compute-market/issues/257); restore only generated lock changes after execution. Installed tested third-party resolution therefore reflects the reinit run, not a later resync to restored locks.
- Core unknown `asyncio_mode`: [#258](https://github.com/arkhai-io/simple-compute-market/issues/258); 15 carrier checks pass without suppressing it.
- Pydantic schema shadowing: [#259](https://github.com/arkhai-io/simple-compute-market/issues/259); no serialization failure observed.
- New credits TestClient Starlette deprecation: [#260](https://github.com/arkhai-io/simple-compute-market/issues/260); HTTP checks pass without suppressing it.
- VM agent-ID default warning remains visible; controlled composition succeeds, not proof of valid production identity configuration.
- VM process completion notice could not read retained output; `process logs` → `read` recovered 244 passes without rerun. Existing owning pi issue `~/dev/mlegls-pi/docs/issues/managed-process-retained-logs-disappear-during-test-run.md` updated in that repository at `8f8ff8a`; no missing-file conclusion is inferred.
- Checks prompted by use: pending must leave zero effects; loss of acknowledgement must retain one grant; reopen must reverify source and reuse operation; foreign principal must not see secret; malformed verified evidence must not become frozen authority; terminal reclaimed source must refuse physical recovery. First four held in the committed entries; last two have explicit counterexamples above. Branch inspection must follow real callers, not count only mechanism-ID literals.

## Task disposition and cleanup

8.1, 8.3 and 9.1 execution completed with the evidence/limits above. Independent 6.1, 6.2 and 8.2 audits completed but **their confirmation boxes remain unchecked** because F3, F1 and F2 respectively falsify the requested acceptance. Ticking them would misstate the result; the reviewer owns behavioral repairs, not this verifier. 6.3 and 8.4–8.7 remain outside this assignment; post-review permanent promotion is not claimed.

All controlled entries/diagnostics cleaned owned temporary databases, coordinators and engines. No dev server, container, browser, tunnel or external deployment was started. All supervised execution finished. No external running resources remain. Visual: false; screenshots: none.
