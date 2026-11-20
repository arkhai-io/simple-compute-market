---
tags: [engineering, packaging, hatchling]
---

# Packaging with Hatchling

The Hatchling form of the project layout ([Packaging Python](packaging-python.md)).

## The wheel target names the one package

The wheel target's `packages` entry names the distribution's one import package at
`src/<package>`, and nothing else in the build configuration remaps, includes, or
excludes files:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/example_package"]
```
