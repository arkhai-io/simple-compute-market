# Tasks — publish indicative listing rates

Implemented. Closeout remains: archival, which applies the spec deltas, and the
index and roadmap links that follow it (8.6, 8.9). Test levels follow
`docs/development/TESTING.md`: integration means the real app, a real database,
wired DI, and the canonical typed client; real-database tests below that level
are supplemental.

## 1. Settled decisions confirmed against code

- [x] 1.1 `PER_UNIT_SECONDS` is exactly `{"hour": 3600}`.
- [x] 1.2 `SettlementPublicationClause` carries an opaque trimmed `asset` and
      positive decimal-text `rate`; the asking-rate amount reuses its grammar.
- [x] 1.3 Settlement asset filters are equality-only.
- [x] 1.4 `contact-exchange.v1` options are rateless.
- [x] 1.5 Overrides replace lists whole; listing comparison refreshes term
      fields in place.
- [x] 1.6 The registry validates the full listing shape only in its dry run.

## 2. Generic registry prerequisite

Names no rate, asset, period, or compute field.

- [x] 2.1 `decimal_text` value type (`core/registry/src/core_registry/api/filter_spec.py`).
- [x] 2.1a Bounds parse to finite `Decimal` (`filter_eval.py`); `number` unchanged.
- [x] 2.1b Resolved listing values coerce from finite decimal text; anything
      else reads as no value, so `on_missing` decides.
- [x] 2.1c The registry client maps `decimal_text` to `QueryValueType.DECIMAL`.
- [x] 2.1d An unimplemented value type is still refused at spec load.
- [x] 2.2 `FilterDecl.requires`.
- [x] 2.2a Spec load refuses an undeclared, self-referencing, or cyclic
      co-requirement.
- [x] 2.2b The registry refuses a filter supplied without its co-requirements;
      one-directional.
- [x] 2.2c `market_core.query_dsl`: `FieldDescriptor.requires` and
      `missing_co_requirement`, positioned at the comparison; help output names
      co-requirements only when declared.
- [x] 2.2d The registry client resolves `requires` from filter names to query
      names.
- [x] 2.2e An empty `requires` is omitted from the served body and etag input
      (`_dump_filter`), pinned by a literal-digest test.

## 3. Declaration, resolution, and publication

- [x] 3.1 `kit/resource-pools/src/market_resource_pools/asking_rates.py`: the `asking_rates` tag, its
      structural check, and its raw reader (`NOT_STATED` for a missing key).
- [x] 3.1a Both pool-write surfaces apply the check.
- [x] 3.2 `AskingRate`; accepted periods are a local constant held equal to
      `PER_UNIT_SECONDS` by `domains/vms/storefront/tests/unit/test_asking_rate_period_parity.py`.
- [x] 3.3 `kit/pool-overrides`: `asking_rates` on the record (an empty list
      accepted), the store, and an additive migration; each market's
      contribution judges the entries.
- [x] 3.4 One resolver, `resolve_asking_rates`, generic over a domain's shape
      digest and vocabulary; VM binds it (`resolve_vm_asking_rates`), and
      derivation gives each candidate its own shape's rate and reports priced
      shapes no listing has.
- [x] 3.5 An unreadable or stated-null declaration or override holds the pool.
- [x] 3.6 VM publishes `listing_resource.asking_rate`; `ComputeResource`
      declares it and omits it when unset.
- [x] 3.7 `asking_rate` is a term field in VM listing comparison.
- [x] 3.8 Bare metal: domain-owned `bare_metal_shape_digest` and
      `bare_metal_shape_problems`; site reading resolves rates and holds an
      unreadable pool (`asking_rates_unreadable`); candidates carry their rate;
      `BareMetalListing` declares it; it is a term field; unpublished priced
      shapes are reported.
- [x] 3.9 No settlement or negotiation path reads the rate (7.11).

## 3b. Bare metal joins the site-scoped override store

- [x] 3b.1 `kit/pool-overrides`: framework-free `PoolOverrideRouteService`
      (`route_service.py`); after-write effects optional. Unit tests:
      `tests/unit/test_route_service.py`. Version unchanged (`design.md`).
