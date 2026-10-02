# Design — compose contact exchange across the compute family

## Context

Settlement by introduction already exists and works: rateless options, a
scalar-declining registration, one non-financial obligation, a durable
authenticated reveal, a loose-listing discovery profile, and bounded retention,
composed end to end on bare metal. The mechanism kit is domain-neutral by
assertion — a package-boundary test pins its permitted imports and explicitly
excludes web frameworks, HTTP clients, the Alkahest carriers, and Stripe.

The obstacle to a second domain is not the mechanism. It is that the glue binding
the mechanism to a domain's accepted state, and the glue sending a reveal to the
seller's sinks, both live in one domain and are mostly not about that domain. A
second obstacle is that the seller's contact is one storefront-wide value, which
stops being correct the moment one storefront publishes for several sellers.

The long-term direction for the compute storefronts is one storefront serving VM
and bare metal, the way one provisioning service already serves both. A domain
then consists of composition, configuration, domain-specific vocabulary such as
listing shapes, and API definitions. Every decision below is weighed against that
direction: logic either lands in a kit or core package, or it is a configuration
carrier, a route binding, or a registration line.

## Goals / Non-Goals

**Goals.** One implementation of accepted-state interpretation. A second composing
domain (VM), with API credits recorded as out of scope. A seller's contact resolved
per listing origin. Delivery available wherever the mechanism composes, routed per
origin. VM buyers able to complete an introduction from the CLI.

**Non-Goals.** No change to the mechanism's registration identity, option shape,
reveal wire shape, or retention semantics. No persistence, framework, delivery, or
foreign-mechanism dependency in the mechanism kit. No coupling to whether a listing
is capacity-backed. No per-deal contact aliasing.

## Decisions

### 1. Promote the glue rather than copy it

The bare-metal glue reads a negotiation thread, requires its terminal state to be
success, validates a settlement plan carrying exactly one obligation, checks the
obligation's mechanism, re-derives `obligation_ref` from the agreement and the
canonical obligation content and compares it against the requested one, then
drives register, materialize, bind, check, and collect.

Every one of those steps is a statement about the mechanism's own invariants, not
about bare metal. The `obligation_ref` re-derivation in particular is a security
check — it is what stops a caller from requesting a reveal against an obligation
that is not the one the plan accepted — and a security check with several
implementations is a security check with several behaviours.

Copying it into each domain was the alternative and is rejected on the
established rule that an extracted concern leaves no domain-local copy, and that
domains retain only the values and hooks that instantiate a kit mechanism.

`load_revealed_introduction`, the read an operator's re-delivery takes, moves with
the glue: it applies the same accepted-state interpretation and is the only path
by which re-delivery obtains material to send.

### 2. Persistence stays injected, as three reads

The promoted bodies take three domain reads as declared Protocols, the pattern the
reveal service already uses for prepare, authorize, persist, load, and complete:

- the negotiation-thread read keyed by negotiation id, returning a mapping carrying
  the terminal state and the settlement plan (`load_negotiation_thread_row`);
- the settlement-obligation read for the reference-only path, where a read request
  names only an `obligation_ref`;
- the agreement's origin, keyed by negotiation id.

The third read is new. The origin is the `site_id` recorded on the negotiation
thread's immutable binding, which the thread inherits from its listing binding when
it opens. It is read through `load_thread_binding`, not the thread row:
`load_negotiation_thread_row` does not select the binding columns. Both compute
storefronts' SQLite clients inherit `load_thread_binding` from the core client, so
neither needs a new query.

### 3. The promoted bodies live in the mechanism kit

**The kit already holds persistence.** `market_contact_exchange` imports `sqlite3`,
owns the `contact_introductions` DDL and its migration, and ships the row functions
operating on an injected connection. Its boundary test permits `sqlite3`
explicitly. What the test forbids is the list it asserts against — `fastapi`,
`httpx`, `market_alkahest`, `requests`, `stripe`, `hosted_settlement_client` —
which is frameworks, HTTP clients, and other mechanisms, not storage.

**The promoted bodies need no persistence types anyway.** Everything beyond the
three injected reads is `market_core.schemas`, `market_identity`, and
`market_settlement_runtime`, all already kit dependencies. The kit is not asked to
learn a foreign vocabulary: it already accepts a `negotiation_id` on the start route
and already calls `derive_obligation_ref` against it.

