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

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Whole-host access acts on a derived lease account | `openspec/specs/physical-provisioning/spec.md` |
| Whole-host access returns the tenant-facing endpoint | `openspec/specs/physical-provisioning/spec.md` |
| Whole-host storefront chain configuration is rendered or absent | `openspec/specs/deployment-state/spec.md` |
| Provisioning host trust is pinned by deployment, not by image configuration | `openspec/specs/deployment-state/spec.md` |
| A domain buyer drives every rail its seller publishes | `openspec/specs/settlement-configuration/spec.md` |
| Negotiation is not purchase | `openspec/specs/settlement-configuration/spec.md` |
| Acceptance validates the negotiated total, not the advertised rate | `openspec/specs/settlement-configuration/spec.md` |
| A run is bound to its authenticated discovery, and beginning is not delivery | `openspec/specs/settlement-configuration/spec.md` |

Not promoted, and not implemented: host-side ownership records, tenant path
isolation, destructive reclaim policies, and end-to-end demonstration evidence.
