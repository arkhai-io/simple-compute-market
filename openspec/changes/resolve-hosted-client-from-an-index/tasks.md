# Tasks

Sections 1 to 3 are implemented and verified. Section 4 is publication, owned
by the producer. Section 5 is what publication makes verifiable.

Verification used a wheelhouse standing in for the index: the released client
built from the producer's source into `.dist`, where `--find-links` finds it.
The bytes are the ones the trust configuration pins
(`5764d9e5…7ea7f35`), so what the suites resolved is what the index will serve.
That establishes the packaging change and not the publication.

## 1. Remove the gate from build and test

- [x] 1.1 `kit/hosted-settlement/Makefile`: `init` and `reinit` no longer
  depend on `verify-hosted-release`.
- [x] 1.2 `domains/vms/storefront/Makefile`: same.
- [x] 1.3 The comment in `kit/hosted-settlement/Makefile` explaining why the
  gate sat on `init` and not on `build` is replaced by one stating what is true
  now: the client is an ordinary external dependency, and verification of a
  producer's release is a publication-time concern that gates nothing here.
- [x] 1.4 `dist-release` no longer calls `verify-hosted-release`.
  `verify-hosted-release` remains a target, with its script and its 186 tests
  unchanged, for a path that consumes a staged release. No build or test target
  invokes it.

## 2. Remove staging from the wheelhouse

- [x] 2.1 `dist-hosted-client` deleted. It copied seven release files into
  `.dist` when a staged directory differed from it, and no-opped when they were
  the same path — which is every default invocation, so `make dist` reported
  success having produced no client.
- [x] 2.2 Removed from `dist`, `dist-kits`, `dist-bare-metal-buyer`, and
  `.PHONY`.
- [x] 2.3 `scripts/resolve-review-scope.py` and its test: `kit/hosted-settlement`
  builds through `dist-kits` alone.
- [x] 2.4 `scripts/tests/test_hosted_compose_contract.py` split the root
  Makefile on `dist-hosted-client:` to bound the protected harness target.
  Repointed at the next surviving target.
- [x] 2.5 The same file's derivation test ran `make -n dist-hosted-client` to
  prove artifact filenames come from the trust configuration rather than being
  spelled out. Repointed at `verify-hosted-release`, which still derives the
  client wheel filename. The generated contract documents are no longer checked
  there because the build no longer names them; the property is narrower and
  still real.
- [x] 2.6 `review-wheelhouse-prepare` simplified. It copied staged release
  inputs to a temporary directory and handed them back to `dist`, because
  `dist-clean` would otherwise delete artifacts that were received rather than
  built. `dist` builds everything it produces, so a clean rebuild loses
  nothing.
- [ ] 2.7 `HOSTED_RELEASE_FILES` in `make/hosted-release.mk` now has no
  consumer — `review-wheelhouse-prepare` was the last. Left in place rather
  than removed in the same pass, because it has two branches in that file and
  removing it is a separate small edit worth its own review. It is dead as it
  stands and should not survive closeout.

## 3. Verification

- [x] 3.1 `make dist` succeeds and produces 38 wheels, none of them the hosted
  client. `.dist` now holds only what this repository builds.
- [x] 3.2 `kit/hosted-settlement`: **187 passed.** This suite could not run at
  all before; it failed on a missing manifest before its environment was built.
- [x] 3.3 `make test-release-tooling`: **186 passed**, covering the verifier,
  the wheelhouse contract, the compose contract, and the review-scope resolver
  — the three files this change edits tests in.
- [x] 3.4 With the client absent, `kit/hosted-settlement` fails at dependency
  resolution naming the missing distribution, rather than at a gate naming a
  missing manifest. One failure mode instead of two, and the surviving one says
  what is wrong.
- [x] 3.5 `domains/vms/storefront` gets past the gate and past the hosted
  client, then fails resolving `torch>=2.7.0` for a non-current platform. Not
  this change's, and not hosted-settlement-related: a pre-existing constraint
  in that project's environment matrix. Recorded as a finding against that
  project rather than fixed here.

