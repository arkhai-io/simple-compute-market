# Design — a pool declares what it advertises and whether it can be admitted against

## Context

`deliverable_modes` was built to close a specific hole: pools carrying legacy mode
metadata wider than anything their configuration could execute. The resulting
contract is deliberately unforgiving — empty authorizes nothing, a set must be
derived from configuration proving delivery, and a declaration wider than its
proof is narrowed to empty rather than retained. Its own migration scenario states
the preference plainly: an unproved capability is worse than no capability.

None of that is wrong. It is a contract about execution and it is correct about
execution. The problem is that it became the only place a pool says which modes
its listings may name.

Separately, nothing on a Resource Pool says whether it can be admitted against.
That has never mattered because every pool can. It starts mattering the moment a
site declares supply it intends to trade by private arrangement.

## Goals / Non-Goals

**Goals.** Let a pool authorize advertising a mode without proving it can deliver
it. Let a pool declare whether it can be admitted against, and make "nothing may be
reserved against an unbacked pool" true rather than aspirational. Keep every
delivery proof and execution recheck exactly as it is. Change no existing
deployment's advertising surface or admission behaviour on upgrade.

**Non-Goals.** No change to the meaning, derivation, or execution rechecks of
`deliverable_modes`. No listing, binding, or registry behaviour — that belongs to
the change that consumes these declarations. No new provider kind. No new pool read
inside the site authority.

## Decisions

### Two declarations, one change, split by service rather than by feature

An earlier version of this work put `advertisable_modes` here and `capacity_backing`
in the downstream storefront change. That produced a dependency cycle: the subset
rule below is scoped to backed pools, so this change's normative text needed a
concept the change that depends on it owned. The cycle was not terminological — the
integration plan asked an operator to create an unbacked pool that could not exist,
and `resource-pool-management` would have permanently defined behaviour for backed
and unbacked pools before either existed.

The cause was splitting by feature when the seam is a service boundary. Both tags
are declarations a site makes about a Resource Pool. They travel the same
policy-tag channel, need the same migration, and take the same fail-closed
validation. Everything that *reads* them for listings — candidate derivation,
listing binding, registry publication, version-skew tolerance — is storefront-side.

Splitting declaration from consumption also gives the site-side migration a home.
Someone has to persist explicit values on every existing pool at upgrade; that is a
provisioning-service migration against `resource-pool-management`, and putting it in
a storefront change would blur a boundary this campaign has spent several rounds
sharpening.

The consequence, accepted deliberately: this change is observable to operators and
to no one else. No listing behaviour changes until the storefront reads the tags.
Its acceptance boundary is that the declarations exist, are validated on every
write path, every existing pool carries both, and one shared resolver exists for a
consumer to read them through.

### A separate declaration, not a conditional reading of `deliverable_modes`

`unbacked-listing-publication` first proposed reading `deliverable_modes` as two
jobs — advertise-authorization for every listing, execute-authorization for backed
ones — and scoping only the second. That does not survive the contract. For an
execution-less seller the proved set is *empty*, and empty "authorizes no mode."
Reading a second job out of a field does not help when the field's value is
nothing.

An earlier draft called the pool conjunct outright vacuous for unbacked listings.
Worse: it would let a pool proving no VM delivery advertise VMs, which is the exact
failure `deliverable_modes` exists to prevent, reintroduced through another door.

So `deliverable_modes` keeps its meaning, derivation, and rechecks, and
`advertisable_modes` answers a question nobody was asking it.

### A backed pool advertises a subset of what it delivers, checked in both directions

A backed pool's advertisable set must be a subset of its deliverable set. Without
that, this change reopens the hole: a pool that can be reserved against could
advertise a mode it cannot execute, and a buyer would reach admission for something
the provider will refuse.

The rule is a relation between two mutable declarations, so either side can break
it. A write that widens `advertisable_modes` beyond the deliverable set is rejected,
and so is a write that narrows `deliverable_modes` below the advertisable set. The
second is **rejected, not repaired**: silently narrowing the advertisable set to
make a deliverable edit succeed would change what a pool advertises as a side
effect of an unrelated declaration. An operator withdrawing delivery narrows both
in the same write.

### An unbacked pool delivers nothing

`unbacked` means no admission authority stands behind the pool, so nothing may be
reserved, committed, or released against it. Nothing in the site authority reads
backing, and this change deliberately adds no such read (the site's pool
dependency is owned by `inject-site-pool-authority`). Admission today refuses a pool only through
`deliverable_modes`. An unbacked pool with a non-empty deliverable set would
therefore be admissible, and the downstream argument that no capacity path is
reachable for an unbacked listing would be false.