**`kit/storefront` was rejected on a dependency ground.** Its `pyproject.toml`
declares `arkhai-kit-alkahest` and `alkahest-py` as hard runtime dependencies, so
landing the glue there would make settlement by introduction depend on a different
mechanism's SDK.

One boundary amendment: `uuid` joins the kit's permitted import roots, for
worker-id generation in the drive sequence, as an explicit reviewable line. The deny
list stays exactly as it is.

### 4. One contact per origin, keyed opaquely

`ContactSettlementConfig.contact_payload` is a single value. That is coherent at one
seller per storefront and stops being coherent the moment one storefront publishes
for several seller sites — the shape Goal 7's multi-seller coverage exercises. A
storefront-wide payload there reveals one seller's contact details for another
seller's listing: a disclosure of the wrong party's personal information, not a
missing feature.

**The kit treats an origin as an opaque, bounded string.** It never parses one and
never learns what a site is. The domain supplies two things: the origin of an
agreement (decision 2) and, at composition, the set of origins it knows — today the
keys of its configured sites. If origins later mean something other than sites, the
kit and the configuration format stay the same. Each origin is a table rather than a
bare payload, so a per-origin setting can be added later without a format change.
Profiles and retention stay storefront-wide: profiles are public terms, and
retention is the storefront's own data policy.

A single-site storefront is unchanged (VM TOML):

```toml
[Settlement.contact]
enabled = true
contact_payload = { email = "sales@bob.example" }

[Settlement.contact.profiles.direct]
channel = "email"
terms = "Quoted per engagement; reply within one business day."
```

One storefront, two sellers:

```toml
[Settlement.contact]
enabled = true

[Settlement.contact.origins.dc-west]
contact_payload = { email = "ops@west-seller.example", signal = "+1-555-0100" }

[Settlement.contact.origins.dc-east]
contact_payload = { email = "sales@east-seller.example" }
```

Bare metal uses the identical shape inside its `BARE_METAL_STOREFRONT_SETTLEMENT`
JSON:

```json
{"contact": {"enabled": true,
  "origins": {"rack-a": {"contact_payload": {"email": "a@seller.example"}}}}}
```

One seller operating two sites writes an entry for each site, even though the
payloads are the same. That is the deliberate cost of never falling back to another
origin's contact.

The storefront refuses to start, naming the offending key or site, when:

- `contact_payload` and `origins` are both set;
- `contact_payload` is set while two or more origins are configured;
- an `origins` key names no configured origin.

A configured origin with no entry is legal: a site selling only through Alkahest
needs no contact. Decision 5 says what happens to a contact option there.

The storefront-wide form is kept as shorthand for one origin rather than retired,
so every existing single-seller deployment is unchanged. It is not a fallback: it is
refused outright once a second origin exists, rather than applying to every origin.

**Rejected: the payload on each site binding.** VM configures sites as a
`[capacity.sites]` name-to-URL table and bare metal through
`BARE_METAL_STOREFRONT_SITES` JSON. Carrying a contact there means two parsers, two
validations, and a PII value travelling in configuration that is otherwise public
routing metadata — against decision 7's direction.

**Rejected: a release contract restricting introductions to one seller per
storefront.** It would make Goal 7's stated value untrue for the multi-seller case
the goal exists to serve, and the restriction would still have to be enforced.

### 5. A missing contact is guarded at publication and at reveal

Resolution happens at introduction start — the existing rule that acceptance stays
payload-free and only a started introduction persists contact data. Three moments
could check that an origin has a contact:

| Case | Publication | Acceptance | Reveal |
|---|---|---|---|
| A. An origin's pools offer a contact option but the origin has no entry | Option never advertised | Buyer negotiates, refused at acceptance | Buyer negotiates and accepts, refused at reveal |
| B. An entry is removed while listings are already published | Fixed at the next publication pass | Caught | Caught |
| C. An entry is removed between acceptance and reveal | — | — | Only this catches it |

**The reveal check is the safety guarantee and is not optional.** It is where the
payload is resolved, so it alone ensures no wrong-origin contact is ever revealed:
an origin with nothing configured refuses the start before anything is persisted,
the obligation is not driven, and nothing is delivered.

