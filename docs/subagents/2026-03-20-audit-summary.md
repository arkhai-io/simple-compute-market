# 2026-03-20 Audit Summary

This file records the first full deployment-audit subagent sweep run on
2026-03-20.

This document is a historical snapshot of the repo state on 2026-03-20.
Its blocker list and `clean-room verdict`: no were accurate at that time, but
later doc and test work superseded that verdict.

## Results

- `local-stack`: fail
  Main blockers: root docs do not define the compose-first full local stack,
  omit Docker/Compose prerequisites, omit image build steps, and omit
  verification/cleanup around `make deploy-local`.
- `registry-deploy`: fail
  Main blockers: the runbook implies direct ZeroTier container membership that
  the registry image does not support, omits GAR auth, and does not document DB
  or dependency verification beyond `/health`.
- `provisioning-deploy`: fail
  Main blockers: direct-run docs do not explain effective inventory delivery,
  SSH private-key injection, or verification of worker startup and secret
  materialization; runtime `PORT` docs also drift from `start.sh`.
- `iac-host-kit`: fail
  Main blockers: stale host aliases in the README, incomplete FRP secret
  handoff, and inconsistent `golden` versus `scratch` expectations for
  `build-vars.yaml` and `management-vars.yaml`.
- `agent-seller`: fail during audit
  Main blockers found by the audit were missing `CHAIN_ID` and explicit registry
  address fields in the deployed env contract. These were patched locally after
  the audit by updating the runbook, production sample, validator, and
  entrypoint flag usage.
- `agent-buyer`: fail during audit
  Main blockers found by the audit were the same agent env-contract gap plus an
  `--env-file` versus `--env_file` mismatch in the auto-registration path. Those
  issues were patched locally after the audit.
- `network-overlay`: fail
  Main blockers: the docs do not state one unambiguous service-to-network model,
  do not surface the exact FRP DNS and downstream credential handoff, and omit
  concrete reachability checks between ZeroTier-joined service hosts.
- `canary-e2e`: fail
  Main blockers: the gate sequence is inconsistent across docs, the runner env
  contract is incomplete, and post-run verification is underspecified outside
  smoke-script output.
- `rollback`: fail
  Main blockers: short rollback docs are not self-contained, do not preserve the
  exact provisioning job/order IDs before cleanup, and do not restate retry
  gates clearly enough.
- `clean-room`: fail
  Main blockers: image-selection guidance is incomplete, provisioning secret
  construction still depends on external IaC detail, and the canary runner/env
  handoff is not yet fully defined from the stand-up docs alone.

## Notes

- The audit set covered every prompt under `docs/subagents/`.
- Seller and buyer audit blockers triggered a real repo patch in the current
  working tree and should be considered partially remediated relative to the raw
  audit output.

## clean-room verdict

`clean-room verdict`: no. A fresh operator with repo access plus the necessary
credentials can get close, but the documented stack is still not fully
stand-up-able without inference around local-stack bring-up, registry and
provisioning deployment details, ZeroTier/FRP wiring, and the final canary
runner bundle.

## Superseded Status

Later doc and test work superseded that verdict. Treat this file as the
historical starting point for the audit effort, not the current production
readiness verdict. The current source of truth is the canonical stand-up docs,
deployment gates, and the green test matrix in the repo.
