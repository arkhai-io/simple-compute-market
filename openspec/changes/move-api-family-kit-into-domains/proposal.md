## Why

A package that several domains of a family share goes under the family, whose
directory `docs/development/ARCHITECTURE.toml` names
(`docs/guidance/repository/package-layers.md`, "Scope"). The compute family
follows this at `domains/compute`. The `api` family does not: its vocabulary
and its twelve other distributions sit at `kit/api`, and to admit them
`scripts/architecture.py`'s `read_path` reads a family directory under `kit/`
as a family, so `kit/` holds specializations. `align-package-paths-with-layers`
designs the opposite, and `ARCHITECTURE.md`'s path table and role words say the
opposite.

A review of the branch carrying the family kit found that departure and seven
smaller ones against rules the repository already states. None needs a new
design decision about the market; each is a known rule the code does not yet
meet:

- The family's buying libraries hold mechanism code that knows no family.
  `arkhai_api_buying_alkahest`'s `escrow_selection.py`, `escrow_client.py`, and
  `chains.py` repeat the VM buyer's modules of the same names, and
  `arkhai_api_buying_arkhai_payments`'s `payments.py` is payments client code.
- `arkhai-api-selling` depends upward on `arkhai-core-storefront`. The exception
  row names `kit-owned-storefront-auth-and-persistence` as its owner, which
  covers authentication and persistence; the library also imports the stage
  log, system models, domain registry, negotiation service, aggregation, and
  the listing, negotiation, and settle models, which no change owns moving, so
  the row cannot be retired.
- The API-credits and inference storefronts each hold
  `settlement_composition.py` and `services/fulfillment_service.py`, which
  differ in about twenty lines of roughly a hundred and are composition code,
  not controllers.
- Issuance pins for the inference label sit in `domains/apicredits/tests`.
- `domains/inference/buyer/tests/test_scope_refusal.py` replaces eleven names
  in kit libraries, and `kit/api/buying/tests/unit/test_credentials.py` patches
  `os` globally; `TESTING.md` admits replacing only factories on the module
  under test.
- The authority's `consume` debits whatever amount the caller sends and never
  compares it with the `request_charge` pinned on the key's terms.
- The roadmap's inference goal fixes the campaign's order of delivery, which
  the roadmap does not hold: sequencing is the change index's.

`compose-api-family-kit`, which built the kit, is archived, and an archived
change is not returned to design, planning, or implementation. This change
owns the corrections instead.

## What Changes

- Move the family from `kit/api` to `domains/api`: the vocabulary package at
  `domains/api` and each distribution as its sibling directory beneath it, with
  the family's `directory` in `ARCHITECTURE.toml` naming `domains/api`.
  Distribution and import names do not change. The gateway and the gate ports
  move with the rest; removing the gateway stays `meter-inference-usage`'s.
- Restore the placement rule: `read_path` reads a family only under `domains/`,
  and `ARCHITECTURE.md` and `package-layers.md` say so again.
- Follow the move everywhere a path is written: project sources and locks, the
  Makefiles, the release components manifest, the workflows, the Compose stacks
  and images, the published-packages table, and the permanent documents that
  cite `kit/api`.
- Move mechanism code that knows no family out of the family's buying
  libraries into its mechanism kit, leaving only the family's stage glue, and
  compose the VM buyer's copies from the same place where that is the same
  code.
- Point `arkhai-api-selling` at `kit/storefront` wherever it already serves
  what the library imports from `core_storefront`, and record every remaining
  import under an owner that moves it, so the exception row has an owner that
  can retire it.
- Move the shared body of `settlement_composition.py` and
  `services/fulfillment_service.py` into `arkhai-api-selling`; each storefront
  keeps only what differs.
- Move the inference-label issuance pins into the family's tests.
- Rewrite the two test modules to replace only what `TESTING.md` admits.
- Make the authority's `consume` refuse an amount that differs from the pinned
  `request_charge`.
- Remove the delivery order from the roadmap's inference goal.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `api-family`: the family's packages live under `domains/api`; the authority
  refuses a consumption whose amount is not the key's pinned charge; the
  family's selling library owns settlement and fulfillment composition.
- `market-composition`: a family kit lives under its family's directory, never
  under `kit/`.

