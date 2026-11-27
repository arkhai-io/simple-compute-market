---
tags: [repository, configuration]
---

# Provisioning definition documents

The definition documents the provisioning service is given, as this repository's
instance of
[`definition-documents.md`](../../../docs/guidance/engineering/definition-documents.md):
their settings, the order startup imports them in, how each kind applies the method,
and the relays' secrets; the service's time source; its operator events; and the
failure messages an operator marks non-retryable. The pool document's own rules are
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
reuse margin to already released ports. Size the grace for the teardown still
due after the lease ends: the reruns' spacing for `teardown_rerun_limit` reruns,
a teardown job's retries with their backoff, and the playbook runs a teardown is
expected to take, so a grant does not expire while a working teardown that
revokes it is still due. It is sized for the same expected teardown as the lease
watchdog's grace, and need not cover that grace: past it no teardown is due,
since the lease is `release_failed` and an operator acts. The default covers the
defaults' backoff and spacing with room for runs. The service refuses to start
with a negative grace or a reuse margin that is not positive. Keep the relay
and provisioning clocks synchronized with skew well below the reuse margin; the
relay plugin checks expiry against its own clock with no leeway. These values
are service settings, not pool fields or buyer inputs.

The lease watchdog's `lease_watchdog_grace_period_seconds` (default 3600
seconds, in the service's settings and in both charts' values) is how long a
lease may stay `releasing`, timed from when it entered `releasing`, before it is
marked `release_failed` with `teardown_timeout` for an operator, whether its
teardown is in progress or a rerun of it is pending. It is sized for the
teardowns a deployment is expected to run, not for the longest the settings
allow: at the defaults a teardown's waits are the reruns' spacing (60, 120 and
240 seconds) and the retry backoff of the one job whose execution starts (60,
120 and 240 seconds again), 14 minutes in all, leaving about 46 minutes for that
job's playbook runs. A teardown running longer is timed out like any stuck
release, and an operator's retry-release then releases its lease once its
teardown is torn down. `teardown_rerun_limit` (default 3) is how many times a
teardown whose job failed before its execution started is run again, each under
a new job, spaced after the previous job's finish by the job retry policy's
backoff; 0 disables reruns, and the service refuses to start with a negative
value. Raise the watchdog grace, and the grant grace with it, when raising
`teardown_rerun_limit`, the job retries or `ansible_timeout_seconds`, or for
teardowns that run longer ([Proof-driven release](architecture.md#proof-driven-release)).

## The service's time source

The provisioning service reads `time.source` from its profile, `"wall"` when unset
or `"injected"`; any other value refuses startup, naming the setting and the value.
Under `"injected"` it starts frozen at the wall instant it started, logs that at
startup, and mounts `POST /api/v1/system/time` behind its signed administrator
authentication; its system status carries the time section in either mode. The
lease watchdog, lease termination, the job engine and the site it hosts read that
source. A service whose relays admit real proxies runs on wall time: the relay
plugin checks a grant's expiry on its own clock, which no lane time moves. No
packaged profile or chart default sets it; only the lanes' `lane-time` profile,
`dev-env/provisioning/config-lane-time.yml`, layered through `ACTIVE_PROFILES`, does
([injected time](../injected-time/architecture.md)).

## Operator events

The provisioning service reads an `[Events]` section configuring the events it
records ([`operator-events.md`](../../../docs/guidance/repository/operator-events.md)):
how long they are kept, how often they are delivered, and which sinks receive which
of them. The contract is the `physical-provisioning` requirement "The provisioning
service delivers events to the sinks its routes select"
([specification](spec.md)); what an operator reads and resumes is the
[operator handbook's "Operator events"](../../../docs/operator-handbook.md#operator-events).

```toml
[Events]
delivery_interval_seconds = 10
sink_max_age_seconds = 86400
finally = "log"

[Events.retention_days]
events = 30
deliveries = 30
lease_end_reports = 0               # 0 keeps every row

[Events.sinks]
enabled = ["ops-push", "audit"]

[Events.sinks.ops-push]
sink = "apprise"                    # its urls in the Secret overlay

[Events.sinks.audit]
sink = "file"
path = "/var/log/provisioning-events.jsonl"

[Events.routes.held-work]
where = "severity = 'action_required'"
sinks = ["ops-push", "audit"]

[Events.routes.long-jobs]
where = "kind = 'provisioning.job_finished' AND duration_seconds >= 1800"
sinks = ["audit"]
```

- `retention_days` is how many days each table's rows are kept: `events` the events
  with their references, `deliveries` the finished delivery state, and
  `lease_end_reports` the signed lease-end reports. 0 keeps every row. The defaults,
  in the service's `settings.toml`, are 30, 30 and 0. An event is pruned only once it
  is past its retention and owed to no active destination; a signed report is kept,
  whatever its own retention, while its event is.
- `delivery_interval_seconds` (default 10) is the event delivery worker's timer: each
  cycle runs every consumer's deliveries, then prunes. A lease command or watchdog
  cycle that ends or releases a lease delivers the storefront's report and callback
  before it returns, so this interval paces retries, operator sinks and pruning.
- `sink_max_age_seconds` (default 86400) is how long a sink's failing delivery is
  retried, with a backoff doubling from 10 seconds to at most an hour, before it is
  abandoned to the finally sink. The storefront peer's deliveries have no maximum age
  and are retried until delivered, parked or refused.
- `finally` (default `"log"`) is where an abandoned operator-sink delivery goes:
  `"log"`, a warning on the `eventing.finally` logger carrying the event and its last
  error, or the name of an enabled sink instance. The storefront peer's consumers
  abandon to the log.
- `sinks` is shaped as a storefront's `[Delivery]`
  ([`introduction-delivery`'s configuration](../introduction-delivery/configuration.md#introduction-delivery)):
  `enabled` names the sink instances, and each `[Events.sinks.<name>]` names the
  installed sink it uses with `sink` — `file`, `command`, `webhook`, `smtp`, or
  `apprise` — and that sink's settings. A webhook instance with `sign = true` signs
  each delivery with the service's identity, as role `service` and operation
  `operator_event_delivery`. No sink is enabled by default, so a deployment that
  configures none delivers events to the storefront peer alone.
- `routes` holds one `[Events.routes.<name>]` per route: `where`, an SQL condition
  over the event, and `sinks`, the enabled instances it selects. The condition's
  columns are the envelope's scalar fields — `kind`, `kind_version`, `severity`,
  `severity_rank` (`info` 0, `warning` 1, `action_required` 2), `subject_type`,
  `subject_id`, `source_service`, `source_instance`, `sequence`, `occurred_at`,
  `correlation_id`, `causation_id`, `summary`, `id` and the rest — and every
  attribute a declared kind declares, which reads `NULL` on an event whose kind does
  not; the table `related` (`event_id`, `type`, `id`) holds its references, read
  through a subquery such as
  `id IN (SELECT event_id FROM related WHERE type = 'host' AND id = 'bm-02')`. An
  event goes to every sink any route selecting it names, once. No route is
  configured by default.

The service refuses to start, naming what is wrong, on an `[Events]` key it does not
know, a negative retention or a delivery interval or maximum age that is not
positive, a sink instance it cannot build, an instance configured but not enabled, a
route whose condition holds anything but comparisons, `AND`, `OR`, `NOT`, `IN`,
`LIKE`, `IS NULL`, literals and subqueries over `related`, or names a column neither
the envelope nor a declared kind has, a route naming a sink that is not enabled, and
a `finally` naming no enabled sink.

A sink's secret settings — an Apprise URL, a webhook URL that carries a token, an
SMTP password — go in the service's Secret overlay, under the chart the
`config-provisioning-secrets.yml` profile its runtime Secret supplies, never in the
public profile the chart renders into its ConfigMap
([`DEPLOYMENT_AND_CONFIG.md`, "Kubernetes: ConfigMap and Secret mounting"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#kubernetes-configmap-and-secret-mounting)).
The chart passes `Events` through its `config` unchanged and the service does not
refuse a secret sink setting stated in the public profile, so keeping it out is the
operator's.

## Non-retryable failure messages

`additional_non_retryable_errors` (default empty) lists substrings an operator marks
non-retryable for both domains' playbook jobs. A failed attempt is not retried,
whatever its class, when one of them occurs, ignoring case, in the deciding failure
record's `msg`, `stdout` or `stderr` — the last failed or unreachable task neither
ignored nor rescued — or in the failure's classified message, which a timeout or a run that
recorded no task also has. The classes the executor and the codecs already refuse to
retry need no entry; the classes and their retry decisions are
[the architecture's "Failure classification"](architecture.md#failure-classification).
The contract is the `physical-provisioning` requirement "Operator-configured
non-retryable substrings are matched against the failure record"
([specification](spec.md)).
