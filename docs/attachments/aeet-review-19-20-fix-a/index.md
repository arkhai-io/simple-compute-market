# Implementation review 19/20: lifecycle filing repairs

## Setup and reproduction

- Required environment: library and in-process API qualification, not a hosted
  authority or deployed compute target. No Cloud target is required for these
  assigned kit findings.
- Prepared target: this checkout's installed `.dist` wheels; each persistence
  scenario owns a temporary SQLite database and removes it. The authority peer
  is the mediation kit's published-vector contract fake, not a remedies engine.
- Personas: public deterministic development buyer/seller signers and the fake's
  documented payer/payee bearer fixtures. No real account or secret is required.
- Readiness observed: wheels build; each selected package can install its locked
  dependencies; the assertion-bearing mediation first use completes with one
  case and signed record sequences `[1, 2]`. No server or container is left up by
  the first-use command.
- Tested code: `d65e98e86`, including preceding review repair commits. Baseline
  regression checks use this repository's `be0b46aaf` source, not stale wheels.
- Visual evidence: not applicable; these are backend library/API contracts.

Run from the repository root:

```sh
unset ALL_PROXY all_proxy
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
make dist-ci
make -C kit/arkhai-mediation demo
make -C kit/arkhai-mediation test
make -C kit/deal-lifecycle-buyer test
make -C kit/deal-lifecycle-client test
make -C kit/deal-servicing reinit
(cd kit/deal-servicing && uv run --with pytest --find-links ../../.dist python -m pytest -q tests/integration/test_review_fix_a.py tests/integration/test_admission_replay.py)
```

The temporary `--with pytest` invocation works independently of the parallel
servicing-suite build-target change. After that integration, the same tests run
through `make -C kit/deal-servicing test` and the repository aggregate.

## Observed criteria

| Finding | Action and observed outcome | Permanent check |
| --- | --- | --- |
| S-F1 / O-F2 | Online and recovery callers return the same signed case. Concurrent reconstructed SQLite callers reserve one original writer; the other refuses with repair required until it can adopt that original. One authority case is allocated. An unknown original blocks a changed claim. | `kit/arkhai-mediation/tests/integration/test_semantic_filing.py`; `kit/deal-servicing/tests/integration/test_review_fix_a.py` |
| O-F2 | A site echo correlated to a controlling seller failure retains both sources and one filing, for both delivered and never-delivered deals. | `kit/deal-servicing/tests/integration/test_review_fix_a.py` |
| O-F5 | A lost durable surrender response leaves case progress pending with no filing. Reconstructed buyer recovery retries the same surrender key and files at acknowledged receipt time with concurrence. | `kit/deal-lifecycle-buyer/tests/integration/test_end_recovery.py` |
| O-F6 | An earlier seller end suppresses receipt concurrence and automatic payer filing. A client can retain an earlier selected end on retry without changing durable receipt time. | Buyer recovery, servicing review and signed-client suites |
| O-F11 | Two authority-rejected filings both remain visible after restart; no resubmission occurs; seller read/list report repair required and every filing outcome. | Servicing review suite |
| O-F12 | The Agreement-bound mediation adapter signs and verifies locally under both signature schemes without an online credential/client; reads fail closed. Both compute callbacks resolve the pinned table, including credential-free local claim capability; absent adapters return no claim. The binding read also succeeds while ingress holds its SQLite write transaction. | `kit/arkhai-mediation/tests/integration/test_adapter.py`; both domains' `test_receipt_adapter.py` |
| O-F13 | Unused duplicate helpers and their helper-only tests are removed. Real receipt persistence/retry and signed-client no-adapter delivery checks retain the observable coverage. | Servicing review suite and signed-client first use |
| O-F14 | A pre-start failure recorded after start keeps Agreement start as its fixed never-delivered claim basis across database reopen. | Servicing review suite |
| O-F15 | An invalid operator request does not consume its key; the corrected command under that key is accepted. | Servicing review suite |
| O-F16 seam | Repeated phase admission preserves revision, while expired-term admission is still refused. | `kit/deal-servicing/tests/integration/test_admission_replay.py` |

## Sensitivity and validation

Baseline checks fail on the reviewed source for all behavioral repairs: three
semantic identity scenarios, both buyer recovery scenarios, the client's earlier
selected-end retry, both offline signature schemes, six servicing cases and the
unchanged-phase admission scenario. All six domain adapter-selection/offline-construction checks also fail on the reviewed domain source. The baseline exhibits duplicate cases,
contested filing after response loss, wrong payer precedence, pre-start basis,
consumed keys and non-enumerated/retried refusals. The concurrent baseline fails
its bounded liveness check because it attempts another authority write instead
of refusing the already-reserved caller.

Focused final results: lifecycle contracts 37, foundation 61, mediation 45,
buyer 20, signed client 2, servicing 9; each compute domain's receipt-adapter checks pass 3 cases. Mediation contract/resource checks and
mypy pass; servicing mypy passes. One helper-only foundation test was deleted
with its unused API; no surviving assertion was weakened.

Final-head qualification passes: `make check-architecture`, `make check-packaging`,
`make check-locks`, `make check-comment-hygiene`, strict OpenSpec validation, and
full `make test`. The combined final-head gate chain completes successfully in
7m 41s, with proxy exclusions and the shell-local Podman compatibility shim.
The earlier complete gate chain also passed before the final domain callback
seam. `make lock` was run after the signed-client test dependency changed. No deployed/hosted mediation or monetary-rule execution
is claimed. The raw producer client still replays linked operator-ruling vectors;
SCM's lifecycle adapter explicitly refuses unsupported linked revision/netting
instead of creating a new semantic filing.
