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
needs no contact. Decision 5 says what happens to a contact option there. An entry
that is present must carry a non-empty `contact_payload`: an empty entry is
refused as configuration rather than read as absence, so readiness never has to
interpret one.

Once a storefront has more than one origin, nothing applies to every origin
implicitly. Here that refuses the single form; decision 7 applies the same rule to
seller-side delivery.

**Readiness.** The mechanism's readiness stays storefront-wide and no longer means
"every origin has a contact":

- no profiles configured → unready, `no_contact_profiles`, as today;
- neither the single form nor any `origins` entry configured → unready,
  `no_contact_payload`, as today;
- otherwise ready. A configured origin without an entry does not affect readiness;
  publication and the reveal enforce availability for that origin.

The public readiness projection carries nothing per origin: origins can be internal
identifiers, and a buyer learns an origin's availability from whether its listing
advertises the option.

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

**The origin is the binding's origin, from publication through reveal.** The
origin a storefront passes to the option builder MUST be the site recorded on that
listing's durable binding — the value the negotiation inherits and the reveal and
delivery routing later resolve. A composing storefront must not supply an origin
derived any other way, or a contact option could be advertised under one origin and
revealed under another. The kit cannot check this, since it treats origins as
opaque; it is the storefront's obligation, pinned by an integration case that
publishes, accepts, and reveals and asserts one origin throughout. VM's listing
creation currently builds its settlement artifacts before it reads the capacity
source's site, so meeting this means reordering it to take the origin from the
value the binding is prepared from.

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
- With no routing table and one known origin, every enabled instance receives
  every reveal: today's behaviour, and right for one seller.
- With no routing table and more than one known origin, sink-set construction is
  refused at startup, naming the configured origins. Broadcasting every reveal to
  every sink is exactly the cross-seller disclosure this decision exists to
  prevent, so a multi-origin storefront routes deliberately — a destination shared
  by every seller, such as an audit file, is still expressible by listing it for
  each origin. This applies the rule decision 4 states for the contact: once there
  is more than one origin, nothing applies to every origin implicitly.
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

The multi-origin refusal is unconditional: it applies whenever seller-side sinks are
enabled and more than one origin is known, whether or not contact exchange is
enabled. `kit/delivery` deliberately knows no mechanism, and today introductions
are its only events, so tying the refusal to the mechanism would mean passing
mechanism state into the delivery kit for no present benefit. A second delivery
event producer — unowned, per `docs/development/ROADMAP.md`'s Goal 6 — should
revisit whether its events are origin-scoped and whether the refusal should then
follow the event rather than the sink set.

Option (b) — leave delivery storefront-wide and record routing as unowned — was
rejected: the first multi-seller deployment would need it, and it would rework the
same configuration grammar this change already extends.

### 8. VM buyers complete an introduction from the CLI (placement superseded by decision 13)

The bare-metal buyer has `request-introduction`, `introduce`, and
`introduction [--deliver]`. The last two are domain-neutral given a recovered run:
they use `core_buyer`'s `IntroductionTransport`, the buyer delivery code, and the
core run log. Their bodies move into `core_buyer` as a command group each domain
buyer mounts, supplying its run-recovery hook (domain buyer configuration and
registry trust refresh) and the mechanism identity. The mechanism identity is
injected rather than named in `core_buyer`, because a core role package must not
depend on a mechanism kit or branch on a concrete mechanism identifier.

Placing mechanism-shaped commands in a core role package sits against
`docs/development/ARCHITECTURE.md`'s rule that what stays in core is universal to
every market. It follows existing precedent rather than setting one: `core_buyer`
already owns the schema-opaque `IntroductionTransport` and buyer-side introduction
delivery, and `openspec/specs/market-composition/spec.md` already has the core buyer
delivering a revealed introduction without depending on a mechanism kit. Injecting
the mechanism identity is what keeps that precedent within the rule's intent.

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

