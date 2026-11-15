---
tags: [repository, testing]
---

# Static configuration tests

What a static configuration test is here, the tools that do its reading, what it
covers, and how it runs. The levels it stands beside are
[`test-levels.md`](../engineering/test-levels.md); chart renders, one of its tools, are
[`chart-render-tests.md`](chart-render-tests.md).

## What a static configuration test is

A static configuration test runs a real tool over committed configuration and asserts
on what that configuration would do, without doing it: no image is built, no container
starts, and no cluster is reached. It is neither a unit test of a class nor an
integration test of a running application: its subject is the committed files, read
the way the tool that consumes them reads them. It is a kind of test beside the four
levels, not a fifth level, and runs where unit tests run. Three tools do the reading
here:

- **Chart renders**, `helm template` over a chart with chosen values
  ([`chart-render-tests.md`](chart-render-tests.md)).
- **Compose renders**, `docker compose config` over a stack's Compose files, such as the
  lanes' image lines in `scripts/tests/test_release_images.py` and the stacks' registry
  settings in `scripts/tests/test_committed_stack_values.py`.
- **Makefile dry runs**, `make -n` of a committed target, reading the recipes it would
  run, following each subproject Makefile it enters. Examples:
  `scripts/tests/test_image_publication_contract.py`, which holds every declared image
  to a build writing its revision tag in `build-dev` and `build-candidate`;
  `scripts/tests/test_change_build_and_helm_targets.py`; and the lane-target cases in
  `test_release_images.py`.

`e2e-tests/tests/unit/`'s image-pin and stack checks are of the same kind.

## What they cover

What committed configuration says — which images a target builds and tags, which image
a Compose service runs, what a chart renders for given values — and two committed
sources held to each other, such as the release declaration and the targets that build
what it declares.

They do not cover whether the commands succeed when they run, whether an image builds,
or whether a stack starts. A build, a lane, or a deployment remains the evidence for
those.

## How they run

In the suite of the scripts or charts they check, beside its unit tests. A test needing
only a tool every runner has, such as `make` or `git`, runs it. A test needing a tool a
runner may lack skips without it, except under that tool's gate variable,
`HELM_REQUIRED=1` or `COMPOSE_REQUIRED=1`, which `tests.yml`'s
`test-deployment-packaging` job sets, so a skip fails there. A test of this kind
needing another such tool gets its own gate, set in that job.
