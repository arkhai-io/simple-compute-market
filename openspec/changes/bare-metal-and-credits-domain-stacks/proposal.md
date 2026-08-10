## Why

Goal 4's capability is two viable domains: bare metal and API credits, deployable and
testable end to end. The kit extractions make them buildable by composition; this change
is what proves they work.

Neither is there today. Bare metal has no compose stack — `domains/vms/compose.yml` and
`domains/apicredits/compose.yml` exist and there is no bare-metal equivalent — so it
cannot be stood up at all. And **no end-to-end test mentions either domain**: the e2e
suite is VM-only, so every deal path the repository actually proves is a VM deal path.

That is what makes "viable domain" currently mean "VM." A domain that cannot be deployed
and has no end-to-end proof is a set of packages, not a market.

## What Changes

- Add a bare-metal deployable stack, following the compose topology the VM and
  API-credits domains already use.
- Add end-to-end scenarios covering a complete deal for each of the two domains:
  discovery, negotiation, settlement, delivery, and teardown.
- Recompose the API-credits storefront so it retains no local implementation of a concern
  the kit extractions own — the domain becomes configuration and codecs over kit, which
  is what "viable" means under this goal rather than merely "works."
- Confirm the completion test for the goal: each domain runs a full deal through a
  composed storefront with no domain-local copy of an extracted concern.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: bare metal has a deployable stack alongside the existing domains'.
- `test-compatibility`: an end-to-end deal path is proven per market domain rather than
  for one domain only.

## Non-Goals

- Do not extract further concerns. If a domain still needs one, that is a finding for the
  owning extraction change, not work to absorb here.
- Do not build the bare-metal buyer — `bare-metal-buyer-domain` owns it, and this change
  depends on it for the bare-metal deal path.
- Do not add a Kubernetes-pod, inference-token, or model-training domain. This change
  delivers the two named domains; the vision they demonstrate is what makes the next ones
  cheap.
- Do not restructure domain package layouts.
- Do not change VM behavior, deployment, or e2e coverage beyond what shared fixtures
  require.

## Impact

- Affected code: a bare-metal compose stack; new e2e scenarios; the API-credits
  storefront's remaining local implementations.
- Affected tests: the e2e suite gains per-domain deal paths; shared fixtures and helpers
  may need generalizing away from VM assumptions.
- Affected deployment: a new stack definition; Helm coverage follows the existing
  per-domain pattern.
- Not affected: core, kit, provisioning, registry, wire contracts, persistence.

## Permanent documentation impact

- [x] `docs/development/TESTING.md` — what an end-to-end deal path proves and that it is
      proven per domain.
- [x] Existing subsystem specification — `openspec/specs/deployment-state/spec.md` and
      `openspec/specs/test-compatibility/spec.md`.
- [ ] New subsystem specification — none.
- [x] `docs/bare-metal-seller-quickstart.md` — standing up the stack.

### Knowledge to promote

- An end-to-end deal path is proven per market domain, not for one domain only —
  `openspec/specs/test-compatibility/spec.md`.
- Every market domain intended for deployment has a deployable stack —
  `openspec/specs/deployment-state/spec.md`.

## Dependencies and Related Changes

- Depends on all four kit extraction changes. A domain missing an extracted concern
  cannot complete a deal, so this change cannot pass its own completion test early.
- Depends on `bare-metal-buyer-domain` for the demand side of the bare-metal deal path,
  and on `market-platform-bare-metal-10-storefront-composition` for its seller side.
- Depends on `multi-domain-storefront-composition` only if the bare-metal stack is
  composed into a shared storefront rather than standing alone; either shape satisfies
  this change, and the choice is recorded in `design.md`.
