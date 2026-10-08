## Why

Marketplace roles persist *accepted artifacts*: records whose exact content was signed
by a counterparty, pinned by a content digest, or used to derive an identity another
service holds. Negotiation messages and terms, accepted settlement plans, accepted
hosted bindings, lease-ready results and evidence, and fulfillment identities derived
from them are all accepted artifacts. They can outlive many releases — a bare-metal
contract can run for a year.

The repository has no rule for evolving them. `unify-host-identity` found the gap:
renaming one field inside bare-metal terms left three choices — rewrite signed
content (breaks the proof), refuse to upgrade until every live contract ends (not
viable for year-long contracts), or reset the database (acceptable only because bare
metal is unreleased). None is a patching strategy.

A second, sharper defect sits beside the gap. The bare-metal storefront verifies a
stored digest by re-serializing the loaded record through the *current* model and
hashing the result (`arkhai_bare_metal_storefront/models.py`'s lifecycle validator;
`arkhai_bare_metal/evidence.py`'s result check). Renaming a field, or adding one with
a non-`None` default, makes untampered stored records fail to load. The check proves
"this record still matches today's code", not "these are the bytes that were
accepted".

One precedent already exists: hosted-fiat keeps historical card-only accepted rows
decodable for recovery under their original identities
(`openspec/specs/settlement-servicing/spec.md`). This change generalizes it.

## What Changes

- Establish a repository-wide rule for accepted artifacts:
  1. **Never rewrite accepted content.** Stored accepted artifacts are immutable
     bytes. Migrations may rewrite derived, unsigned state freely.
  2. **Verify over stored bytes.** A digest or signature is checked against the
     exact stored canonical bytes, never against a re-serialization through a live
     model.
  3. **Stop producing a kind; keep reading it.** Retiring an artifact `kind` stops
     new production immediately. A read-only decoder for the retired kind remains,
     converting to the current in-memory model.
  4. **Retire decoders by measurement.** Each retained decoder has a count of
     non-terminal records that still need it. The decoder is removed once that count
     is zero on every deployment — so contracts retire their own kinds by ending, and
     no operator is forced to drain.
  5. **Never rename a kind retroactively.** Identities derived under a kind stay
     under it.
- Fix bare-metal digest verification to rule 2.
- Add retained-decoder and live-count machinery, first for `bare_metal.v1`, and
  decide whether it is shared kit machinery or per-domain.
- Promote the rule to `docs/development/ARCHITECTURE.md`'s schema-evolution guidance
  and to `deployment-state`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: accepted artifacts evolve by retained readers and are verified
  over stored bytes.

## Non-Goals

- Do not reintroduce a `bare_metal.v1` decoder for the preprod reset performed by
  `unify-host-identity`; that state is gone by design. The first retained decoder is
  for whichever kind is next retired after this change lands.
- Do not change what any artifact contains or how any identity is derived.
- Do not migrate hosted-fiat's existing recovery-only card path; confirm it already
  satisfies the rule, and cite it as the precedent.

## Status

Proposed for a future session. Not planned. **Must land before bare metal is
released**, because after release a reset stops being acceptable.

## Impact

- **Affected code (expected):** `domains/bare_metal/storefront` lifecycle model and
  persistence; `domains/bare_metal/src/arkhai_bare_metal/evidence.py` and
  `hosted_contract.py`; possibly `kit/negotiation-runtime` for transcript storage; a
  shared decoder registry if one is chosen.
- **Affected data:** stored accepted artifacts gain a stored canonical-bytes form
  where they lack one. Additive.
- **Wire:** none.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Build, packaging, and initialization"'s
      schema-evolution paragraph gains the accepted-artifact rule.
- [x] Existing subsystem specification — `deployment-state`.
- [ ] New subsystem specification — none.
- [ ] No permanent documentation change — not applicable.

### Knowledge to promote

- The five-part accepted-artifact rule — `ARCHITECTURE.md` and
  `openspec/specs/deployment-state/spec.md`.

## Dependencies and Related Changes

- **Found by `unify-host-identity`**, which reset the preprod bare-metal storefront
  instead of applying this rule.
- **Blocks bare-metal release** — `add-bare-metal-hosted-settlement` and any change
  that release-qualifies the bare-metal stack.
- Precedent: hosted-fiat's recovery-only card path.
