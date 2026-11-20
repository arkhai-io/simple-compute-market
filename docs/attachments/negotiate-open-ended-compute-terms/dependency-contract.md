# Dependency contract checkpoint

This is code-level dependency evidence, not a completed terms implementation or
a deployed recurring-deal qualification. The branch starts at `ba77a3b30` from
PR #350 and merges PR #349 as `faa339eea`.

## Observed price contract

The VM negotiation scalar is nonnegative integer basis points (10,000 = 1x).
The selected shape's complete exact rational quote is rounded upward once and
refused above uint256. Flat pricing retains its existing absolute-amount path.

The accepted Agreement contains the computed monetary total, not basis points.
The existing library-integration test
`domains/vms/storefront/tests/integration/test_vm_multiplier.py::test_shape_change_keeps_the_floor_and_exact_payment_through_persistence`
asserts this against the accepted response, persisted Agreement bytes and plan.
Its separate transcript assertion retains the scalar 10,000. Therefore an
accessor that interprets this Agreement amount as a multiplier would charge the
wrong amount. Terms design D2 needs an explicit reconciliation before migration.

The registry merge carries top-level rates and retained seller publication
proof. Those authority decisions stand; this checkpoint does not substitute a
current listing for accepted recovery evidence.

## Reproduce

Run from a fresh checkout of `open-ended-terms`; no service, identity, secret,
seeded database or inherited deployment selector is required. These are existing
tests, not a new permanent acceptance suite.

```sh
make dist-ci
(cd core && python3 ../scripts/uv_project.py reinit && \
  uv run --frozen --no-sync pytest tests/unit/test_rate_helpers.py \
  tests/unit/test_settlement_options.py -q)
(cd domains/vms/storefront && make reinit && \
  ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' \
  uv run --frozen --no-sync pytest tests/unit/test_vm_multiplier.py \
  tests/integration/test_vm_multiplier.py -q)
```

Results on 2026-11-06: wheel build passed; core 21 passed; VM 8 passed.
Core warns about an unknown `asyncio_mode` setting; storefront configuration
warns that `agent_id` defaults to `root_agent`. Neither warning changed a result.
The VM integration file invokes the negotiation runtime against real SQLite;
it is library integration, not application/HTTP or deployed evidence.

## Repository checks

`make check-packaging` passed on the merged stack. The first
`make check-change CHANGE=negotiate-open-ended-compute-terms` failed only because
the proposal's promotion bullets did not name decision IDs. Commit `7cb03533e`
names the already planned D1–D8 destinations; no permanent behavior was promoted.
The change check then passed all 12 checks. Explicit pinned validation also
passed:

```sh
bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict
```

## Not observed

No hosted rate mandate, buyer selection flow, E2E stack, physical delivery or
billing stop was attempted. Tasks 1.2 onward and closeout remain unimplemented.
The next execution point is task 1.1 after the price-carrier decision is recorded.
