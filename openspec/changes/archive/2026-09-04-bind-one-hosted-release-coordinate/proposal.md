## Why

Raising the hosted contract means editing the same version in several files that
have no way to disagree out loud, and they already do. `manifests/` binds
`hosted-settlement-v0.2.1-trust.json` in three Makefiles, while three
`pyproject.toml` files pin `arkhai-hosted-settlement-client==0.3.0`. Both are
deliberate — 0.3.0 is built locally and not yet published — but nothing states
that, and nothing notices when a bump lands in two of the six places.

With the authority now at 0.4.0, the next bump would touch six literals across
five files again. The version a consumer asserts should come from the release it
bound, and where a literal is unavoidable it should appear once.

## What Changes

- One make fragment owns every hosted-release coordinate, and states no version.
  It asks `scripts/select-hosted-client-channel.py`, which already derives the
  whole binding from the pinned version and what `manifests/` signs. The three
  Makefiles set only their own path to the repository root and include it.
- A caller may still name a trust configuration directly, and then everything
  follows from that file's contents, as it already did.
- The client pin gains a check. The two follower distributions must agree with
  `kit/hosted-settlement/pyproject.toml`, which the selector already treats as
  the statement of record; disagreement is named with the file, not discovered
  later as a resolver error. A `--fix` mode moves them.
- Raising the contract becomes one edit and one command, with no Makefile
  touched.
- One behavior does change, and it is the defect this removes: with the pin
  ahead of the last signature, `verify-hosted-release` verified the last signed
  release while the tree installed a different one, and passed. It now says the
  pinned version is unsigned and succeeds, which is the state the internal
  channel already describes. The protected path is untouched and still fails
  closed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is build configuration: which files state a version, not what any
component does. The change sets `skip_specs: true`.

## Impact

- `make/hosted-release.mk` (new), `Makefile`, `domains/vms/storefront/Makefile`,
  `kit/hosted-settlement/Makefile`.
- `tools/check_hosted_client_pin.py` (new), wired into the ordinary check target.
- `kit/hosted-settlement/pyproject.toml`,
  `domains/bare_metal/storefront/pyproject.toml`,
  `domains/bare_metal/buyer/pyproject.toml`: unchanged in value, now checked.
