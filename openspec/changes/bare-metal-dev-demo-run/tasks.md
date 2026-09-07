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

Not promoted, and not implemented: host-side ownership records, tenant path
isolation, destructive reclaim policies, and end-to-end demonstration evidence.
