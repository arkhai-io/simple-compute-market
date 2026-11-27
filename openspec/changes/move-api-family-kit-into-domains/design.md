# Design — the api family lives under its family directory

## Context

The `api` family's vocabulary and its distributions sit at `kit/api`. To admit
them there, `read_path` in `scripts/architecture.py` reads a family directory
under `kit/` as a family, and
`docs/guidance/repository/package-layers.md`, "Scope", says a family kit
belongs under `kit/`. `align-package-paths-with-layers` designs the opposite:
a family kit lives under its family, with its distributions as siblings there.

A review of the branch found that departure and seven smaller ones. Each was
checked against the code before a decision was taken, and several did not
survive as the review stated them: two concern code that cannot move yet, one
was already answered by the change that owns it, and one named a rule in a
document that does not hold it. The decisions below record what each became.

Nothing imports by path. Every internal dependency resolves from a built wheel
in the wheelhouse, no `pyproject.toml` names a sibling by path, and the locks
record the wheelhouse by a relative path whose depth the move does not change.
The move is therefore build plumbing, tests that reach the family by path, and
documents.

No marketplace release carries an api-family or inference distribution under
its present name, and the branch this change lands on has no `kit/api`.

## Decisions

### D1 — The family lives at `domains/api`, and a family is read only under `domains/`

The vocabulary project is `domains/api` and each distribution is a directory
directly beneath it — `contracts`, `client`, `authority`, `selling`, `buying`,
`gate`, `gateway`, `gate-ports`, and the four mechanism libraries — the shape
it has today under a new parent. Distribution names and import names do not
change. The family's `directory` in `docs/development/ARCHITECTURE.toml` names
`domains/api`, `read_path` returns to reading a family only under `domains/`,
and the test asserting the loosened reading is removed.
`package-layers.md` and `ARCHITECTURE.md` state the rule again: a package
several domains of a family share goes under the family's directory, and
`kit/` holds no specialization.

This supersedes the placement recorded when the family was put under `kit/`,
whose reason was that a family is not a listing schema a buyer shops for. That
reason distinguishes a family from a domain; it does not make a family
market-neutral, which is what `kit/` means. The compute family already lives
at `domains/compute`, and one rule for both families is what the scope rule
says.

With `read_path` restored and the directory renamed, every one of the twelve
Python projects reads the layer, kind, and scope it reads today: none of the
family's directory names is a role word, and a mechanism library's scope comes
from its own directory name. The four exception rows naming family
distributions are keyed by distribution name and are unaffected.

The family's build and test recipes move from `kit/Makefile` to
`domains/Makefile` and join its `dist-release`, `test`, and `.PHONY`
aggregates; the root Makefile reaches them through the domain aggregates and
needs no target of its own. The continuous-integration job that runs the
domain tests installs Node and Rust, because the gate ports' tests run with
the family's.

Rejected: `domains/api/vocabulary` for the vocabulary project.
`align-package-paths-with-layers` holds that question open for all four
vocabulary packages; three sit at their scope root today, and placing this
one there pre-empts neither answer. Rejected: leaving the family under `kit/`
with an override row per project, which records the divergence instead of
removing it.

### D2 — The Alkahest buyer modules stay in the family's buying library

`escrow_selection.py`, `escrow_client.py`, and `chains.py` in
`arkhai_api_buying_alkahest` stay where they are.
`move-escrow-into-alkahest` places them.

- `escrow_selection.py` imports the policy kit, and the policy kit imports the
  Alkahest kit, an edge `move-escrow-into-alkahest` owns as an exception row.
  Moving the module into `kit/alkahest` closes a cycle between the two kits.
  An exception row could excuse it, but `package-layers.md` asks that no new
  dependency of an already-excepted shape be added.
- `escrow_client.py` is not a copy of the VM buyer's module. Eight helper
  functions are the same; the settlement payload builder differs in behaviour,
  since the family's sends the chain name and the VM buyer's does not, and the
  codec class is the family's own.
- `chains.py` reads the user's configuration file, which `package-layers.md`
  names as misplaced in a kit, and `move-escrow-into-alkahest` removes the one
  such read `kit/alkahest` has.
- Any change to `kit/alkahest`'s contents takes a version step, because a
  release records its present version.

Rejected: moving the eight shared helpers alone. It removes about a hundred
lines, costs the kit a version step and its dependents a relock, and edits VM
buyer modules that `move-escrow-into-alkahest` reworks. Rejected here: a
separate buyer-side Alkahest kit, which avoids the cycle and the version step
but needs the rule that one kit holds a mechanism's scope amended; that
question travels to `move-escrow-into-alkahest` with the three files.

### D3 — The Arkhai-payments buyer library stays as it is

Nothing moves from `arkhai_api_buying_arkhai_payments` into
`kit/arkhai-payments`. The mechanism's buyer-side logic, the approval of a
seller-derived mandate, is already in the kit. What the family library adds is
buyer orchestration over the buyer role's own types, and a payment kit imports
no role orchestration; that edge is the exception row
`kit-owned-buyer-orchestration` owns. The library is not a copy of the VM
buyer's payments module, which commits through the deal-lifecycle client where
the family's posts a settlement request.

