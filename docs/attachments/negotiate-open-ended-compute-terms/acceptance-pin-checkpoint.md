# Signed-acceptance pricing pin checkpoint

Observed 2026-11-07, starting at `3972a9bc0`, for draft PR #351. This implements
task 2.1b after the projection slice, not parent 2.1 or the terms feature.

## Decision and surface

D2b is decided by webapp owner 2026-11-06, pending maintainer review. The
seller-signed acceptance binds the agreed multiplier and **the same rate-structure
digest D-e pins at opening**, computed over the as-published rates (D-b). The
buyer verifies that identity against the registry's retained seller-signed
publication (D-c). It never authenticates a seller-returned database snapshot.
`Agreement.listing_hash` keeps its database-listing meaning; its mismatch to the
published document remains a known maintainer follow-up.

- The shared VM digest helper preserves D-e's canonical sorted JSON algorithm.
  Opening, continuation counters and acceptance expose `rate_structure_digest`.
  Multiplier acceptance adds `pricing_pin` with `multiplier` as decimal text and
  that digest. The HTTP response models preserve both fields before signing.
- The core amount codec has optional domain validators on authenticated replies
  and accepted outcomes. VM supplies historical publication verification at the
  envelope's signed timestamp, `listing.publish` context, accepted publisher trust,
  listing identity, as-published pricing fields and exact selected option checks.
  It holds the pin to the transcript scalar and the monetary Agreement to exact
  unit-aware derivation before acceptance is observed or stage validation runs.
- VM recovery uses archived exact seller response and buyer request envelopes in
  the existing evidence store. It checks signatures/context, parties, Agreement
  bytes, published rate identity and transcript scalar, including the previous
  signed seller counter when a buyer accepts without a proposal. It verifies
  pricing before settlement-stage enrichment. Missing proof/pin fails closed for
  multiplier deals; no current listing repairs old evidence.
- The retained snapshot includes storefront URL and seller principal, needed by
  the existing VM listing-price parser. Rateless/exact selections do not acquire
  a fictitious multiplier. `Agreement.amount` and `listing_hash` are unchanged.

Remaining work belongs to 2.1c: migrate other readers, caps and mandate checks to
the accessor and integrate the direct-read guard. The proof gate is not a claim
that every existing price consumer has already migrated.

## First-use setup and replay

The owned target is an invocation-local Python process in the driver's checkout.
The committed diagnostics use deterministic development seller/buyer identities
and account fixtures, which must never be used on a public network. They create
their own publication, Agreement, signed requests/responses and temporary evidence
database. No secrets, ignored seed files, external login, resident server or
authority service is needed; temporary databases are removed when the process
exits. Both entry points below were personally executed.

From a fresh checkout:

```sh
make dist-ci
(cd domains/vms/buyer && make reinit && \
  uv run --frozen --no-sync python \
  ../../../openspec/changes/negotiate-open-ended-compute-terms/acceptance_pin_probe.py)
(cd domains/vms/storefront && make reinit && \
  ENABLE_EVENT_QUEUE=true AGENT_WALLET_ADDRESS='' uv run --frozen --no-sync python \
  ../../../openspec/changes/negotiate-open-ended-compute-terms/seller_pin_probe.py)
```

After the codec fixture's existing PASS lines, the first entry point reports:

```text
publication -> live codec pin -> archived signed acceptance recovery (total=5000000): PASS
publication -> live codec pin -> archived signed acceptance recovery (PT1M=41667): PASS
changed rate identity, proof context, inputs, multiplier, money and archived signature refused: PASS
LIMIT: PT1M projection is injected; no hosted rate materialization, approval, deployment or E2E
```

It exercises immediate and counter/accept recovery from the real file-backed
evidence store, reopened from disk. The period projection is injected through the
normal amount-codec seam; the installed payments adapter still refuses hosted
rates. This does not qualify a hosted recurring mandate or any authority I/O.

The second entry point observes the existing real-SQLite runtime scenarios without
adding collected tests or changing their assertions. Its additional invocation-local
observations report **3 acceptances** whose pins survive the HTTP carrier's JSON
round trip. The existing selected scenarios report **15 passed**. This is runtime
plus response-carrier evidence, not application HTTP or a deployed storefront.

## Existing regression evidence

After rebuilding wheels and reinitializing each environment:

```sh
(cd core/buyer && make reinit && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync pytest tests/unit -q)
(cd domains/vms/buyer && make reinit && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync pytest tests/test_negotiate_stage_dispatch.py \
  tests/test_buy_orchestrator.py tests/test_buyer_client.py \
  tests/test_buyer_client_resume.py tests/test_resume_helpers.py \
  tests/test_buy_resume_cli.py tests/test_introduction_cli.py -q)
(cd domains/vms/storefront && make reinit && ENABLE_EVENT_QUEUE=true \
  AGENT_WALLET_ADDRESS='' uv run --frozen --no-sync pytest \
  tests/unit/test_vm_multiplier.py tests/integration/test_vm_multiplier.py \
  tests/unit/test_sync_negotiation_seller_round_hook.py -q)
(cd kit/negotiation-runtime && make reinit && uv run --frozen --no-sync pytest tests -q)
(cd core/storefront && make reinit && \
  uv run --frozen --no-sync pytest tests/unit/test_negotiation_models.py -q)
(cd domains/bare_metal/storefront && make reinit && \
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  uv run --frozen --no-sync pytest tests/test_http_negotiation.py -q)
(cd domains/vms/buyer && uv run --frozen --no-sync --with mypy \
  mypy --follow-imports=silent --ignore-missing-imports \
  src/arkhai_vms_buyer/pricing_record.py \
  src/arkhai_vms_buyer/negotiation_amounts.py \
  src/arkhai_vms_buyer/deal_helpers.py)
```

Observed: core buyer **168 passed**; VM buyer **45 + 28 passed**; VM storefront
**19 passed**; generic negotiation runtime **62 passed**; core response models
**1 passed**; bare-metal signed HTTP negotiation regression **51 passed**.
Targeted mypy checked **3 files**, with imported code followed
silently and missing third-party stubs ignored; this is not whole-repository typing.

Core buyer emits an existing retired-identity serialization warning. The seller
diagnostic emits a default development agent-ID warning and a pytest import-rewrite
warning from embedding the existing suite. Neither is an acceptance failure.

Initial attempts used nonexistent buyer `tests/unit` paths and assumed mypy was
installed in the buyer's dev group. The corrected paths and explicit ephemeral
`--with mypy` invocation above pass. The first diagnostic exposed that the retained
subset omitted the storefront URL required by the listing parser; retention now
includes that and seller principal, and the complete replay passes.

`make check-packaging` and `make check-change CHANGE=negotiate-open-ended-compute-terms`
pass, including architecture, locks, comment hygiene, citations and pinned strict
OpenSpec validation. No permanent tests were added and no existing assertions were
weakened.

## Limits and restart

Parent 2.1 stays unchecked; resume at **2.1c**, then 2.2 onward in order. No deployed
E2E, live buyer checkout/approval, hosted recurring execution, billing stop,
independent implementation review, final rebase, promotion, archival or
ready-for-review state is claimed. No external resources were started.
