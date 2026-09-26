## Why

Goal 4's capability is two viable domains: bare metal and API credits, deployable and
testable end to end. The kit extractions make them buildable by composition; this change
is what proves they work.

When this change opened (2026-08-06), neither was there: bare metal had no compose
stack and no end-to-end test mentioned either domain, so every deal path the
repository proved was a VM deal path. That is what made "viable domain" mean "VM."

**Re-grounded 2026-09-26.** Much of that has since landed around this change: bare
metal has a compose stack and its own end-to-end lane
(`bare-metal-publication-reads-pool-declarations`, archived 2026-09-25), an
installable buyer contribution and a real-host deal scenario (delivered by the
parallel bare-metal producer this repository merged), and it composes the kit
publication runtime. What remains is the part of "viable" that is about
composition rather than presence: bare metal still carries a domain-local copy of
the negotiation lifecycle (`negotiation_service.py`, `negotiation.py`, and the
`/api/v1/negotiate/*` and listing routes in `api.py`) beside the kit that now owns
it for every other domain, and API credits still carries its copies. This change is
now the owner of all remaining "bare metal on the kit" work — moved here from
`multi-domain-storefront-composition`, whose external-producer gates described a
contribution that has since been merged — and of the verification that
`bare-metal-buyer-domain` and `market-platform-bare-metal-10-storefront-composition`
carried before they were archived on 2026-09-26.

## What Changes

- Add a bare-metal deployable stack, following the compose topology the VM and
  API-credits domains already use. (Delivered: `domains/bare_metal/compose.yml`,
  `compose.bare-metal.yml`, `compose.bare-metal-local.yml`; what remains is the
  quickstart and the deployment-shape decision.)
- Add end-to-end scenarios covering a complete deal for each of the two domains:
  discovery, negotiation, settlement, delivery, and teardown. (The scenarios exist;
  the bare-metal deal that runs on every pipeline run is
  `bare-metal-mock-provisioned-deal`'s, and the real-host run is the protected
  lane's.)
- **Compose bare metal onto the kit negotiation runtime** and remove its parallel
  negotiation and listing routes, persistence, and service, so the bare-metal
  storefront is contribution adapters over the shared shell with no domain-local
  copy of an extracted concern. Moved here 2026-09-26 from
  `multi-domain-storefront-composition`'s external-producer gates.
- **Verify the bare-metal buyer and seller requirements** migrated from the two
  archived changes against the delivered packages, and promote those that hold
  through this change's deltas.
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
  authorities (migrated from `bare-metal-buyer-domain`).
- `test-compatibility`: an end-to-end deal path is proven per market domain rather than
  for one domain only; the bare-metal buyer passes the shared conformance suite and a
  package-boundary check (migrated).
- `negotiation-protocol`: a bare-metal opening carries only buyer-owned demand and
  resumes transcript-exact (migrated; verified as bare metal composes the kit
  negotiation runtime).

## Non-Goals

- Do not extract further concerns. If a domain still needs one, that is a finding for the
  owning extraction change, not work to absorb here. Composing bare metal onto a kit
  that already exists is not extraction; it is this change's.
- Do not build the bare-metal buyer. It was delivered by the parallel producer and
  `bare-metal-buyer-domain` was archived 2026-09-26; this change verifies it.
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
- Where each requirement of the two archived bare-metal changes went — this change's
  `design.md`, "Migrated requirements".

## Dependencies and Related Changes

- Depends on the kit extraction changes. `kit-owned-negotiation-runtime` and
  `kit-owned-capacity-and-publication` have landed for VM and API credits; the seam is
  in place. A domain missing an extracted concern cannot pass this change's completion
  test.
- Owns, since 2026-09-26, the bare-metal gates `multi-domain-storefront-composition`
  carried as tasks 1.3, 3.7, 5.3, 5.5, 7.2, and 7.3: the contribution is merged, so the
  gates are composition work, not an integration wait.
- `bare-metal-buyer-domain` and `market-platform-bare-metal-10-storefront-composition`
  were archived 2026-09-26; their surviving requirements and verification tasks are
  here and in `bare-metal-mock-provisioned-deal` (see `design.md`, "Migrated
  requirements").
- `bare-metal-mock-provisioned-deal` supplies the bare-metal deal evidence that runs on
  every pipeline run and owns the buyer-side deal requirements migrated to it.
- `market-platform-compute-40-multi-domain-proof` depends on this change: its
  two-authority topology needs bare metal on the kit, not merely in the shell.
- The deployment-shape decision (standalone service or a second contract in a shared
  process) is still deferred; either shape satisfies this change, and the bare-metal
  lane runs standalone today.
