# Registry stack replay

Base: `ca498b1e6` (`dev`, 2026-11-11). The backup is
`pre-rebase/registry-as-published` at `dd0a2edb1`.

The pre-floor rename and demands/API-key repair is superseded by dev's fixed
`v0_3_0_baseline`; it is omitted rather than restoring the deleted Alembic tree.
`019_retained_publications` (since renamed
`20261106_001_registry_retained_publications`, with a refusing downgrade) ships
inside `core_registry/alembic/versions`, after that baseline. Existing baseline, adoption, revision-discovery and command tests
follow the new head; adoption preserves the legacy row and null proofs and reaches
the same schema as a fresh chain. The floor fixture and baseline are unchanged.
Campaign/design conflicts retain dev's archived migration status and PostgreSQL
scope, alongside this PR's retained-publication decision and implementation status.
No publication semantics changed beyond adapting deployment to dev's migration
contract.

Validation after rebuilding `.dist` and refreshing each consumer with its `reinit`:

| Scope | Result |
|---|---|
| Registry `pytest tests -q --tb=short` | 285 passed |
| Registry client `pytest tests -q --tb=short` | 25 passed |
| Core storefront `pytest tests -q --tb=short` | 222 passed |
| VM storefront `pytest tests -q --tb=short` | 1709 passed, 1 skipped |
| Registry client `mypy src` | passed, 5 files |
| VM storefront `mypy src` with its lint extra | 136 errors in 33 files; same count reproduced from dev's source using the same environment |
| `make check-comment-hygiene` | passed |
| `make check-packaging` | passed |

VM listing code has no independent locked test project; its existing tests are
in the VM storefront suite. Registry/core storefront have no declared typing
check. The existing typing restoration owner is
[`type-core-packages`](../../../openspec/changes/type-core-packages/).
No full end-to-end deployment or browser run was requested or performed.

First use (run from the repository root):

```sh
make dist
make -C core/registry reinit
(cd core/registry && uv run --frozen --no-sync python ../../openspec/changes/archive/2026-11-11-store-registry-listings-as-published/first-use.py)
```

Observed health 200, verified seller proof, one search result, and whole-document
replacement retaining the closed status. This now uses the packaged migration
chain over a temporary SQLite file. Its deterministic development identities,
state and cleanup are committed; no service, credentials or resident process is
needed.
