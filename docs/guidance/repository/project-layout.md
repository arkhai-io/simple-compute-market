---
tags: [repository, packaging, python, hatchling]
---

# Project layout

How each Python distribution here is laid out and built, as
[`packaging-python.md`](../engineering/packaging-python.md) and its Hatchling form
give it. The normative requirements are the
[deployment and state specification](../../../openspec/specs/deployment-state/spec.md).

## Project layout

Every distribution builds its wheel with Hatchling, laid out as
[`packaging-python.md`](../engineering/packaging-python.md) gives it, in the
Hatchling form of
[`packaging-hatchling.md`, "The wheel target names the one package"](../engineering/packaging-hatchling.md#the-wheel-target-names-the-one-package),
as `arkhai-vms-listings` declares it:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/arkhai_vms_listings"]
```

The VM negotiation models are data files of this kind
([`packaging-python.md`, "Data files live inside the package"](../engineering/packaging-python.md#data-files-live-inside-the-package)).
Every project installs itself editable
([`packaging-uv.md`](../engineering/packaging-uv.md#every-project-installs-itself-editable)),
and `make check-project-layout` refuses a Makefile, script, or workflow that turns
that off ([`packaging-checks.md`](packaging-checks.md)).