- [x] 3b.2 VM's override handlers bind the route service; VM's override,
      client-parity, CLI, and admin tests pass unchanged.
- [x] 3b.3 Bare-metal storefront: `pool_overrides.py` (terms, contribution,
      reader, accepted-generation record); migration
      `bare-metal-storefront-0011-accepted-site-generations`; publication reads
      overrides once per run, records each accepted generation, applies a pool's
      override, and holds an unreadable one (`pool_override_unreadable`) or a
      bound conflict (`pool_override_terms_conflict`); the runtime composes the
      service; three admin routes authenticated by the kit's contract; status
      reports `pool_overrides`; the kit is a declared dependency.
- [x] 3b.4 `bare-metal-storefront pool-override` (`pool_override_cli.py`), signing
      with `storefront_signer_from_environment`. Tests:
      `tests/test_pool_override_cli.py`, and `tests/test_runtime_environment.py`
      building the runtime from its environment.
- [x] 3b.5 `tests/test_pool_overrides_api.py`, through the typed client: round
      trip, refusals storing nothing, a missing pool, all four override states,
      a non-administrator refused, and a minimum above the configured maximum.
      `tests/test_publication_cycle.py`: generation recording, override refresh,
      unreadable and conflicting overrides held.
- [x] 3b.6 `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py`
      stages 05b–05d (passed; see 8.8). An override's clauses reaching a listing are
      not asserted: the lane's configured clauses are not visible to the
      scenario.

## 4. Filters and the compute schema

- [x] 4.0 `asking_rate` names the upper bound, `asking_rate_min` the lower.
- [x] 4.1 Four filters in `core/registry/filter-spec.yaml`, with the naming rule
      in a comment.
- [x] 4.1a All `on_missing: fail`.
- [x] 4.1b Both bounds co-require asset and period.
- [x] 4.1c Asset and period match by equality; nothing is converted.
- [x] 4.2 `listing_resource.asking_rate` in the compute `listing_shape`.
- [x] 4.3 Only the compute specification's etag changes.

## 5. Specification

- [x] 5.1 `specs/registry-discovery/spec.md`: finite exact decimals and
      co-requirements.
- [x] 5.1a Same delta: the bound-naming rule.
- [x] 5.2 Same delta: the compute schema's rate and filters.
- [x] 5.3 `specs/storefront-publication/spec.md`: declaration, precedence,
      fail-closed holds including stated null, listing attribute, in-place
      refresh, and bare metal's overrides with effective bounds.
- [x] 5.4 `specs/resource-pool-management/spec.md`: the policy tag, its period
      in the settlement unit grammar.
- [x] 5.5 `openspec/specs/storefront-publication/architecture.md`, "Asking rates".
- [x] 5.6 Same companion, "Storefront pool overrides";
      `docs/development/DEPLOYMENT_AND_CONFIG.md`, "Storefront listing shapes and
      pool overrides"; `docs/development/ARCHITECTURE.md`, the pool-override kit.

## 6. Cross-change reconciliation

- [x] 6.1 `capacity-shape-pricing` names the negotiation-side rate only.
- [x] 6.2 `docs/development/ROADMAP.md` Goal 7 corrected, then closed for rate
      comparison (8.5).
- [x] 6.3 The change index reflects this change's state (8.6).

## 7. Validation

- [x] 7.1 **Unit.** `core/registry/tests/unit/test_filter_eval.py`,
      `test_filter_spec.py`: exact and finite decimal comparison.
- [x] 7.2 **Unit.** Co-requirements: the same two files and
      `core/tests/unit/test_query_dsl.py`.
- [x] 7.3 **Unit.** `kit/resource-pools/tests/unit/test_asking_rates.py`:
      structure, resolution, stated null.
- [x] 7.4 **Integration.** `core/registry/tests/integration/test_asking_rate_filter.py`:
      exact comparison, both bounds, asset exclusion, round trip.
- [x] 7.5 **Integration.** Same file: the registry refuses a bound without its
      co-requirements.
- [x] 7.6 **Integration** (library). `kit/resource-pools/tests/integration/test_resource_pool_service.py`:
      every pool-write surface.
