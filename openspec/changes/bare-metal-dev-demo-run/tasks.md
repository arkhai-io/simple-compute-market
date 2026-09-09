## 1. On the demonstration path

- [x] 1.1 Account admission before grant and reclaim dispatch, with tests.
- [x] 1.2 Exact settlement-identity derivation, pinned against the previous
      derivation so existing leases keep resolving.
- [x] 1.3 SSH probe: only the lease key, no default identity fallback, no
      agent, no operator SSH configuration, host-key checking kept on.
- [x] 1.4 Post-teardown classification separating an authentication refusal
      from an unreachable host, a local credential error, and a remote command
      failure.
- [x] 1.5 Listing envelope read as the buyer CLI actually emits it.
- [x] 1.6 Optional explicit buyer subprocess environment, default unchanged.
- [x] 1.7 Chart renders chain and signing-key configuration under Alkahest,
      and nothing when it is disabled.
- [x] 1.8 Bare-metal provisioning adapter test target and lock repair.
- [x] 1.9 Optional provisioning host-key pinning: an operator-managed
      `known_hosts` Secret mounted read-only together with the strict Ansible
      environment, a render refusal when the Secret is unnamed, and image
      defaults untouched when it is disabled. Chart render test included.
      Promoted to `openspec/specs/deployment-state/spec.md`.

## 2. Not done, deliberately

- [ ] 2.1 Host-side ownership records and path hardening. Out of scope; an
      operator preflight checks the one reserved host instead.
- [ ] 2.2 Destructive reclaim policies. The demonstration uses exact-key-only
      removal; existing policy behaviour is untouched.
- [ ] 2.3 Bound management and publication operations. The scenario still takes
      operator-supplied commands. Their exact target, credential role and
      read-back are reviewed out of band for this run.
- [ ] 2.4 Controlled SSH-server integration coverage.

## 3. Closeout

- [x] 3.1 `make check-comment-hygiene`.
- [x] 3.2 Import placement. The imports this change added are module level.
      Three function-local imports were added inside tests
      (`test_host_service.py`, `test_lease_accounts.py`) and are deliberate:
      they keep an ORM model and a domain helper out of collection-time import
      for modules that other tests import cheaply. No repository-wide cleanup
      was performed.
- [x] 3.3 Documentation placement re-checked against `openspec/README.md`.
      Three durable behaviours are now named in `proposal.md` with their
      destinations; scaffolding is not promoted.
- [x] 3.4 Narrative compression: these notes state final behaviour and
      deferred work only.
- [x] 3.5 Roadmap currency. Disposition: **no roadmap edit owed.** This change
      hardens admission and persists an endpoint within existing capabilities;
      it moves no goal. Recorded explicitly rather than omitted.
- [x] 3.6 Campaign index row added to `openspec/changes/README.md`.
- [x] 3.7 Promotion complete for the three implemented behaviours:
      whole-host access acts on a derived lease account, and returns the
      tenant-facing endpoint, in
      `openspec/specs/physical-provisioning/spec.md`; whole-host storefront
      chain configuration in `openspec/specs/deployment-state/spec.md`.
      Deliberately not promoted: host-side ownership, hostile-tenant
      isolation, destructive reclaim policies, and any claim that the
      end-to-end demonstration has run.

## 4. Buyer crypto rail

- [x] 4.1 Buyer resolves the rail from the selected option; hosted path
      unchanged. `domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/
      settlement_composition.py`, `cli.py`.
- [x] 4.2 Escrow expiry is buyer-chosen (`--escrow-expiration-seconds`); the
      advertised `AcceptedEscrow` carries none.
- [x] 4.3 Acceptance callback verifies the escrow target, chain, funded token
      and collection conditions it displaces in `core_buyer`, and does not
      restate the shared principal/amount/expiry/asset checks.
- [x] 4.4 Buyer transport gains the two wire paths the server already served
      and nothing called: `POST /api/v1/settle/{escrow_uid}` and
      `POST /api/v1/fulfillments/begin`.
- [x] 4.5 `bare-metal fund` creates the accepted escrow through shared
      `market_alkahest` codecs, has it verified, and begins fulfillment;
      records the escrow before verification and adopts an existing one.
