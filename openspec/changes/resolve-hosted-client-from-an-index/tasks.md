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

- [ ] 4.1 The producer publishes the released client to the public index. Every
  code change here is complete without it; the suites resolve once it lands.
- [ ] 4.2 Re-run the six consuming suites against the real index rather than
  the wheelhouse. Expect real failures behind them in projects whose tests have
  not run in some time; record those separately rather than folding them into
  packaging.

## 5. Closeout

- [ ] 5.1 **Comment hygiene.** `make check-comment-hygiene`. Then read the
  three Makefiles: the removed gate must leave no comment explaining a
  prerequisite that is gone.
- [ ] 5.2 **Import placement.** No Python imports added; the three script edits
  are call-site changes. Recorded as not applicable.
- [ ] 5.3 **Documentation compliance.** `docs/development/DEPLOYMENT_AND_CONFIG.md`
  gains how the client is obtained; `docs/development/RELEASING.md` gains what
  a staged release is still for. `docs/development/TESTING.md` has a "Raising
  the hosted contract" section the removed comment cited — check it still
  describes a flow that exists.
- [ ] 5.4 **Narrative compression.** Reduce task notes to final behaviour and
  evidence. The rejected alternatives — vendoring the contract source, an
  offline digest gate on `init` — stay in `design.md`.
- [ ] 5.5 **Roadmap currency.** `docs/development/ROADMAP.md`'s hosted
  settlement section records that the client cannot currently be obtained.
  Update it when publication lands, not before.
- [ ] 5.6 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location | State |
|---|---|---|
| An externally produced dependency resolves from a package index; nothing stages it into the wheelhouse | `openspec/specs/deployment-state/spec.md` | Pending |
| `.dist` holds only what this repository builds | `openspec/specs/deployment-state/spec.md` | Pending |
| Verification of a producer's signed release is a publication-time activity that gates no build or test | `openspec/specs/deployment-state/spec.md` | Pending |
| How an externally produced dependency is obtained | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Pending |
