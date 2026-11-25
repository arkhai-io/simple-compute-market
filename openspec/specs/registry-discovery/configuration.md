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

## The registry's time source

The registry reads `TIME_SOURCE`, `"wall"` when unset or `"injected"`; any other
value refuses startup, naming the setting and the value. Under `"injected"` it
starts frozen at the wall instant it started, logs that at startup, and mounts
`POST /admin/time` beside `/admin/api-keys`, behind the same administrator bearer
key, `REGISTRY_ADMIN_API_KEY`; `GET /admin/status`, behind that key too, reports
the time section in either mode. Publisher authentication and listing decisions
read that source. No chart default, production Compose stack or example env file
sets it; only the lanes' registry profile, `dev-env/registry/config-payments-lane.env`,
does ([injected time](../injected-time/architecture.md)).

## RFQ registry settings

| Setting | Purpose |
| --- | --- |
| `REGISTRY_RFQ_SPEC_PATH` | Selects the installed family's RFQ requirements, response-quantity and filter declarations. The compute registry image packages `/app/rfq-schema.json`. |
| `REGISTRY_RFQ_AUTHORITIES` | Maps stable account-authority namespaces to their allowed public signing identities. The trust set can temporarily include both signers during rotation. |
| `REGISTRY_RFQ_REPLAY_KEYS_FILE` | References the mounted digest keyring used for the logical request bindings in the RFQ replay store. |
| `REGISTRY_RFQ_CONTACT_KEYS_FILE` | References the mounted encryption keyring used by responses and introductions. Retain each key with live payloads until rotation verifies coverage. |
| `REGISTRY_RFQ_CONTACT_WINDOW_SECONDS` | Sets the window for new introductions in whole seconds. Defaults to 2592000 seconds (30 days). The Helm value is `registry.config.rfqContactWindowSeconds`. |
| `REGISTRY_RFQ_REDACT_RESTORED_CONTACTS` | Enables startup redaction for a restored database whose retained contact eligibility cannot be reconstructed. Contact operations stay closed while the setting is enabled. |

RFQ admission requires a schema, authority trust, a replay digest keyring and a separate contact encryption keyring. Startup and background retention remove expired contact rows independently of RFQ admission. The [operator handbook](../../../docs/operator-handbook.md#operate-and-recover-rfqs) covers rotation and restore.