So an unbacked pool's deliverable set MUST be empty, enforced on every write and by
the shared resolver. That makes the guarantee true through the existing
reservation, scheduling, and dispatch rechecks, each of which already refuses a
pool declaring no deliverable mode. An unbacked pool's advertisable set is then
unconstrained by delivery — there is nothing for it to be a subset of — and that is
precisely the execution-less seller's case.

The asymmetry with backed pools is the point rather than an exception: the subset
rule protects a path unbacked pools never enter, and the empty-deliverable rule is
what guarantees they never enter it.

An earlier draft left "an unbacked pool with a non-empty deliverable set" open as
representable-but-undecided — a seller with real execution integration choosing to
trade out of band. Refusing it costs that seller nothing today: they can declare a
backed pool, or an unbacked pool beside it. **Revisit trigger:** a seller with
working execution integration who needs a single pool to be both provisionable and
out-of-band. Allowing it then requires a backing check at site admission, which
must go through the pool-facts port `inject-site-pool-authority` introduces.

### Both tags are required on every write; nothing is defaulted, preserved, or merged

Every pool write — create, replace, patch when it supplies `policy_tags`, and every
entry of an authoritative definition document — MUST carry both
`advertisable_modes` and `capacity_backing` explicitly. A write omitting either is
refused with a validation error. There is no create-time default, no
preserve-on-omission exception to replacement semantics, and no merge of a request's
tags with stored ones: the map a request supplies is the map stored, exactly as for
every other policy tag.

This is what makes "every pool carries both tags" true by construction. Migration
establishes it for existing rows; required-on-write keeps it. The projection's
emit-on-every-pool guarantee then needs no machinery of its own, because the
projection copies stored tags verbatim.

Two alternatives were considered and rejected.

- **Default on create, preserve on omission.** Create records `backed` and `[]`
  when omitted; replace, patch, and import copy a stored value forward when the
  request omits it. That keeps existing callers working, but it needs a narrow merge
  of request tags with stored tags on every write path, a reconciliation comparison
  against the merged map rather than the document, and cross-tag checks that read
  stored state during document validation. It also makes `capacity_backing` a
  permanent exception to the replacement rule the spec states for optional tags.
  All of that exists only to tolerate a client or document written before the tags
  existed.
- **Default on every omission.** Writing `[]` whenever `advertisable_modes` is
  omitted keeps every pool populated, but silently stops a legacy pool advertising
  after an unrelated edit.

What makes rejection affordable is that there is little to be compatible with.
Every existing pool is backed supply, migration writes both tags onto every row,
and the callers and fixtures writing pools are few and in this repository. An
old-format document or client is refused loudly, naming the missing tag, which is
a better failure than any silent default: a default for `capacity_backing` asserts
whether anything stands behind a listing, and a default for `advertisable_modes`
either widens or silently narrows what a pool may sell.

The general rule that a full replacement resets omitted *optional* policy tags is
unchanged. These two tags are not optional, so it does not reach them.

### Backing is fixed at creation

Every listing derived from a pool inherits its backing, so changing it in place
would silently reinterpret listings already published — a buyer holding a listing
reference would find the claim behind it altered without the listing changing. The
supported path is a second pool declaring the intended backing with capacity
resources migrated across.

With both tags required on every write, immutability is a single check: a replace,
patch, or document entry for an existing pool whose `capacity_backing` differs from
the stored value is refused and the pool is unchanged. There is no omission case to
reason about.

A stored pool with no backing value may be given one, on every write path. That
state is reachable only through a rolled-back older version rewriting a pool's
tags, and the service then refuses to start, so the API is unavailable and the
repair arrives through a changed definition document. Restricting the exception to
the import path was considered and rejected: it would thread a mode through the
service to guard a state no running service can hold. For document import the check compares against stored state, so it is
evaluated while reconciliation is planned and reported as a structured problem on
the validate-only path as well as refusing the import.

This has a consequence downstream worth stating here, because it is the reason the
rule is normative rather than advisory. `unbacked-listing-publication` makes a
backing change close-and-republish at the listing level, and
`storefront_listing_bindings` is immutable with a `NOT NULL UNIQUE`
`derivation_key`. If a pool's backing could change in place, the republished
listing would derive from the same site, pool, mode, and domain identity, hash to
the same key, and collide with the closed listing's surviving row — the transition
would deadlock on the unique index. Pool replacement gives the new listing a
different `pool_id` and therefore a different key by construction, which is also
why backing does not need to appear in the derivation source envelope.

The same argument applies to a pool's provider, which
`pools-9-retire-local-physical-authority` fixes at creation for the same reason.

### Validation is shared by the API models and document import