- [x] 7.7 **Integration.** `domains/vms/storefront/tests/integration/test_pool_overrides_api.py`
      and `domains/bare_metal/storefront/tests/test_http_publication_rates.py`:
      declared and override rates reach the listing a buyer reads.
- [x] 7.8 **Integration.** `test_pool_overrides_api.py`: an empty override
      withholds a declared rate; rates a market cannot read are refused at the
      write.
- [x] 7.9 **Integration.** Both domains' app tests: a rate change and an empty
      override refresh the same listing.
- [x] 7.10 **Integration.** Both apps hold rather than publish or fail: VM on an
      unreadable declaration, bare metal on an unreadable rate and on a bound
      conflict. Supplemental edge matrix:
      `domains/vms/storefront/tests/integration/test_reconciler_projection.py`
      and `domains/bare_metal/storefront/tests/test_publication_cycle.py`.
- [x] 7.11 **Integration.** `test_pool_overrides_api.py`: asking and settlement
      rates publish independently.
- [x] 7.12 **Integration.** `test_asking_rate_filter.py`: a listing whose only
      option is a rateless introduction is found by its asking rate.
- [x] 7.13 **Transferred** to `compose-contact-exchange-across-compute` 6.4 (VM)
      and `unbacked-bare-metal-listings` (bare metal); see `design.md`.
- [x] 7.14 **Integration.** `test_pool_overrides_api.py`
      (`test_each_seller_sites_rate_reaches_only_its_own_listing`): multi-seller
      provenance; see `design.md`.

## 7b. Review findings

- [x] 7b.1 Finite decimals on both sides (2.1a, 2.1b; 7.1).
- [x] 7b.2 A stated null holds (3.1, 3.5); bare-metal `terms` that are not a
      mapping are unreadable. The store's `NULL`/`"null"` distinction is
      unchanged (`design.md`).
- [x] 7b.3 Bare-metal bounds by overlay precedence, checked at write and
      publication (3b.3, 3b.5; `tests/test_pool_override_terms.py`).
- [x] 7b.4 Test levels relabelled; app integration added (7.7–7.10).
- [x] 7b.5 Stale test comment corrected.
- [x] 7b.6 Precedence placement kept, with a revisit trigger (`design.md`).
- [x] 7b.7 Scope verified against the reviewer's snapshot: this change touched
      no file under `pools-9-retire-local-physical-authority` or
      `remove-dead-storefront-physical-surfaces`, nor the e2e-log utility,
      `Makefile`, or `docs/development/TESTING.md`.
- [x] 7b.8 Pre-closeout: app-level hold evidence, the touched module header,
      the receiving proposal, and the exported sentinel.
- [x] 7b.9 Interaction with `store-registry-listings-as-published` recorded
      (`design.md`).

## 8. Closeout

- [x] 8.1 **Comment hygiene.** `make check-comment-hygiene` passes; a direct read
      of the touched production files found no history narrated.
- [x] 8.2 **Import placement.** Two local imports kept, each for a verified
      reason: the resource-pool kit is an optional extra of `arkhai-vms-listings`,
      and the bare-metal command loads its client stack only when it runs. Test
      imports moved to module level.
- [x] 8.3 **Documentation compliance.** Normative behaviour in the three deltas;
      rationale in the companion `architecture.md`; cross-system facts in
      `ARCHITECTURE.md`; operator rules in `DEPLOYMENT_AND_CONFIG.md`.
- [x] 8.4 **Narrative compression.** This file is reduced to behaviour,
      evidence, deferrals, and destinations; rationale is in `design.md`.
- [x] 8.5 **Roadmap currency.** Goal 7 describes published, filterable rates and
      its rate-comparison gap row is closed; the goal stays open on its
      unbacked-supply rows.
- [ ] 8.6 **Campaign index currency.** Current, except at archival: the row
      becomes archived with its link, and the roadmap's closed-gap link follows.
- [x] 8.7 **Documentation citations.**
      `make check-doc-citations CHANGE=publish-indicative-listing-rates` passes.
