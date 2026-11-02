# Compute domain re-review repairs

## Scope and setup

Base: `db2e2a9b6` on the agreed-evidence-and-early-termination implementation.
This is nonvisual, deterministic API/library integration evidence. It claims no
real hardware access, remote payment/mediation effects, or fresh hosted deployment.

Each invocation owns temporary SQLite databases and in-process ASGI applications.
Personas are accepted buyer, seller/administrator and configured site, signed with
the tests' public deterministic development identities (never for a public network).
No credentials, external seed, ignored configuration or resident server is needed.
The tests seed accepted Agreements and reservations, wire the real signing clients,
and control only external authority/physical boundaries. Setup completes before
API actions; this is not a browser deployment requiring a remote readiness probe.

## Replay

From a clean checkout, build the ordinary wheelhouse and refresh the selected
package environments:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist-ci
make -C domains/compute reinit
make -C domains/vms/storefront reinit
make -C domains/bare_metal/storefront reinit
make -C kit/site reinit
make -C provisioning/compute/service reinit
```

The direct first-use entry point for the producer story is:

```sh
cd provisioning/compute/service
ACTIVE_PROFILES=mock uv run --find-links ../../../.dist pytest tests/integration/test_lease_end_reports.py -q
```

Other focused entry points, from the corresponding package directories:

- VM: `uv run --find-links ../../../.dist pytest tests/integration/test_lifecycle_cycle.py tests/integration/test_lifecycle_database_execution.py tests/integration/test_lifecycle_ends.py tests/integration/test_lifecycle_failures.py tests/integration/test_servicing_composition.py tests/unit/test_interrupt_deal_admin.py -q`
- Bare metal: `uv run --find-links ../../../.dist pytest tests/integration/test_lifecycle_database_execution.py tests/integration/test_lifecycle_ends.py tests/integration/test_servicing_composition.py tests/test_fulfillment_service.py -q`
- Compute family: `uv run --find-links ../../.dist pytest -q`
- Site: `uv run --find-links ../../.dist pytest tests/integration/test_ledger.py -q`

These are ordinary package tests. CI's existing `test-kits`, `test-provisioning`,
`test-storefront`, `test-bare-metal` and `test-compute` targets discover them. No
optional example, CI-only runner or new workflow matrix row is needed.

## Observed criteria

| Criterion | Action and observation |
|---|---|
| S-N3 / O-F16: complete report recovery with finite polling | Push only the later release-failure report and prove physical release, then pull a two-report history. Before repair there are zero lease reads. After repair both reports are retained, empty reads continue recovery, and a successful complete read retires polling across reconstructed composition. The unchanged-cycle test still preserves the admission revision. Three cases pass. |
| E-N4 / O-F10 domain half: SQLite contention does not hold the event loop | Hold an independent real SQLite writer, start VM cycle/interruption or bare-metal cycle/local end, and let an unrelated coroutine release the writer. All four fail before repair and pass after it. Both signed site push/pull encounters additionally observe injected verifier thread identity; verification and synchronous ingress execute on a database worker. VM focused set: 11 passed; bare-metal set: 14 passed. |
| O-F7: shared compute classification/actor policy | Exercise the shared API for command matching, pending-source selection and opaque account mapping; the new API is absent before extraction. Existing domain scenarios continue to prove lawful correlation, actor attribution and retention. Shared compute suite and domain re-drive pass (VM 12; bare metal 8). Domain-specific storage, codecs and atomic journal writes remain local; no dependency or lock changed. |
| S-N4: producer/outbox checks are CI regressions | Real site sessions prove atomic transition/event/outbox rollback and deduplication for four transition paths. Temporarily removing report reservation makes all four fail; the mutation is restored. Real compute application clients exercise expiry, termination, direct release, release failure and force-release, pre-send reconstruction, lost ACK/retry identity, signer rotation without re-signing stored reports, exact signed push/pull, held capacity on failure, unsigned HTTP 404 parking versus transient HTTP 503 retry, future parked events, owner reconfiguration and explicit resumption. Four new application cases pass; the preceding focused lease/capacity-outbox set passed 24. |

S-N4 is a missing-verification repair, not a newly discovered producer algorithm
failure: the permanent checks assert the existing producer's contract. The
sensitivity experiment demonstrates the new gate detects loss of atomic report
reservation rather than claiming an unrelated production fix.

## Integration seam

At the parent's request this branch merges implementation head `49219d221`,
including the parallel S-N2 journal repair. Both domain correction adapters pass
`controlling_source_ref` from the shared compute result into `resolve_correction`,
without creating a new filing for that echo. The VM merge conflict preserves the
shared classifier and the new keyword; the bare-metal keyword merges directly.
The family module still owns no journal API or schema. The merged kit's permanent
correction-adoption tests and both domains' correlation tests are the seam re-drive.
This extraction introduces no new servicing policy.

## Encountered fixture repair

The first aggregate reached compute-service integration and failed its existing
retired-setting startup test with `RecursionError` after 457 other tests passed.
The same startup test passes alone. The fixture checked top-level `app.routes`
for mock paths; FastAPI represents included routers lazily, so every fixture
mounted them again and accumulated lifespan wrappers. The guard now uses the
public OpenAPI path projection and invalidates its cache only when mounting.
This is a separate two-minute fixture repair, not a waived aggregate failure.

## Validation

Focused red/green observations above were run with the prescribed proxy exclusions.
Fresh-wheelhouse packaging passed after each production repair. Final combined
validation on merge `0143c1ea9` passed in 7m27s with this root invocation:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
make check-architecture check-packaging check-locks check-comment-hygiene &&
  bunx @fission-ai/openspec@1.14.0 validate agreed-evidence-and-early-termination --strict &&
  make test
```

The prescribed Podman shim is a host prerequisite for the full aggregate; the
focused API/library replay above does not need it. The result includes compute
14 passed, VM unit 1196 passed with one existing optional RL skip, VM integration
523 passed, bare-metal storefront 540 passed, compute-service unit 607 passed and
integration 458 passed, plus release tooling and Helm structural/render checks.
The aggregate runs the existing kit typing targets; no standalone domain mypy
run is claimed. No browser, dev server or external deployment was started.
Change-wide independent review, documentation promotion and archival remain the
owning change's closeout rather than this bounded repair assignment.
