## 1. One place names the bound release

- [x] 1.1 Add `make/hosted-release.mk` deriving `HOSTED_RELEASE_TRUST` and every
      value that follows from it, composing all paths from `HOSTED_REPO_ROOT`.

      It states no version of its own. `scripts/select-hosted-client-channel.py`
      already owns the relationship between the pinned version and what
      `manifests/` signs, and its docstring says why a third statement must not
      exist. The first draft here added one, `HOSTED_RELEASE_BOUND_VERSION`, and
      was replaced.
- [x] 1.2 Replace the duplicated blocks in `Makefile`,
      `domains/vms/storefront/Makefile`, and `kit/hosted-settlement/Makefile`
      with `HOSTED_REPO_ROOT` plus an include.
- [x] 1.3 Evidence: each Makefile resolves the same trust path, wheel path, and
      release file list as before the change, proven by printing them from all
      three directories and diffing against the values recorded first.

      Identical on the release channel, with two additive differences: the two
      sub-Makefiles now also define `HOSTED_RELEASE_SCHEMA` and
      `HOSTED_RELEASE_FILES`, which they previously left empty and do not use.
      `scripts/tests` passes, 114 tests.

## 2. The client pin has a single source

- [x] 2.1 Use the version `kit/hosted-settlement/pyproject.toml` states, which
      the channel selector already reads, rather than declaring another.
- [x] 2.2 Add `scripts/check-hosted-client-pin.py`, failing with the file and the
      found value when a follower disagrees, and rewriting them under `--fix`.
- [x] 2.3 Run it as an ordinary tree-consistency test under `scripts/tests`, with
      `make check-hosted-client-pin` and `make fix-hosted-client-pin` for hand use.
- [x] 2.4 Evidence: the check passes as the tree stands; mutating one pin fails
      it and names that file; `--fix` restores it. Four unit tests cover the
      agreeing tree, a named laggard, `--fix`, and a file stating no version.

## 3. The bump is one edit

- [x] 3.1 Record in `docs/development/TESTING.md` how to raise the contract:
      which variable moves when a release is published, which moves when this
      source starts consuming a new capability, and that they differ while a
      capability is built locally.