### 13. Decisions settled during planning review

**Deployable by Helm, on the pass-through baseline.** VM contact exchange must deploy
through the umbrella chart in this change. `pass-through-storefront-config` made the
VM storefront chart pass each agent's configuration through as `storefront.json`, and
generated the values schema's `storefrontServiceConfig` definition from the
storefront's typed models (`market_storefront/values_schema.py`,
`make helm-values-schema`). That schema closes `Settlement` to the mechanisms the
storefront registers and refuses every field marked `"secret": true`. So
`[Settlement.contact]` reaches the storefront once VM registers the mechanism and the
schema is regenerated, with no template edit.

`[Delivery]` is an untyped section in that schema today, so it passes through open —
including the webhook sink's secret-marked `url` and `headers` and the SMTP sink's
`password`, which would then render into the ConfigMap. This change therefore types
the section in the generator: `enabled`, `timeout_seconds`, and `origins` at the root;
each instance table typed by the sink it instantiates — its `sink` value, or its own
name when it states none — using that sink's settings model, so the secret-marked
fields are refused like any other; and a table naming a sink the generator does not
know left open, as the pass-through design already accepts for externally installed
plugins.

The generator learns which sinks it knows by discovery, never by import. A sink plugin
may declare its settings model beside its factory, and the delivery kit's discovery
collects the declared models of every installed sink; the generator types the
instances of those sinks and leaves the rest open. A storefront that imported a sink's
settings by name would make an optional plugin a hard code dependency and would need
an edit for each future sink, which is the enumeration the delivery spec forbids. The
schema is generated in the storefront's locked environment and committed, so
discovery at generation time sees exactly the sinks its image installs, and the drift
test catches an environment that differs. A plugin declaring no settings model keeps
working as an open instance. Both storefronts keep `arkhai-kit-delivery-apprise` as a
plain dependency: that is what ships it in their images, and it is a packaging choice
that no code names. An optional extra was considered and not taken, since the images
install from their locks and would need build changes to opt in.

An instance whose name is
a known sink's name and whose `sink` names a different one is refused, by the
delivery kit at startup and by the schema at render, so a table's name never
misleads about what it delivers through.

**Contact details are ordinary configuration.** A seller's onboarding contact is not
the class of secret the Secret overlay carries, and placing it there would force
secret management on every operator. `contact_payload` and per-origin contacts are
public-layer configuration. The `"secret": true` marker they carry today now does
three jobs: the generated values schema refuses the field, `kit/config`'s layered
resolution forbids it from a public layer, and the settlement runtime's readiness
leak check refuses it in public output. The contact fields take a new marker,
`"never_published": true`, in place of `"secret"`: the values schema and layered
resolution accept it, and the settlement runtime's leak check treats it exactly as a
secret, so the value may come from any configuration layer and still never appears in
a listing, option, readiness projection, or obligation. Sink credentials keep
`"secret": true` and arrive through the Secret overlay.

**Seller delivery reaches the seller's own systems.** The built-in `webhook` sink
already POSTs the delivery event to any REST endpoint; with origin routing, each
origin's reveals go to that seller's own API. It gains optional request signing with
the storefront's marketplace signer (`sign = true`), so the receiving API can verify
the sender against the storefront principal it already pins. The signer reaches the
sink through the sink-set builder rather than its settings, since signing material
never travels through configuration. For the wider range of
integrations, an installable `apprise` sink plugin, `kit/delivery-apprise`, wraps the
Apprise library, which reaches over a hundred services from one URL each, rather than
this repository writing them; both storefront images install it. Its `urls` are
marked secret, since Apprise URLs routinely embed service tokens. Alertmanager was
considered and rejected as the carrier: buyer contact details would rest in its alert
state and interface. A site-owned path, where the storefront hands the contact to the
site authority and the site runs its own sinks, is a larger cross-service contract
left for later.

