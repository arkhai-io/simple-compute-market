# Tasks

- [x] Update `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_service.py` to read the optional API key, suppress repr, and supply publication/reachability bearers.
- [x] Extend the authorized environment/client-factory unit coverage in `domains/bare_metal/storefront/tests/test_publication_cli.py` and signed-read coverage in `test_http_system.py` for bearer present/absent.
- [x] Update `helm/charts/bare-metal-storefront/{values.yaml,values.schema.json,templates/deployment.yaml,examples/production-values.yaml,tests/test_render.py}` for public registry settings and Secret-only credential injection; regenerate the umbrella schema with `make helm-values-schema`.
- [x] Patch-bump `domains/bare_metal/storefront/pyproject.toml` and refresh locks with `make lock`.
- [x] Run bare-metal storefront tests, chart render tests using `mise exec helm@3.15.3`, `make check-locks`, and `make check-architecture`.
- [x] Closeout: check comment hygiene and touched imports; review documentation placement and compress task notes; record no roadmap impact and update the campaign index status; validate documentation citations; run `make check-packaging`; record end-to-end evidence or explicitly unrun qualification; after code review promote optional bearer behavior to the storefront-publication spec, Secret/public chart boundaries to deployment-state, and configuration names to DEPLOYMENT_AND_CONFIG; complete the design-promotion record. Preserve signature checks and disclose deployment limits.

## Validation

- Bare-metal storefront: 311 passed, including bearer present/empty/absent and signed-read verification.
- Dedicated and umbrella chart render suites passed with Helm 3.15.3; generated values-schema unit suite: 34 passed.
- `make helm-values-schema` regenerated the umbrella and storefront definitions against this branch's own installed models. No payment implementation or wire schema changed.
- `make check-locks`, `make check-architecture`, and `make check-packaging` passed. `make check-comment-hygiene`, scoped documentation citations, and strict scoped OpenSpec validation passed.
- Setup uses the repository wheelhouse and reinit/lock scripts. On this host the Make caller must prepend the selected Python to PATH; local tests unset inherited proxy variables. Initial failures were interpreter/proxy environment failures, then reruns passed.
- End-to-end pipeline and publication to a deployed authenticated registry are unrun: this worker owns only the checkout, with no deployment target or credentials. Deployed qualification belongs to the follow-on verifier; these results are not deployment evidence.

Permanent decisions are promoted as recorded in `design.md`. Roadmap goals and campaign dependencies are unchanged; the focused repair index row records review pending.
