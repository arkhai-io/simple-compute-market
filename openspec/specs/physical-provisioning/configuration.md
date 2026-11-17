---
tags: [repository, configuration]
---

# Provisioning definition documents

The definition documents the provisioning service is given, as this repository's
instance of
[`definition-documents.md`](../../../docs/guidance/engineering/definition-documents.md):
their settings, the order startup imports them in, how each kind applies the method,
and the relays' secrets. The pool document's own rules are
[`resource-pool-management`'s](../resource-pool-management/configuration.md#pool-definitions).

## Definition documents

The provisioning service is given YAML definition documents describing the
relays, pools, hosts, and capacity declarations it should hold
([`definition-documents.md`](../../../docs/guidance/engineering/definition-documents.md)).

Four settings name such a document, all read by the provisioning service:
`relay_definitions_path`, `pool_definitions_path`, `host_definitions_path`, and
`capacity_definitions_path`. The provisioning chart derives each from the
presence of its value under `definitions` (`relays`, `pools`, `hosts`,
`capacity`) rather than configuring it beside the document
([`definition-documents.md`, "Its path is derived from its presence"](../../../docs/guidance/engineering/definition-documents.md#its-path-is-derived-from-its-presence)),
and its schema refuses every one of the four paths under `config` for that
reason. Every value is empty by default, so a
deployment that supplies none is managed entirely through the API.

Startup imports them in dependency order: relays, then pools (which may name a
relay), then the pool seed on a fresh site, then the check of every stored pool,
then hosts (whose entries may name a pool), then capacity (whose declarations
name a pool and may name a host). Every pool a host or capacity document names
must exist when it is imported: already stored, or created by the pool document,
or, on a fresh site with none, by the seed.

### The method a document kind follows

The provisioning service's document kinds follow
[`definition-documents.md`'s method](../../../docs/guidance/engineering/definition-documents.md#the-method-a-document-kind-follows).
Here a kind's path setting is `<kind>_definitions_path`, set by the
provisioning chart from `definitions.<kind>`, rendered into its ConfigMap so
that an edit rolls the pod through the ConfigMap checksum, refused under
`config`, and mounted under a name `configFiles` refuses. A kind's validation
route is its import route with `validate_only`, or for pools
`POST /api/v1/pools/validate`, and the chart replaces the pod with `Recreate`,
so a document is validated before the release that mounts it. A kind's slot in
startup's dependency order is the one above.

The pool, host, and capacity
kinds each have a section naming the setting and where the kind's own
rules are: its specification, and the
[operator handbook](../../../docs/operator-handbook.md#definition-documents) for its
format and the procedures around it. The host document follows all of the
method. The others diverge in part: the capacity
document has no export, the relay document has no import route or export, and
the pool document validates at its own route and its import and export answer
in their own shapes.

### What a document does to entries it stops naming

Each kind states its rule
([`definition-documents.md`, "What a document does to entries it stops naming"](../../../docs/guidance/engineering/definition-documents.md#what-a-document-does-to-entries-it-stops-naming));
the pool document's is
[`resource-pool-management`'s](../resource-pool-management/configuration.md#pool-definitions).
Each kind's import reconciles as
[`definition-documents.md`, "Reconciliation follows the document, not the process"](../../../docs/guidance/engineering/definition-documents.md#reconciliation-follows-the-document-not-the-process)
says.

A relay absent from the document is **retained**. Disabling one drains it:
every pool referencing it stops taking new delivery until it is enabled again,
while the deliveries already leased on it run to their end. That is an
operator's explicit decision, made through the relay's `enabled` entry or the
API, not what an operator editing an unrelated entry is asking for, and a stale
row costs far less. A relay established from a document and then administered through
the API is one relay, not two.

A capacity declaration absent from the document is **retained**, as a relay is.
An unnamed declaration may have been registered through the API, derived from a
host's inventory by a migration of the v0.3.0 floor, or be backing a live reservation, and
none of those is what an operator editing an unrelated entry means to switch off. A capacity document
therefore adds and updates declarations and never removes one; disabling is an
explicit `enabled: false`, in the document or through the API.

A host absent from the document is **retained**, its enabled state included, and
each apply reports it as registered and not named: in the startup log, and in
the import response's `not_named`. Hosts registered through the API, as every
end-to-end lane registers them, coexist with the document, and disabling every
host a document stopped naming would take them out of service. Disabling a host
is an explicit `enabled: false`, in the document or through the API; it keeps
new deliveries off the host while work already placed there runs, as the
operator handbook's ["Host definitions"](../../../docs/operator-handbook.md#host-definitions)
describes.

### Host definitions

`host_definitions_path` names the host document, a top-level `hosts` list whose
entries have the host registration API's field names; the provisioning chart
sets it from `definitions.hosts`, and the Compose stacks set
`PROVISIONING_HOST_DEFINITIONS_PATH` to the document they mount. The retired
`inventory_ini` and `inventory_path` are refused (see
[`service-configuration.md`, "A setting that belongs to one domain is named for it"](../../../docs/guidance/repository/service-configuration.md#a-setting-that-belongs-to-one-domain-is-named-for-it)).
The contract is the
[`physical-provisioning` specification](spec.md);
the format, the export and import routes, and the upgrade from an INI inventory
are in the operator handbook's
["Host definitions"](../../../docs/operator-handbook.md#host-definitions).

### Capacity definitions

`capacity_definitions_path` names the capacity document, a top-level
`resources` list whose entries are whole declarations with the capacity
registration API's field names; the provisioning chart sets it from
`definitions.capacity`. The contract is the `physical-provisioning` requirement
["Capacity definitions are imported from a mounted document"](spec.md#requirement-capacity-definitions-are-imported-from-a-mounted-document)
with [`site-capacity`](../site-capacity/spec.md); the format
and the rules for VM and bare-metal declarations are in the operator handbook's
["Capacity definitions"](../../../docs/operator-handbook.md#capacity-definitions).

### Secrets are named, not carried

A relay entry may name which key of the deployment's secrets profile holds its
admission token, resolved when the relay is created
([`definition-documents.md`, "Secrets are named, not carried"](../../../docs/guidance/engineering/definition-documents.md#secrets-are-named-not-carried)).

A relay entry's `grant_key_secret_key` names the profile value containing the
Ed25519 private key as one-line standard base64 PKCS#8 DER. The importer strips
surrounding whitespace and refuses a missing, malformed or non-Ed25519 value
without echoing it. The profile key is resolved at relay creation; after API
rotation the API-held key remains authoritative during document reconciliation.
Keep the supplied profile key current when an empty-database reinstall must
recreate the plugin's trust. A service-generated key is recoverable only from
the service database.

Relay grant signing keys have the same create-time profile resolution rule. An
API key rotation is authoritative; a later relay-definition import does not
replace it from the named profile key. The provisioning service's
`relay_grant_expiry_grace_seconds` (default 3600 seconds) extends the lease end
for the signed grant, while `relay_port_reuse_margin_seconds` (default 300
seconds) delays reuse after that grant expiry. The allocator applies a raised
reuse margin to already released ports. Keep the grace at least the lease
watchdog's grace period plus a teardown job's retries and their backoff, so a
grant never expires while the teardown that revokes it is still due; the default
covers the default watchdog and retry settings. The service refuses to start
with a negative grace or a reuse margin that is not positive. Keep the relay
and provisioning clocks synchronized with skew well below the reuse margin; the
relay plugin checks expiry against its own clock with no leeway. These values
are service settings, not pool fields or buyer inputs.
