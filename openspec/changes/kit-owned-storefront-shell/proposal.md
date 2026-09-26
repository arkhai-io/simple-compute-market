## Why

Three storefronts carry the same shell. Each has its own route set over the same core
request and response models — listings, negotiate, negotiations, settle, system, and
hosted-settlement controllers (1,370 lines in the VM storefront, 1,093 in API credits,
`api.py` at 863 in bare metal) — its own executable assembly (`server`, `startup`,
`container`, and configuration loading: 1,978, 1,083, and 680 lines), its own health
and system service, and its own timer loops (`lifecycle.py` at 420 lines in VM; bare
metal gains pause and step controls of its own). Core already owns the shell's
foundation — `app_composition`, `domain_registry`, `domain_plugins`, `app_lifecycle` —
and the provisioning service already shows the target shape: one executable that
composes adapter bundles, where an adapter is codecs and hooks, not a second server.

The duplication is the cost the kit extractions exist to remove. A defect in one copy
of the settle route stays live in the other two; a cross-cutting change such as the
pause-and-step convention `TESTING.md` makes repository-wide has to be built once per
domain; and a fourth compute domain would begin by copying a shell.

## What Changes

- Move the storefront route set into kit: listing, negotiation, settlement, system,
  and hosted-settlement routes over the core models, dispatching to injected domain
  hooks. A domain contributes codecs and the per-route hooks it already contributes to
  the negotiation and settlement kits; it contributes no controller.
- Move executable assembly into kit: one composition root that loads the frozen
  domain registry, assembles the container, applies the middleware set, mounts the
  shared routes and each contribution's extra routes, and runs the lifespan. A domain
  storefront becomes a contribution plus an entry point.
- Move the health and system service and the timer-loop runtime into kit: every loop
  a domain runs (publication, negotiation watchdog, settlement servicing, fulfillment
  convergence) is registered with the kit's lifecycle, held by one pause, and stepped
  by one control, so the pause-and-step convention is composed rather than
  reimplemented.
- Compose all three domains onto the kit shell and remove every domain-local copy in
  this change, per the extraction rule.
- Record, per concern, where the three copies already diverged and which behavior was
  chosen.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: the storefront shell — route set, executable assembly,
  health, and timer-loop lifecycle — is kit-owned and composed by every domain.

## Non-Goals

- Do not merge the compute-family domains into one storefront or one contribution.
  That is an evolution direction for later goals; this change extracts what every
  domain duplicates today, API credits included.
- Do not extract the listing lifecycle, fulfillment convergence, authentication
  middleware, or persistence residue — sibling changes own those.
- Do not change any wire contract; the shared routes serve the same paths, models,
  and authentication as the copies they replace.

## Impact

- Code: every domain storefront's `controllers/`, `server.py`, `startup.py`,
  `container.py`, `services/system_service.py`, and `lifecycle.py` or equivalent;
  `kit/storefront` gains the shell.
- Tests: three domains' controller and startup suites collapse into kit suites plus
  per-domain contribution conformance.
- Deployment: entry points and images for each storefront point at the kit
  composition root with the domain's contribution installed.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — role map and package layers.
- [x] Existing subsystem specification — `openspec/specs/market-composition/spec.md`.
- [x] `docs/development/TESTING.md` — the loop table names the kit lifecycle.
- [ ] New subsystem specification

### Knowledge to promote

- The storefront route set, executable assembly, health, and timer-loop lifecycle
  are kit-owned; a domain contributes codecs, hooks, and timings —
  `openspec/specs/market-composition/spec.md`.

## Dependencies and Related Changes

- Depends on `kit-storefront-composition-seam` for the seam and the extraction rule,
  and on the negotiation, settlement, and capacity/publication kits, whose hooks the
  shared routes dispatch to.
- Sequenced first of the three follow-on extractions:
  `kit-owned-listing-and-fulfillment-lifecycles` and
  `kit-owned-storefront-auth-and-persistence` land as contributions to this shell.
- `bare-metal-and-credits-domain-stacks` reduces bare metal's `runtime.py` and
  `server.py` to contribution adapters over the existing shell; this change replaces
  those adapters, and either order works.
