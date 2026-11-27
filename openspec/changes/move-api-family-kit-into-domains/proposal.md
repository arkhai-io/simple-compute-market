## Why

The `api` family's vocabulary and its distributions sit at `kit/api`. To admit
them there, `scripts/architecture.py`'s `read_path` reads a family directory
under `kit/` as a family, and
`docs/guidance/repository/package-layers.md` says a family kit belongs under
`kit/`. The compute family lives at `domains/compute`,
`align-package-paths-with-layers` designs family kits under their family, and
`kit/` otherwise means a package that knows no market. Two families follow two
rules.

A review of the branch carrying the family kit found that departure and
several smaller ones against rules the repository already states. Checked
against the code, these stand:

- The selling library imports the stage-event emitter from the storefront role
  in three modules and takes it as a parameter in two others.
- The API-credits and inference storefronts each assemble the same settlement
  composition, so the order of assembly and the rule that issuance evidence is
  trusted only from the storefront's own signer are written twice.
- The inference-label issuance pin is replayed by an API-credits test, though
  the code under test is the family vocabulary's.
- `domains/inference/buyer/tests/test_scope_refusal.py` replaces eleven names
  inside kit libraries, and `kit/api/buying/tests/unit/test_credentials.py`
  patches the standard library and a collaborator's class, against
  `docs/guidance/engineering/testing-python.md` and
  `docs/guidance/engineering/testing.md`.
- The authority's `consume` debits whatever amount it is sent and never
  compares it with the request charge pinned on the key's first grant.
- The roadmap's inference goal fixes the campaign's order of delivery, which
  the roadmap does not hold.

`compose-api-family-kit`, which built the kit, is archived, and an archived
change is not returned to design, planning, or implementation. This change
owns the corrections.

## What Changes

- Move the family from `kit/api` to `domains/api`: the vocabulary project at
  `domains/api` and each distribution directly beneath it. Distribution and
  import names do not change.
- Restore the placement rule: `read_path` reads a family only under
  `domains/`, and `package-layers.md` and `ARCHITECTURE.md` say a family kit
  lives under its family's directory.
- Follow the move wherever the path is written: the Makefile recipes and
  aggregates, the continuous-integration job, the release components manifest
  and the published-packages table, tests that reach the family by path, and
  the documents that cite `kit/api`.
- The selling library's listing service, storefront loops, and negotiation
  runtime builder take the stage-event emitter by injection, and each
  storefront passes it.
- One settlement composition builder in the selling library replaces the body
  the two storefronts repeat; each storefront passes its own resources.
- The family's pin test replays the inference-label case.
- The two test modules take their doubles through seams: the Alkahest buyer
  stage gains optional collaborators for the seller calls and the chain
  resolver, and the file credential store optional `replace`, `fsync`, and
  `open` parameters.
- The authority refuses a pinned key's consumption at an amount other than its
  pinned charge, as `charge_mismatch`, after the refusals of the key itself.
- The roadmap's inference goal no longer fixes a delivery order.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `api-family`: the family's packages live under `domains/api`; the authority
  refuses a pinned key's consumption at another amount.
- `market-composition`: the family's vocabulary and kit are under
  `domains/api`.
- `api-credits`: the family distributions it composes are under `domains/api`.

## Non-Goals

- No change to a route's path, method, or success shape, a digest, a
  persisted record, a distribution name, or an import name. The pinned API-credits digests hold byte for byte.
- No change to API-credits behaviour: its keys are unpinned and are charged
  the amount sent, as before.
- No move of the Alkahest buyer modules in the family's buying library; that
  is `move-escrow-into-alkahest`'s.
- No move of the Arkhai-payments buyer library or of the buyer role's
  orchestration; the latter is `kit-owned-buyer-orchestration`'s.
- No move of the storefront's authentication, persistence, or wire models;
  that stays `kit-owned-storefront-auth-and-persistence`'s.