- [x] 8.8 **End-to-end pipeline.** Run 36841346733, including every fix: VM 126
      passed with its 2 existing skips; bare metal all 11 publication stages,
      05b–05d covering a declared rate, a storefront override, and its removal;
      no tracebacks. `make test` passed in the reviewer's environment, covering
      the VM chain-dependent tests and `rl` extra this environment cannot run.
- [ ] 8.9 **Promotion.** The record below lists every destination; the spec
      deltas are applied at archival.
- [x] 8.10 **Packaging.** `make check-packaging` passes on the relocked tree.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| An exact-decimal declared value type whose comparison never passes through binary floating point | `openspec/specs/registry-discovery/spec.md` |
| Declarative filter co-requirements, resolved from the specification by registry and buyer alike | `openspec/specs/registry-discovery/spec.md` |
| An undeclared co-requirement leaves a specification's serialization and etag unchanged | `openspec/specs/registry-discovery/spec.md` |
| The compute schema's asking-rate field, validated by the registry only in the dry run | `openspec/specs/registry-discovery/spec.md` |
| Rate filters match the period and the asset rather than normalizing across them; a listing publishing no rate is excluded | `openspec/specs/registry-discovery/spec.md` |
| A bound filter's bare query name follows the field's preferred search direction (lower bound for capacity-shaped dimensions, upper bound for cost-shaped ones), not bound position | `openspec/specs/registry-discovery/spec.md` |
| The asking rate is declared per shape; override, then pool declaration, then none; no configuration default | `openspec/specs/storefront-publication/spec.md` |
| A malformed asking-rate declaration holds its pool | `openspec/specs/storefront-publication/spec.md` |
| The asking rate is a listing attribute and independent of any mechanism rate | `openspec/specs/storefront-publication/spec.md` |
| An asking-rate change refreshes the listing in place | `openspec/specs/storefront-publication/spec.md` |
| The `asking_rates` policy tag and its structural validation | `openspec/specs/resource-pool-management/spec.md` |
| Why the rate is keyed by shape, why the storefront has final authority, why a site range is deferred | `openspec/specs/storefront-publication/architecture.md` |
| Bare metal's override vocabulary, status source, and shared route service | `openspec/specs/storefront-publication/architecture.md` and `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Goal 7 current state and gap ownership | `docs/development/ROADMAP.md` (Goal 7 current state; rate-comparison gap row closed) |
| The pool-override kit's framework-free route service, bound by each storefront | `docs/development/ARCHITECTURE.md` (pool-override kit) and `openspec/specs/storefront-publication/architecture.md` ("Storefront pool overrides") |
| One asking-rate resolver in `kit/resource-pools`, generic over each domain's shape digest and vocabulary, because bare metal cannot import VM | `openspec/specs/storefront-publication/architecture.md` |
| A market's override contribution judges override rates, so the override kit gains no resource-pool dependency | `openspec/specs/storefront-publication/architecture.md` ("Storefront pool overrides") |
| Accepted periods are a local contract held equal to `PER_UNIT_SECONDS` by a parity test, not imported | `openspec/specs/storefront-publication/architecture.md` |
| An unpriced listing publishes no `asking_rate` field rather than null, so a withdrawn rate refreshes in place | `openspec/specs/storefront-publication/spec.md` (delta: "A shape is priced nowhere") |
| The bare-metal command signs as the storefront's own identity from the server's inputs | `docs/development/DEPLOYMENT_AND_CONFIG.md` ("Storefront listing shapes and pool overrides") |
| `kit/pool-overrides` keeps its version: backward-compatible additions, unchanged requirements | Temporary: change history only |
| The decimal value type is finite: a non-finite bound is refused, a non-finite listing value is no value | `openspec/specs/registry-discovery/spec.md` |
| A stated `null` asking-rate declaration is malformed and holds the pool | `openspec/specs/storefront-publication/spec.md` |
| Bare-metal duration bounds replace their configured counterparts independently; the effective pair is checked at write and at publication | `openspec/specs/storefront-publication/spec.md`, and the operator rule in `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Storefront precedence stays beside the pool declaration's parser, with its revisit trigger | `openspec/specs/storefront-publication/architecture.md` |
