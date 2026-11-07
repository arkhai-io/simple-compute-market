# Joined settlement closeout after repairs

Target: checkout-owned `closeout-final`, campaign production `4d04fbf7` plus import/comment repair `2d22f6e4`. Mode: auditing then documentation closeout. This packet supersedes the original audit's findings disposition, not its independent observations. No behavioral repairs or new permanent tests were made by closeout. Visual: false; screenshots: none.

## Result

Every original named suite and every repair-worker entry passed. Original verifier F1/F2/F3 and review fixes hold, each under a committed regression test. Storage and protected recovery confirmation tasks 6.1/6.2 are complete. At this closeout, 8.2 was blocked by standalone API-credit negotiation (B1) and disabled-contact accepted reveal/re-read (B2), recorded in [final-inventory.md](final-inventory.md). Both were then repaired through their declared stages ([apicredits-negotiate](../apicredits-negotiate/index.md), [contact-disablement](../contact-disablement/index.md)), and 8.2 holds.

## Validation

[validation.md](validation.md) records how to rerun validation with each project's `make` targets, the regression test that holds each finding, and the counts on the tree after `dev` was merged. It replaces this closeout's replay scripts and pre-merge counts.

Prepared target: installed local CLI/library and in-process ASGI authority with fresh owned temporary SQLite/run logs. Synthetic canonical buyer/seller/service identities and an ephemeral operator key; no external credentials or inherited deployment selector. No live payment/site/provider/auth target was supplied; complete deals over the docker-compose stack run in the `E2E` workflow.

## Observations

- VM: pending/0 deliveries → provisioning → ready/1; payment escrow rows 0. Actual accepted-run CLI preserves the recorded mechanism/reference with and without a stray proposal.
- API credits: health 200; pending grants 0 → lost-ack 1 → final 2, balance 5, payment escrows 0, payment polls 3. Owner-only private retrieval and secret-free top-up/exact retry hold; temporary databases removed.
- Malformed verified VM storage refuses (`verified VM evidence requires a sha256 Agreement digest`), held by `test_vm_evidence_validation.py`.
- A reclaimed bare-metal Alkahest journal refuses before physical effects (`no longer active`), held by `test_http_settlement.py`.
- VM standalone negotiation inspection: old config-key, payer-helper, wallet/chain and proposal-absence dispatch absent; all four selected-stage hooks present. Fresh CLI cases are in the 105-pass group.
- API-credit verified receipt recovery survives unavailable polling; prepared Alkahest delivery does not perform a second preparation; neutral failure release correlates by negotiation. Bare-metal recovery rechecks authoritative chain state/index and refuses inactive journal variants before physical effects.

## Import and comment closeout

Actual diff from `9233a332` was scanned for added/touched local imports, comments and docstrings. API-credit settle imports moved to module scope and its real buyer/recovery/client suites passed. Three local imports remain with concrete reasons: VM recovery table import reproduced `ChainSettings` circular import after wheel rebuild; VM delivery connectivity import reproduced a `fulfill_vm_obligation` cycle; VM publication's domain runtime loads process-global operator config and stays deliberately lazy for help/pure payload construction. Reasons are local in code. Historical job-hook wording was replaced by the current recovery invariant. No production reference to active change documents was introduced. `make check-comment-hygiene` passes.

An initial import probe used a nonexistent leaf `dist` target and was corrected to `make -C domains dist-buyer`; uninstalled guessed import names were corrected to the declared wheel module. These are operator command corrections, not product regressions. All temporary module-scope probes were reverted before final builds/tests.

## Documentation and residual ownership

`openspec validate route-settlement-by-mechanism --strict` and
`openspec validate --specs --strict` both pass, as does final comment hygiene.
Informational long-requirement notices are not validation failures.

All six deltas and existing architecture companions are promoted; repository architecture, Goal 6 and active change status describe both repaired behavior and the remaining inventory gaps. `design.md` records exact destinations. No new capability companion was needed; the capability index is unchanged. Four repair packets now live under repo-level attachments: [core](../core-settlement-closeout/index.md), [bare metal](../baremetal-recovery-gate/index.md), [API credits](../apicredits-settlement-repair/index.md), [VM](../vm-settlement-findings/index.md).

- Quota-ledger `escrow_uid` correlation API rename: `openspec/changes/move-escrow-into-alkahest/proposal.md`.
- Cross-domain helper duplication (review F7): [#261](https://github.com/arkhai-io/simple-compute-market/issues/261), idea.
- Credits service dev wheel closure (review F9): [#262](https://github.com/arkhai-io/simple-compute-market/issues/262), idea; runtime authority coupling is not alleged.
- Reinit lock churn [#257](https://github.com/arkhai-io/simple-compute-market/issues/257), core asyncio warning [#258](https://github.com/arkhai-io/simple-compute-market/issues/258), Pydantic schema warnings [#259](https://github.com/arkhai-io/simple-compute-market/issues/259), TestClient deprecation [#260](https://github.com/arkhai-io/simple-compute-market/issues/260) remain visible. Generated lock churn was restored only after execution; tested environments were not resynced.

No server, browser, container, tunnel or external deployment was started. Temporary databases, engines, run logs and coordinators were cleaned. All supervised work finished; no external resource remains.