**The publication check is kept** because case A is the standing misconfiguration:
without it the catalogue advertises introductions that always fail, and nothing
tells the operator until a buyer finds out. The kit's option builder receives the
listing's origin among its publication inputs. Where the origin has no resolvable
contact it builds no option, logged like a suppressed unready mechanism; where the
origin-keyed form is configured and no origin was supplied, it refuses rather than
guessing, so a composition that forgot to pass one fails closed.

**No acceptance check.** Cases B and C are rare operator actions, no funds are at
stake in an introduction, and an accepted deal refused at reveal registers nothing
for servicing. An acceptance check would also need origin threaded through
bare-metal acceptance, which `bare-metal-mock-provisioned-deal` is moving onto the
kit negotiation runtime in parallel. Revisit if an introduction ever carries value
at acceptance, at which point a dead accepted deal would cost the buyer something.

### 6. The reveal service resolves the seller's contact per agreement

`IntroductionRouteService` takes `seller_contact` once at construction. It takes a
resolver over the running configuration instead, called with the agreement's origin
(`IntroductionAgreement` gains `origin`). The wire shape of the reveal is unchanged.
A start whose origin resolves no contact answers HTTP 503 with a stable code,
`seller_contact_unavailable`, before persisting: the storefront cannot serve the
reveal under its current configuration, and an operator restoring the entry makes
the same start succeed. This replaces bare metal's storefront-wide 503 check, which
moves to the per-origin path.

### 7. Delivery follows composition, routed per origin, in the delivery kit

A reveal that only sits behind an authenticated read is a worse product than one
that reaches its owner. Delivery remains non-authoritative in every domain that
gains it: best-effort delivery is safe because the durable reveal is what the
parties fall back to, and re-delivery reads that reveal rather than reconstructing
one.

**The seller-side dispatch has one implementation, in `kit/delivery`.** Bare metal's
`delivery.py` holds background dispatch, retention of in-flight tasks until they
finish, outcome logging, sink-set construction with warnings, and re-delivery.
Copying it into VM would be a second domain-local delivery implementation. It moves
into `kit/delivery`, which reads the agreement by shape (`agreement_ref`,
`buyer_principal`, `origin`) exactly as its event constructor already reads a reveal
projection by shape, so neither kit imports the other. Each domain keeps only its
configuration carrier (environment JSON for bare metal, TOML for VM), its route
bindings, and its operator command binding.

**Routing per origin needs named sink instances.** Today each sink plugin can be
enabled once, so a storefront has one webhook URL for every reveal. With two sellers
behind one storefront, pointing that webhook at one seller's system sends the other
seller's buyers' contacts there too — the disclosure the origin rule exists to
prevent, moved from the reveal to delivery. `kit/delivery` gains named instances and
an origin routing table:

```toml
[Delivery]
enabled = ["west-hook", "east-hook", "audit"]

[Delivery.west-hook]
sink = "webhook"
url = "https://west.example/hook"

[Delivery.east-hook]
sink = "webhook"
url = "https://east.example/hook"

[Delivery.audit]
sink = "file"
path = "/var/log/introductions.jsonl"

[Delivery.origins]
dc-west = ["west-hook", "audit"]
dc-east = ["east-hook", "audit"]
```

- A table with no `sink` key is the plugin of the same name, so every existing
  configuration keeps working unchanged. `origins` joins `enabled` and
  `timeout_seconds` as a reserved section key.
- With no routing table, every enabled instance receives every reveal: today's
  behaviour, and right for one seller.
- With a routing table, an origin it does not list receives no seller-side delivery;
  every routed name must be enabled; every enabled instance must be routed for at
  least one origin; and every origin key must name a known origin, checked at
  composition like contact origins. Each is a startup refusal naming the offending
  entry, following the existing rule that settings for a sink nobody enabled are
  refused.
- Instances work identically on the buyer side, so the section shape stays the same
  on both sides. A routing table is refused on the buyer side: the buyer has no
  origin.
- Operator re-delivery routes by the introduction's origin, through the same table.

Option (b) — leave delivery storefront-wide and record routing as unowned — was
rejected: the first multi-seller deployment would need it, and it would rework the
same configuration grammar this change already extends.

### 8. VM buyers complete an introduction from the CLI; the bodies are core-owned

