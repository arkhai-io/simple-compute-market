---
tags: [repository, packaging]
---

# Packaging checks

What `make check-packaging` runs here and what each of its checks fails on. Here the
packaging checks
([`packaging.md`, "Packaging checks run before a commit"](../engineering/packaging.md#packaging-checks-run-before-a-commit))
are `make check-packaging`, run with the typing checks, `make -C <project> typecheck`
in each project whose Makefile has that target.

## Checks

`make check-packaging` builds the wheelhouse and runs every check, including the package architecture check whose rules [`package-layers.md`](package-layers.md) states and [`ARCHITECTURE.toml`](../../development/ARCHITECTURE.toml) encodes. Each is also its own
target. None resolves dependencies, relocks, or contacts a package index; building the
wheelhouse fetches only the build backends each project declares. Every change runs it at
closeout ([this repository's closeout parts, "Packaging"](../../../openspec/README.md#packaging)).

| Target | Fails on |
|---|---|
| `check-uv-setup` | a literal `--upgrade-package`, `--reinstall-package`, or `--refresh-package` in a Makefile or Dockerfile; a Makefile recipe running `uv sync` itself; a `reinit` recipe other than the script call by a path that resolves; a project with tests and wheelhouse packages but no `reinit`; a Dockerfile that rewrites a lock, spells a repository distribution's version, installs from the wheelhouse without the script, calls the script where its stage did not copy it, or copies the wheelhouse into the runtime stage |
| `check-locks` | a lock `uv lock --check --offline` rejects; a lock pinning an internal version the tree does not build; a lock whose record of an internal package disagrees with that wheel's metadata (a requirement added or removed, unconditionally or under an extra in use, or a locked version its specifier no longer admits); a version check it cannot evaluate; a repository distribution resolved from an index or from a local registry other than `.dist`; a lock carrying a lock revision other than 5, the one the repository's minimum uv writes |
| `check-uv-version` | an installed uv older than the minimum that writes the repository's locks, or one whose version cannot be read; `make lock` runs it, and `check-packaging` does not, since it reads the locks without writing them |
| `check-project-layout` | a distribution whose wheel target is not exactly `packages = ["src/<package>"]` with that package present, or that builds with another backend or other build settings; a `[tool.uv]` `find-links` or `cache-keys`; a `[tool.uv.sources]` entry naming a path; `UV_NO_EDITABLE`, `--no-editable`, or `no_editable` in a Makefile, shell script, or workflow |
| `check-architecture` | any of the four parts below failing; it reads only the tree, so it needs no wheelhouse, and it also runs on every push in CI |
| `check-architecture-layers` | a dependency, imported or declared, on a higher layer; packages of one layer depending on each other; a scope its layer may not hold; a project that is unclassified, that does not build exactly one package under `src/`, or whose override row no longer describes it; a rules file or package table naming something that does not exist, a duplicate row, or an owner that is not an open change |
| `check-architecture-scope` | a dependency whose scope is not a subset of the package's own; an identity literal outside a core or kit package's scope (a warning elsewhere) |
| `check-architecture-dependencies` | an internal distribution imported and not declared; a runtime reason for a dependency no longer declared, or now imported (a declaration without an import or a reason is a warning) |
| `check-architecture-kinds` | a contracts or client package depending on something its kind allowlist does not name; a declaration or import outside a package allowlist, the `allowed-dependencies` in a package's own `pyproject.toml`, or a third-party import such a package does not declare; any import of a plugin |
| `check-python-version` | a `.python-version` other than the root one; a literal `--python` version in a Makefile, shell script, or tool phase configuration; a Makefile running uv without exporting `UV_PYTHON` from the root declaration; a CI job running uv without it, setting it before checkout or under a different `if:` than checkout, or a setup pin of another minor version; a Dockerfile `FROM` naming a Python version, using `${PYTHON_VERSION}` without an `ARG` default before the first `FROM`, or a default other than the declared one |

uv records no section for an empty extra, and no extra on the consumer's dependency edge
either, so `check-locks` derives the extras in use from every place that can request one:
the lock's dependency edges, each locked project's `requires-dist`, and the requirements of
the wheels the lock installs. It compares environment markers only to decide which extra a
requirement belongs to, so a same-version wheel that changes nothing but a marker is not
seen; `make lock` followed by an unchanged tree is the stronger proof. It needs `.dist`
built first, which `check-packaging` does.
