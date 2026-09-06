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

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Whole-host access acts on a derived lease account | `openspec/specs/physical-provisioning/spec.md` |
| Whole-host access returns the tenant-facing endpoint | `openspec/specs/physical-provisioning/spec.md` |
| Whole-host storefront chain configuration is rendered or absent | `openspec/specs/deployment-state/spec.md` |

Not promoted, and not implemented: host-side ownership records, tenant path
isolation, destructive reclaim policies, and end-to-end demonstration evidence.