- [x] 4.6 Acceptance scenario runs the rail's settlement command between
      negotiation and the delivery view; `BARE_METAL.SETTLE_COMMAND`.
- [x] 4.7 Promotion: buyer rail dispatch, displaced-check ownership, and
      negotiation-is-not-purchase in
      `openspec/specs/settlement-configuration/spec.md`.

- [x] 4.8 Scenario argv corrected to the real parser (`--run-id`, no `--json`,
      `teardown`/`status` as separate commands) and tested through the real
      Typer app; `status` no longer requires a hosted settlement reference.
- [x] 4.9 Chain address configuration read from the field the SDK defines, and
      `fund_accepted_obligation` exercised with only the chain call controlled.
- [x] 4.10 Acceptance re-derives the whole obligation with the shared
      materialization instead of comparing an enumerated field list; nested
      amount/arbiter/demand substitutions are refused. Physical terms are left
      to the shared client, which already validates them.
- [x] 4.11 Rerun adopts the escrow recorded in the run log and refuses a payer
      address the funding key does not control.

- [x] 4.12 Acceptance re-derives from the accepted obligation's negotiated
      absolute total rather than the advertised hourly rate, so a rental
      shorter than one rate unit is no longer refused before funding. No
      scaling or rounding was added to the buyer.
- [x] 4.13 Scenario asserts the run-log events this buyer emits
      (`run_started`, `agreement_accepted`, `run_ended`) and proves discovery
      through the opening record's registry, authority, listing, storefront and
      publisher principals. Offline coverage produces those events with the
      real `RunLog` instead of naming them by hand.
- [x] 4.14 Scenario reads the runtime's real projections: the `result` receipt
      envelope, `fulfillment.state` from `status`, a bounded wait to the active
      state before delivery and access are read, and the same wait for the
      teardown terminal state.
- [x] 4.15 The lease session's own privilege level is captured over the granted
      SSH session and judged before teardown is requested: non-zero uid, no
      privileged supplementary group, no sudo grant. An incomplete answer
      fails rather than defaulting to unprivileged.
- [x] 4.16 The buyer process receives the domain configuration path and, on the
      crypto rail only, one named funding key; the operator's environment is
      not inherited and no secret is passed in argv. The generated profile
      carries the selected chain for the shared loader.
- [x] 4.17 Promotion: negotiated total, run-log/discovery binding and
      begin-is-not-delivery in
      `openspec/specs/settlement-configuration/spec.md`.

Not implemented, and not claimed: any live crypto run, buyer reclaim of an
expired escrow, and hosted-lane live qualification. Host-side proof that the
lease account was created unprivileged is the executing authority's, not this
buyer's; the scenario evidences only what the granted session reports.

## 5. Seller crypto acceptance

- [x] 5.1 Alkahest owns its accepted obligation: `create_alkahest_registration`
      supplies an `accepted_obligation_builder` that materializes through the
      shared proposal → plan seams the buyer re-derives from, so the funded
      `obligation_data` is one derivation, not two.
      `kit/alkahest/src/market_alkahest/settlement_config.py`.