The bare-metal buyer has `request-introduction`, `introduce`, and
`introduction [--deliver]`. The last two are domain-neutral given a recovered run:
they use `core_buyer`'s `IntroductionTransport`, the buyer delivery code, and the
core run log. Their bodies move into `core_buyer` as a command group each domain
buyer mounts, supplying its run-recovery hook (domain buyer configuration and
registry trust refresh) and the mechanism identity. The mechanism identity is
injected rather than named in `core_buyer`, because a core role package must not
depend on a mechanism kit or branch on a concrete mechanism identifier.

`request-introduction` opens a negotiation, which is domain-specific: provision
terms and the domain's opening. VM gets its own thin command over the VM opening and
the shared selection and run-log fields; bare metal keeps its own.

### 9. Composition is independent of backing

A capacity-backed listing may settle by introduction, and an unbacked listing may
settle by another mechanism. A domain that can publish unbacked listings declares,
per mechanism it composes, whether settling through it delivers through the
domain's capacity-backed fulfillment, and an unbacked listing publishes only options
its domain does not fulfil that way. When VM composes contact exchange it declares
it as not fulfilling through capacity. No pool-level or listing-level field names a
settlement mechanism.

### 10. Retention first

This change was gated on `contact-payload-retention`, now archived. That change
placed retention in the mechanism kit — redaction leaving a tombstone,
`retention_seconds`, the sweep and its loop runner, a framework-free admin service,
and the disclosure object — and requires every composing storefront to run it. VM
inherits the kit parts and the configuration; this change owns VM's wiring: the
sweep registered with VM's loop controller, the admin service bound behind VM's
administrator authentication, and the disclosure embedded in VM's readiness.

### 11. The compute family is VM and bare metal, so this change composes VM

Only VM and bare metal register a `market.storefront_contributions` entry point.
API credits ships its own registry filter specification under schema identity
`api_credits` and is a different market family, so it is out of scope for that
reason rather than by omission. Bare metal already composes the mechanism, so the
remaining compute-family domain is VM.

### 12. System evidence is new scenario modules

The end-to-end harness is being refactored in parallel. This change adds new scenario
modules only and edits no shared helper or fixture. Lane configuration may change
where a scenario needs topology the lanes lack — two seller sites behind one VM
storefront for the multi-seller scenario — and each such edit is named in its task.

## Risks / Trade-offs

- **[Promotion changes behaviour subtly]** → The glue's checks are security checks.
  Mitigated by promoting the bodies unchanged first and composing VM only after the
  bare-metal coverage passes against the promoted implementation.
- **[Parallel bare-metal work]** → `bare-metal-mock-provisioned-deal` is editing the
  bare-metal storefront's negotiation and deal-control wiring. This change touches
  that storefront's introduction composition, delivery, and route wiring. Mitigated
  by keeping bare-metal edits to deletions and rewiring onto kit calls, and by
  threading no origin through bare-metal acceptance (decision 5).
- **[The combined compute shell]** → The VM storefront process can host the
  `bare_metal` contribution beside `vms`. Registering contact exchange in VM's
  settlement composition makes it available to that process; planning confirms what
  the bare-metal contribution's fulfillment declaration says there before VM
  registers the mechanism.
- **[Delivery grammar extension]** → A reserved `origins` key could collide with a
  third-party sink plugin named `origins`. Accepted: such a plugin is still reachable
  as an instance under another name with `sink = "origins"`.
- **[Delivery multiplies configured sinks]** → Each sink is a place a contact comes to
  rest outside the storefront's retention control. This is why the retention
  disclosure is scoped to the introduction record.
- **[The promoted home is wrong]** → Mitigated by keeping the boundary test's deny list
  unchanged, so a later framework, HTTP client, or foreign-mechanism dependency still
  fails loudly.

## Open questions

None. Every question raised in design review is recorded above as a decision.

## Migration Plan

1. Promote the glue with persistence injected; bare metal composes the promoted
   implementation and its existing coverage passes unchanged.
2. Make the contact origin-keyed and the reveal resolve per agreement; bare metal's
   single-site configuration resolves exactly as before.
3. Extend `kit/delivery` with instances, routing, and the seller dispatcher; move bare
   metal onto it.
4. Compose VM: mechanism, persistence, migrations, retention, routes, delivery.
5. Promote the buyer introduction commands into `core_buyer`; bare metal mounts them;
   VM gains them.

Purely additive for existing deals and configuration: accepted plans, obligation
records, and revealed introductions are untouched, the reveal surface's wire shape
does not change, and every existing `[Settlement.contact]` and `[Delivery]` section
remains valid.
