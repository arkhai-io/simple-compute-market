# Design

## Decisions

- Use `BARE_METAL_STOREFRONT_REGISTRY_API_KEY`, optional and excluded from dataclass repr. Empty/unset means no bearer. Reuse `MultiRegistryClient.auth` keyed by the configured URL; the signed reachability client receives the same optional `api_key`.
- Add `registry.url`, `registry.authority`, `registry.principals`, and `registry.apiKeySecret.{name,key}` to the dedicated chart. No URL means publication remains unconfigured. A configured registry requires its complete public trust pin. An empty Secret name omits the API-key environment variable.
- Reference an existing Kubernetes Secret, never a plaintext Helm value or a chart-managed credential. Keep this credential separate from the identity signer.
- Patch-bump the storefront distribution for this bug fix and regenerate consuming locks through repository tooling. No wire or payment changes.

## Alternatives

A generic secret environment map would add a broader interface than needed. A bearer in public values would leak into release metadata. Neither is required for this fix.

## Open questions

None.

## Design promotion record

The focused implementation diff was reviewed before promotion. No repository-wide architecture decision or companion rationale is needed: the existing client owns bearer authentication. This repair changes no roadmap goal or campaign dependency.

| Accepted decision | Permanent location |
|---|---|
| Optional bearer on signed publication and reachability, excluded from representations and diagnostics | `openspec/specs/storefront-publication/spec.md#requirement-registry-publication-ownership` |
| Public registry trust and existing Secret-only bearer reference in Helm | `openspec/specs/deployment-state/spec.md#requirement-independently-deployable-bare-metal-seller-role` |
| Environment/value names and absence behavior | `docs/development/DEPLOYMENT_AND_CONFIG.md#bare-metal-role-configuration` |
| Roadmap and campaign disposition | No roadmap impact; focused repair row in `openspec/changes/README.md`, no dependency change |
