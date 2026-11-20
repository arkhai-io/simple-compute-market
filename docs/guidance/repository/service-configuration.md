---
tags: [repository, configuration, kubernetes]
---

# Service configuration

What this repository's services take from their environment and their configuration,
as instances of [`configuration.md`](../engineering/configuration.md) and its forms
beside it. How the services resolve their configuration — the profile layers, the
resolver variables, the shared loader — is
[`DEPLOYMENT_AND_CONFIG.md`, "Profile-based configuration"](../../development/DEPLOYMENT_AND_CONFIG.md#profile-based-configuration).

## Application settings stay out of the environment

Application settings stay out of the environment
([`configuration.md`](../engineering/configuration.md#application-settings-stay-out-of-the-environment)):
a Dockerfile or pod spec sets only `ACTIVE_PROFILES` and
`CONFIG_DIRECTORY`, and the provisioning service reads `ANSIBLE_CONFIG`
from its resolved settings at startup and writes it into `os.environ`
once.

## Secrets travel in a secret profile or overlay file

**Secrets travel in a secret profile or overlay file, never in a variable the
configuration names**
([`configuration.md`](../engineering/configuration.md#secrets-travel-in-a-secret-profile-or-overlay-file)).
Here the file is a Secret-backed `config-<profile>.yml` (or the registry's
`config-<profile>.env`) added to `ACTIVE_PROFILES`, or a storefront's
`storefront.secrets.toml` overlay. On a cluster that file is a Kubernetes Secret
key, which External Secrets writes; under Compose it is a bind-mounted file.
Trust follows the same rule
([`configuration.md`](../engineering/configuration.md#trust-is-configured-where-its-client-reads-it)):
a private CA is a configured bundle path the one client that needs it reads,
such as `[Settlement.arkhai_payments].ca_bundle_path`, or a
`[[DisputeCredential]]`'s `ca_bundle_path` for that authority's client. The signing
credential `ARKHAI_IDENTITY_CREDENTIAL` is the one exception to the rule, declared in
[`AGENTS.md`, "Exceptions to shared guidance"](../../../AGENTS.md#exceptions-to-shared-guidance):
it reaches a service as a variable sourced from a Secret.
A buyer's `api_key_env`, in its payments section or a `[[DisputeCredential]]`, is
not a service's configuration but the buyer's own exact named-variable provider,
beside its keyring and secret-file providers (see
[`marketplace-identity`'s configuration](../../../openspec/specs/marketplace-identity/configuration.md)).

## A setting that belongs to one domain is named for it

**A setting that belongs to one domain is named for it**
([`configuration.md`](../engineering/configuration.md#a-setting-that-belongs-to-one-domain-is-named-for-it)).
The compute provisioning service reads the VM playbook from
`vm_playbook_path` and the bare-metal playbook from
`bare_metal_playbook_path`; neither has an alias. Its first startup step
refuses a configuration stating the retired `playbook_path` in any layer,
environment included, naming `vm_playbook_path`, and the
provisioning chart's values schema refuses `config.playbook_path`. The same step
refuses the retired `inventory_ini` and `inventory_path`, whatever value either
states, naming `host_definitions_path` (the operator handbook's
["Upgrading from an INI inventory"](../../operator-handbook.md#upgrading-from-an-ini-inventory)
gives the upgrade). A setting
retired because the service stopped needing it, such as
`default_pool_inventory_group` and `default_host_id`, is not refused.

## A storefront's configuration

Every configuration value of a storefront
reaches it through its configuration system
([`configuration.md`, "The configuration system carries every value"](../engineering/configuration.md#the-configuration-system-carries-every-value)).
Beside the values that select which configuration loads, a storefront takes
outside that system only the signing credential `ARKHAI_IDENTITY_CREDENTIAL`,
which must be kept from the loader. The storefront charts know the port their
container, probes, and Service share, and the path of the CA bundle whose
`ca_bundle_path` they derive. A storefront's
secrets — its wallet key, a registry write token, its payments `api_key`, its
`[[DisputeCredential]]` entries — are settings in its Secret overlay, never pod
variables, so a storefront pod's environment holds only `XDG_CONFIG_HOME` and the
signing credential. A storefront does not refuse to start because a value reached
it through its environment. Both storefront charts set
`enableServiceLinks: false`
([`kubernetes.md`](../engineering/kubernetes.md#service-links-are-off-where-a-loader-reads-a-prefixed-override-layer)),
since a Service named `storefront…` would land in the storefronts'
`STOREFRONT_` override layer.
