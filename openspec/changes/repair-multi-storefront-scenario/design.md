# Design — repair-multi-storefront-scenario

## Original failure and containment

Alice originally skipped incidentally because her e2e settings were absent.
Once configured, she called Bob's authority, which correctly rejected her
principal. Explicit skips on `06b` and `06c` made the negotiation gap visible
while retaining registry coverage. The earlier four-stage estimate was not
an observed skip count. Those two explicit skips are removed by this repair;
downstream prerequisite skips still identify missing scenario state.

## Accepted topology and unblocking

Alice and Bob are separate storefronts. Give each a separate provisioning
service instance with its own authority identity, configured storefront
counterparty, callback destination, and inventory. Alice must consume her
authority's projections and stop using local-table listing derivation.

This preserves the topology in `service-identity-signing` and
`replace-polling-with-authenticated-push`: each site uses its own credential,
distinct from the storefront's, and each authority serves one storefront.
Neither change needs a topology amendment for this repair.

Rotation overlap accepts credential generations of the same counterparty;
it must not be used to introduce an independent storefront. The earlier
proposal to configure several sellers on one authority is rejected.

Acceptance proves registry isolation, fan-in, and distinct negotiations across
two projection-backed storefronts, not shared-site storefront substitution.
The explicit blocked-stage skips are `06b` and `06c`; verify the actual runtime
skip set rather than relying on the earlier four-stage estimate.

The file-level plan is recorded in tasks.md. Alice uses a deterministic
Ed25519 service identity and container-local database state. Job queues are
process-local. The existing Redis setting in Bob's Compose service is unused
by provisioning, so Alice does not need a separate Redis service. Both storefronts may call their local site alias `default`: the alias is
scoped to its storefront and resolves to a different authority in each.

The VM fiat overlay profiles Alice's authority with Alice herself,
so hosted-only stacks do not start an unconfigured extra authority. The
scenario uses the same typed provisioning and capacity administration clients
for both storefronts, then explicitly refreshes each projection before listing
creation. Local CSV scenario seeding is removed for both storefronts.

## Deliberately not addressed

Multiple storefronts per site, shared-authority ownership and routing, new
authentication protocols, general push delivery, and expanding this scenario
to multiple sites per storefront are out of scope.

## Permanent documentation text prepared for post-review promotion

`docs/development/DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition":
The VM development stack runs Bob and Alice as separate storefronts, each with
its own provisioning authority, service signer, callback destination, database,
and process-local job queue. Both storefronts name their local site `default`; these
aliases resolve to different authorities. The local identity overlay supplies
the deterministic development credentials. The fiat overlay keeps Alice and
her authority behind the same optional profile.

`docs/development/TESTING.md`, end-to-end scenario guidance:
The multi-registry scenario seeds each storefront's authority through typed
administration clients and refreshes its projections before listing creation.
It proves Bob's publication to both registries, Alice's publication to only the
public registry, deduplicated discovery, resilience to an unavailable registry,
and independent negotiations. It does not prove shared-site tenancy.

`docs/development/ROADMAP.md`, Goal 1:
Remove this change's shared-hardware substitution gap mapping: this repair
establishes two projection-backed storefronts using separate authorities.
Multiple storefronts per site remain explicitly out of scope. Retain the
pools-9 local-authority retirement gap until its own implementation completes.

No service API or authentication invariant changes, so the existing subsystem
specifications remain authoritative without a new protocol delta. These
changes are development composition and test coverage.
