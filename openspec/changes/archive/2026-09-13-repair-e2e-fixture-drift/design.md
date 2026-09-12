# Design — repair E2E fixture drift

## Context

Both failures are constructor calls, so they raise during fixture setup and every
test depending on them reports an error rather than a result. That is why a
two-line cause produces 88 errors, and why the count is not a measure of how
much is wrong.

## Decisions

### The suite moves, not the libraries

Each mismatch is a library that gained a capability the suite has not caught up
with.

`SyncProvisioningClient` now takes `(base_url, signer, expected_authorities, *,
timeout, transport)`. The service it drives authenticates per caller — the
compose stack configures `PROVISIONING_IDENTITY__*`,
`PROVISIONING_STOREFRONT_IDENTITY__*`, and `PROVISIONING_ADMIN_IDENTITY__*`, and
the storefront profiles pin it as a `service_peer`. A shared `X-Admin-Key` is
the model that preceded that. Reverting the client would undo per-caller
identity across the provisioning boundary to avoid editing a fixture.

`ProfileStore.revision` is `Field(ge=0)` with no default, and
`ProfileRepository.replace` takes `expected_revision` — together they are
optimistic concurrency on the buyer profile document. The fixture already passes
`expected_revision=0`, so it half-knows about the mechanism; it just does not
set the field on the candidate.

### The initial state has a constructor, but the constructor is not enough

`ProfileStore` exposes a classmethod returning `cls(revision=0)`, and the
instinct is to call that and populate it rather than pass `revision=0`
literally — a hard-coded zero is a second place to change if the initial
revision ever stops being zero.

That instinct is right about ownership and wrong about mechanism.
`ProfileRepository.replace` refuses a candidate whose revision does not advance
past `expected_revision`, so `empty()` populated in place fails exactly as a
literal `revision=0` does, with `ProfileRevisionConflict` instead of the
`ValidationError` seen today. Both were run against the installed package to
confirm it.

The model owns the increment as well as the initial value: `add_profile` goes
through `_next_store`, which returns `revision=store.revision + 1`. So the
fixture composes the two — `add_profile(ProfileStore.empty(), profile,
select=True)` — and hard-codes neither number. The general form of the lesson
is the one already on this branch: reading a field's default is not the same as
reading the contract that field participates in.

### Repair, then classify — not repair and chase

Turning 88 errors into 88 results will expose whatever the suite was written to
catch and has not been able to report since mid-August. The temptation is to fix
those findings in the same pass.

It should not. The identities change absorbed five unrelated pre-existing
defects before reaching a boundary, and each one made its proposal less true
than when it was written. This change ends when the fixtures are correct and
the remaining failures are classified — every one either a real finding with an
issue raised, or a genuine pass.

### What the fixture needs, and the one thing to confirm first

The repaired `provisioning_client` needs two values the settings may not yet
carry:

- **A signer.** The provisioning service's admin principal is
  `0x9965507d1a55bcc2695c58ba16fb37d819b0a4dc`, configured as
  `PROVISIONING_ADMIN_IDENTITY__IDENTIFIER` in
  `compose.local-identities.yml`. The e2e settings expose `SELLER.PRIVATE_KEY`
  and `SELLER.ADMIN_API_KEY`, and the second is now the wrong shape entirely —
  it is a bearer key, not a credential.
- **An `expected_authorities` set.** The provisioning service signs as
  `PROVISIONING_IDENTITY__IDENTIFIER`, `0xf39fd6e5…`.

**Confirm before writing the fixture** whether the suite should drive
provisioning as the *admin* principal or as the *storefront* principal
(`0x3c44cddd…`, pinned as `PROVISIONING_STOREFRONT_IDENTITY__IDENTIFIER`).
Those are different callers with different authorisation, and the answer decides
which credential the fixture needs. The retired shared admin key made the
question invisible, which is part of why the drift went unnoticed.

## Risks / Trade-offs

- **[The repaired fixture authenticates as the wrong principal]** → It would
  fail on authorisation rather than construction, which is a clearer signal
  than today's `TypeError` but still not a result. Settling the caller question
  before writing the fixture is what avoids it.
- **[The suite reports many real failures once it runs]** → Expected, and the
  reason this change classifies rather than fixes. A long list of genuine
  findings is a better position than 88 errors that say nothing.
- **[Fixture repairs drift again]** → The root cause was that no working stack
  existed to run against, which the archived identities change fixed. The
  nightly workflow now exercises this path, so the next divergence surfaces in
  a day rather than a month.

## What the repair actually found

The proposal assumed two drifted construction sites. There were six, plus two
payload-shape mismatches behind them. The other four were invisible: pytest
reports the first fixture that raises, and `provisioning_client` raised first,
so `storefront_client`, `storefront_admin_client`, `registry_client`, and
`ProvisioningTestClient` were never constructed. An error count is a count of
*first* failures, which is why the survey had to read every construction site
against the installed signature rather than work down the reported list.