The shape of `deliverable_modes`, the presence and shape of both new
declarations, the backed subset rule, and the unbacked empty-deliverable rule are
one shared validation in `market_resource_pools` (`pool_declaration_problems`),
applied identically by the typed pool models used by create, replace, and patch,
by the service, and by authoritative document validation and import. Create and
replace declare `policy_tags` as a required field rather than defaulting it to an
empty map that validation then refuses, so the published schema matches the
rule. This follows the existing rule that
declaration semantics do not depend on which administration surface an operator
chooses, and it keeps document validation free of database reads for everything
except backing immutability, which by definition compares against stored state.

### Seeding and stored state fail closed and loudly at service load

A service that seeds pools at startup — the provisioning service importing its pool
definition document, and the API-credits service creating its own `default` pool —
MUST refuse to start when a seeded pool does not carry valid declarations, naming
the pool and the problem. A pool definition document is only re-applied when its
digest changes, so an unchanged deployment still starts; an edited document that
predates the tags stops startup rather than importing pools without them.

Stored state is checked at load the same way. After migration every stored pool
carries valid declarations, so the check never fires on a straight upgrade. It
exists for the case migration cannot cover: a pool written by a rolled-back
older version, which drops tags it does not know when it replaces a pool's
`policy_tags`. Failing at load names the pool for an operator to repair instead of
letting a pool without declarations reach a projection, where a consumer would have
to distinguish it from an old producer.

### Migration clobbers both tags on every existing pool

Every existing pool is backed supply, and each one advertises exactly what it
delivers because that is the only mode declaration it has. So migration writes, for
every Resource Pool row, `advertisable_modes` equal to its proved deliverable set and
`capacity_backing: backed`, and reports each derived value at INFO, matching how the
deliverable sets were derived. Upgrading changes nothing observable; any divergence
afterwards is an explicit operator act.

Migration overwrites whatever the row held under those keys. Unknown policy tags
were forward-compatible opaque metadata, so a row could hold either key with any
value, but no consumer ever read one, so clobbering it changes no behaviour. The
same applies to the API-credits service's own pool storage, which holds a
`default` pool it creates itself outside pool administration: its existing rows are
migrated and its seed writes both tags.

Defaulting absence to "advertise anything" is the failure `deliverable_modes` was
built to fix, and repeating it in a neighbouring field would be indefensible.
Absent authorizes nothing here too; required-on-write means absence can only reach
a reader from a producer predating the tags.

### A producer that emits these tags emits them on every pool

The emit-on-every-pool requirement is what makes the consuming side's version-skew
rule possible, and it is worth stating here rather than assuming. The consumer's
rule distinguishes "no pool carries the tag" (a producer predating it) from "some
pool is missing it" (a producer defect, which fails that pool closed). Without
completeness an upgraded site holding legacy pools would read as an old producer
indefinitely, and the first explicitly unbacked pool an operator created would turn
every other pool into a partial omission and fail working pools closed on a correct
operator action.

Here completeness is structural: migration writes both tags on every row,
required-on-write keeps them there, load-time checks catch rows that escaped both,
and the projection copies stored tags verbatim. The requirement is still stated
normatively, because it is a property a consumer depends on and cannot verify from
its own side.

### A malformed backing value fails closed

`capacity_backing` is a discriminator, so an unrecognized value is refused rather
than resolved to either side. This differs deliberately from the cardinality hint,
where an unrecognized value falls back to a domain's structural default: a
cardinality default is a reasonable guess about how many candidates to publish,
while a backing default is a claim about whether anything stands behind a listing.

### One shared resolver; the storefront is the consumer

The only reader of projected pool tags is the storefront, and storefront listing
behaviour is outside this change. What this change owns is the definition of a
valid declaration, so it exposes one domain-neutral resolver in
`market_resource_pools` that turns a pool's `policy_tags` into typed
`(advertisable_modes, capacity_backing)` or fails:

- a malformed value of either tag, a backed pool whose advertisable set exceeds its
  deliverable set, and an unbacked pool with a non-empty deliverable set each raise
  rather than resolving to a default;
- an absent tag is reported distinctly from a malformed one, so a consumer can apply
  its producer-version rule to "no pool carries it" while failing a single omitting
  pool closed.

Advertisement membership is a method on the resolved `PoolDeclarations`, and
backing is typed as `Literal["backed", "unbacked"]` there. No public function reads
`advertisable_modes` from raw tags: such a reader would treat an absent
declaration as empty, which is precisely the distinction a consumer of projected
declarations must keep, and the easiest-looking API should not be the one that
erases it.

`resource-pool-management` requires any reader of projected declarations to resolve
them through this function, so the write side and every read side agree on what a
valid declaration is without the site's validation and the storefront's diverging.
The write-side validation and the resolver share one implementation.

`unbacked-listing-publication` wires the resolver into the storefront's projection
ingestion. It owns the producer-version rule the resolver deliberately leaves to its
caller, and it is the first change whose behaviour reads the resolved values; wiring
the call here would ship a storefront read whose result nothing uses. The split is
bookkeeping rather than a design seam — the roadmap lands these changes without a
deployment between them — so this change proves the resolver at the kit level and
proves the producer side of the projection, and the consumer change proves
ingestion.