**Buyer introduction commands are mechanism-owned.** Contact exchange is a settlement
mechanism, not a listing type (decision 9), and mechanism kits already own buyer
command groups: `kit/hosted-settlement` provides `market settlement stripe …` through
its registration's `command_group`, with a context factory the domain buyer supplies.
`kit/contact-exchange` gains the same: `market settlement contact introduce` and
`… introduction [--deliver]`, with the transport, run recovery, and buyer sinks
injected through the context. The kit gains `typer`; its deny list is unchanged and it
imports neither `core_buyer` nor `kit/delivery`. `request-introduction` stays a domain
command because it opens a negotiation in the domain's terms. This supersedes decision
8's placement in `core_buyer`; `core_buyer`'s existing `IntroductionTransport` stays
where it is.

**More of the composition is kit-owned.** `kit/contact-exchange` gains a SQLite
introduction store over its own table, so neither storefront keeps persistence
wrappers, and a composition object that builds the retention service, the
disclosures, and the reveal service from the running configuration. A domain supplies
its injected reads, configuration carrier, route bindings, and loop registration.

**No clause, no contact option.** The contact option builder publishes no option when
no publication clause selects it, rather than raising, so a VM listing published
without explicit clauses is unaffected by contact exchange being enabled.

**Disclosures on core health.** VM's health route returns core `HealthResponse`, which
gains `disclosures`. That bumps `arkhai-core-storefront`, and the exact-pin cascade
through `arkhai-kit-capacity-publication` to the VM, bare-metal, and API-credit
storefronts is taken rather than a VM-local response model.

**System evidence.** Mailpit, an off-the-shelf SMTP server with a query API, joins the
VM lane and, optionally, the Helm `dev-env` subchart. The VM introduction scenario
routes its origin to a built-in SMTP sink instance pointed at Mailpit and reads the
message back, proving seller-side delivery without a bespoke receiver. The SMTP sink's
host, port, sender, and recipients are public settings, so the lane and a Helm
deployment configure it without a Secret; Apprise URLs are secret-marked and would
not be. The Apprise plugin is proven at integration level against a loopback
receiver. The two-seller
scenario (6.5) is transferred to `unbacked-bare-metal-listings` for both domains: it
needs one storefront serving two seller sites, which no lane provides, and the
behaviour it covers is proven here at integration level.

### 14. An unpriced selection is accepted as published

Composing VM exposed that it could not accept an introduction at all. VM's seller
policy chain ends in a scalar bargaining policy, `bisection`, which counters with
the seller's opening whenever the buyer's proposal carries no amount. An option that
bargains no amount — an introduction — never carries one, so every opening was
countered forever, contrary to the existing negotiation-protocol requirement that a
non-scalar mechanism can reach acceptance on the published option's terms. Earlier
VM evidence missed it because it seeded already-accepted deals.

The policy kit gains `accept_unpriced_selection`: it accepts an exact selection of an
advertised option that `option_uses_scalar_amount` says bargains no amount, and
passes every other proposal through. VM's default guards run it last, so it fires
only after the opening, buyer-counter, inventory, and escrow-shape guards pass, and
before any bargaining policy. It lives in the policy kit rather than VM because
"nothing to bargain means accept the published terms" is the mechanism-neutral
reading of the scalar declaration, and any storefront composing a scalar terminal
policy needs it.

Rejected: a prerequisite change. Fixed here, since the VM half of this change does
not work without it. Rejected: making `bisection` accept an amountless proposal; a
terminal bargaining policy should not decide what a guard can decide from the option
declaration, and other terminal policies would need the same change.

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
5. Give the mechanism kit the buyer introduction commands; bare metal mounts them in
   place of its own; VM gains them with its own `request-introduction`.

Purely additive for existing deals and configuration: accepted plans, obligation
records, and revealed introductions are untouched, the reveal surface's wire shape
does not change, and every existing `[Settlement.contact]` and `[Delivery]` section
remains valid.
