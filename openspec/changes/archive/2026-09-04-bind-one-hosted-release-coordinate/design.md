## Context

Three things named a hosted version, for three different reasons, and only one
of them was ever the same question.

| literal | what it answers | derived before |
| --- | --- | --- |
| `HOSTED_RELEASE_TRUST` filename, ×3 Makefiles | which published release is bound | no |
| `HOSTED_LOCAL_HOSTED_VERSION` | which locally built producer a development lane binds | yes, read from the producer's own Makefile |
| `arkhai-hosted-settlement-client==`, ×3 pyprojects | which contract this source is written against | no |

Everything downstream of the trust manifest was already derived from its
*contents* — release version, schema version, wheel filename, release file list.
That part was right. What was left was the manifest's own filename, restated
three times with three different relative paths, and the pin, restated three
times with no relation to it.

## Decisions

**The answer was already written; nothing used it.**
`scripts/select-hosted-client-channel.py` derives the entire binding from the
version `kit/hosted-settlement/pyproject.toml` pins: whether `manifests/` holds
a trust configuration signing it, and if so that config's path, manifest name,
wheel name, and schema. Its own docstring warns that a third statement of either
fact "would be the first thing to disagree with the other two, and nothing would
notice" — which is exactly what the Makefiles were. So the fragment calls the
selector rather than introducing a variable of its own, which was the first
design here and would have been that third place.

**A make fragment, not an exported variable.** The root Makefile invokes the
sub-Makefiles with `cd domains/vms/storefront && make`, so an exported
`HOSTED_RELEASE_TRUST` would arrive holding a path relative to the wrong
directory. Each Makefile sets `HOSTED_REPO_ROOT` — the one thing only it knows —
and includes the fragment, which composes every path from that.

**The trust file stays an input, not only an output.** The default comes from
the selector, but `HOSTED_RELEASE_TRUST ?=` still honours a caller who names
one, and then version, schema, wheel, and file list are read from that file's
contents. `test_the_build_names_the_artifacts_of_the_release_it_binds` depends
on exactly this, and it is the right property to keep: pointing at a release
should be enough to bind it.

**An unsigned pin states itself instead of verifying something else.** With the
pin ahead of the last signature — today, 0.3.0 pinned and 0.2.1 signed —
`verify-hosted-release` used to verify 0.2.1 while the tree installed 0.3.0, and
pass. That is a false assurance, and removing the hardcoded filename removes it.
It now says the pinned version is unsigned and succeeds, because an unsigned pin
is a state the design supports: the wheel comes from the producer's
access-controlled index or a local build. Nothing is loosened, because a
protected run binds a signed release by construction and is therefore on the
`release` channel; were it ever to land here it would carry an empty `--trust`
and fail closed in the verifier.

**The pin is checked, not derived.** A `pyproject.toml` dependency cannot read a
JSON file, and loosening the pin to a range was rejected when the pin was
introduced — an exact pin is how a consumer states the contract it was written
against. The source of truth is the file the selector already reads, and
`scripts/check-hosted-client-pin.py` asserts the two follower distributions
agree with it, with `--fix` to move them.

## Risks

**A check that only runs in one target is a check people route around.** It runs
as an ordinary test under `scripts/tests`, alongside the other tree-consistency
contracts, rather than beside the release targets.

**`make` include ordering.** The fragment uses `?=` throughout, so a variable set
on the command line or in the environment still wins, which is how the local
development lane, CI, and the release-tooling tests already override these.

**One test had to change.** `test_the_released_producer_identities_come_from_the_trust_config`
reached a trust config only because the pinned version happened to be signed. It
now names the config it reads, like its sibling does, so it asserts that the
identities are derived rather than that a particular version is current.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| One pin states the hosted contract and the whole binding derives from it; raising the contract is one edit and one command | `docs/development/TESTING.md` — "Raising the hosted contract" |
| Every Makefile reads the binding from `make/hosted-release.mk` rather than naming a release itself; each sets only `HOSTED_REPO_ROOT` | `docs/development/TESTING.md` — "Raising the hosted contract" |
| A caller may still name a trust configuration directly, and version, schema, wheel, and file list then follow from that file | `make/hosted-release.mk`, whose `?=` defaults are the contract; procedure documented in `docs/development/TESTING.md` |
| Follower distributions must agree with `kit/hosted-settlement/pyproject.toml`, and disagreement is named with the file rather than surfacing later as a resolver error | `scripts/check-hosted-client-pin.py`, run as an ordinary test under `scripts/tests` |
| `verify-hosted-release` no longer passes when the pin is ahead of the last signature — it names the disagreement instead | `docs/development/TESTING.md` — "Raising the hosted contract" |
| Why the fragment calls the selector rather than introducing its own variable, why an exported variable fails across `cd`-invoked sub-Makefiles, and why the check runs as a test rather than beside the release targets | This change's `design.md` |

This change carries no delta specs: it changes how the repository binds an external release, not observable market behavior, so no subsystem contract owns it.

