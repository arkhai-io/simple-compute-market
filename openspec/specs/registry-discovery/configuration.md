---
tags: [repository, configuration]
---

# Registry configuration

How the registry resolves its configuration and what a deployment gives it, as this
repository's instance of
[`configuration.md`](../../../docs/guidance/engineering/configuration.md). The
other services' profile configuration is
[`DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#profile-based-configuration).

## Registry descriptor configuration

The registry is a Pydantic-settings service rather than a Dynaconf service, but it
takes the profile resolver variables the Dynaconf services take. Each setting is
read by its variable name from, a later source winning on a key both state: the
dotenv files `.env.local`, `.env` and `/app/shared-env/.env`, each skipped when
absent; then `<CONFIG_DIRECTORY>/config-<profile>.env` for each entry of
`ACTIVE_PROFILES`, in order, each skipped when absent; then the process
environment. A profile file has the dotenv form, so a JSON value goes on one
single-quoted line. The registry parses `ACTIVE_PROFILES` itself rather than
through `arkhai-kit-config`, which builds only Dynaconf loaders. The filter
specification is a setting, `REGISTRY_FILTER_SPEC_PATH`, unset meaning the
packaged `filter-spec.yaml` ([`core/registry/README.md`](../../../core/registry/README.md)
lists the sources and settings).

Every Compose registry takes its `REGISTRY_*` values from committed profiles in
`dev-env/registry/`
([`DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition)).
The registry chart renders
its values — identity, descriptor, `config.*`, `service.port`, the credential
file's path and the filter specification path — into a ConfigMap key,
`config-production.env`, mounted at `/app/config/config-production.env`, and the
Deployment's environment holds only `CONFIG_DIRECTORY=/app/config` and
`ACTIVE_PROFILES`. Secret settings — the bootstrap key
`REGISTRY_BOOTSTRAP_API_KEY` and the administrator key `REGISTRY_ADMIN_API_KEY` —
arrive as `secretProfile: {secretName, profile}`: a pre-existing Secret holding
`config-<profile>.env`, as External Secrets writes one, mounted beside the
rendered profile and appended to `ACTIVE_PROFILES` after `production`, so a
setting it states overrides the rendered one. The profile may not be named
`production`. `auth.bootstrapKeySecret` and `auth.adminKeySecret` are refused at
render, naming `secretProfile`; the operator handbook's
["Registry secret profile"](../../../docs/operator-handbook.md#registry-secret-profile) gives
the move.

The public descriptor fields are `REGISTRY_DESCRIPTOR_BASE_URL`,
`REGISTRY_DESCRIPTOR_DISPLAY_NAME`, and `REGISTRY_DESCRIPTOR_OPERATOR_IDENTITY`,
the chart's `descriptor.baseUrl`, `displayName` and `operatorIdentity`. When
`REGISTRY_REQUIRE_READ_API_KEY=true`, the deployment must also set
`REGISTRY_DESCRIPTOR_ACCESS_ACQUISITION_POINTER`; a public registry must omit
that pointer. Startup rejects missing fields and either posture mismatch.

These values are public operator assertions. The service derives the
descriptor's authority principal from the credential-backed active signer and
derives its schema identity from the loaded filter specification. Helm keeps
the descriptor values in ordinary values while mounting the signer credential
from a Secret. Compose profiles likewise carry public descriptor values beside
public identity pins, and the overlays keep signer credentials in service-owned
file mounts.

An operator may also supply `REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES`
(a JSON array), or Helm `descriptor.recommendedDisputeAuthorities`. Each item has
an authority's full identity, interface-owned `params`, and an `advertisement`
copy as described under
[`settlement-configuration`'s "Dispute authority preferences"](../settlement-configuration/configuration.md#dispute-authority-preferences).
The signed descriptor exposes them in preference order as
`recommendedDisputeAuthorities`; an empty or unconfigured list is omitted.
No registry code or chart ships an authority. Recommendations are public
operator assertions, not credentials and not an instruction to override a role's
local policy. Roles verify the descriptor under that registry URL's configured
identity pins before using it.

The umbrella chart enables the compute registry by default and keeps the
`api-credits-registry` alias disabled. Enabling the alias instantiates the same
schema-opaque registry chart a second time. The compute instance selects
`/app/filter-spec.yaml` (`compute.market`); the API-credits instance selects
`/app/filter-spec-apicredits.yaml` (`api_credits`). Both specifications are
packaged in the registry image, but each process loads exactly one. Identity,
credential Secret, descriptor, `secretProfile`, Service, and PVC values are
instance-local. `global.registryIdentity` configures
the compute storefront's trust pin and does not constrain the alias signer.