Rejected: moving `payment_selection_for_listing` and
`serviceable_payments_config`. No other buyer has either, so the move removes
no duplicate and costs the payments kit a version step.

### D4 — The authority refuses a pinned key's consumption at another amount

`consume`, and each item of a batched consume, is refused when the key's first
grant pins a request charge and the amount sent differs from it. The refusal
is named `charge_mismatch`, a single consume answers `409`, and a batched item
is an outcome in its place that leaves the other items applied. Nothing is
debited. A key whose first grant is unpinned is charged the amount sent, so
API credits, every one of whose keys is unpinned, behaves as before and its
recorded baselines do not move.

The gate needs no change. It already charges a verified key its pinned charge,
and it answers a consume refusal outside the key refusals it knows as a
refusal of its own call, `502` naming the reason, leaving the key's balance
and credit untouched. The conformance trace charges an unpinned key and does
not change.

The authority is the one party that holds both the pinned charge and the
ledger, and the requirement that a key's balance is spent at the charge each
grant was bought at is one only it can secure.

Rejected: leaving the check to `meter-inference-usage`. That change's proposal
adds hold and settle routes with server-side pricing but does not retire
`consume` for inference, and its non-goals leave API-credits consumption,
which shares the route, untouched; the gap could outlive it. Rejected: the
authority debiting the pinned charge whatever amount is sent, which hides a
defective caller instead of refusing it.

### D5 — The selling library takes the stage-event emitter by injection

`ListingService`, `StorefrontLoops`, and `build_negotiation_runtime` each take
the stage-event emitter as a required keyword, as the library's issuance and
failure-policy code already does, and `listings.py`, `lifecycle.py`, and
`negotiation.py` stop importing it from the storefront role. Each storefront
passes the emitter it already imports where it constructs these. No default is
given: a default that imported the role would keep the edge.

The emitter goes on the two constructors and the builder, not on the methods
that use it, because one of those methods is registered as a loop step taking
no arguments and another is reached through the listing route's protocol.

The exception row for `arkhai-api-selling` on `arkhai-core-storefront` stays,
with the stage-event log dropped from its reason: fifteen import lines remain,
all the storefront carve-out's to place.

Rejected: repointing the library at `kit/storefront`, which serves none of
what the library imports from the role. Rejected: carrying the emitter in the
contributions bundle, which holds what a domain contributes, where the emitter
is the storefront's own collaborator.

### D6 — The move precedes the two buyer changes' closeout

The move does not wait for `keep-buyer-credentials-private` or
`derive-buyer-settlement-inputs`. Their code is written and on the branch, D2
and D3 leave it where it is, and the only overlap is the path. The move
rewrites the `kit/api` citations in their documents. Waiting would put two
closeouts in front of the move to save ten line edits.

### D7 — One settlement composition builder is the selling library's

The body the two storefronts' settlement composition builders share moves into
the selling library as one builder. Each storefront keeps a function that
builds its own resources — its chain clients, chains, the Alkahest stage's
resources, and the chain probe — and passes them, with its signer, authority
client, failure policy, worker identity, and event recorder; the library opens
the repository, assembles the runtime, the evidence service that trusts only
the storefront's own signer, the private-result repository, and the servicing
worker, and returns the composition. API credits alone passes a dispute policy
and the mediation interface. The stage-validation loop both storefronts repeat
moves with it.

The gain is not lines. It is that the order of assembly and the rule that
issuance evidence is trusted only from the storefront's own signer are stated
once, as the family's. The library gains no dependency: it already imports the
dispute policy type, and the probe and the mediation interface pass as data.

`services/fulfillment_service.py` stays in each storefront. It binds the
storefront's process-wide objects to functions the library already takes them
as arguments to, which is wiring, and wiring belongs in the composition root.
After this decision the two files have the same shape: a thin binding over a
parameterised library function.

Inference composes no dispute policy because it settles through Alkahest
alone and reads no dispute authority. That reason is stated in the inference
architecture companion, where the difference lives.

Rejected: a builder taking every collaborator separately, whose callers would
be as long as the bodies they replace. Rejected: moving the failure-context
function out of `fulfillment_service.py`; the API-credits tests replace names
in that module, and the function is small beside what moving it disturbs.

### D8 — Two test modules take their doubles through seams

`domains/inference/buyer/tests/test_scope_refusal.py` replaces eleven names
inside kit libraries, against `testing-python.md`'s rule that a test replaces
a factory on the module that defines it and nothing else.

- Its test of the delivered credential's rows is rewritten to call the
  settlement resume's `finish` with the inference contributions, a memory
  credential store, and a log double, as the buying library's own tests do. No
  production code changes.
