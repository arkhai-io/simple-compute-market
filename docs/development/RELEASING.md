# Releasing Python packages

The repo publishes internal Python packages to PyPI via
`.github/workflows/publish-pypi.yml`:

| Package | Path | Initial version | Internal deps |
|---|---|---|---|
| `market-identity` | `kit/identity/` | 0.1.0 | none |
| `market-core` | `core/` | 0.1.0 | `market-identity` |
| `core-buyer` | `core/buyer/` | 0.1.0 | none |
| `core-storefront` | `core/storefront/` | 0.1.0 | `market-core`, `market-identity` |
| `market-alkahest` | `kit/alkahest/` | 0.1.0 | `market-core` |
| `market-config` | `kit/config/` | 0.1.0 | `market-alkahest` |
| `market-policy` | `kit/policy/` | 0.1.0 | none |
| `provisioning-service` | `domains/vms/provisioning/service/` | 0.1.2 | none |
| `arkhai-storefront-client` | `core/storefront-client/` | 0.4.0 | none |
| `arkhai-registry-client` | `core/registry-client/` | 0.2.0 | none |

## One-time setup (per package)

For each package, configure trusted publishing on PyPI:

1. Create the project on PyPI (first publish requires the name to exist).
   - For first-time release, run `uv build --no-sources` locally and
     `uv publish --token <TOKEN>` once with a manually-issued PyPI token,
     then switch to trusted publishing.
2. Go to `https://pypi.org/manage/project/<pkg>/settings/publishing/`.
3. Add a "GitHub Actions" trusted publisher with:
   - **Owner**: `arkhai-io`
   - **Repository**: `simple-compute-market`
   - **Workflow**: `publish-pypi.yml`
   - **Environment**: `pypi-<pkg>` — e.g.
     `pypi-arkhai-storefront-client`, etc. (matches `environment.name`
     in the workflow).
4. Create the matching environment in this repo at
   `https://github.com/arkhai-io/simple-compute-market/settings/environments`.
   Default environment settings are fine — we don't restrict the deployer.

## Cutting a release

1. Bump the package's `version` field in its `pyproject.toml`.
2. Commit + push to `main` (or merge a PR that touches the package).
3. The `Publish Python packages` workflow detects the path change,
   rebuilds, and publishes to PyPI via OIDC trusted publishing.

The workflow skips packages whose current `version` is already on PyPI,
so version-only commits trigger publishes and other commits don't.

`workflow_dispatch` is also available — it forces a publish attempt for
every package whose current version isn't yet on PyPI.

## Versioning policy

We follow [SemVer](https://semver.org) per package:

- **Major** — incompatible API change (e.g. removing a public function,
  changing a returned shape that consumers index into).
- **Minor** — new public API, backwards compatible.
- **Patch** — bug fix or internal change.

Cross-package compatibility is enforced via dependency constraints in
`pyproject.toml`. Use `>=X.Y` (lower bound) for forward compatibility,
or `>=X.Y,<X+1` if a breaking major release is anticipated.

## Local development

`tool.uv.sources` workspace path overrides remain in `pyproject.toml`
for local dev — they let `uv sync` pick up sibling-package changes
immediately without a publish round-trip. Building wheels with
`uv build --no-sources` strips those overrides so the wheel records
plain PyPI deps. The publish workflow always uses `--no-sources`.

## Troubleshooting

- **403 from PyPI** — trusted publishing isn't configured for this
  package, or the environment name doesn't match. Check both
  `pypi.org/manage/project/<pkg>/settings/publishing` and the workflow's
  `environment.name`.
- **400 "version already exists"** — the version-skip check should have
  caught this. If it didn't, the PyPI cache may be stale; the workflow
  retries on the next push.
- **Workflow runs but nothing publishes** — check that the path filter
  matched. Files outside `<pkg>/**` don't trigger a publish for that
  package.
- **Wheel records the workspace path** — `uv build` was run without
  `--no-sources`. The workflow always passes it; locally, run
  `uv build --no-sources` to test.