## 4. Publication — owned elsewhere

- [x] 4.1 The producer publishes the released client to the public index. Every
  code change here is complete without it; the suites resolve once it lands.
  Published. The wheel on the index hashes to `5764d9e5…7ea7f35`, the digest
  the trust configuration pins, so what the index serves is what the manifest
  binds.
- [x] 4.3 First real failure behind the gate, and it is not a code defect.
  `domains/apicredits` `test-domain` failed collecting
  `test_hosted_settlement_contract.py`: `SettlementOption` missing from the
  installed `market_core.schemas`. The symbol is present in `core/` source and
  in the `arkhai_core-0.2.0` wheel in `.dist`. The installed copy was an older
  build of the same version number, so `uv` saw 0.2.0 already satisfied and did
  not replace it. A fresh environment passes: **39 passed**.

  The cause is structural rather than incidental. `test-domain` runs
  `uv run --find-links $(DIST_DIR) pytest tests -q` with no `init` and no
  `reinit`, and the domain root Makefile has no force-reinstall target at all —
  its own `service/` sibling has one, and every other project in the repository
  does. Internal wheels change contents without changing version, which is what
  `reinit` and its `--reinstall-package` flags exist for, so a project that
  reaches its tests without passing through one tests whatever it installed
  first.

  This is the same shape as `domains/bare_metal/buyer` having no `test` target:
  a project that does not run the way the repository runs things, and is
  therefore silently testing something other than the current tree.

  Fixed: a `reinit` following the repository's established pattern, reinstalling
  the four internal wheels the domain declares, with `test-domain` depending on
  it as every sibling's `test` does.

  A caution learned while verifying it. `uv` hardlinks installed files from its
  cache, so editing a file inside `.venv` edits the cached wheel too. An attempt
  to simulate a stale install that way corrupted the cache, and `reinit`
  faithfully restored the corruption — which looked like the fix not working.
  It was the test that was wrong. Where a cache entry is genuinely stale for a
  version whose contents changed, `--reinstall-package` reinstalls from that
  cache and `uv cache clean <package>` is what clears it.

- [x] 4.4 A second, unrelated failure in the same suite:
  `test_storefront_domain_imports_resolve_without_a_raw_source_copy` created
  three throwaway environments with `uv venv` and no interpreter pinned, so each
  took `uv`'s default. Where that default is newer than the available wheels —
  3.14 on the reporting machine — the install fell back to building
  `pydantic-core` from source and failed for a reason unrelated to the wheel
  resolution being tested. It passed here only because this machine's default
  was older.

  Pinning the throwaway venvs to the suite's own interpreter was necessary and
  not sufficient: the project venv was itself 3.14, so the pin faithfully
  reproduced the problem. The cause is that the whole `domains/apicredits`
  family declared `requires-python = ">=3.12"` with no upper bound, and its
  dependency set has no wheels for 3.14.

  Sixteen projects in this repository already carry `<3.14` for exactly this
  reason; the six in this family were missed. Bounded to match, after which
  `uv` selects 3.13 and the suite passes. Both parts are kept — the bound stops
  an unsupported interpreter being selected, and the pin stops the throwaway
  environments diverging from the one under test.

- [x] 4.5 A coupling this change created, found the same way.
  `tests/test_distribution.py` requires
  `arkhai_hosted_settlement_client-<pinned>-py3-none-any.whl` to be present in
  `.dist`, and asserts on its absence. `make dist` no longer puts it there, so
  the fixture fails for eight of the file's tests.

  It never arrived from `make dist` before either — `dist-hosted-client`
  no-opped whenever the staged directory and `.dist` were the same path — so
  this test has always depended on someone having staged a release by hand. It
  is the same latent breakage as the six suites, in a place that reads as a
  packaging test rather than a hosted-settlement one.

  Not fixed here, because the fix depends on the destination. Once the client
  resolves from an index the fixture should stop copying it out of `.dist` and
  let resolution supply it, which cannot be written against an index that has
  nothing in it yet. Verified that the suite passes with the client present:
  **39 passed**.

