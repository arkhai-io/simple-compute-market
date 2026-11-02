# Servicing implementation-review repairs

## Revision and setup

Code revision: `4510feb50` (repair branch based on `be0b46aaf`).
This is a nonvisual library/API journey, not a deployed-domain or live-authority
qualification. No browser, external service, cloud target or credentials are
needed. Each example and test owns its temporary SQLite database. Authentication
uses public deterministic development principals and the vendored in-process
authority fixtures; none of these values may be used on a public network.

Reproduce the prepared first-use surface from a clean checkout:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist-ci
make -C kit/deal-servicing test typecheck first-use
make -C kit/arkhai-payments test
```

The first-use target directly opens the library story surfaces, including the
mounted FastAPI router driven through its signed typed client. It seeds and
cleans its own state. Wheelhouse/environment preparation completed successfully;
no resident server or machine-local seed state is part of the handoff.

## Observations

All servicing test paths below are relative to `kit/deal-servicing/tests/`.
Injected authorities prove SCM consumer behavior, not authority remedy algorithms.

| Claim | Action and observed result | Reproduction |
|---|---|---|
| S-F4: current read is not cached success | First failed payment/dispute reads, outages and verification rejections after success return their own outcome; recovery returns accepted. Kept records remain separate. | `integration/test_observation.py` |
| S-F5: replay floor includes empty snapshots | After sequence 2 is durable, empty and sequence-1 histories reject after reconstruction; last records/cursor remain intact. | Same file |
| O-F3: account discovery progresses | A missing Agreement or digest mismatch is retained as repair-required; a later case is answered and the page cursor advances. A repaired resolver later answers the skipped case. | `integration/test_respondent.py` |
| O-F4: watch cannot preempt concurrence | Watch before respondent discovery creates no plain append; discovery signs matching facts and exports contesting evidence for a mismatch. Lost append acknowledgement recovers after restart and case close. | Same file |
| O-F8: ruling actor is the authority | A prepared/applied repeated delivery-end effect produces one physical effect and retains the pinned record signer, even with a seller-valued account resolver. | `integration/test_watch_and_seller.py` |
| O-F9: retention has a seller API | Held/unknown funds, open cases and incomplete recovery keep evidence. Complete financial/case observations and proven recovery permit pruning after the frozen window; refresh does not slide first completion. | `integration/test_evidence.py`, `unit/test_retention_and_budget.py`; payments `tests/test_retention_projection.py` |
| O-F10: database execution is isolated | While authorization is suspended, another SQLite writer records an end. Revision CAS refuses the stale protected write. Database/retention callbacks run off-loop; constructors perform no I/O. | `integration/test_end.py`, `integration/test_database_execution.py` |
| Sections 10/13: permanent verification | Real SQLite covers end/restart/teardown/correction and deferred filings. Mounted signed-client integration covers authentication, response binding, relay/backdate/future/introduction refusal, outage-independent receipt/retry and exact owner-only site bytes. | `integration/test_ingress.py`, `integration/test_routes.py` and files above |

## Sensitivity and validation

- Running the read/replay/respondent tests against original servicing source
  produced nine expected failures (cached success, empty/shorter replay,
  missing/mismatched discovery and append preemption); five unaffected tests passed.
- The actor test separately failed against original source because the actor was
  the seller. Database-execution and payout-projection tests also fail against
  their original sources. These are sensitivity checks, not unresolved failures.
- Current servicing suite: **39 passed**; source typing and all nine asserted
  first-use examples passed.
- Payments suite: **98 passed**, including typing, installed contract vectors and
  generated-resource checks.
- `make lock`, `check-locks`, `check-packaging`, `check-architecture`,
  `check-comment-hygiene`, strict pinned OpenSpec validation and `git diff --check`
  passed.
- Full `make test`: **passed in 8m19s**, including release tooling and Helm
  structural/render checks, with the prescribed proxy environment and Podman shim.
  Reproduce it after the setup above with:

```sh
eval "$(~/.local/share/simple-compute-market/podman-shim/setup)"
make test
```

## Boundaries

Domain retention composition and domain ingress-thread offloading are assigned to
the parallel domain repair. Filing identity, terminal filing rejection visibility
and selected-end receipt signing are assigned to the parallel lifecycle repair.
No revised live mediation, real hardware, browser or deferred rate execution is
claimed here. Specification promotion and archival remain the owning change's
post-review closeout work. No resident process or external target was left running.