The same shape recurred at the payload level once construction succeeded:
`create_listing` first refused a retired `agent_wallet_address`, then required
a `capacity_source` that had not existed, then required the resource to declare
`offering_mode`. Each was one layer under the last, and three consecutive runs
reported identical counts while the cause changed every time.

## One client per role

The retired shared admin key made every caller look alike, so nothing forced
the question of who the suite is when it acts. Per-caller identity forces it,
and `SyncStorefrontClient` binds exactly one role per instance and refuses
operations belonging to another. The suite therefore carries one client per
role, named for the role, so the assertion is visible at the call site and in
the service's request log:

| Caller | Role | Principal |
|---|---|---|
| Buyer | `buyer` | buyer marketplace credential |
| Seller | `seller` | storefront publishing principal |
| Storefront administrator | `admin` | `Identity.administrators.operator` |
| Provisioning administrator | `admin` (fixed by the client) | provisioning admin identity |
| Registry discovery | `buyer` | buyer credential |
| Registry publish validation | `seller` | seller credential |

The registry has no administrator in its vocabulary — it accepts `buyer`,
`seller`, or `service` — so its two clients split on what the call means rather
than on privilege. Its reads here are unauthenticated, so the role attributes
the call without gating it.

Seller and administrator were the same principal in development configuration,
which is precisely the conflation the identity model separates: a storefront's
`Identity.principal` publishes, and its `Identity.administrators.operator`
operates. They are now distinct accounts, so the suite exercises the boundary
instead of assuming the two parties coincide.

## System status is readable by two roles

`admin_system_status` asserted `service` while binding an operation named for
an administrator, and its sibling read on the same prefix,
`GET /api/v1/system/events`, was already an administrator contract. Correcting
it to `admin` then broke the provisioning adapter's `storefront_auth` health
check, which reads status as a service peer to confirm its own signing path
works — the only side-effect-free service operation there is, since every other
one is a fulfillment callback that mutates state.

The route serves both callers, and the design already said so: both middlewares
dispatch on the asserted role for this exact path, with the administrator
middleware passing a `service` request through to the service-peer middleware.
The original error was removing one branch instead of adding the other beside
it. A client now asserts whichever of the two roles it holds.

The general lesson, which the branch's existing lessons did not cover: a route's
required role is not always single-valued, and reading one middleware's contract
table is not reading the dispatch.

## Diagnosing through suppression rather than through the error

The last seven listing failures returned `400 no enabled settlement mechanism
is ready`, which reads like a third defect and is not one. Settlement
composition suppresses any mechanism that is not ready and raises only when
nothing survives, so the message names the consequence rather than the cause.
The storefront logged `[SETTLEMENT] option suppressed mechanism=alkahest.v1
blockers=alkahest.address_config_invalid` exactly once per failure, which is
what tied those seven to the same configuration fault as the three alkahest
preflight assertions — ten of eleven failures being one fault, not two.

This is the reason the change reports causes rather than counts, and the reason
the failure classification is worth more than the failure list.

## Resolved questions

- **Admin or storefront principal for `provisioning_client`?** **Admin**, and
  the client decides it. `SyncProvisioningClient` sets `caller_role = "admin"`
  in its base `__init__` and offers no override; the service resolves the trust
  set from the asserted role. The storefront credential would construct and
  then 403. The question was real, but it had an answer in the code rather than
  in topology preference.

- **Does `SELLER.ADMIN_API_KEY` still have any consumer?** No. The storefront's
  `/admin/*` routes moved to signed identity with administrator trust pins, and
  `SyncStorefrontClient` has no `admin_key` parameter. Its only readers are
  fixtures that are themselves drifted, so the removal is correct but ordered
  behind their repair. Distinct from the registry bearer tokens, which survive
  as `SyncRegistryClient(api_key=...)`.

## Open questions

- **What role does each storefront fixture assert?** `SyncStorefrontClient`
  binds one `caller_role` and refuses operations belonging to another, and the
  storefront now separates `admin`, `buyer`, `seller`, and `service`. The
  existing `storefront_admin_client` serves both seller-owned routes and
  `/admin/*`, so it becomes two clients and its callers must be reassigned.
  This is the same shape of question as the provisioning caller — invisible
  while a shared key made every caller look alike — and it wants the same
  explicit answer before the fixture is written.

- **Should the suite keep a single `registry_client` at all?**
  `SyncRegistryClient` now requires `signer`, `caller_role`,
  `expected_registries`, and `registry_authority`. The last is per-registry,
  and the multi-registry scenario spans `registry-a` and `registry-b` with
  different authorities and schemes, so one module-scoped fixture may no longer
  be the right shape.
