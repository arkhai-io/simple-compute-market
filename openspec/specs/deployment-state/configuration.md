---
tags: [repository, configuration, deployment]
---

# Deployment configuration

How a deployment gives the registry its configuration, as this repository's instance
of [`configuration.md`](../../../docs/guidance/engineering/configuration.md) and
[`deployment.md`](../../../docs/guidance/engineering/deployment.md), under
[this capability's requirement "The registry reads profile-shaped env files"](spec.md#requirement-the-registry-reads-profile-shaped-env-files).
The other services' profile configuration is
[`DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#profile-based-configuration);
what the registry's descriptor settings mean is
[`registry-discovery`'s "Registry descriptor configuration"](../registry-discovery/configuration.md#registry-descriptor-configuration).

## Registry profile configuration

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
