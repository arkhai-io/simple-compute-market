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

## Prerequisites

- Docker/Podman with Compose v2 on a Linux host.
- The staged internal wheels and the images built from this checkout.
- Canonical marketplace principals and matching role-scoped signer files for
  the registry, storefront, and selected-site provisioning authority.
- An Ansible inventory containing a real whole-host SSH target and a dedicated
  provisioning SSH private-key file.
- A Resource Pool document that explicitly declares `bare_metal`; absence is
  not a permissive default.
- A chain/settlement deployment accepted by the storefront and a funded public
  seller address. Never put a wallet private key in Compose or this document.

The marketplace buyer contribution is a separate prerequisite. A running
seller stack is not end-to-end evidence until the installed `market
bare-metal` plugin completes discovery, negotiation, settlement, access,
teardown, and access revocation.

## Build the images

```bash
make dist build-registry build-provisioning build-bare-metal-storefront
```

`domains/bare_metal/storefront/Dockerfile` installs
`arkhai_bare_metal_storefront-0.2.0` from `.dist`. The runtime image does not
copy repository source or resolve an editable sibling package.

## Define the selected site

Create an operator-owned inventory file outside the repository:

```ini
[bare_metal_nodes]
host-ca-h200-01 ansible_host=10.0.0.25 public_host=203.0.113.25 ansible_user=ubuntu
```

Create a Resource Pool document outside the repository. The executor target
and inventory group must name real operator-controlled resources:

```yaml
pools:
  - id: whole-host-california
    label: Whole Host California
    provider: ansible
    enabled: true
    policy_tags:
      deliverable_modes: [bare_metal]
      region: California, US
    provider_config:
      playbook_path: /opt/domains/vms/provisioning/iac/ansible/playbooks/bare-metal/node-access.yaml
      inventory_group: bare_metal_nodes
```

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

The stack persists registry, Redis, provisioning, and storefront state in
separate named volumes. Do not treat an HTTP 200 alone as deal readiness:
inspect the storefront health projection and stop if database, selected-site
capacity, fulfillment, or the configured settlement mechanism is unavailable.

The dedicated image exposes the installed bare-metal publication selection and
command seam but does not yet run an autonomous registry publication daemon.
Until the accepted storefront contribution lifecycle invokes that seam, an
operator must drive the ordinary signed publication command externally. A
healthy but undiscoverable storefront is therefore an explicit blocker, not a
successful seller deployment.

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
