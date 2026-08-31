## Why

A KVM host that has no inbound route does not answer SSH on port 22 at an
address the provisioning service can name. It answers on whatever port a
reverse tunnel, NAT port-forward, or bastion publishes. The host registry
cannot express that.

`Host` has `kvm_host`, `public_host`, `ssh_user`, and `ssh_key_*`, and no port.
`HostCreate` and `HostUpdate` have no port field. Both inventory renderers —
`HostService.render_inventory_ini` and `AnsibleService.write_inventory` — emit
`ansible_host`, `ansible_user`, and `ansible_ssh_private_key_file` and nothing
else. `_parse_ini` documents its variable mapping and places `ansible_port`
under "All other variables → ignored", so `POST /api/v1/hosts/import` and the
`inventory_ini` startup seed both discard it.

The INI input format already promises otherwise.
`domains/vms/provisioning/iac/ansible/inventory/hosts.example` lists
`ansible_port=<port>` as a supported per-host argument under both `[kvm_hosts]`
and `[bare_metal_nodes]`, with the comment "if SSH isn't on 22". An operator
following the documented inventory format writes a port that is silently
dropped, and the resulting connectivity check fails against port 22 with no
indication that the supplied value was discarded.

The consequence is that no host reachable only on a non-default port can be
registered, and every downstream operation against it — `GET
/hosts/{host}/connectivity`, capacity checks, VM create and destroy — connects
to the wrong port. This blocks provisioning against any rented node behind a
firewall or NAT, which is the deployment shape the product exists to serve.

## What Changes

- `Host` gains an `ssh_port` column, `NOT NULL` with a default of 22, so every
  existing row keeps today's behaviour without operator action.
- `HostCreate`, `HostUpdate`, and `HostResponse` gain `ssh_port`. It is
  optional on create and defaults to 22, so existing clients are unaffected.
- `_parse_ini` maps `ansible_port` to `ssh_port`, with a non-integer or
  out-of-range value rejected rather than coerced. The variable mapping comment
  is corrected, since it currently states the opposite of the intended
  behaviour.
- `HostService.render_inventory_ini` and `AnsibleService.write_inventory` emit
  `ansible_port` for every host.
- The connectivity, capacity, and VM operation paths inherit the port through
  the rendered inventory; none of them constructs its own connection.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: the host registry records the SSH port the
  provisioner connects on, and rendered inventories carry it.

## Non-Goals

- Do not decide how a tunnel port is allocated, by whom, or from what window.
  This change makes a port storable and renderable; it takes no position on
  where the value comes from. See `relay-vm-access-without-a-dashboard` for the
  VM-facing half and the infrastructure repository for the host-facing half.
- Do not change buyer-facing connection strings. `public_host` remains the
  tenant-facing address and is untouched here.
- Do not add a bastion, jump-host, or `ProxyCommand` concept. A single
  `ansible_port` covers the tunnel case; a proxy chain is a different feature
  with a different shape.
- Do not migrate any existing deployment onto a non-default port. Every current
  host keeps port 22 by column default.

## Compatibility

**Database.** One additive column with a server-side default. Existing rows
backfill to 22. No data is rewritten and no read path changes meaning.

**Wire.** `ssh_port` is optional on `POST /api/v1/hosts/` and
`PUT /api/v1/hosts/{host}`, and additive on `HostResponse`. A client that omits
it gets today's behaviour. A client that ignores the new response field is
unaffected.

**Rendered inventory.** `ansible_port=22` appears on hosts that previously
rendered without it. This is explicit rather than implicit and Ansible resolves
it identically. The alternative — emitting the variable only when it differs
from 22 — keeps existing inventories byte-identical but makes a rendered
inventory ambiguous between "port 22" and "no port recorded". See `design.md`.

## Dependencies and Related Changes

- `relay-vm-access-without-a-dashboard` needs this to register a host reached
  through a management tunnel, but does not otherwise depend on it: the two
  changes touch different code and can land in either order.
- `capacity-resource-administration` and `pools-9-retire-local-physical-authority`
  both touch host inventory seeding. This change adds a column and a parsed
  variable and removes nothing, so it does not compete with either for
  ownership of the seeding path.

## Impact

- An operator can register a host reachable only on a non-default SSH port, and
  the documented `ansible_port` inventory variable stops being silently
  discarded.
- Every Ansible operation against a registered host connects on the recorded
  port.
- Deployments that never used a non-default port see no behavioural change.

## Permanent documentation impact

- [x] Existing subsystem specification: `openspec/specs/physical-provisioning/spec.md` — host registry records the SSH port and rendered inventories carry it
- [ ] `docs/development/ARCHITECTURE.md` — no repository-wide shape change
- [ ] New subsystem specification

### Knowledge to promote

- The host registry is the authority for how the provisioner connects to a
  host, including port, and every execution path derives its connection from
  the rendered inventory rather than constructing one → `openspec/specs/physical-provisioning/spec.md`
- Whether `ansible_port` renders always or only when non-default, and why →
  `openspec/specs/physical-provisioning/spec.md` if it becomes normative,
  otherwise the design decision stands in this change only