- [x] 5.2 The seller's injected settlement resources travel with the acceptance
      context, so a chain-materializing mechanism accepts against the same
      address book and payout wallet it published from.
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/
      settlement_composition.py`.
- [x] 5.3 An option that advertises no physical facts composes its physical
      terms from the seller's own trusted listing and binding; the hosted
      envelope stays byte-identical to the one `validate_accepted_hosted_plan`
      reconstructs. A selection whose expiry nothing else pins is refused once
      it has passed. `negotiation_service.py`.
- [x] 5.4 Regression at the seller and mechanism seams: real publication builder
      → buyer proposal helper and mechanism validator → composed acceptance,
      whole-obligation comparison, whole physical envelope compared to an
      independently written expectation, and no-write negatives. This covers the
      mechanism validator and the seller's composition; it does not by itself
      exercise the buyer client's own serializer or its outer acceptance checks.
      `domains/bare_metal/storefront/tests/test_alkahest_exact_selection.py`,
      `e2e-tests/tests/unit/test_bare_metal_alkahest_selection_contract.py`,
      `domains/bare_metal/storefront/tests/test_http_negotiation.py`.
- [x] 5.5 Round trip through the production buyer client: its request signing and
      serialization, the composed storefront app, its signed reply, the client's
      reply parser and acceptance validation, and the domain's accepted-plan
      callback. Only the socket is substituted. Refusals cover expiry, listing
      bounds, unadvertised access, another listing's option, buyer-supplied
      physical identities and an untrusted seller principal.
      `e2e-tests/tests/unit/test_bare_metal_alkahest_client_roundtrip.py`.
- [x] 5.6 Promotion: mechanism-owned accepted obligation and acceptance context in
      `openspec/specs/settlement-configuration/spec.md`; trusted physical
      composition, selection expiry and the whole-envelope comparison in
      `openspec/specs/negotiation-protocol/spec.md`.
- [x] 5.7 Closeout: comment hygiene and import placement checked; sqlite3 is
      module-level in the round-trip test. The accepted-obligation builder keeps
      proposal/plan/schema imports lazy so registration does not eagerly load
      acceptance-only materialization; clause publication retains its documented
      lazy chain/token imports. Every repository path cited by the two edited
      permanent specifications resolves on this branch, and
      the campaign index row from 3.6 still describes this change. Disposition on
      the roadmap: **no edit owed** — this completes an advertised rail's
      acceptance inside existing capabilities and moves no goal. Typing: no mypy
      or ruff target is configured for these packages, so none was run.

## 6. Refreshing a served listing after a settlement configuration change

- [x] 6.1 `bare-metal-storefront publish --refresh-listing-id` names one tracked
      open listing to republish under its existing identifier. Without it the
      round still skips every open listing.
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py`,
      `.../publication_cli.py`.
- [x] 6.2 The refresh reuses the round's own payload construction and the
      same-identifier publication callback, and the runner reaches the candidate
      because the round's skip set is narrowed by exactly the refreshed
      derivation key.
      `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py`,
      `.../storefront_adapter.py`,
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`.
- [x] 6.3 A target that is untracked, not locally open, or absent from the
      current available candidates is refused before any write. Refresh
      publishes to the registry before replacing local terms, so a failed
      publication leaves the locally persisted terms unchanged and the same
      refresh is retryable. The registry may already have accepted the changed
      terms when the failure is ambiguous; nothing here rolls a remote write
      back or makes the two stores atomic.
- [x] 6.4 Regression at the real command, adapter and CLI seams over a temporary
      SQLite database with no network:
      `domains/bare_metal/storefront/tests/test_publication_refresh.py`.
- [x] 6.5 Promotion: refresh identity, ordering and refusal semantics in
      `openspec/specs/storefront-publication/spec.md`.

## 7. Settling an exactly selected agreement

- [x] 7.1 Settlement resolves the accepted obligation from the committed plan
      when the thread carries a selection envelope, and keeps the legacy escrow
      proposal path unchanged.
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_service.py`.
- [x] 7.2 The resolver binds the accepted plan back to the committed record —
      parties, obligation roles and principals, amount, asset, declared
      conditions, selected mechanism, option and listing, and both physical
      views (provision terms and the binding restating the host and access
      method) against the domain terms artifact — and refuses with a typed
      settlement error before any chain read or write. Numbers the opaque
      mechanism carriers hold are parsed inside that refusal, so a malformed or
      absent value is a refusal rather than an unhandled fault.
- [x] 7.3 The shared Alkahest verifier takes the accepted obligation payload and
      its accepted expiry as one explicit expected candidate, so an otherwise
      matching escrow with a different future deadline is refused. The pair is
      required in both directions — half of it is rejected at entry rather than
      leaving the expiry unpinned — and proposal materialization stays the
      default for every other caller.
      `kit/alkahest/src/market_alkahest/escrow_verification.py`.
- [x] 7.4 Regression: producer-shaped settlement over the real exact-selection
      negotiation with a mocked verifier, one parametrized case per accepted-record
      mismatch, plus a real-verifier expiry regression with only codec and chain
      read substituted.
      `domains/bare_metal/storefront/tests/test_settlement_canonical_selection.py`,
      `kit/alkahest/tests/unit/test_escrow_verification_expected_terms.py`.
