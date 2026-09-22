## Why

Relays, pools, and capacity declarations reach the provisioning service as
definition documents. A startup applies such a document only when its digest
differs from the one recorded with the last apply, so editing a mounted document
and rolling the deployment applies the edit, while a restart against an
unchanged document changes nothing and API edits survive.

Host inventory follows an older rule. The inventory (`inventory_ini`, or the
file at `inventory_path`) is read at startup only when the host registry is
empty, and never again. An operator who edits the inventory of a running
deployment and rolls it sees nothing happen: the new host is not registered,
and no error says why. `POST /api/v1/hosts/import` is the only way to apply
the edit.

That used to be partly hidden. Execution fell back to the inventory file when a
host had no registered record, so a host added only to the file could still be
dispatched to, though it was never registered, carried no capacity declaration,
and appeared in no projection. That fallback is gone: execution renders only from
the registered host record and refuses a host with none. So the gap between what
the operator edited and what the service holds now surfaces as refused dispatch.

The principle the definition documents already follow, that a process start is
not a submission but a changed document is, applies to hosts exactly as it
applies to relays.

## What Changes

- Bring host inventory under the definition-document mechanism: a startup
  reconciles it when its digest differs from the last applied one, recording the
  digest in the same transaction as the apply, and an explicit import still
  reconciles regardless.
- Define what reconciliation does to a registered host the document no longer
  names, what an upgraded deployment's first startup does with no recorded
  digest, and how applying hosts orders against capacity documents. These are
  open questions in `design.md`, not decisions.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: how host inventory enters the host registry.
- `deployment-state`: startup reconciliation of mounted configuration, if the
  definition-document contract is stated there.

### New Capabilities

None.

## Non-Goals

- Do not change how execution resolves a host: it renders only from the
  registered host record.
- Do not change the INI format's capacity derivation rule; a host's legacy GPU
  count still derives a declaration once.
- Do not decide who generates a host's key material;
  `contain-embedded-host-key-material` owns that.

## Impact

- Provisioning service startup (`app_runtime.py`'s inventory seeding) and the
  definition-document importer.
- The provisioning Helm chart's `definitions` values and schema, if host
  inventory joins them.
- Operator documentation of how hosts are added.

## Dependencies and Related Changes

- Follows `project-capacity-resources-without-hosts`, which removed the
  execution fallback that masked this gap and documented the current seeding
  rule.
- Coordinates with `contain-embedded-host-key-material`: an inventory may name
  embedded key material, and definition documents are defined as never carrying
  a credential.
- Coordinates with `pools-9-retire-local-physical-authority`, which retires the
  storefront's CSV import. That is a different inventory path from this one.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification: `physical-provisioning`, and possibly
      `deployment-state`
- [ ] New subsystem specification
- [ ] No permanent documentation change

`docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Definition documents" section and
both seller quickstarts describe host inventory today, and change with it.

### Knowledge to promote

To be determined at design completion.