- Its test that a scope refusal is reported once and not retried moves to the
  Alkahest buying library's tests, since the behaviour is that library's.
  `AlkahestBuyerStage` gains two optional keyword collaborators for the seller
  calls, resolved when called, as its wallet is, so the module-level
  replacements other tests still make keep working. The test passes a
  settlement resume whose log, buy configuration, and seller principals are
  doubles. The chain lookup is left as it is.

`kit/api/buying/tests/unit/test_credentials.py` patches the standard library
and a collaborator's class. `FileCredentialStore` gains optional `replace` and
`fsync` parameters, the patch of a method no code under test calls is deleted,
and the log failures use a log double or a real unwritable path.

The remaining replacements of library names across the family's and the
inference domain's tests stay with the roadmap's unowned gap on command-module
test seams, which already covers them; the move changes those files' paths and
nothing else in them.

Rejected: handing `test_credentials.py` to `keep-buyer-credentials-private`.
That change has no open task to carry it, and a small, understood defect is
fixed in the change that finds it.

### D9 — The family's test replays the inference-label pin

The inference-label issuance case leaves
`domains/apicredits/tests/test_issuance_pins.py`. The family's own pin test
replays it from the recorded fixture, as it replays the API-credits cases, and
its helper is extended to carry accepted terms, the terms digest, and the
request charge. The recorded bytes do not change. The API-credits file keeps
its own cases and a writer for those alone.

The code under test is the family vocabulary's, and a domain knows only itself
and its family.

### D10 — The roadmap's inference goal fixes no order

The paragraph of the roadmap's inference goal that fixes the campaign's order
and recounts a withdrawn approach is replaced by its closing pointer to the
change index, which already holds both. The `qualify-inference-market` row's
reference to the goal's completion test names the right goal.

### D11 — Nothing is owed to a release

The record of deployment read is the tag `marketplace-v0.4.0`. Neither it nor
any earlier tag carries a path under `kit/api`, `domains/api`, or
`domains/inference`, or an `arkhai-api-*` or `arkhai-inference-*`
distribution. The change owes no migration, compatibility path, or recovery
machinery. Migration identifiers are literal strings and the libraries' import
names are unchanged, so a database an API-credits deployment adopts from a
release is unaffected.

No version step is owed for the family's packages, which do not exist on the
branch this change lands on, nor a further one for the API-credits storefront
and buyer, which have each taken their step on this branch. This holds while
the change lands with the branch that introduces the family.

### D12 — What leaves this change is named where it lands

- `move-escrow-into-alkahest`'s proposal names the three modules of D2, the
  VM buyer's copies, and the question of a buyer-side Alkahest kit.
- `kit-owned-storefront-auth-and-persistence`'s design names the negotiation
  service's error as an import of the selling library its carve-out places.
- This change's row notes that the stage log's redesign is
  `redesign-storefront-stage-events`'s.
- `sign-multi-language-credits-middleware`'s row notes that the TypeScript and
  Rust gates send no key scope and ignore a pinned charge, though the family's
  companion says the three gates implement one protocol.
- The index's unowned work gains the payments adapter the VM and bare-metal
  buyers each construct in near-identical lines.
- The unowned row saying the API-credit lane has never run against the family
  kit is replaced by the run that did, recorded in `compose-api-family-kit`'s
  row.

### D13 — One change, on the branch that holds the family

The fixes of D4, D5, D7, D8, and D9 stay in this change. Each is understood and
small beside the move, and a change of its own would cost each a design,
reviews, validation, and a closeout.

The change is worked on the branch that carries the inference campaign's code,
by the owner's decision, although one change per branch is the workflow's
rule: the family it moves exists on that branch alone.

## Implementation cadence

Two rounds, one session each, each closed by an implementation review and a
validation of its own.

- **Round 1 — the move.** The tree, the rules file and `read_path`, the
  Makefile recipes and aggregates, the continuous-integration job, the release
  components manifest and the published-packages table, the tests outside the
  family that reach it by path, the lines inside it that name its own path,
  and every document and citation. Nothing else, so a failure in this round is
  the move's.
- **Round 2 — the fixes.** D4, D5, D7, D8, D9, D10, and the notes and rows of
  D12.

## Notes for planning

- An ignored `domains/api` directory of stale environments and caches is in
  the working tree. It is removed before the move, or `git mv` nests the
  family beneath it.
- Six files build the family's path from separate words and are found by no
  search for `kit/api`: the wheel-source lists in the API-credits and
  inference test support, the API-credits service's baseline test, both
  API-credits pin tests, and the family's distribution test.
- `kit/Makefile` reaches the family by relative `cd api/...` lines, and the
  continuous-integration conditions name the test target, not the path.
- The moved recipes use a wheelhouse variable `domains/Makefile` does not
  define.
- The environments that travel with the move carry absolute paths and are
  reinstalled; a dependent keeps a stale wheel of an unchanged version until
  the wheelhouse is rebuilt and its environment reinstalled.
- The TypeScript gate's package metadata names its repository directory.
- `compose-api-family-kit` reaches `archived` before implementation starts,
  and this change's dependency on it is then dropped from its row.

## Open Questions

None.
