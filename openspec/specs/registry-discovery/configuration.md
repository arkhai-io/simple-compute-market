---
tags: [repository, configuration]
---

# Registry configuration

What the registry's descriptor settings mean and how the umbrella chart instantiates
the registry, as this repository's instance of
[`configuration.md`](../../../docs/guidance/engineering/configuration.md). How a
deployment gives the registry its settings — its profile files, its chart's rendered
profile, and its secret profile — is
[`deployment-state`'s "Registry profile configuration"](../deployment-state/configuration.md#registry-profile-configuration).

## Registry descriptor configuration

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