## Non-Goals

- No change to a wire shape, a route, a digest, a distribution name, or an
  import name. The pinned API-credits digests hold byte-for-byte.
- No change to buyer or seller behaviour beyond the authority's refusal of a
  mismatched amount.
- No removal of the gateway, and no change to what a failed upstream request
  costs; both are `meter-inference-usage`'s.
- No move of the buyer role's orchestration; that is
  `kit-owned-buyer-orchestration`'s, which keeps the three buying exception
  rows.
- No move of the storefront's authentication and persistence; that stays
  `kit-owned-storefront-auth-and-persistence`'s.
- No copied controller is merged: a domain's controllers stay copied until
  controller and client derive from the contract and model packages.

## Questions for design

- Which package takes the Arkhai-payments buyer code: `kit/arkhai-payments`, or
  a buyer-side distribution beside it, given that a buyer installs no selling
  code.
- Whether the Alkahest buyer modules move here or wait for
  `move-escrow-into-alkahest`, which owns the escrow exception rows and edits
  the same VM buyer modules.
- Which change owns each `core_storefront` import `kit/storefront` does not yet
  serve: a widened `kit-owned-storefront-auth-and-persistence`, or
  `kit-owned-storefront-shell`.
- Whether the mismatched-amount refusal is a new refusal code on the
  authority's contract, and what `consume_batch` does with one bad item.
- Whether the move is one section or several, since every later section edits
  paths it changes.

## Impact

- Code: every file under `kit/api`, which moves; `scripts/architecture.py`;
  `docs/development/ARCHITECTURE.toml`; each project that names a family
  distribution by path, and its lock; `manifests/release-components.json`; the
  workflows; the API-credits and inference storefronts and buyers; `kit/alkahest`
  and `kit/arkhai-payments`; the VM buyer where it composes moved mechanism
  code.
- Tests: the family's suites move with their packages; the two rewritten test
  modules; the issuance pins.
- Evidence: the family has never been exercised end to end by the API-credit
  lane on the branch its kit was built on. This change's validation runs the
  pipeline's four lanes on the moved tree.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the family kits section, the path
  table, and the domain-anatomy diagram.
- [x] Existing subsystem specification — `openspec/specs/api-family/spec.md`
  and its companion; `openspec/specs/market-composition/spec.md`;
  `openspec/specs/inference/architecture.md` where it cites the kit's paths.
- [ ] New subsystem specification
- [x] `docs/guidance/repository/package-layers.md`,
  `docs/guidance/repository/published-packages.md`,
  `docs/guidance/repository/contract-conformance.md`, and
  `docs/guidance/repository/migrations-at-startup.md` — the paths they cite.
- [x] `docs/development/ROADMAP.md` — the inference goal.

### Knowledge to promote

- A family kit lives under its family's directory; `kit/` holds no
  specialization — `docs/development/ARCHITECTURE.md`,
  `docs/guidance/repository/package-layers.md`,
  `openspec/specs/market-composition/spec.md`.
- The authority refuses a consumption whose amount is not the pinned charge —
  `openspec/specs/api-family/spec.md`.
- The family's selling library owns settlement and fulfillment composition —
  `openspec/specs/api-family/spec.md` and its companion.

## Dependencies and Related Changes

- Depends on `compose-api-family-kit`, which built the kit and whose archive
  cleanup has not run.
- Takes from `compose-api-family-kit` the corrections its closeout left: the
  family's directory, the mechanism code in its buying libraries, and the
  selling exception's owner.
- Coordinates with `align-package-paths-with-layers`, whose design the
  placement rule returns to.
- Coordinates with `kit-owned-storefront-auth-and-persistence`, whose scope
  widens or whose exception row gains a second owner, as design settles.
- Coordinates with `kit-owned-buyer-orchestration` and
  `move-escrow-into-alkahest`, which own exception rows on packages this
  change moves and edit the buyer modules it touches.
- Coordinates with `keep-buyer-credentials-private` and
  `derive-buyer-settlement-inputs`, which edit `kit/api/buying` files this
  change moves.
- Precedes `meter-inference-usage`, which removes the gateway from where this
  change leaves it.

## Status

Ready for design.