- No removal of the gateway, and no change to what a failed upstream request
  costs; both are `meter-inference-usage`'s.
- No rewrite of the other tests that replace library names; they stay with the
  roadmap's unowned gap on command-module test seams.

## Impact

- Code: every file under `kit/api`, which moves; `scripts/architecture.py`
  and its test; `docs/development/ARCHITECTURE.toml`; `kit/Makefile` and
  `domains/Makefile`; the tests workflow; `manifests/release-components.json`;
  the selling library, the Alkahest buying library, the buying library's
  credential store, and the authority's key service; the API-credits and
  inference storefronts.
- Tests: the family's suites move with their packages; the issue-discovery
  bootstrap test that runs a recipe in the family's directory; tests in the
  API-credits and inference domains that reach the family by path; the pin
  tests; the two test modules.
- Evidence: each implementation round is validated on the pipeline's four
  lanes and the Helm lane.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — the family kits section, the
  vocabulary paragraph, and the domain-anatomy diagram.
- [x] Existing subsystem specification — `openspec/specs/api-family/spec.md`
  and its companion; `openspec/specs/market-composition/spec.md`;
  `openspec/specs/api-credits/spec.md`;
  `openspec/specs/inference/architecture.md`; the paths the evidence sections
  of `deployment-state`, `resource-pool-management`, and
  `storefront-publication` cite.
- [ ] New subsystem specification
- [x] `docs/guidance/repository/package-layers.md`,
  `docs/guidance/repository/published-packages.md`,
  `docs/guidance/repository/contract-conformance.md`, and
  `docs/guidance/repository/migrations-at-startup.md`.
- [x] `docs/development/ROADMAP.md` — the inference goal, and the path the
  kit goal names.

### Knowledge to promote

- D1: a family kit lives under its family's directory and `kit/` holds no
  specialization — `docs/guidance/repository/package-layers.md`,
  `docs/development/ARCHITECTURE.md`, `openspec/specs/api-family/spec.md`,
  `openspec/specs/market-composition/spec.md`.
- D2: no permanent destination — the modules do not move;
  `move-escrow-into-alkahest` records its own outcome.
- D3: no permanent destination — nothing changes.
- D4: the authority refuses a pinned key's consumption at another amount —
  `openspec/specs/api-family/spec.md` and its companion's section on the
  gate.
- D5: the selling library takes the stage-event emitter by injection —
  `openspec/specs/api-family/architecture.md`, "Current limits", and the
  exception row's reason in `docs/development/ARCHITECTURE.toml`.
- D6: no permanent destination — an ordering between changes.
- D7: the selling library assembles the settlement composition from the
  resources a storefront passes, and inference composes no dispute policy —
  `openspec/specs/api-family/architecture.md` and
  `openspec/specs/inference/architecture.md`.
- D8: no permanent destination — the tests conform to rules already written.
- D9: no permanent destination — a test moves.
- D10: the inference goal fixes no order — `docs/development/ROADMAP.md`.
- D11: no permanent destination — no compatibility is owed.
- D12: no permanent destination — the notes live in the change index and in
  the changes that receive them.
- D13: no permanent destination — the change's own shape.

## Dependencies and Related Changes

- Builds on `compose-api-family-kit`, which built the kit and is archived on
  this branch; the dependency is released.
- Hands to `move-escrow-into-alkahest` the Alkahest buyer modules in the
  family's buying library, with the question of a buyer-side Alkahest kit.
- Notes for `kit-owned-storefront-auth-and-persistence` an import its
  carve-out places, and for `sign-multi-language-credits-middleware` what the
  ported gates do not yet do.
- Coordinates with `align-package-paths-with-layers`, whose design the
  placement rule returns to.
- Precedes the closeout of `keep-buyer-credentials-private` and
  `derive-buyer-settlement-inputs`, whose documents cite the family's path.
- Precedes `meter-inference-usage`, which removes the gateway from where this
  change leaves it.

## Status

Ready for implementation; planned in `tasks.md`.