### Declaration validation lives in the pool models

The shared declaration validation runs as a model validator on `PoolCreate`,
`PoolReplace`, and `PoolUpdate` (when it supplies `policy_tags`), and in document
validation. A typed client therefore cannot construct an invalid pool write, and the
API refuses one with the framework's 422 before the service runs. The service still
applies the same validation to what it persists, so a model built without
validation cannot bypass it. Backing immutability needs stored state, so it stays a
service check and refuses with 400 like the service's other validation failures.

Document-import failures name each problem's path — the pool entry and tag — in the
raised error, so a service refusing to start on a seeded document says which pool
to fix.

### Not a publication-only provider kind

The alternative considered was a provider kind meaning "never dispatches", letting
an execution-less pool satisfy the existing schema honestly. Rejected: it puts a
pool into the fleet whose provider exists to be never called, and every dispatch
path then depends on a handler doing nothing rather than on a declaration saying
nothing. A missing declaration is a safer thing to get wrong than a no-op
executor. An execution-less seller's pool names an existing configuration-free
provider, which `unbacked-listing-publication` records as an accepted decision.

### Both tags are projected

Every other pool policy tag travels the projection, and the storefront needs both
values as inputs rather than as checks — it derives candidates from the projection
and has no other route to a pool's record. They travel inside `policy_tags`, which
the projection already copies verbatim, so no projection code changes.

### Nothing to split

`resource-pool-management`'s mode contract comes from the archived
`pool-declared-offering-modes` change. No active change owns it, so there was no
in-flight work to carve a minimal piece out of — this amends a permanent
specification directly, which is the ordinary path.

## Risks / Trade-offs

- **[Two mode declarations drift]** → An operator can widen advertisable while
  deliverable narrows, which for a backed pool is exactly what the subset rule
  refuses. Enforced in both directions on every write, and again by the shared
  resolver, because the two sides upgrade independently and a write-side-only check
  would let a reader accept what an operator could not write.
- **[The subset rule is read as universal]** → It applies to backed pools.
  Stating the scope in the requirement rather than leaving it inferred is what
  keeps an unbacked pool from being forced back into an execution proof.
- **[Required tags break existing writers]** → Every client, fixture, and
  definition document that writes pools must carry both tags from this change on.
  Accepted: the writers are in this repository and are updated with it, and a
  refused write names the missing tag. An operator's own edited definition document
  that predates the tags stops the service at load rather than importing silently.
- **[Rollback then roll forward]** → An older version replacing a pool's
  `policy_tags` drops both tags, and the one-shot migration will not rewrite them
  on the next upgrade. The load-time check names each such pool and refuses to
  start, so the API is unavailable for the repair; the operator restores the
  declarations through a changed pool definition document, which is imported
  before the check runs. A pool with no stored backing may be given one, so that
  import is a repair rather than a refused backing change.
- **[A change with no observable behaviour ships and is forgotten]** → Its value is
  entirely in what depends on it. Mitigated by it being a declared prerequisite
  with a named consumer rather than speculative groundwork.
- **[A second and third policy tag invite a fourth]** → Accepted. The line worth
  holding is that each tag answers one authorization or capability question about
  the pool; a tag answering a question about cardinality or settlement belongs in
  the field that already owns it.

## Open questions

None remain in this change.

The question of how the site authority should read pool declarations is owned by
`inject-site-pool-authority`. `kit/site`'s ledger reads `ResourcePool` directly,
contrary to `ARCHITECTURE.md`'s kit layers, and this change deliberately adds no
read to it: an unbacked pool stays out of admission through its empty deliverable
set. That change replaces the direct reads with an injected, session-scoped
pool-facts port and a boundary test that enforces the layer rule. If the revisit
trigger for refusing an unbacked pool that delivers fires, the backing read it
needs goes through that port.

## Migration Plan

1. Add both tags with shared validation and the typed resolver alongside
   `deliverable_modes`, and require them on every pool write path.
2. Migrate every existing Resource Pool — provisioning and API-credits storage —
   overwriting `advertisable_modes` with its proved deliverable set and
   `capacity_backing` with `backed`, reporting each derived value at INFO.
3. Update every in-repository pool writer — seeds, fixtures, chart values, and
   definition documents — to carry both tags.
4. Fail service load on a seeded or stored pool lacking valid declarations.

No deployment's advertising surface or admission behaviour changes at any step:
every pool advertises exactly what it delivered before and remains admissible,
until an operator changes it. Rollback is a code rollback; the tags remain and are
ignored by a restored reader as opaque metadata. Rolling forward again after the
older version has rewritten a pool is covered under Risks.
