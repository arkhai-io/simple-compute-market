## Context

Eight projects depend on a client wheel produced outside this repository. Three
channels can deliver it today — assets on a signed release in the producer's
repository, an authenticated private package index, and a sibling checkout —
and none is reachable from a plain clone or a forked pull request. No index is
configured for it in any `pyproject.toml`.

The build layer compensated by treating `.dist` as a delivery inbox and by
gating `init` on verifying the signed release. Both compensations are load
bearing today and both are in the wrong layer: the first conflates artifacts
this repository builds with one it receives, and the second makes an
attestation about a deployed authority a prerequisite of running unit tests.

Ten variables in `make/hosted-release.mk` and thirty-one in the root `Makefile`
carry the state this arrangement needs, two of them computed by `$(shell uv run
…)` at parse time on every invocation of `make` — including `make help` — with
failures discarded by `2>/dev/null`.

## Goals / Non-Goals

**Goals:** `make dist` and `make test` succeed from a clean checkout with no
producer access; verification of a producer's release happens where a
publication happens and nowhere else; `.dist` holds only what this repository
builds.

**Non-Goals:** the end-to-end harness, its two targets, its locally built
producer path, and the contents of the release verifier. Publication of this
repository's own artifacts, which `publish-wheels-through-a-gate` owns.

## Decisions

### D1. The client is an external dependency, resolved from an index

It is declared in `pyproject.toml`, resolved by `uv`, and pinned by the
lockfile, exactly as every other third-party dependency is. Nothing stages it,
nothing copies it, and no target special-cases it.

The index is the public one, so nothing here configures an index either. A
private registry in the producer's own organization was the first plan and is
closed: organization policy refuses anonymous reads on it. The public index is
also where this repository's own distributions already go, and where the
wrapper that declares this client as a dependency already sits — declaring a
dependency the index does not carry, which is why every external installation
of it fails today.

This is the decision the rest follow from. A staged binary needs a stager, and
a stager needs credentials, a channel, and a failure mode — which is where the
gate, the seven-file derivation, and the two-branch producer selection all came
from. Removing the staging removes their reason to exist.

*Alternative considered:* vendor the contract source into this repository and
build it here. It works — the producer's wheel is reproducible, so a
source-built wheel matches the digest its trust configuration pins — and it was
the first shape proposed for this change. Rejected because it gives the contract
two homes. The client is the producer's public interface; a second copy here
would be a fork that agrees by construction until it does not.

### D2. Nothing on the build or test path verifies a release

`init`, `reinit`, and `dist-release` stop invoking `verify-hosted-release`. The
verifier keeps its behaviour, its arguments, and its tests.

What guarantees a build used the intended client is the lockfile, which records
the resolved version and its hash, and — once
`publish-wheels-through-a-gate` lands — the release inventory, which records
what actually resolved. Both are cheaper and better placed than re-verifying a
signature that describes a service this build does not deploy.

The trade is real and worth stating: a developer can now build against a
locally modified client. That is a property, not a regression. Working against
uncommitted dependency source is an ordinary development activity, and the
place to establish that a published artifact used a trusted dependency is
publication, not `make test`.

*Alternative considered:* keep a gate on `init` but make it an offline digest
check — hash the resolved client, compare against the trust configuration's
pin. It is a genuine check and it runs without producer access. Rejected: it
re-imposes clean-tree discipline on the development loop to defend against a
threat the development loop does not face, and it puts verification back in the
layer this change is removing it from.

### D3. `.dist` holds only what this repository builds

With the client resolved from an index, this becomes true by construction
rather than by convention, and no `.vendor` directory or Dockerfile change is
needed. The Dockerfiles keep `COPY .dist/ /.dist/` and `--find-links /.dist`
unchanged; the client arrives through the index alongside every other external
dependency.

A consequence worth recording: the storefront image resolves the client at
image build and carries it inside the image. A promoted image therefore needs
no client index at its destination, and the public index is required for
building and for external consumers rather than for deployment.

### D4. The harness keeps the staging path it still needs

`prepare-hosted-compose.py` reads the OpenAPI, conformance, and migrations
documents from a staged release, and `gates.py` reads the conformance document
at run time and hashes it against the value the manifest signed. Those are the
only remaining readers of the five contract documents outside the verifier.

`HOSTED_RELEASE_DIR` and the file derivation therefore survive as harness
inputs and leave the `dist` graph. When the harness is replaced, they leave with
it and this repository needs none of the seven release files.

### D5. Documentation states how a dependency is obtained

`docs/development/DEPLOYMENT_AND_CONFIG.md` gains the index and the resolution
path. Neither it nor `docs/development/RELEASING.md` currently says how the
client is obtained, which is why staging survived as folklore.

## Risks / Trade-offs

- **[The client is not published when this lands]** → The code changes are
  complete and verified against a wheelhouse standing in for the index; what
  remains is publication, which another repository owns. Until then a consuming
  suite fails at dependency resolution with a message naming the missing
  distribution, which is an ordinary and legible failure rather than the two
  it replaces.
- **[Unblocked suites fail for unrelated reasons]** → Expected. Six suites have
  not run in some time. Record them as findings against their owners; do not
  fix packaging and behaviour in one change.
- **[A developer builds against a modified client without noticing]** →
  Accepted deliberately (D2). Publication is where it is caught.
- **[Removing the gate is read as weakening supply-chain posture]** → The
  verifier is unchanged and still runs where a release is consumed. Record the
  before/after invocation sites in the promotion note so the reduction in
  coverage is explicit rather than discovered.
- **[The harness breaks because its client no longer arrives in `.dist`]** →
  It resolves from the index like every other consumer; `hosted-stripe-test`
  already runs `uv run --frozen --find-links "$(DIST_DIR)"` and gains an index
  rather than losing a directory. Verify by running both harness targets before
  archive.

## Migration Plan

1. Land the index and the producer's publication to it. Nothing here works
   before that.
2. Declare the index and re-lock. Confirm `make dist` produces a `.dist`
   containing no client wheel and that resolution still succeeds.
3. Remove the gate from `init`/`reinit` in the two Makefiles and from
   `dist-release`.
4. Remove `dist-hosted-client` from the `dist` graph and the variables that
   served only it.
5. Run all eight consuming suites. Separate genuine failures from packaging.
6. Run both harness targets to confirm D4 held.

## Permanent Documentation Promotion

The resolution path and the index belong in
`docs/development/DEPLOYMENT_AND_CONFIG.md`. The rule that verification is a
publication-time activity, and the layer boundary that keeps `.dist` to
locally built artifacts, belong in `openspec/specs/deployment-state/spec.md`
and its `architecture.md` companion. `docs/development/RELEASING.md` gains how
an external dependency is obtained, which it does not currently state.
