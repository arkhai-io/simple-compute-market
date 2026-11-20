---
tags: [engineering, packaging, python]
---

# Packaging Python

The Python forms of the packaging rules: how a distribution lays out the import
package it ships and the data that package loads. The build backend's form is
[Packaging with Hatchling](packaging-hatchling.md); the environment's is
[Packaging with uv](packaging-uv.md).

## One import package per distribution

Every distribution builds its wheel from exactly one import package, at
`src/<package>`.

## Nothing remaps the package

Nothing in the build configuration remaps, includes, or excludes files, so a module
added under `src/<package>` ships without a packaging edit, and the installed name is
the directory name.

## Data files live inside the package

Data files a package loads, such as a model or a schema it reads at run time, live
inside the package directory and ship with it.
