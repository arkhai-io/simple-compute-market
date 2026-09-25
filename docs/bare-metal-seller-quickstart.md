# Bare-metal seller quickstart

This stack composes the services required to publish exclusive whole-host
capacity, schedule fulfillment through one explicitly trusted site authority,
grant SSH access after settlement, and revoke that access at teardown. It uses
the dedicated wheel-only `arkhai:bare-metal-storefront` image and the ordinary
compute provisioning service; it does not use a direct executor or mock
provisioning.

For VM slices, see [`seller-quickstart.md`](./seller-quickstart.md). A single
Physical Resource may back VM and bare-metal offers only when both listings
use the same stable physical-host identity and their Resource Pools explicitly
declare the relevant `deliverable_modes`.

Whole-host listings may publish Alkahest and hosted Stripe fiat as independent
settlement alternatives. Hosted options use one exact `card.v1`, US/USD
`us_bank_transfer.v1`, or US/USD `us_ach_debit.v1` profile; slow or interactive
payment never reserves, allocates, or provisions the host before authoritative
funding. See the
[`buyer quickstart`](./buyer-quickstart.md#supported-settlement-methods) for
payment behavior and
[`ROADMAP.md`](./development/ROADMAP.md#hosted-settlement-release-status) for
the distinction between shipped support and completed external qualification.

## Prerequisites

- Docker/Podman with Compose v2 on a Linux host.
- The staged internal wheels and the images built from this checkout.
- Canonical marketplace principals and matching role-scoped signer files for
  the registry, storefront, and selected-site provisioning authority.
- An Ansible inventory containing a real whole-host SSH target and a dedicated
  provisioning SSH private-key file.
- A Resource Pool document that explicitly declares `bare_metal`; absence is
  not a permissive default.
- One strict shared settlement configuration. Hosted-only roles require the signed released hosted manifest/client/API capability pins, public authority trust and environment scope, seller account binding, exact profiles/currency/country/condition policy, and no wallet/RPC secret. Alkahest roles require the ordinary chain configuration and funded public seller address. Never put a wallet private key, Stripe credential, payer binding, or provider object in Compose or this document.

The installed `arkhai-bare-metal-buyer` contribution supplies the `market bare-metal` discovery, negotiation, hosted start/status/reclaim, and recovery commands. A running seller stack is not end-to-end evidence until that public path also observes authenticated access, teardown, and access revocation against a disposable host.

## Build the images

```bash
make dist build-registry build-provisioning build-bare-metal-storefront
```

`domains/bare_metal/storefront/Dockerfile` installs
`arkhai_bare_metal_storefront-0.2.1` from `.dist`. The runtime image does not
copy repository source or resolve an editable sibling package.

## Define the selected site

Create an operator-owned inventory file outside the repository:

```ini
[bare_metal_nodes]
host-ca-h200-01 ansible_host=10.0.0.25 public_host=203.0.113.25 ansible_user=ubuntu pool_id=whole-host-california
```

Create a Resource Pool document outside the repository. The pool id must match
the inventory host's `pool_id`; executor connectivity remains service-owned:

```yaml
pools:
  - id: whole-host-california
    label: Whole Host California
    provider: bare_metal.ansible
    enabled: true
    policy_tags:
      deliverable_modes: [bare_metal]
      advertisable_modes: [bare_metal]
      capacity_backing: backed
      region: California, US
    provider_config: {}
```

Every pool must declare `advertisable_modes` — the offering modes its listings
may name — and `capacity_backing`. A `backed` pool may advertise only modes it
also delivers. The service refuses a pool document, and refuses to start, when
an entry omits either declaration; nothing is defaulted.

The bare-metal provider rejects pool-local playbook paths, inventory groups,
credentials, and executor targets. The service-owned
`bare_metal_playbook_path`, the selected Physical Resource, and the registered
host record it names determine execution.

The mounted inventory seeds the host registry when the provisioning service
starts with no hosts registered; it is not read at execution. A host added to it
later must be imported (`POST /api/v1/hosts/import`) before work can be
dispatched to it. A host's `public_host` is passed to the access playbook as a
host variable.

The pool declaration is authoritative. Do not add `vm` merely to make a
request pass; add it only if the same pool and executor can actually deliver
that mode.

## Prepare role credentials

Use separate owner-readable files:

- `BARE_METAL_REGISTRY_IDENTITY_CREDENTIAL_FILE` contains only the registry
  signing credential expected by its configured public principal.
- `BARE_METAL_STOREFRONT_IDENTITY_ENV_FILE` contains the storefront's
  `ARKHAI_IDENTITY_CREDENTIAL`.
- `BARE_METAL_PROVISIONING_IDENTITY_ENV_FILE` contains the provisioning
  authority's `ARKHAI_IDENTITY_CREDENTIAL`.
- `BARE_METAL_PROVISIONING_SSH_PRIVATE_KEY_FILE` is the Ansible key for the
  selected host. It is not a marketplace credential.

The files must be regular owner-readable files. Do not reuse one principal or
credential across roles, and do not commit credential values.

## Configure public bindings

Export the paths plus exact public principals. Values shown in angle brackets
are required deployment inputs, not defaults:

```bash
export BARE_METAL_REGISTRY_IDENTITY_CREDENTIAL_FILE=/run/operator/registry-credential
export BARE_METAL_STOREFRONT_IDENTITY_ENV_FILE=/run/operator/storefront-identity.env
export BARE_METAL_PROVISIONING_IDENTITY_ENV_FILE=/run/operator/provisioning-identity.env
export BARE_METAL_PROVISIONING_SSH_PRIVATE_KEY_FILE=/run/operator/site-ssh-key
export BARE_METAL_PROVISIONING_INVENTORY_FILE=/run/operator/bare-metal-hosts.ini
export BARE_METAL_POOL_DEFINITIONS_FILE=/run/operator/resource-pools.yaml

export BARE_METAL_REGISTRY_AUTHORITY_ID=bare-metal-registry
export BARE_METAL_REGISTRY_AUTHORITY_SCHEME=<scheme>
export BARE_METAL_REGISTRY_AUTHORITY_IDENTIFIER=<canonical-identifier>

export BARE_METAL_STOREFRONT_IDENTITY_SCHEME=<scheme>
export BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER=<canonical-identifier>
export BARE_METAL_STOREFRONT_ADMIN_IDENTITIES_JSON='[{"scheme":"<scheme>","identifier":"<canonical-admin-identifier>"}]'
export BARE_METAL_STOREFRONT_PUBLIC_URL=https://seller.example/
export BARE_METAL_STOREFRONT_EVM_ADDRESS=<public-settlement-address>
export BARE_METAL_STOREFRONT_SETTLEMENT_JSON="$(cat /run/operator/settlement.json)"
export BARE_METAL_PUBLICATION_CLAUSES_JSON='<exact versioned settlement clauses>'
export BARE_METAL_FUNDING_DEADLINES_JSON='{"card.v1":900,"us_bank_transfer.v1":86400,"us_ach_debit.v1":432000}'
export BARE_METAL_OFFER_EXPIRES_AT=<UTC-timestamp>
export BARE_METAL_FULFILLMENT_DEADLINE=<UTC-timestamp>
export BARE_METAL_MAX_DURATION_SECONDS=7200

export BARE_METAL_PROVISIONING_IDENTITY_SCHEME=<scheme>
export BARE_METAL_PROVISIONING_IDENTITY_IDENTIFIER=<canonical-site-authority-identifier>
export BARE_METAL_PROVISIONING_ADMIN_IDENTITY_SCHEME=<scheme>
export BARE_METAL_PROVISIONING_ADMIN_IDENTITY_IDENTIFIER=<canonical-admin-identifier>
export BARE_METAL_SITE_ID=california-1

export BARE_METAL_STOREFRONT_SITE_PLACEMENT=fill_first
export BARE_METAL_STOREFRONT_SITES_JSON='[{"site_id":"california-1","authority_url":"http://bare-metal-provisioning:8081","authority_principal":{"scheme":"<scheme>","identifier":"<canonical-site-authority-identifier>"}}]'
```

The site object is an exact trust binding. The storefront does not infer a
site from inventory, payload fields, reachability, or list order. With
`most_available`, it compares authoritative capacity projections only among
the listed trusted sites.

## Start and inspect

```bash
docker compose -f compose.bare-metal.yml up -d
docker compose -f compose.bare-metal.yml ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8081/health
curl -fsS http://localhost:8080/health
```

Register the same host as one exclusive Physical Resource through
`SiteCapacityAdminClient.register_resource` using the configured provisioning
administrator signer and exact provisioning-authority trust. The authenticated
`PUT /api/v1/capacity/resources/<physical-resource-id>` body is:

```json
{
  "total_units": 1,
  "resource_type": "compute.bare-metal",
  "pool_id": "whole-host-california",
  "host_id": "host-ca-h200-01",
  "capacity": {"units": 1},
  "attributes": {
    "physical_host_id": "<provider-stable-host-id>",
    "allocation_mode": "exclusive",
    "bare_metal_publication": {
      "enabled": true,
      "access_methods": ["ssh"],
      "capabilities": {}
    }
  },
  "enabled": true
}
```

The URL path's Physical Resource id, the `host_id`, and `physical_host_id` are
separate fields with the exact values shown by their roles. `host_id` is the
host's inventory alias, the first token of its line in the Ansible inventory;
`physical_host_id` identifies the physical machine for cross-mode accounting.
Do not substitute the provider id or public IP for the inventory alias.
`physical_host_id` and `allocation_mode` belong at the top level of
`attributes`, where the site authority's exclusive/shareable accounting reads
them; `bare_metal_publication` carries only what the listing view exposes.
Everything in `attributes` is published to storefronts. Registration is
independently idempotent and must complete before publication.

The stack persists registry, Redis, provisioning, and storefront state in
separate named volumes. Do not treat an HTTP 200 alone as deal readiness:
inspect the storefront health projection and stop if database, fulfillment, or
the configured settlement mechanism is unavailable. Each configured site is
reported separately under `site_projections`, with its resource-pool projection
`loaded` (with its revision and digest) or `unavailable` (with the error). A site
that is down is reported there and does not mark the whole storefront degraded.

The dedicated image includes the bare-metal publication command. Run one
authenticated publication round with `bare-metal-storefront publish`. Each round:

- Reads every configured site's resource-pool projection through that site's
  own trusted client, and derives one listing per Physical Resource from the
  bare-metal view the site projects for it.
- Lists a resource only if its pool advertises `bare_metal`, is enabled, and is
  capacity-backed, as the Resource Pool document above declares. A pool that
  declares itself unbacked yields no bare-metal listing, and the round reports
  it by name.
- Closes a listing whose capacity declaration is disabled, or whose pool stops
  advertising `bare_metal` or is disabled.
- Closes a listing whose machine is leased, and reopens it once the machine is
  free again.
- Treats a Physical Resource moved to another pool as a new listing: the old
  one closes and a new one is published under the new pool.
- Leaves a listing its seller closed as it is.
- Holds, without closing or refreshing, the listings of a site that cannot be
  reached or whose projection is malformed, and of a pool whose declarations do
  not resolve. The round reports each one; every other site is reconciled as
  usual.
- Writes every new listing locally before any registry is told of it, records
  each registry's answer, and resends to any registry that missed a publish,
  close, or reopen. A later round repairs a registry that was unreachable.

The round prints a report of every publish, refresh, reopen, close (with its
reason), hold, refusal, and registry repair. It publishes independent typed
settlement options; it does not manufacture availability or substitute a
different site or resource.

`BARE_METAL_STOREFRONT_EVM_ADDRESS` is required only when Alkahest is enabled. Hosted-only startup leaves it empty and constructs no wallet, RPC, chain, or Alkahest client. The shared settlement JSON is mounted read-only and contains public authority/account/trust/release settings only. The runtime registers the ready mechanisms, the shared hosted route service, and bare-owned lifecycle callbacks; a disabled or unready mechanism is omitted rather than represented by a fake adapter.

### Resetting the storefront database

The bare-metal storefront refuses to start against a database written under a
listing kind it can no longer decode, and names this section. Accepted
bare-metal state is signed or pinned by content digest, so it is never rewritten
in place, and no decoder for a retired listing kind is kept. The remedy is to
remove the bare-metal deployment and install it fresh:

1. Terminate every active bare-metal lease through the provisioning service's
   lease API, force-releasing any whose teardown cannot complete after
   verifying the node externally. The provisioning service outlives the reset,
   so a lease left active there is orphaned rather than removed.
2. `helm uninstall` the bare-metal release and delete its persistent volume
   claims. Its registry listings go with it only if the registry belongs to
   that release. A registry shared with other roles keeps them, and nothing in
   a fresh storefront knows their listing ids; before uninstalling, disable the
   bare-metal capacity declarations at the provisioning service and run one
   `bare-metal-storefront publish` round, which closes every listing the
   storefront tracks once its sites report no bare-metal resources.
3. Deploy the upgrade. The provisioning service migrates its own database in
   place. It is shared with VM fulfillment and is never reset.
4. Install the bare-metal release fresh, re-enable its capacity declarations,
   and publish.
5. Discard bare-metal buyer run logs that reference deals made before the
   reset; nothing can decode them afterwards.

This applies only while bare metal is unreleased. A released deployment cannot
drain long-running contracts to patch, so a retired kind must keep a read-only
decoder until nothing references it.

## Release-qualified deal evidence

Once signed registry publication, the buyer contribution, selected-site
authority, settlement authority, and real host are available, inject the E2E
role inputs and run:

```bash
uv run pytest -m e2e_bare_metal_deal -v
```

The scenario drives the installed `market bare-metal` command. It checks the
public lifecycle in order, performs real SSH with the returned access
descriptor, requests teardown through the buyer command, waits for the
accepted terminal teardown status, and proves that the same SSH access is
revoked. A mock job, unit result, Compose render, health response, or
provisioning database row is not substitute evidence.

## Operational rules

- Keep Physical Resource, Resource Pool, site, listing, negotiation, and
  fulfillment identities stable through recovery.
- Never provision or reserve a whole host before the accepted settlement
  lifecycle permits it.
- `remove_lease_key`, `lock_user`, and `delete_user` have different blast
  radii. Configure the reclaim policy deliberately for the selected site.
- Teardown releases whole-host access; it is not VM destruction. Collection
  and post-collection lease teardown remain independent of payment reclaim.
- Preserve the storefront and provisioning volumes while a listing,
  negotiation, reservation, fulfillment, or teardown is recoverable.