- [x] 7.5 Promotion: settlement verification authority, accepted-record
      consistency and the accepted-expiry boundary in
      `openspec/specs/settlement-configuration/spec.md`. The consistency
      contract is stated for the bare-metal Alkahest path that implements it;
      other domains and mechanisms, including plans carrying several
      obligations, are explicitly left unrestricted.

## 8. Reopening a tracked listing the registry still holds closed

- [x] 8.1 Republication transitions the registry record to open explicitly and
      confirms it by read-back before the round reports a publication; the
      publish body carries terms only, so a registry that preserves the status
      it holds would otherwise keep serving nothing.
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py`.
- [x] 8.2 The reopen path advances the local and tracking records only after
      that confirmation, matching the same-identifier refresh path, so a failed
      or ambiguous transition stays retryable under the same identifier and
      never creates a second listing.
      `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py`.
- [x] 8.3 Regression over a registry whose publish preserves an existing
      record's status, driven from the real listing request serializer: normal
      reopen, a record that stays closed, a rejected update, an unreadable
      confirmation, and local records left closed with a clean retry.
      `domains/bare_metal/storefront/tests/test_publication_reopen_registry.py`.
- [x] 8.4 Promotion: explicit reopen transition, read-back confirmation and
      ordering in `openspec/specs/storefront-publication/spec.md`.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Whole-host access acts on a derived lease account | `openspec/specs/physical-provisioning/spec.md` |
| Whole-host access returns the tenant-facing endpoint | `openspec/specs/physical-provisioning/spec.md` |
| Whole-host storefront chain configuration is rendered or absent | `openspec/specs/deployment-state/spec.md` |
| Whole-host publication optionally supplies a write-scoped registry credential and reports candidate failure through its exit status | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| A registry credential that cannot be sent as a header is refused before any request, and a candidate failure caused by a registry call is reported by type and, where available, HTTP status only | `openspec/specs/deployment-state/spec.md`; `docs/development/DEPLOYMENT_AND_CONFIG.md` |
| Provisioning host trust is pinned by deployment, not by image configuration | `openspec/specs/deployment-state/spec.md` |
| A domain buyer drives every rail its seller publishes | `openspec/specs/settlement-configuration/spec.md` |
| Negotiation is not purchase | `openspec/specs/settlement-configuration/spec.md` |
| Acceptance validates the negotiated total, not the advertised rate | `openspec/specs/settlement-configuration/spec.md` |
| A run is bound to its authenticated discovery, and beginning is not delivery | `openspec/specs/settlement-configuration/spec.md` |
| A mechanism builds its own accepted obligation through the same materialization the counterparty re-derives from, and receives the seller's settlement resources to do it | `openspec/specs/settlement-configuration/spec.md` |
| Physical terms for an option that advertises no physical facts come from the seller's trusted listing and binding, and the hosted physical envelope is compared whole | `openspec/specs/negotiation-protocol/spec.md` |
| A served listing is refreshed only when explicitly named, keeps its identifier, is validated against the tracked derivation and current availability, and publishes before local persistence so it stays retryable | `openspec/specs/storefront-publication/spec.md` |
| A bare-metal Alkahest agreement settles against its committed accepted obligation, bound whole to the rest of the committed record, and its accepted expiry is verified exactly | `openspec/specs/settlement-configuration/spec.md` |
| Reopening a tracked listing transitions the registry record to open explicitly, confirms it by read-back, and advances local records only afterwards | `openspec/specs/storefront-publication/spec.md` |

Not promoted, and not implemented: host-side ownership records, tenant path
isolation, destructive reclaim policies, and end-to-end demonstration evidence.

## 9. Publication consolidation design

- [x] 9.1 Reconcile the change scope in `proposal.md` with the implemented buyer
      crypto rail, seller acceptance, exact settlement, refresh, and reopen work.
- [x] 9.2 Record the current registry request/readback DTO, existing
      at-least-one multi-registry write success, per-registry result persistence,
      and remote-before-local ordering in `design.md` with source citations.
- [x] 9.3 Accept the proposed optional explicit publication status: omit it when
      unset, omit it for refresh, and send `open` for reopen. Record the later
      normative amendment without editing the permanent spec in this
      documentation-only submilestone.
- [x] 9.4 Reject configurable quorum scope. Preserve aggregate compatibility,
      expose partial results through the CLI's existing failed-candidate path,
      and restrict failed-target filtering to the exact same current operation
      intent. A later invocation addresses all intended targets; persisted old
      success is not a cross-operation retry token. Leave automatic retry
      scheduling as an open policy.
- [x] 9.5 Record settlement consolidation as required later scope while
      preserving mechanism ownership, accepted envelopes, hosted behavior,
      wallet-derived payout fallback, and the legacy settlement path.
- [x] 9.6 Record later qualification obligations: deterministic default
      development-environment alignment, the existing single E2E scenario,
      actual-host-only mutation, and the downstream VM consumer of the changed
      capacity-publication kit.

## 10. Publication implementation sequence — separately reviewed slices

- [x] 10.1 Add optional `status` to `ListingRequest`, omitting the key when
      unset, with registry-client serialization and registry integration
      coverage. Files:
      `core/registry-client/src/registry_client/models.py`,
      `core/registry-client/tests/test_listing_request.py`,
      `core/registry/tests/integration/test_listings.py`.
- [x] 10.2 Preserve `MultiRegistryClient`'s at-least-one aggregate write
      contract while returning the ordered per-registry outcomes through the
      publication result and supporting authenticated same-registry preflight
      and readback. Model confirmed, write-unconfirmed and known failed-write
      target results distinctly; transport-unknown and confirmation-mismatch
      results also require read-only reconfirmation rather than blind writes. Do
      not add quorum configuration or a generic intent journal. Files:
      `core/storefront/src/core_storefront/multi_registry_client.py`,
      `core/storefront/src/core_storefront/registry_publication.py`,
      `core/storefront/tests/unit/test_multi_registry_identity.py`,
      `core/storefront/tests/unit/test_registry_publication.py`.
- [x] 10.3 Deepen `PublicationRuntime`: distinct refresh/reopen operations,
      exact current-operation intent identity, typed canonical same-target
      confirmation, and one domain commit delegate invoked only after compatible
      aggregate success. Every new invocation addresses all intended targets;
      only an exact in-flight retry filters to known failed targets, while
      write-unconfirmed targets receive read-only reconfirmation. Refresh
      preflight writes only after a found eligible/open record or authenticated
      404; every other error is unknown/no-write. Reopen requests explicit
      `open`; refresh omits status. Treat a concurrent status change as a
      mismatch, not an atomicity guarantee. Files:
      `kit/capacity-publication/src/market_capacity_publication/publication.py`,
      `kit/capacity-publication/src/market_capacity_publication/__init__.py`,
      `kit/capacity-publication/tests/unit/test_publication.py`, and
      `kit/capacity-publication/tests/integration/test_publication_runtime.py`.
- [x] 10.3a Extract the prerequisite core reuse seam without changing kit or
      domain behavior: the factory-opening publication wrapper and an
      opened-client helper share request construction, fanout, callbacks, safe
      results, and receipt preservation. Optional status is absent from legacy
      factory kwargs unless explicit. Exact subsets reject duplicate,
      unconfigured, and empty targets before I/O and retain configured order.
      Expose only immutable public publisher and configured target
      authority/trust identity metadata. Files:
      `core/storefront/src/core_storefront/registry_publication.py`,
      `core/storefront/src/core_storefront/multi_registry_client.py`,
      `core/storefront/tests/unit/test_registry_publication.py`, and
      `core/storefront/tests/unit/test_multi_registry_identity.py`.
- [x] 10.3b Resolve the cross-consumer and concurrency boundary before changing
      the kit: retain VM and API-credit disabled-discovery policies through
      explicit adapters or record an accepted compatibility decision; use an
      immutable intent-bound operation/result passed explicitly to recovery or
      keep recovery within the executing call, never a shared mutable current
      intent slot. This task adds no automatic retry or journal framework.
- [x] 10.3c Regression cases: changed terms after an older success; reopen after
      a successful refresh; successful write with interrupted readback; retry of
      only a known failed subset inside the same intent; refresh preflight
      non-404 uncertainty with no write; concurrent status mismatch; durable
      receipt/event retry without repeated writes; exact candidate/payload
      identity; and partial bare-metal reopen recovery without a repeated local
      commit.
- [x] 10.4 Replace bare-metal CLI lifecycle sequencing with the kit interface;
      retain domain-owned candidate/binding validation and persistence. Refresh
      replaces terms without changing status/paused; reopen changes terms and
      clears paused only after confirmed remote success. Files:
      `domains/bare_metal/src/arkhai_bare_metal/storefront_publication.py`,
      `domains/bare_metal/src/arkhai_bare_metal/storefront_adapter.py`,
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication.py`,
      `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py`,
      `domains/bare_metal/storefront/pyproject.toml`,
      `domains/bare_metal/storefront/uv.lock`,
      `domains/bare_metal/storefront/Makefile`,
      `domains/bare_metal/tests/test_storefront_adapter.py`,
      `domains/bare_metal/tests/test_storefront_publication.py`,
      `domains/bare_metal/storefront/tests/test_publication.py`,
      `domains/bare_metal/storefront/tests/test_publication_refresh.py`, and
      `domains/bare_metal/storefront/tests/test_publication_reopen_registry.py`.
      Preserve the current JSON-before-exit behavior and the existing exit-1
      rule whenever `failed` contains a candidate. A partially converged
      candidate remains explicit in `failed`, even though shared aggregate
      consumers retain at-least-one success; do not introduce another exit code.
      Implementation used the existing storefront publication composition file
      rather than adding `storefront_adapter.py`; no separate adapter or root-
      domain test file was needed. VM and API-credit publication hooks now state
      their disabled-publication compatibility policy explicitly.
