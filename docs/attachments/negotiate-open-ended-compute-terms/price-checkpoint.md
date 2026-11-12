# Partial quote and retention checkpoint

Observed 2026-11-07, starting at `aae6852e5` on the stacked terms branch.
This packet records the first slice of task 2.1, not a completed terms feature.
The existing draft PR is #351, stacked on #349 and #350. D2a remains monetary.

## Before and after

Before: core exposed no unit-bearing accepted-price accessor. Both VM buyer
recording paths retained only listing identity/resource/rates/options/escrows;
the seller publication's signed bytes, authenticated request and provenance were
not in that pricing record.

After:

- Core `agreed_price` returns immutable `AgreedPrice` with amount, asset and unit.
  Selected options require an explicit mechanism-owned `PriceBasis` projection.
  Recurring bases carry period text and its positive whole-second length; totals
  carry neither. Core does not parse any mechanism's settlement period.
- The accessor never re-multiplies accepted money. It checks a supplied retained
  listing's identity and exact selected option. It does not authenticate that
  listing, verify a transcript multiplier or authorize a mandate by itself.
- For rate-structured listings, both VM recording paths deep-copy seller publication/request, updates, trust and
  provenance together with their existing pricing fields. They do not backfill
  legacy logs from current listings. Retention is not verification enforcement.
- The temporary `price_probe.py` calls the actual VM `accepted_listing_record`
  hook with an installed payments selection, JSON-round-trips its record and
  verifies the retained seller signature historically with explicit trust and
  `listing.publish` context. Mutating the source listing afterward leaves the
  retained proof and pricing unchanged. The fixture publication is signed in
  process; this probe does not publish it to a deployed registry.
- The same diagnostic drives prepaid recovery, no-option absolute fallback,
  selected-option/projection refusal, and injected PT15M/PT1M quote labels. The
  recurring amounts are fixture inputs, not evidence of pre-acceptance recurring
  derivation or an implemented hosted rate adapter.

The first diagnostic run found that the existing generic decimal-string parser
accepts integers above uint256. The new quote carrier now explicitly refuses
those amounts. Its replay passes. The generic parser and old rate helpers were
not changed. No permanent acceptance tests were added or assertions weakened.

## Reproducible first-use setup

The owned target is an invocation-local Python process in the driver's checkout,
not a deployed stack or shared database. It uses the committed diagnostic and
existing codec probe with deterministic development signer/account fixtures.
No secrets, wallet approval, browser, network listener, seeded external state or
inherited deployment selector is needed. It leaves no service running.

From a fresh checkout at this checkpoint:

```sh
make dist-ci
(cd domains/vms/buyer && make reinit && \
  uv run --frozen --no-sync python \
  ../../../openspec/changes/archive/2026-11-12-negotiate-open-ended-compute-terms/price_probe.py)
```

This command was opened/executed at the changed surface itself. Expected output
includes four existing codec PASS lines, followed by:

```text
VM acceptance record -> JSON recovery -> historical seller proof; source edits isolated: PASS
monetary prepaid/recovery/fallback; explicit projection and snapshot correspondence refusals: PASS
injected sub-hour period labels preserve accepted money; inconsistent basis/overflow refused: PASS
LIMIT: no production billing projection wiring, transcript-price verification, reader migration or rate execution
```

## Existing regression checks

After building wheels, run:

```sh
(cd core && python3 ../scripts/uv_project.py reinit && \
  uv run --frozen --no-sync pytest tests/unit/test_rate_helpers.py \
  tests/unit/test_settlement_options.py -q && \
  uv run --frozen --no-sync mypy src)
(cd domains/vms/buyer && make reinit && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync pytest tests/test_negotiate_stage_dispatch.py \
  tests/test_buy_orchestrator.py tests/test_buyer_client.py \
  tests/test_buyer_client_resume.py -q)
(cd domains/vms/buyer && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync pytest tests/test_buy_resume_cli.py \
  tests/test_resume_helpers.py tests/test_negotiate_stage_dispatch.py -q)
(cd domains/vms/storefront && make reinit && \
  ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' \
  uv run --frozen --no-sync pytest tests/unit/test_vm_multiplier.py \
  tests/integration/test_vm_multiplier.py -q)
```

Results: core **21 passed**; core mypy **9 source files clean**; VM buyer **45
passed** and **30 passed** (the latter repeats stage-dispatch coverage); VM
multiplier **8 passed**. Core reports the existing unrecognized `asyncio_mode`
warning; the storefront reports its existing default-agent-id warning. The VM
multiplier integration invokes the runtime with real SQLite, not HTTP or a
running storefront. Buyer suites use their existing controlled seams.

Repository checks passed:

```sh
make check-packaging
make check-change CHANGE=negotiate-open-ended-compute-terms
bunx @fission-ai/openspec@1.14.0 validate negotiate-open-ended-compute-terms --strict
```

Packaging rebuilt all wheels and checked locks, Python selection, project layout
and architecture. The change check included comment hygiene, citations, task and
change/spec indexes, strict validation, decision destinations, history wording,
version steps, local imports and the capability index. No hook bypass was used.

## Limits and restart

Task 2.1 remains unchecked. Its next steps are production billing projection
wiring, seller-proof and transcript-price verification before recovery/mandate
reads, recurring amount derivation, both-domain consumer migration, and the
fail-closed direct-read guard. Then resume 2.2 onward in order. The accessor's
optional listing argument is a retained acceptance snapshot, never permission to
read current rates for a committed deal.

No deployed E2E, hosted rate execution, actual buyer checkout, delivery or billing
stop was attempted. No E2E failure or readiness result is claimed. Full final
validation, post-review promotion, archival, rebase and ready-for-review status
remain for later checkpoints. The draft PR must not be marked ready on this packet.