- [x] 4.2 Re-ran the consuming suites against the index, with the client absent
  from the wheelhouse entirely. Five pass: `kit/hosted-settlement` 187,
  `domains/bare_metal/storefront` 124, `domains/apicredits/storefront` 77,
  `domains/apicredits/buyer` 17, and `domains/apicredits` 39. Their locks now
  record `https://pypi.org/simple` and a `files.pythonhosted.org` URL rather
  than a path into `.dist`.

  `domains/vms/buyer` and `domains/vms/storefront` fail resolving
  `torch>=2.7.0` for a platform absent from their environment matrix. Not
  hosted-settlement's and not this change's: the same failure appears with the
  client present. Recorded as a finding against those projects.

  `domains/bare_metal/buyer` has no Makefile at all, so there is nothing to
  run — the finding the original handoff recorded, confirmed.

- [x] 4.6 `tests/test_distribution.py` split. Structural assertions — what each
  wheel carries, requires, and exports — read the archives directly and need no
  environment: 7 tests, ~8s. Installation behaviour, which creates throwaway
  environments to assert what resolves with only wheels present, is now
  `test_distribution_install.py`: 3 tests, ~13s. The shared wheel-building
  fixture and its helpers moved to `tests/conftest_wheels.py`.

  The split is worth it because a collection error takes a whole file with it.
  Every failure this file produced during this session was the install half
  breaking on interpreter selection or a missing artifact, and the structural
  half — which would have passed — did not run at all.

- [x] 4.7 Three Pydantic shadow warnings filtered rather than fixed, scoped to
  the two modules that raise them. The field is named `schema` because that is
  the wire key: it is serialized into HTTP request bodies and into the
  canonical JSON that issuance evidence is digested and signed over. Renaming
  it with an alias would require every `model_dump` call to pass `by_alias=True`
  in the same commit — four call sites, two of them feeding signed digests —
  and a missed one changes an emitted key silently. That is a contract change
  with signature consequences, not a cleanup, and it wants its own change and
  its own verification.

## 5. Closeout

- [x] 5.1 **Comment hygiene.** `make check-comment-hygiene` passes. Read the
  three Makefiles: the removed gate must leave no comment explaining a
  prerequisite that is gone.
- [x] 5.2 **Import placement.** No Python imports added; the three script edits
  are call-site changes. Recorded as not applicable.
- [ ] 5.3 **Documentation compliance.** `docs/development/DEPLOYMENT_AND_CONFIG.md`
  gains how the client is obtained; `docs/development/RELEASING.md` gains what
  a staged release is still for. `docs/development/TESTING.md` has a "Raising
  the hosted contract" section the removed comment cited — check it still
  describes a flow that exists.
- [ ] 5.4 **Narrative compression.** Reduce task notes to final behaviour and
  evidence. The rejected alternatives — vendoring the contract source, an
  offline digest gate on `init` — stay in `design.md`.
- [x] 5.5 **Roadmap currency.** `docs/development/ROADMAP.md` recorded that the
  client could not be obtained. It can; the paragraph now describes how it is
  obtained and what the index does and does not attest, which is durable rather
  than a note about a gap that closed.
- [ ] 5.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| An externally produced dependency resolves from a package index; nothing stages it into the wheelhouse | `openspec/specs/deployment-state/spec.md` | Pending |
| `.dist` holds only what this repository builds | `openspec/specs/deployment-state/spec.md` | Pending |
| Verification of a producer's signed release is a publication-time activity that gates no build or test | `openspec/specs/deployment-state/spec.md` | Pending |
| How an externally produced dependency is obtained | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Pending |
