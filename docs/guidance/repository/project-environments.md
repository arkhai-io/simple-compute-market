---
tags: [repository, packaging, uv]
---

# Project environments

How each Python project here gets its environment, and what its `Makefile` must
allow.

## Project environments

A project's `reinit` target is one line:

```make
reinit: ## Sync this environment, refreshing the internal wheels its lock installs. Run make dist first.
	python3 ../../scripts/uv_project.py reinit
```

It syncs the environment and upgrades and reinstalls every internal package. It may
rewrite `uv.lock` when an internal wheel's requirements changed without a version bump;
commit that rewrite. `init` and `install` targets depend on `reinit` rather than syncing
themselves; test and service targets use `uv run --find-links $(DIST_DIR)` against the
environment `reinit` built. A project with tests whose lock installs anything from the
wheelhouse must have a `reinit` target.

## The interpreter stays configurable

A project's own `Makefile` must keep its interpreter selection configurable so the
offline review environment can use the wheelhouse's declared Python version
([`TESTING.md`, "Offline Review Validation"](../../development/TESTING.md#offline-review-validation)).
