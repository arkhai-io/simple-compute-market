## Why

Goal 4's capability is two viable domains: bare metal and API credits, deployable and
testable end to end. The kit extractions make them buildable by composition; this change
is what proves they work.

Bare metal has a compose stack, its own end-to-end lane, an installable buyer
contribution, a seller composition that starts through the shared shell and composes
kit publication, and a real-host deal scenario. What it lacks is the part of "viable"
that is about composition rather than presence: it still carries a domain-local copy
of the negotiation lifecycle (`negotiation_service.py`, `negotiation.py`, and the
`/api/v1/negotiate/*` and listing routes in `api.py`) beside the kit that owns it for
every other domain. API credits completes deals with its own implementations of
concerns the kit owns. A domain that passes an end-to-end scenario over a parallel
implementation satisfies the letter of the completion test and none of its value.

## What Changes

- Compose bare metal onto the kit negotiation runtime and remove its parallel
  negotiation and listing routes, persistence, and service, so the bare-metal
  storefront is contribution adapters over the shared shell with no domain-local copy
  of an extracted concern.
- Complete the bare-metal deployable stack: the seller quickstart, render coverage
  for VM-only, bare-metal-only, and combined seller profiles, and operator examples
  exposing separately composed roles.
- Verify the bare-metal buyer's negotiation ownership and transcript-exact resume,
  clean wheel, independent authorities, and package boundary, and promote them.
- Add end-to-end scenarios covering a complete deal for each of the two domains:
  discovery, negotiation, settlement, delivery, and teardown. The bare-metal deal
  that runs on every pipeline run is `bare-metal-mock-provisioned-deal`'s; the
  real-host run is the protected lane's.
- Recompose the API-credits storefront so it retains no local implementation of a concern
  the kit extractions own — the domain becomes configuration and codecs over kit, which
  is what "viable" means under this goal rather than merely "works."
- Confirm the completion test for the goal: each domain runs a full deal through a
  composed storefront with no domain-local copy of an extracted concern.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: bare metal has a deployable stack alongside the existing domains';
  the bare-metal buyer ships as a clean wheel and addresses independently configured
  authorities.
- `test-compatibility`: an end-to-end deal path is proven per market domain rather than
  for one domain only; the bare-metal buyer wheel's dependencies point downward and
  a package-boundary suite enforces it.
- `negotiation-protocol`: a bare-metal opening carries only buyer-owned demand and
  resumes transcript-exact.

## Non-Goals

- Do not extract further concerns. If a domain still needs one, that is a finding for the
  owning extraction change, not work to absorb here. Composing bare metal onto a kit
  that exists is not extraction.
- Do not build the bare-metal buyer; it exists. This change verifies it.
- Do not build the bare-metal mock or the lifecycle pause/step controls;
  `bare-metal-mock-provisioned-deal` owns them and supplies the pipeline deal evidence.
- Do not add a Kubernetes-pod, inference-token, or model-training domain. This change
  delivers the two named domains; the vision they demonstrate is what makes the next ones
  cheap.
- Do not restructure domain package layouts.
- Do not change VM behavior, deployment, or e2e coverage beyond what shared fixtures
  require.

## Impact

- Affected code: the bare-metal storefront's `negotiation_service.py`,
  `negotiation.py`, `api.py` (negotiation and listing routes), `sqlite_client.py`
  (thread persistence), and `runtime.py`; the API-credits storefront's remaining local
  implementations; the bare-metal quickstart.
- Affected tests: the e2e suite gains per-domain deal paths; shared fixtures and helpers
  may need generalizing away from VM assumptions.
- Affected deployment: a new stack definition; Helm coverage follows the existing
  per-domain pattern.
- Not affected: core, kit, provisioning, registry, wire contracts, persistence.

## Permanent documentation impact

- [x] `docs/development/TESTING.md` — what an end-to-end deal path proves and that it is
      proven per domain.
- [x] Existing subsystem specification — `openspec/specs/deployment-state/spec.md`,
      `openspec/specs/test-compatibility/spec.md`, and
      `openspec/specs/negotiation-protocol/spec.md`.
- [ ] New subsystem specification — none.
- [x] `docs/bare-metal-seller-quickstart.md` — standing up the stack.

### Knowledge to promote

- An end-to-end deal path is proven per market domain, not for one domain only —
  `openspec/specs/test-compatibility/spec.md`.
- Every market domain intended for deployment has a deployable stack —
  `openspec/specs/deployment-state/spec.md`.
- The bare-metal buyer is a clean wheel that addresses independent authorities —
  `openspec/specs/deployment-state/spec.md`.
- A bare-metal opening carries only buyer-owned demand; resume is transcript-exact —
  `openspec/specs/negotiation-protocol/spec.md`.
- Why bare metal's composition onto the kit is not an extraction, and how the
  bare-metal requirements are split between this change and the mock-provisioned
  deal — this change's `design.md`.

## Dependencies and Related Changes

- Depends on the kit extraction changes; the seam and the negotiation and
  capacity/publication kits are in place for VM and API credits. A domain missing an
  extracted concern cannot pass this change's completion test.
- `bare-metal-mock-provisioned-deal` supplies the bare-metal deal evidence that runs
  on every pipeline run and owns the buyer-side deal requirements (exact demand,
  strict result decoding, idempotent teardown, restart recovery).
- `multi-domain-storefront-composition` owns the shared shell; bare metal composing
  the kit negotiation runtime inside it is this change's Section 4a.
- `market-platform-compute-40-multi-domain-proof` depends on this change: its
  two-authority topology needs bare metal on the kit, not merely in the shell.
- The deployment-shape decision (standalone service or a second contract in a shared
  process) is deferred; either shape satisfies this change.
- `bare-metal-buyer-domain` and `market-platform-bare-metal-10-storefront-composition`
  (archived) planned the buyer package and the seller composition this change
  verifies; their disposition records are in their archived headers.
