---
tags: [repository, testing]
---

# Test targets

How this repository's aggregate test targets run, locally and in CI.

## Aggregate test targets

The aggregate Make targets, `make test` among them, are held to [`test-levels.md`, "Aggregate test targets"](../engineering/test-levels.md#aggregate-test-targets).

## CI runs `make test`'s targets

CI's test matrix runs `make test` as a change's validation runs it locally: one
job per target `make test` is made of, each running that target after `make
dist-ci`, so the Make dependency graph, rather than the workflow, owns the wheel
inventory, the build order, and how each suite is invoked. A suite passes in CI
exactly when it passes under `make test`; `scripts/tests/test_tests_workflow.py`
holds the matrix to `make test`'s targets. The jobs set
`_TYPER_FORCE_DISABLE_TERMINAL`, because Typer forces Rich's terminal styling
whenever `GITHUB_ACTIONS` is set, which a local run never sees.
