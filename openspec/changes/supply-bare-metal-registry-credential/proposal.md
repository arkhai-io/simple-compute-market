# Bare-metal registry publication credential

Fixes [#281](https://github.com/arkhai-io/simple-compute-market/issues/281).

The bare-metal publisher signs requests but cannot supply the registry's separate write API key. Its dedicated chart also cannot configure the registry URL or trust pin.

## Scope

Read an optional registry API key from the environment, keep it out of configuration representations and diagnostics, and pass it to the existing authenticated registry clients. Expose public registry URL/authority/principals and an optional existing Secret reference in the dedicated chart. Preserve signature verification and credential-free defaults. Do not change market contracts or payment code.

## Permanent documentation impact

- [x] Existing subsystem specifications: storefront publication and deployment state
- [x] Deployment configuration reference
- [ ] Repository-wide architecture: no new dependency or authority boundary

### Knowledge to promote

Registry bearer configuration is independent of the marketplace signer, optional, and Secret-backed in Helm. Promote behavior to `openspec/specs/storefront-publication/spec.md`, deployment to `openspec/specs/deployment-state/spec.md`, and environment/value names to `docs/development/DEPLOYMENT_AND_CONFIG.md`.
