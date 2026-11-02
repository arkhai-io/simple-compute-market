# Buyer and servicing re-review repair evidence

Code revision: `18e7f42df` on the worker branch. Documentation-only records follow
that revision. This is implementation evidence for the independent driver, not
an independent acceptance verdict.

## Setup and replay

This is a nonvisual library/API repair. The prepared target is the checkout's
own Python environments and wheelhouse. No hosted deployment, wallet, browser,
long-lived server, or external account is required. The authority is the
published mediation contract's in-process signed HTTP peer, not a live financial
service. Tests seed fresh temporary SQLite journals and use public deterministic
buyer, seller, and authority fixtures. Credentials are contract-fake values only;
no user secrets are required.

From a clean checkout, the first-use entry point is:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist &&
make -C kit test-deal-servicing test-deal-lifecycle-buyer test-deal-lifecycle-client test-arkhai-mediation
```

Both real buyer transport ports are separately exercised with:

```sh
for project in domains/vms/buyer domains/bare_metal/buyer; do
  (cd "$project" && make reinit &&
   uv run --no-sync pytest tests/test_lifecycle_adoption.py -q) || exit
done
```

Package reinitialization completed, the signed peer and fresh journals were
usable, and no resident service was left running. The independent driver can
reproduce from committed code rather than inheriting worktree-local state.

## Claims and observed regression sensitivity

| Finding | Before repair | Observed repaired behavior | Durable check |
|---|---|---|---|
| S-N1 | Both real buyer ports raised missing `case` on lost-response recovery. | Reconstructed buyer storage adopts the signed original; one case and one POST. Credentials remain lazy. | [VM port](../../../domains/vms/buyer/tests/test_lifecycle_adoption.py), [bare-metal port](../../../domains/bare_metal/buyer/tests/test_lifecycle_adoption.py) |
| S-N2 / E-N6 | Delayed correction could not name/adopt its controlling source. | Lawful and nonlawful delayed echoes resolve after reconstruction without changing the request or duplicating a filing. Invalid controllers are refused. | [Correction adoption](../../../kit/deal-servicing/tests/integration/test_correction_adoption.py) |
| E-N2 | A later superseded failure journaled a second, different filing. | Later requests remain evidence only; a genuinely earlier late source still journals a revision. Replay preserves both distinctions. | [Correction ordering](../../../kit/deal-servicing/tests/integration/test_correction_adoption.py) |
| E-N1 | An uncertain original produced `unknown`, then the other caller became terminally `rejected`. | First cycle is `unknown` / `pending`; reconstructed dispatch resolves both to the same accepted signed case. Terminal authority refusals remain terminal. | [Owner recovery](../../../kit/deal-servicing/tests/integration/test_filing_owner_recovery.py), [semantic concurrency](../../../kit/arkhai-mediation/tests/integration/test_semantic_filing.py) |
| E-N3 / O-F6 | Respondent signed payer concurrence despite an earlier selected seller end. | Explicit payer claims over superseded surrender receive contest evidence containing the earlier end, never concurrence. | [Respondent selection](../../../kit/deal-servicing/tests/integration/test_respondent.py) |
| E-N5 | Foreign cases became permanent repairs; retry order was case-ref lexical. | Foreign cases are skipped, unresolved local cases remain repairable, and failed retries rotate in arrival order across reconstruction. | [Ownership and fairness](../../../kit/deal-servicing/tests/integration/test_respondent_ownership.py) |
| E-N7 | Later operator submit inherited another filing's rejection; repair reasons doubled their prefix; progress serialized a redundant flag. | Submit reports only its own filing, reasons have one prefix, and receipt-backed recovery replays retained plans without the obsolete output field. | [Operator/diagnostics](../../../kit/deal-servicing/tests/integration/test_review_fix_a.py), [buyer recovery](../../../kit/deal-lifecycle-buyer/tests/integration/test_end_recovery.py) |

Each new regression was run before its corresponding fix and failed at the
behavior named above. Existing assertions about terminal refusals, semantic
revision safety, receipt basis, and lost-response idempotency remain in place.
The terminal-refusal fixture now uses successively selected failures so it still
proves two real required filings rather than relying on a superseded filing.

The tests live in ordinary package discovery. The repository's
[CI test matrix](../../../.github/workflows/tests.yml) runs the root `make test`
targets that invoke these packages; no regression depends on a temporary script.

## Scope and seams

The only seller-domain seam is one optional `controlling_source_ref` keyword in
each existing correction caller. Buyer changes add lazy `case` forwarding. No
payment remedy, authority identity, stop timing, silence default, or held-funds
penalty semantics changed. Financial effects remain authority-owned.

Current API guidance is in [the servicing README](../../../kit/deal-servicing/README.md).
Normative refinements are retained in the change's deal-lifecycle delta for
promotion during the parent's existing closeout, not prematurely written as a
permanent specification of an unarchived subsystem.

## Validation

- Servicing: 61 passed; mypy passed across 11 source files.
- Buyer lifecycle: 20 passed.
- Signed lifecycle client: 2 passed.
- Both real buyer-port recovery checks: 1 passed each.
- Mediation: 45 passed in the full target; focused semantic-filing checks: 3 passed,
  including concurrent writer/adoption.
- Servicing first-use examples and buyer/client first-use examples passed.
- Architecture, packaging, locks, comment hygiene, and strict pinned OpenSpec validation passed.
- Full repository `make test`: passed in 7m59s with the prescribed proxy settings
  and Podman-compatible Docker shim; no failing target. The pre-existing optional
  VM RL test module skipped because `torch` is not installed. No assigned
  lifecycle regression was skipped.
- Scoped documentation-citation check passed after correcting premature references
  to closeout outputs; existing delta/design sources remain the current references.

Visual evidence: not applicable; no rendered surface changed.
