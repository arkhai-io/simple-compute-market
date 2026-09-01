# Design

## What the code does today

Four places would each have to be changed for a port to survive from operator
input to an Ansible connection, and none of them carries one.

| Location | Today |
|---|---|
| `compute_provisioning_service/db/models.py` — `Host` | `name`, `kvm_host`, `public_host`, `ssh_user`, `ssh_key_type`, `ssh_key_value`, `gpu_count`, `gpu_model`, `enabled`, `pool_id`. No port. |
| `vm_provisioning_operator/models.py` — `HostCreate`/`HostUpdate`/`HostResponse` | No port field on any of the three. |
| `host_service._parse_ini` | Maps `gpus`, `gpu_model`, `public_host`, `ansible_ssh_private_key_file`, `pool_id`. Docstring: "All other variables → ignored". |
| `host_service.render_inventory_ini` and `ansible_service.write_inventory` | Both emit `ansible_host`, `ansible_user`, `ansible_ssh_private_key_file`; the second also emits `public_host`. |

The two renderers are separate implementations of the same INI line, which is
why both are named explicitly. They already disagree — only
`write_inventory` emits `public_host` — so a change that edits one and not the
other produces a host that behaves differently depending on which path built
the inventory.

## Why the port belongs on the host record rather than in configuration

A per-service setting cannot express it: two hosts registered against one
provisioning service can sit behind different tunnels on different ports. The
port is a property of how *that host* is reached, which is what the host
registry already exists to record for address, user, and key material. Putting
it anywhere else splits one connection descriptor across two stores and makes
the rendered inventory unreproducible from the registry alone.

## Decisions

**`ansible_port` renders for every host, not only when it differs from 22.**

Conditional rendering keeps existing inventories byte-identical, which is
tempting. It also makes the absence of the variable ambiguous: an inventory
without `ansible_port` could mean "this host is on 22" or "this host predates
the column". Since the column is `NOT NULL`, the registry never holds the
second state, and rendering unconditionally means the INI says exactly what the
registry holds. Debugging a connection failure then involves reading one file
rather than reasoning about what a missing line implies.

The cost is that inventory fixtures asserting exact INI text need updating.
That is a test-fixture edit, not a behaviour change — Ansible resolves an
explicit `ansible_port=22` identically to an omitted one.

**A malformed `ansible_port` fails the entry rather than defaulting to 22.**

`_parse_ini` currently coerces a non-integer `gpus` to 0 in a `try/except`,
which is defensible for a capacity hint — a wrong GPU count produces a bad
listing, and the operator sees it. A wrong port produces a host that cannot be
reached at all, and silently substituting 22 turns an operator's typo into a
connectivity failure that looks like a network problem. The entry is skipped
with a warning, matching how the parser already handles a missing
`ansible_host` or `ansible_user`.

This is a behaviour difference between two fields in one parser, so it is worth
being explicit that it is deliberate rather than inconsistent: `gpus` degrades,
`ansible_port` refuses, because the failure modes are not comparable.

**The column is `NOT NULL` with default 22 rather than nullable.**

Nullable would let a row mean "unspecified", which every read path would then
have to resolve to 22 anyway. Three call sites resolving the same default
independently is how they drift. The default lives in the schema, and the
migration backfills existing rows in the same statement.

**Range validation is 1–65535 at the model boundary.**

Pydantic rejects the value before it reaches the database, so the API returns
400 rather than a database error. The INI path validates the same range so both
entry points agree.

## Alternatives considered

**Encode the port in `kvm_host` as `host:port`.** Requires no schema change and
is how a human would write it. Ansible does not parse it — `ansible_host` is a
hostname, and `1.2.3.4:6000` is treated as a literal name that fails to
resolve. Every consumer of `kvm_host` would need to learn to split it, and
`public_host` would face the same question with a different answer.

**A separate `host_connection` table.** Correct if a host could have several
connection descriptors — a management tunnel and a direct route, say, with
failover between them. Nothing today selects between routes, so the table would
have exactly one row per host and one join for no gain. Worth revisiting if a
fallback route becomes a real requirement rather than a hypothetical.

**Per-group `ansible_port` in `group_vars/all.yml`.** Works for a single-host
environment and is the smallest possible change. It applies one port to every
host in `[kvm_hosts]`, which is wrong as soon as a second host is registered
behind a different tunnel, and it puts a connection detail in the IaC repository
rather than the registry that owns the rest of the connection.

## Verification

Neither Ansible nor a database is available in the session environment, so the
following are stated as intended evidence rather than as results. Everything in
this change is exercisable without cloud state.

- Parser: an INI entry carrying `ansible_port` produces the port; a malformed
  one is skipped with a warning; an absent one yields 22.
- Both renderers: a host with a non-default port emits `ansible_port`, and the
  two renderers produce the same line for the same host.
- API: create with and without `ssh_port`; update the port; confirm
  `HostResponse` carries it.
- Migration: applied against a database holding rows created before the column,
  every row reads 22.

Live evidence that a connection actually reaches a tunnel port belongs to
whoever prepares the host, not here — this change can be fully verified without
a host existing.

## Deployment consequence

`check_schema_version` compares the database against `MIGRATIONS[-1]` and raises
`SchemaDriftError` at startup when the last declared migration is not recorded.
Appending `20260901_001_hosts_ssh_port` therefore means every deployed database
must have migrations applied before an image carrying this code starts — through
the Helm init container, `compute-provisioning-migrate`, or `make migrate`.

This change does not run them. Applying a migration to a deployed database
mutates persistent state and needs its own authorized packet.

## Open questions

None. The shape of this change is determined by what the code already does; the
decisions above are about consistency rather than about unresolved direction.