- [ ] 10.5 Rebuild the capacity-publication wheel and qualify focused package,
      registry, storefront, import-boundary, and typing checks. Qualify the
      downstream VM and API-credit consumers with the changed kit installed;
      disclose any unavailable check rather than substituting another suite.
- [x] 10.6 Promote the implemented lifecycle behavior to
      `openspec/specs/storefront-publication/spec.md` and the module/seam
      rationale to `openspec/specs/storefront-publication/architecture.md`.
      Update repository architecture, capability index, roadmap, and campaign
      index only where their current-state text requires it, and record every
      promotion in the design-promotion table.
- [ ] 10.7 Closeout: run `make check-comment-hygiene`; review imports touched by
      this milestone and move them to module level wherever safe; verify
      documentation placement and every cited path; compress completed-task
      narrative after moving durable rationale into `design.md`; check roadmap
      and campaign-index currency; complete promotion only after code review;
      run strict OpenSpec validation and `git diff --check`.

## 11. Required later settlement consolidation

- [ ] 11.1 Assess construction duplicated across the mechanism-owned accepted
      obligation builder, bare-metal negotiation composition, buyer acceptance,
      and seller settlement resolver. Name the smallest shared artifact/interface
      that removes duplicate construction while leaving physical validation in
      the domain.
- [ ] 11.2 Consolidate only after a separate reviewed plan. Preserve accepted
      Alkahest and hosted envelopes, wallet-derived seller payout fallback,
      exact accepted-expiry verification, and the legacy escrow-proposal path.
- [ ] 11.3 Close out the later settlement section with focused unit and
      integration coverage, permanent settlement/negotiation specification
      promotion, comment/import hygiene, narrative compression, roadmap and
      campaign-index checks, cross-reference validation, and post-review
      promotion.

## 12. Later E2E and actual-host qualification

- [ ] 12.1 Keep deterministic default development-environment values aligned
      across bare-metal and VM consumers and retain the existing bare-metal E2E
      scenario as the only cross-service harness.
- [ ] 12.2 Keep host/account mutation in the operator-controlled actual-host
      lane. Default package/E2E validation remains host-independent; no new
      actual-host script path is added merely to test publication consolidation.
- [ ] 12.3 Run the authorized actual-host campaign only after its own review
      gate, with exact source/artifact provenance, retained-resource declaration,
      and cleanup evidence.
- [ ] 12.4 Keep vLLM, model-cache lifecycle, GPU allocation/qualification, and
      GPU-specific host configuration deferred to a separately proposed change.
