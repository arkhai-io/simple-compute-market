# contact-exchange.v1 coverage inventory

Facts only, cited to the file or spec heading that owns them. Nothing here decides anything.

Snapshot taken at `a1c46d20`.

Where the implementation and `openspec/specs` disagree, both are stated; the implementation is
authoritative.

## 1. Which composition roots register the mechanism

`contact-exchange.v1` is registered in exactly one composition root:
`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py:41`,
inside `build_bare_metal_settlement_registry`, alongside `create_alkahest_registration()` and
`create_stripe_registration()`.

No other domain registers it:

- `domains/vms/storefront/src/market_storefront/settlement_composition.py:267-268` registers
  Alkahest and Stripe only. The same pair is registered again in
  `domains/vms/storefront/src/market_storefront/groups/settlement.py:176-177` and twice in
  `domains/vms/storefront/src/market_storefront/groups/config.py:57` and `:79`.
- `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py:65-69`
  registers Alkahest and Stripe only — its docstring reads "Install peer Alkahest and hosted
  mechanism registrations".
- A repo-wide grep for `contact_exchange`/`contact-exchange` under `domains/vms` and
  `domains/apicredits` returns nothing. (`domains/apicredits/storefront/tests/unit/test_selection_dispatch.py:44`
  and `domains/bare_metal/storefront/tests/test_selection_dispatch.py:35` define a synthetic
  `demo.intro.v1` to exercise non-scalar dispatch; that is not this mechanism.)

So the ticket's first-pass suspicion holds: **the mechanism is wired into `bare_metal` only, and
the webapp's two launch registries (`vms.compute`, `api_credits`) have no contact-exchange
support at all.** The repo says so itself: `docs/development/ROADMAP.md:236` lists "Cross-domain
contact-exchange composition beyond bare metal; contact-payload retention automation" as
**Unowned — needs a new change**, and `docs/development/ROADMAP.md:237` lists "Delivery beyond
bare metal" the same way.

Note also that **no buyer composition root registers the mechanism at all**, in any domain. The
bare-metal buyer imports only the mechanism-ID constant
(`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:36`) and hardcodes the comparison
(`cli.py:656`). Consequently `contact_buyer_compatibility` and the `contact.channel` clause field
(`settlement_config.py:269-283`, `:403-414`) are declared but unreachable in production:
`registry.buyer_compatible` is called only from `domains/vms/buyer/settlement_composition.py:211`,
`:243`, `domains/apicredits/buyer/settlement_composition.py:209`, `:241`, and
`kit/settlement-runtime/src/market_settlement_runtime/clauses.py:211`, and none of those roots
installs the contact registration.

The *mechanism-neutral* half, however, is already in core and kit, not in `bare_metal`:

| Piece | Location | Domain-neutral? |
| --- | --- | --- |
| Mechanism registration, config schema, option builder, obligation builder | `kit/contact-exchange/src/market_contact_exchange/settlement_config.py:385-417` | yes |
| Reveal route mechanics (framework-free) | `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py:168-331` | yes |
| Persistence DDL + row helpers | `kit/contact-exchange/src/market_contact_exchange/migrations.py:17-98` | yes |
| Settlement client (all no-ops) | `kit/contact-exchange/src/market_contact_exchange/client.py:16-95` | yes |
| Delivery sink contract, dispatch, built-in sinks | `kit/delivery/src/market_delivery/` | yes |
| Buyer HTTP transport for start/read | `core/buyer/src/core_buyer/introductions.py:17-68` | yes, in **core** |
| Buyer-side sink delivery | `core/buyer/src/core_buyer/delivery.py:34-87` | yes, in **core** |
| Registry filter profile for introduction markets | `core/registry/filter-spec.introductions.yaml` | yes, in **core** |

`kit/contact-exchange` is provably domain-free: its import allowlist is
`{__future__, collections, dataclasses, json, market_contact_exchange, market_core,
market_identity, market_settlement_runtime, pydantic, re, sqlite3, typing}` and it is asserted
to import no web framework, no HTTP client, and no other mechanism
(`kit/contact-exchange/tests/unit/test_package_boundary.py:6-42`). Its declared dependencies are
`arkhai-core`, `arkhai-kit-identity`, `arkhai-kit-settlement-runtime`, `pydantic`
(`kit/contact-exchange/pyproject.toml:7-12`).

### What registering it costs a domain

Essential — imposed by `kit/contact-exchange` itself:

1. **The registration call.** One line in the settlement registry
   (`settlement_composition.py:41`). This alone buys config validation, preflight, the option
   builder, buyer compatibility, the accepted-obligation builder, and the `contact.channel`
   clause field (`settlement_config.py:390-416`).
2. **Config subsection.** `config_key = "contact"` → `[Settlement.contact]`, model
   `ContactSettlementConfig` with `enabled`, `contact_payload`, `profiles`
   (`settlement_config.py:28`, `:96-132`). The seller must supply at least one profile and a
   non-empty contact payload or preflight reports `no_contact_profiles` /
   `no_contact_payload` and the mechanism is not ready (`settlement_config.py:154-187`).
   Without the registration, the section is rejected outright: an unknown `[Settlement]` key
   (`kit/settlement-runtime/src/market_settlement_runtime/configuration.py:486-491`) or an
   "uninstalled settlement configuration section" (`configuration.py:560-564`).
3. **Two mechanism resources at publication.** `contact_option_builder` reads
   `resources["publication_clause"]` (`settlement_config.py:221-223`) and
   `resources["claimant_principal"]`, raising "contact-exchange option requires a claimant
   principal" without the latter (`settlement_config.py:240`, `:199-204`). `bare_metal` supplies
   the principal at `runtime.py:340` and `:373`. Neither `vms`
   (`domains/vms/storefront/src/market_storefront/settlement_composition.py:1297-1302`) nor
   `apicredits`
   (`domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py:743-749`)
   passes it today.
4. **Three required acceptance-context keys.** `buyer_principal`, `seller_principal`, and a
   positive `expiration_unix` (`settlement_config.py:302-306`). `domain_param_keys`,
   `listing_id` and `negotiated_context` are optional (`:313`, `:325-330`). Worth recording:
   **`negotiated_context` is supplied by no domain** — the only occurrences are the kit and a
   kit test (`kit/contact-exchange/tests/unit/test_accepted_obligation.py:86`, `:102`). The
   "agreed context" that actually travels is therefore option id, profile, channel, terms and
   listing id.
5. **One migration, wired into the domain's migration list.** `CONTACT_EXCHANGE_MIGRATIONS`,
   migration id `20260815_006_contact_introductions`, creating table `contact_introductions`
   (`migrations.py:17-40`), spliced in at
   `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py:80-85`.
6. **Five domain callbacks** implementing `IntroductionRouteCallbacks`
   (`introduction_routes.py:124-132`): `prepare`, `authorize`, `persist`, `load`, `complete`,
   with the Protocol signatures at `introduction_routes.py:71-104`. `bare_metal`'s
   implementations are `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/introduction_routes.py:81-161`.
   A sixth hook, `DeliverIntroduction`, is optional and defaults to `None`
   (`introduction_routes.py:107-121`, `:182`). The service constructor additionally refuses an
   empty `seller_contact` (`introduction_routes.py:185-187`).
7. **Two HTTP routes mounted on the domain's own router**: `POST /api/v1/introductions` and
   `GET /api/v1/introductions/{obligation_ref}`
   (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/api.py:253-272`). The kit
   supplies the mechanics but mounts nothing — it is framework-free by construction
   (`introduction_routes.py:135-141` defines an HTTP-shaped error rather than raising
   `HTTPException`). The paths and the signed operation names `introduction_start` /
   `introduction_read` are not free choices: the shared buyer transport hardcodes them
   (`core/buyer/src/core_buyer/introductions.py:41`, `:50`, `:59`, `:64`).
8. **A publication clause path** carrying `mechanism=contact-exchange.v1`,
   `asset=introduction`, no `rate`, and `mechanism_input={"profile": ...}`
   (`settlement_config.py:220-235`; clause model at
   `kit/settlement-runtime/src/market_settlement_runtime/publication.py:47-107`).
9. **A buyer-side path that can negotiate a rateless option.** The registration declares
   `negotiates_scalar_amount=False` (`settlement_config.py:395`), and the option builder and
   obligation builder both refuse a rate (`settlement_config.py:230-231`, `:300-301`); the
   runtime enforces the symmetry in both directions (`configuration.py:731-733`, `:774-782`).

Incidental — how `bare_metal` happened to do it, not required by the mechanism:

- **SQLite specifically.** The kit ships raw `sqlite3` DDL and row helpers
  (`migrations.py:20-98`), and `bare_metal` wraps them
  (`sqlite_client.py:88-113`). A domain on other storage would have to supply its own `persist`
  and `load`; nothing in the kit's callback Protocols requires SQLite
  (`introduction_routes.py:90-100`).
- **Driving the obligation to `collected` by hand.** `bare_metal`'s `complete` callback runs
  `register_plan → materialize → bind_fulfillment → check → collect` inline
  (`domains/bare_metal/.../introduction_routes.py:117-149`). That sequencing is a domain choice;
  the kit only calls `complete(agreement)`.
- **Deriving the agreement from a negotiation thread row.** `_accepted_introduction` reads
  `load_negotiation_thread_row`, requires `terminal_state == "success"`, and re-derives the
  obligation ref (`domains/bare_metal/.../introduction_routes.py:30-61`).
- **Environment-carried delivery config.** `BARE_METAL_STOREFRONT_DELIVERY` holds the delivery
  section as a JSON object (`domains/bare_metal/.../delivery.py:38`, `:102-116`) because this
  storefront is configured by environment; the buyer side reads the same section shape from a
  TOML file (`core/buyer/src/core_buyer/delivery.py:31-47`).
- **Bare-metal provision terms on an introduction deal.** The buyer CLI negotiates an
  introduction by sending `BareMetalProvisionTerms(payload={"duration_seconds": ...,
  "access_method": "none"})` with `initial_price=0.0, max_price=0.0`
  (`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py:686-698`). An introduction deal
  therefore still rides a physical-provisioning term shape in this domain.
- **The `X-Market-Role` header default.** `bare_metal`'s authorize adapter reads
  `request.headers.get("X-Market-Role", "buyer")` and rejects anything else with 403
  (`api.py:200-202`).
- **Replay support.** `AuthorizedIntroductionRequest.exact_retry` defaults to `False`
  (`introduction_routes.py:57-58`); a domain may always return `False` and lose only replay.
- **The provisioning bypass.** `bare_metal` skips its physical-selection validation with
  `provisions_machine = "bare_metal" in selected_option.params`
  (`domains/bare_metal/.../negotiation_service.py:374-382`), paired with
  `domain_param_keys=("bare_metal",)` at `negotiation_service.py:561`. The discriminator is a
  params key, not the mechanism id; it works today only because the contact option builder never
  emits a `bare_metal` param (`settlement_config.py:236-241`).
- **Site, pool and physical-provisioning coupling is absent from the contact path entirely.**
  Nothing in `domains/bare_metal/.../introduction_routes.py`, `sqlite_client.py:88-115`, or
  `api.py:229-272` touches sites or pools.
- **Delivery.** `domains/bare_metal/.../delivery.py` in full, plus `runtime.py:121`, `:411-417`,
  the storefront CLI command, and the `arkhai-kit-delivery` dependency
  (`domains/bare_metal/storefront/pyproject.toml:9`,
  `domains/bare_metal/buyer/pyproject.toml:16`). Optional by construction
  (`introduction_routes.py:182`, `:292-293`, `:303-304`); `docs/development/ROADMAP.md:230`
  records that the mechanism kit gained no delivery dependency because dispatch is injected.

The concrete diff for a domain that wanted it, taken from what `bare_metal` actually has: one
dependency line (`domains/bare_metal/storefront/pyproject.toml:10`,
`arkhai-kit-contact-exchange==0.1.2`), one registration line, one `claimant_principal` resource
key, one migration splice, two thin persistence wrappers (~28 lines), a domain
`introduction_routes.py` (189 lines, of which `_accepted_introduction` at `:30-61` and `complete`
at `:117-149` carry all the domain-specific interpretation), and two routes plus an authorize
adapter (~82 lines). For `vms` there is an extra step its middleware imposes: its seller-auth
layer maps path and method to `(operation, resource)` in a hand-written chain
(`domains/vms/storefront/src/market_storefront/middleware/seller_auth.py:280-307`), so two new
arms would be needed there.

`docs/development/ARCHITECTURE.md:230` names `stripe`, `alkahest`, and `contact` as the
registered subsections; `openspec/specs/settlement-configuration/spec.md` "Requirement: Peer
mechanism configuration hierarchy" names only the `alkahest.v1` → `[Settlement.alkahest]` and
`fiat.stripe.v1` → `[Settlement.stripe]` mappings and does not mention `contact`. That is a
documented gap in the settlement-configuration spec, not a behavioural one.

## 2. The buyer-facing HTTP surface

Two routes, both signed, both mounted by the domain.

| Method | Path | Handler | Who may call |
| --- | --- | --- | --- |
| `POST` | `/api/v1/introductions` | `api.py:253-261` → `IntroductionRouteService.start` (`introduction_routes.py:229-276`) | buyer only (`introduction_routes.py:241`) |
| `GET` | `/api/v1/introductions/{obligation_ref}` | `api.py:264-272` → `.read` (`introduction_routes.py:306-331`) | buyer **or** seller (`introduction_routes.py:318`) |

There is **no HTTP re-delivery route**. Re-delivery on both sides is a local CLI action; see §4.

Reaching the point of calling them requires the ordinary negotiation routes:
`POST /api/v1/negotiate/new` (`api.py:363-383`) carrying a `SettlementSelection`
(`core/src/market_core/schemas.py:578-585`), which the bare-metal storefront answers
take-it-or-leave-it — its continue route always refuses further rounds (`api.py:413-416`).

**Signing.** All routes use the marketplace request signature `arkhai.market-request-signature.v2`
(`kit/identity/src/market_identity/models.py:13`), a fixed string with no negotiation: a
mismatch is 401 before any crypto (`core/storefront/src/core_storefront/auth.py:124-126`).
Headers: `X-Market-Signature-Version`, `X-Market-Identity-Scheme`, `X-Market-Identity-Identifier`,
`X-Market-Role`, `X-Market-Request-ID`, `X-Market-Timestamp`, `X-Market-Signature`
(`core/storefront/src/core_storefront/auth.py:32-38`; emitted at
`core/buyer/src/core_buyer/negotiation_client.py:556-565`).

The signed bytes are **not** JSON. `_frame` emits, for each field, a 4-byte big-endian unsigned
length followed by its UTF-8 bytes, refusing any field over 4096 bytes
(`kit/identity/src/market_identity/canonical.py:186-196`, bound at `:23`). The request preimage
is exactly ten framed fields in order: protocol, role, principal scheme, principal identifier,
method (uppercased), operation, resource, request id, `str(timestamp)`, body hash
(`canonical.py:60-76`). The response preimage is eleven, inserting `str(status)` before the body
hash (`canonical.py:79-96`). The body hash is lowercase SHA-256 over RFC-8785 canonical JSON, with
explicit nulls kept, or over the empty string for a bodiless request
(`canonical.py:40-57`). Two identity schemes exist, `ed25519` and `eip191`, and no others
(`kit/identity/src/market_identity/models.py:27-31`).

`operation` and `resource` are **not on the wire** — both sides derive them per route
(`introduction_start` / `introduction_read`, resource `obligation_ref`;
`core/buyer/src/core_buyer/introductions.py:50`, `:64`; server side
`introduction_routes.py:238-241`, `:315-318`). Default maximum
clock skew is 300 s (`core/storefront/src/core_storefront/auth.py:29`;
`kit/identity/src/market_identity/verification.py:133-134`). The caller signs with its own buyer
(or seller) key; no operator credential is involved. Responses are signed back by the storefront
under `arkhai.market-response-signature.v2` with role `seller` and verified by the buyer against
registry-pinned publisher principals — and every shipped client hard-fails when that verification
fails (`api.py:216-221`; `core/buyer/src/core_buyer/introductions.py:53`, `:67`;
`core/storefront-client/src/storefront_client/auth.py:192-207`).

**Request shape.** `IntroductionStart` (`introduction_routes.py:22-38`), `extra="forbid"`:
`negotiation_id: str`, `obligation_ref: str` matching `^[0-9a-f]{64}$`,
`contact_payload: dict[str, str]` with at least one entry, bounded by `validate_contact_payload`
(`settlement_config.py:48-65`).

**Response shape.** Both routes return the same projection
(`introduction_projection`, `introduction_routes.py:144-165`):
`{"obligation_ref": str, "mechanism": "contact-exchange.v1", "revealed": true,
"introduction": {...}, "counterparty_contact": {...}}`. It is an untyped `Mapping[str, Any]` on
the handler signature, with no FastAPI `response_model`, so it is not described in OpenAPI
(`api.py:253-272`).

**Idempotency and replay.** Two independent layers:

- Transport replay keyed on `(principal, X-Market-Request-ID)`, reserved before dispatch
  (`core/storefront/src/core_storefront/auth.py:219-249`). A repeat with the same id and same
  request hash replays the recorded status and body verbatim
  (`introduction_routes.py:204-214`); the same id with a different hash is a 409; a still-leased
  retry is `409 "request retry is pending"` (`introduction_routes.py:206-208`). The replay hash
  deliberately excludes the timestamp and proof so a caller may re-sign the same semantic request
  (`canonical.py:118-133`).
- Semantic idempotency of `start`: with a *fresh* request id, `persist` returns the existing row
  when the record is identical and raises on a differing contact payload, mapped to 409
  (`migrations.py:43-68`; `introduction_routes.py:261-262`).

Reveal called twice returns the same projection with no duplicate row. **Delivery fires at most
once**: `start` observes whether a record already exists *before* persisting and suppresses a
second seller-side delivery (`introduction_routes.py:247-254`, `:270-271`). Reads never deliver
(`introduction_routes.py:313-331`).

There is no idempotency-key header beyond `X-Market-Request-ID`, no rate limiting, and no
one-shot/consume semantics.

**Is every step storefront-mediated?** For obtaining the contact: yes. The buyer's path is
`POST /api/v1/negotiate/new` → `POST /api/v1/introductions` (the response *is* the seller's
contact) → `GET /api/v1/introductions/{ref}` as often as wanted. Everything else that is local is
optional or is the seller's prior configuration:

- seller configures `[Settlement.contact]` and any sinks — operator-local prerequisite;
- storefront drives the obligation to `collected` in-process — server-internal, no operator action
  (`domains/bare_metal/.../introduction_routes.py:117-149`);
- seller-side sink delivery is scheduled off the request path — operator-local, non-gating
  (`domains/bare_metal/.../delivery.py:72-99`);
- buyer-side sink delivery runs inline in the buyer CLI *after* the answer is printed — buyer-local,
  optional (`domains/bare_metal/buyer/.../cli.py:745-768`);
- re-delivery on either side is a local CLI invocation with no HTTP equivalent.

One caveat about the shipped buyer CLI rather than the protocol: `market bare-metal introduction`
recovers the deal from a local signed run log keyed by `--run-id`
(`domains/bare_metal/buyer/.../cli.py:607-630`, `:823-825`). The HTTP read itself needs only the
`obligation_ref` and the buyer's key, so a consumer holding those can call it directly.

## 3. The authoritative repeatable read

**It exists.** `GET /api/v1/introductions/{obligation_ref}` is an authenticated, side-effect-free,
durable read of the persisted introduction, callable by either party, any number of times.

- `IntroductionRouteService.read` calls only `prepare → authorize → load → project`; it never
  persists, never completes, never delivers (`introduction_routes.py:306-331`).
- Durability is the module's stated design: "inverted durability: the contact payloads persist and
  the read is idempotent. An introduction that could be lost to a missed poll would not be an
  introduction" (`introduction_routes.py:1-8`).
- The spec requires it: `openspec/specs/contact-exchange-settlement/spec.md` "Requirement: Contact
  is revealed only after acceptance, only to the counterparty" — "the read MUST be idempotent" —
  and "Requirement: The agreed context is durable", scenario "Reveal after restart".
- Pinned by tests: `kit/contact-exchange/tests/unit/test_introduction_routes.py:140-148` (both
  parties read the counterparty payload), `:224-234` (two reads deliver nothing),
  `domains/bare_metal/storefront/tests/test_http_introductions.py:263-289` (real HTTP GET by both
  parties) and `:294-315` (GET after a full storefront restart returns the same payload).

A read before any start is `409 "introduction has not been started"`
(`introduction_routes.py:324-326`). A non-party is refused 403
(`introduction_routes.py:314-320`; `api.py:191-202`).

This is the one downstream assumption that is fully underwritten: a consumer may treat an inbound
webhook as a hint and re-fetch authoritative state.

## 4. The sink plugin contract

**Interface.** A sink is a plain synchronous callable `(event: DeliveryEvent) -> None` that raises
on failure — `DeliverySink` Protocol at `kit/delivery/src/market_delivery/sinks.py:40-44`. A sink
*factory* is `(settings: Mapping[str, Any]) -> DeliverySink`
(`sinks.py:47-50`). Settings models subclass `SinkSettings`, which is strict and closed and
carries only `timeout_seconds` (`sinks.py:53-62`).

**Event.** `DeliveryEvent` (`kit/delivery/src/market_delivery/events.py:33-56`), frozen,
`extra="forbid"`:
`kind` (`"introduction.revealed"`, `events.py:18`), `obligation_ref`, `agreement_ref | None`,
`role` (`"buyer" | "seller"`), `counterparty` (canonical `scheme:identifier` of the *other* party,
`events.py:25-30`), `contact: dict[str, str]` verbatim, `context: dict[str, Any]` (the agreed
introduction package), and `rendered: str`, a deterministic human-readable block built at
construction (`events.py:59-94`).

**Discovery.** Entry-point group `market.delivery_sinks` (`sinks.py:21`), loaded via
`importlib.metadata.entry_points` (`discovery.py:42-59`). The four shipped sinks are declared in
`kit/delivery/pyproject.toml:12-16` as `file`, `command`, `webhook`, `smtp`. A third party can ship
a sink as a separate installable distribution — but it must be installed **into the same Python
process that performs the delivery**: the storefront process for seller-side delivery, the buyer
CLI process for buyer-side delivery. A distribution that fails to load is reported and skipped, not
fatal (`discovery.py:51-58`); an enabled name that is not installed, or settings a factory rejects,
raises at set-construction time (`discovery.py:76-92`).

**Configuration.** One delivery section per side, identical shape on seller and buyer
(`config.py:1-17`): `enabled = [names]`, `timeout_seconds`, and one per-sink table. Duplicate
names are rejected (`config.py:70-74`); settings for a sink nobody enabled are rejected
(`config.py:82-89`). **Scope is per-process and global** — there is no per-account, per-deal, or
per-buyer scoping anywhere in the section shape or in `DeliveryConfig` (`config.py:31-46`). One
`webhook` entry means exactly one URL for the whole process. The carriers differ: the buyer reads
a dotted path out of layered TOML (`core/buyer/src/core_buyer/delivery.py:31`, `:34-41`), the
bare-metal storefront reads a JSON blob from an environment variable
(`domains/bare_metal/.../delivery.py:38`, `:102-116`).

A small discrepancy worth recording: the docstring and the specs spell the section `[Delivery]`
(`config.py:3-11`), but the buyer looks it up as the dotted path `"delivery"`
(`core/buyer/src/core_buyer/delivery.py:31`, `:40`) through `get_dotted`, which does no case
folding (`kit/config/src/market_config/config_loader.py:281-290`). The buyer's own test fixture
writes lowercase `[delivery]` (`core/buyer/tests/unit/test_delivery.py:29-32`).

**What the `webhook` sink sends** (`builtin/webhook_sink.py:36-78`): `POST` to the configured URL,
`Content-Type: application/json` plus whatever static headers the operator configured, body is
`json.dumps(event.payload(), ensure_ascii=False, sort_keys=True)` — that is the full
`DeliveryEvent` model dump, contact included — unless `send = "text"`, in which case the body is
`{"text": event.rendered}` — with `Content-Type: application/json` either way. Any HTTP status
≥ 400, URLError, or OSError becomes a `DeliveryError` whose message deliberately omits the URL,
because "a webhook URL is usually the credential" (`webhook_sink.py:61-76`).

Two timeouts, and they are not the same one. The socket timeout passed to `urlopen` is the
**per-sink** `timeout_seconds`, whose default is `None` (`webhook_sink.py:44`, `:59`;
`sinks.py:62`). The section-level `timeout_seconds` (10 s by default, `sinks.py:23`) sets only the
dispatcher's join bound (`discovery.py:93` → `dispatch.py:86-96`), which abandons the thread
rather than cancelling the socket. A webhook sink configured without its own `timeout_seconds`
therefore has no socket timeout; the dispatcher still gives up on it at the section bound and
reports `timed out after Ns` (`dispatch.py:88-96`).

**Authentication.** There is none defined by the protocol, in either direction:

- The sink does not authenticate itself to the operator's process: it is discovered by entry point
  and trusted because it is installed (`discovery.py:46-59`).
- The operator's process does not sign what it sends. The complete header set constructed by the
  webhook sink is `{"Content-Type": "application/json", **config.headers}`
  (`webhook_sink.py:56`) — no HMAC, no signature header, no timestamp, no nonce. The only
  available authentication is a static operator-configured header or a secret in the URL; both
  are marked `secret: True` in `WebhookSinkSettings` (`webhook_sink.py:22-32`).

This is a direct mismatch with the downstream standing rule that every inbound webhook be
"signature-verified, idempotency-deduped by event id" (`webapp:CONTEXT.md:215`): the event carries
no id field at all (`events.py:33-51`) and nothing signs the body.

**Dispatch semantics** (`dispatch.py:61-118`): every sink runs in its own daemon thread, all
started at the same instant, each joined under its own bound measured from that common start; an
overrunning sink is abandoned, not interrupted. `deliver` never raises. Outcomes are
`DeliveryOutcome(sink, obligation_ref, delivered, failure)` (`dispatch.py:29-41`) and a failure
from anything other than a `DeliveryError` degrades to its exception class name
(`dispatch.py:44-47`). There is **no retry, no queue, no outbox, and no durable delivery record** —
the only durable artifact is the introduction row itself. Seller-side dispatch is scheduled as an
asyncio task off the request path (`domains/bare_metal/.../delivery.py:84-99`); buyer-side runs
inline after printing (`core/buyer/src/core_buyer/delivery.py:1-11`, `:50-67`).

**Re-delivery** is an explicit local operator action on each side and has no HTTP surface:
`market-bare-metal-storefront redeliver-introduction`
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/cli.py:60-85`, implementation
`delivery.py:119-138`) and the buyer's `--deliver` flag on `market bare-metal introduction`
(`domains/bare_metal/buyer/.../cli.py:810-834`). Both re-read the durable record rather than
reconstructing one.

### Does a hosted multi-tenant sink fit this model?

The model as written is operator-local and self-addressed. `openspec/specs/introduction-delivery/spec.md`
"Requirement: Delivery is local, self-addressed, and recipient-side": each side "MUST deliver only
to destinations configured by that side's own operator", and "neither side MUST deliver anything to
the counterparty". `docs/development/ARCHITECTURE.md:234` states the same: the storefront delivers
to the seller's destinations, "the buyer's CLI delivers the seller's to theirs".

Measured against that, a hosted backend registering itself as one sink for many accounts is a
different arrangement wearing the same name. Four things in the code say so:

1. **The event carries no account or tenant identity.** `DeliveryEvent`'s fields are `kind`,
   `obligation_ref`, `agreement_ref`, `role`, `counterparty`, `contact`, `context`, `rendered`
   (`events.py:44-51`). `counterparty` is the *other* party's principal
   (`events.py:25-30`; set from `agreement.buyer_principal` seller-side at
   `domains/bare_metal/.../delivery.py:92`, from the seller principal buyer-side at
   `domains/bare_metal/buyer/.../cli.py:755`). Nothing names the recipient. A multi-tenant sink can
   only route by correlating `obligation_ref` / `agreement_ref` against its own records — which
   works only if it already holds those deals.
2. **Sink configuration has no per-account dimension.** The delivery section is one flat
   per-process table per sink name, with duplicates rejected (`config.py:48-90`). There is no
   place to express "account A's introductions go here, account B's there". A factory does
   receive its settings once at construction (`discovery.py:84-85`), so an account credential can
   be baked into one sink instance — but that identifies the *process*, one account per
   configured instance, and the constructed sink thereafter receives only the event
   (`sinks.py:44`).
3. **The buyer side delivers from the buyer's own process.** `core/buyer/src/core_buyer/delivery.py`
   runs sinks inline in the command (`:1-11`), and the shipped buyer path is the Python CLI. A
   non-Python backend driving the reveal over HTTP never executes any sink — it already has the
   seller's contact in the `POST /api/v1/introductions` response body
   (`introduction_routes.py:272-276`). For a buyer-side consumer the webhook sink is not the
   channel; the response is.
4. **A sink that serves many accounts sees every account's revealed contact.** The event carries
   the counterparty payload verbatim and the spec normatively forbids redacting it
   (`openspec/specs/introduction-delivery/spec.md` "Requirement: The delivered event carries the
   introduction without interpreting it"; `events.py:37-40`, `:117-118`). Concentrating that in one
   destination is coherent only where that destination *is* the operator of all those identities.
   Because `obligation_ref` is identical on both sides of one deal
   (`introduction_routes.py:160`), a sink configured by both parties to the same introduction
   receives both halves keyed identically and can join them into a full two-sided contact record —
   something neither party's own local delivery can produce. The design record already rests the
   privacy case on exactly the property this removes: an operator "only ever exports data to
   themselves" (`docs/development/ARCHITECTURE.md:234` makes the same point about the retention
   boundary).

The arrangement is mechanically possible where the hosted backend is itself the operator running
the role process, since the sink set is process-global and the backend would be addressing itself.
It is not what the spec's "each side's own operator" wording describes when the backend is a
third party relaying to many separate account holders, and the protocol supplies neither the
addressing nor the authentication such a relay needs. This inventory records the mismatch; #191
owns what to do about it.

## 5. Reveal payload and redaction

**Payload.** `dict[str, str]`, opaque, never interpreted. Bounded at every ingress by
`validate_contact_payload` (`settlement_config.py:48-65`): at most 16 entries, keys 1-64 chars,
values non-blank and at most 512 chars. The seller's half comes from operator configuration
(`[Settlement.contact].contact_payload`, `settlement_config.py:107-111`, marked
`repr=False` and `secret: True`); the buyer's half arrives on the wire at introduction start
(`introduction_routes.py:33`). Neither is ever seller-supplied at publication.

The projection each side receives is
`{obligation_ref, mechanism, revealed, introduction, counterparty_contact}`
(`introduction_routes.py:159-165`), where `counterparty_contact` is the *other* side's half only,
selected by viewer role (`introduction_routes.py:156-158`, `:216-227`). The `introduction` package
is `{option_id, profile, channel, terms}` plus optional `listing_id` and `negotiated_context`
(`settlement_config.py:319-330`).

**Redaction, surface by surface.** Confinement is achieved by construction plus substring
leak-guards; there is no masking helper in either kit.

| Surface | What applies | Citation |
| --- | --- | --- |
| Published listings / registry records | option `params` are only `{profile, channel, terms, claimant_principal}`; publication raises if any configured contact value appears as a substring of the serialized params | `settlement_config.py:236-247` |
| Seller config itself | config validation rejects a payload whose values appear in the published profiles | `settlement_config.py:134-151` |
| Settlement options pre-acceptance | same object, same guard | `settlement_config.py:242-247` |
| Accepted obligation | no contact in the obligation; guard over `{"params", "introduction"}` raises on a substring match; `amount=None` | `settlement_config.py:331-358` |
| Readiness details | only `{"channels": [...]}`, seller role only; the runtime rejects any public-detail key outside the declared allowlist `{"channels"}` | `settlement_config.py:178-187`, `:402`; `kit/settlement-runtime/src/market_settlement_runtime/configuration.py:873-880` |
| Wire responses | only the two introduction routes return contact, both authenticated and party-restricted; no partially redacted form exists anywhere | `api.py:253-272`; `introduction_routes.py:241`, `:318` |
| Logs | the payload is never logged; storefront logs only `obligation_ref` and a safe outcome description, and a scheduling failure by exception class alone | `domains/bare_metal/.../delivery.py:52-69`; `dispatch.py:29-47` |
| Buyer command output | **deliberately unredacted** — the CLI prints the full projection, contact included; that is the command's purpose | `domains/bare_metal/buyer/.../cli.py:806`, `:827` |
| Delivery events | **deliberately unredacted** — verbatim contact plus a rendered block, as the spec requires | `events.py:37-40`, `:86-94` |
| Evidence / audit artifacts | none exist for this mechanism; its four receipts carry only `kind`, `mechanism_ref`, `fulfillment_ref` | `client.py:32`, `:56-59`, `:71-76`, `:90-94` |

Two observations recorded as found, not as recommendations:

- The settlement-runtime's readiness secret check derives secret values with
  `configuration.py:998-1022`; for a `dict`-typed secret field it adds `str(revealed)` — the repr
  of the whole dict — to the compared set (`:1011`) and substring-matches JSON (`:882-885`). An
  individual contact *value* leaking into `public_details` would not match that repr. The
  contact-exchange kit's own guards do compare individual values
  (`settlement_config.py:243-247`, `:336-340`).
- `kit/config`'s secret-redacting projections (`resolution.py:433-437`, `:356-363`) would redact
  `contact_payload` correctly, but `redacted_projection`, `public_projection`,
  `public_fingerprint` and `resolve_model` have no production caller in this repo; the storefront
  reads the section through `composition.config.mechanism_config("contact")` (`api.py:237`).

## 6. Listing advertisement, and coexistence with a funded option

**Mechanism identifier.** `MECHANISM = "contact-exchange.v1"` (`settlement_config.py:27`);
`INTRODUCTION_ASSET = "introduction"` (`:29`); config key `"contact"` (`:28`).

**How a listing advertises it.** Not by a compatibility flag. A listing carries a
`settlement_options` array, and a contact-exchange option is one entry whose `mechanism` is
`contact-exchange.v1`, whose `asset` is `introduction`, whose `rates` is empty, and whose `params`
are `{profile, channel, terms, claimant_principal}` (`settlement_config.py:236-259`). A buyer
would detect compatibility by shape: `contact_buyer_compatibility` accepts any enabled,
well-shaped, rateless introduction option and nothing else (`settlement_config.py:269-283`), and
the advertised `channel` is queryable through the registered clause field `contact.channel`
(`settlement_config.py:361-366`, `:403-414`). Both are unreachable today because no buyer root
installs the registration (§1); the shipped bare-metal buyer string-compares the mechanism
instead (`domains/bare_metal/buyer/.../cli.py:656`).

There is also a whole registry *profile* for introduction markets:
`core/registry/filter-spec.introductions.yaml`, which requires option-only listings with no escrow
contracts, leaves `offer_resource` open, and matches missing-field-tolerantly so sparse listings
stay discoverable (`filter-spec.introductions.yaml:1-38`). It filters on `region`, `mechanism`, and
`settlement_options[*].params.channel`. It is deployed by pointing `REGISTRY_FILTER_SPEC_PATH` at
it (`:10`) — i.e. it is a whole-registry deployment choice, not a per-listing one.

**Coexistence with a funded option on the same resource.** Structurally supported, and nowhere
affirmatively sanctioned. Publication takes one candidate resource and a *sequence* of clauses,
evaluates readiness per mechanism, and concatenates every ready mechanism's options into one
listing's `settlement_options`, guarding only against duplicate option identities
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py:102-185`,
duplicate guard at `:170-174`). `openspec/specs/settlement-configuration/spec.md` "Requirement:
Priority orders choices but never changes accepted settlement" describes exactly this: options are
emitted in priority order for every enabled and ready mechanism with a valid clause, and accepted
Terms pin one exact option. Nothing rejects mixing an introduction option with `fiat.stripe.v1` or
`alkahest.v1` on one resource — but no test, spec requirement, or comment permits it either, and
no test in the repo exercises a mixed publication. This is read from the merge loop, not from
observed behaviour.

Two caveats about *which* resource, in bare metal specifically. The clause list is read once per
publication round from `BARE_METAL_STOREFRONT_PUBLICATION_CLAUSES`
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/publication_cli.py:177-183`) and
applied to every candidate in that round (`publication_cli.py:222-238`) — so enabling a contact
clause attaches an introduction option to *every* listing published, not to a chosen resource.
`vms` by contrast takes clauses per listing on the create request
(`domains/vms/storefront/src/market_storefront/models/listing_models.py:34-37`).

**Deterministic option identity across settlement outcomes.** `derive_settlement_option_id` hashes
`{"mechanism", "asset", "rates", "params"}` as compact sorted-key JSON with SHA-256
(`core/src/market_core/schemas.py:531-547`). Because `mechanism` and `asset` are both inside the
hash, an introduction option (`contact-exchange.v1` / `introduction` / empty rates) and a funded
option (`fiat.stripe.v1` or `alkahest.v1`, a priced asset, non-empty rates) cannot collide, however
similar their commercial description. The settlement-configuration spec states the same principle
for funding profiles: "Equal resource, rate, currency, parties, and condition under different
profiles MUST produce distinct option identities." A genuine digest collision would be refused,
not silently resolved: publication raises (`settlement_composition.py:170-174`;
`domains/bare_metal/src/arkhai_bare_metal/hosted_publication.py:63-69`) and selection requires
exactly one match (`negotiation_service.py:363-377`;
`domains/bare_metal/src/arkhai_bare_metal/hosted_contract.py:382-386`).

The identity anomaly that does exist runs the other way: **a contact option's id is not
listing-unique.** `contact_option_builder` receives the candidate resource in `resources`
(`settlement_composition.py:129`) and ignores it, building `params` from the profile and the
claimant principal alone (`settlement_config.py:236-241`). One seller with one profile therefore
produces the byte-identical `option_id` on every listing in a round. The duplicate guard is
per-publication-payload, i.e. per listing, so it never fires. No code path traced here depends on
listing-uniqueness — option lookup is always scoped to a listing's own `settlement_options`
(`negotiation_service.py:352-356`) and `obligation_ref` mixes in the negotiation id
(`kit/settlement-runtime/src/market_settlement_runtime/models.py:61-74`) — and no comment or spec
line acknowledges it either.

Two mechanism-level guards keep the two kinds from being confused after selection: the buyer CLI
refuses to run `request-introduction` against an option with rates and tells the operator to use
`buy` instead (`domains/bare_metal/buyer/.../cli.py:656-660`), and the accepted-obligation builder
refuses a rated option outright (`settlement_config.py:300-301`).

**Terminal state, and the absence of a reply channel.** There is no state enum for the negotiation
thread — `terminal_state` is a free `TEXT` column
(`core/storefront/src/core_storefront/sqlite_client.py:325`) set to `"success"` alongside
`status = "terminated"` in the accepting write
(`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/sqlite_client.py:257-258`), after
which continuation is 409 (`core/storefront/src/core_storefront/services/negotiation_service.py:258-263`).
The settlement side has typed literals
(`kit/settlement-runtime/src/market_settlement_runtime/models.py:19-35`) and the introduction lands
at `materialization_state="materialized"`, `condition_state="ready"`,
`collection_state="succeeded"` (`kit/settlement-runtime/src/market_settlement_runtime/runtime.py:557-564`),
because every `ContactExchangeClient` call answers ready immediately (`client.py:23-60`).

The obligation is driven `register → materialize → bind_fulfillment → check → collect` at reveal
time (`domains/bare_metal/.../introduction_routes.py:126-149`), with every client operation a
local no-op (`client.py:16-95`). `openspec/specs/settlement-servicing/spec.md` "Requirement:
Non-financial obligations are serviceable", scenario "Servicing an introduction obligation": the
runtime "records it ready, completes collection with a receipt, and no funding or reclaim machinery
is invoked". `openspec/specs/contact-exchange-settlement/spec.md` "Requirement: An introduction
completes a deal" makes the terminal settled state independent of whether either party has read the
reveal. There is no post-introduction messaging surface in the protocol, and the delivery spec
forbids one: "neither side MUST deliver anything to the counterparty"
(`openspec/specs/introduction-delivery/spec.md` "Requirement: Delivery is local, self-addressed, and
recipient-side"). The downstream reading of an introduction as terminal state plus notification,
never a reply channel, matches what is implemented.

Two related observations. **Accepting one option does not invalidate the others**: nothing closes
or marks the listing on acceptance — the accepting write touches only the negotiation thread and
the plan (`negotiation_service.py:422-444`), and the opening guard checks only that the listing is
`open` and unpaused (`:195-199`). What is pinned is per-deal, not per-listing. And **settlement
does not happen at acceptance**: `register_plan`/`materialize`/`collect` run only inside the
`complete` callback that `POST /api/v1/introductions` triggers
(`domains/bare_metal/.../introduction_routes.py:117-149`), so a deal that is accepted and never
introduced has no settlement obligation record at all. That is consistent with the
no-contact-for-unstarted-deals requirement, but it separates "accepted" from "settled" by a
buyer-initiated call, where the spec's "An introduction completes a deal" reads as if acceptance
suffices.

## 7. Contact retention

**Where it lives.** Table `contact_introductions`, migration `20260815_006_contact_introductions`
(`migrations.py:17-32`): `obligation_ref` (PK), `agreement_ref`, `buyer_contact` (JSON),
`seller_contact` (JSON), `introduction_package` (JSON), `created_at` (defaulted timestamp). Written
exactly once, idempotently, at introduction start (`migrations.py:43-68`). A deal that never starts
its introduction persists no contact at all — acceptance is payload-free by construction
(`introduction_routes.py:170-174`; spec scenario "Unstarted deals hold no contact data").

**How long it is kept: indefinitely.** There is no TTL, no expiry column, no scheduled deletion, no
purge job, and no defined retention window.

- The table has no `expires_at`/`retain_until` column and nothing reads `created_at` — the only
  `SELECT` filters on `obligation_ref` alone (`migrations.py:75-79`).
- `openspec/specs/contact-exchange-settlement/spec.md` "Requirement: Contact payloads are bounded,
  deliberate PII persistence" requires payloads to be **deletable**, not deleted, and its teardown
  scenario refers to "the end of its retention window" without defining, bounding, or defaulting
  that window anywhere.
- `expiration_unix` on the obligation (`settlement_config.py:304-306`) is the deal's expiry, not a
  retention clock; `reclaim_expired` is an explicit no-op that touches no row
  (`client.py:79-95`).

**Deletion.** The primitive exists and nothing calls it. `delete_introduction(conn,
obligation_ref)` is defined at `migrations.py:91-98` and exported at `__init__.py:18`. Its only
callers in the repo are its own unit test (`kit/contact-exchange/tests/unit/test_migrations.py:59`,
`:61`). There is no `DELETE` route (the storefront exposes only `POST` and `GET` at
`api.py:253-272`), no storefront CLI command for it (the only introduction command is
`redeliver-introduction`, `cli.py:60-85`), and `bare_metal`'s SQLite wrapper wires `insert` and
`load` but not `delete` (`sqlite_client.py:38-39`, `:88-113`). The spec scenario "Introduction
teardown removes the payloads" is therefore satisfiable today only by direct SQL or by an operator
writing their own caller.

**Copies outside the boundary.** Delivered events land in operator-configured files, webhooks and
mailboxes with no rotation or expiry (`builtin/file_sink.py:24-30`).
`docs/development/ARCHITECTURE.md:234` states this plainly: a delivered copy "falls outside the
introduction retention boundary".

## 8. What a non-Python consumer must reimplement versus call

Callable over HTTP, no Python required:

- `POST /api/v1/negotiate/new` and `POST /api/v1/negotiate/{negotiation_id}`
  (`api.py:363-416`), carrying a `SettlementSelection`
  (`core/src/market_core/schemas.py:578-585`).
- `POST /api/v1/introductions` (`api.py:253-261`).
- `GET /api/v1/introductions/{obligation_ref}` (`api.py:264-272`), repeatedly.
- Registry reads for the listing and its `publisher_principals`.

Must be reimplemented:

1. **The framed canonical preimage.** Not JSON: a 4-byte big-endian length prefix per field, ten
   fields for a request and eleven for a response, in fixed order, each field capped at 4096 bytes
   (`kit/identity/src/market_identity/canonical.py:60-96`, `:186-196`). Plus the seven
   `X-Market-*` headers (`core/storefront/src/core_storefront/auth.py:32-38`) and a 300 s skew
   bound (`auth.py:29`).
2. **Ed25519 signing with the repo's encodings** — 32-byte seed, identifier and proof as
   *unpadded* base64url (`kit/identity/src/market_identity/schemes/ed25519.py:19`, `:30-37`;
   `models.py:108-113`). `eip191` is the only alternative
   (`kit/identity/src/market_identity/models.py:27-31`).
3. **RFC-8785 (JCS) body hashing** (`canonical.py:40-57`) — a real JCS implementation, not
   `JSON.stringify` with sorted keys. JCS sorts by UTF-16 code unit and formats numbers by the
   ECMAScript rules; the two diverge above U+FFFF and on float rendering.
4. **A second, different canonical serializer** for content-addressed refs:
   `json.dumps(ensure_ascii=False, separators=(",",":"), sort_keys=True)`, which sorts by Unicode
   code point and formats numbers by Python's rules
   (`kit/settlement-runtime/src/market_settlement_runtime/models.py:39-40`;
   `core/src/market_core/schemas.py:544-546`). Same name, different bytes from (3). This is the
   likeliest place for a port to diverge silently.
5. **`obligation_ref` derivation**, which uses serializer (4) over
   `{"protocol": "arkhai.settlement-obligation.v1", "agreement_ref", "obligation_index",
   "obligation"}` (`kit/settlement-runtime/src/market_settlement_runtime/models.py:61-74`). It is
   returned by no endpoint; the buyer computes it from the accepted plan
   (`domains/bare_metal/buyer/.../cli.py:620-624`), and the route 404s on a mismatch against its
   own derivation (`domains/bare_metal/.../introduction_routes.py:44-50`). This is the highest-risk
   reimplementation item in the contact-exchange flow.
6. **The per-route `(role, operation, resource)` table**, since neither `operation` nor `resource`
   is on the wire. For this flow: `negotiate_new`/listing id, `negotiate_continue`/negotiation id,
   `introduction_start`/`obligation_ref`, `introduction_read`/`obligation_ref`
   (`core/buyer/src/core_buyer/introductions.py:50`, `:64`;
   `core/storefront-client/src/storefront_client/client.py:1413-1447`).
7. **Response signature verification**, including resolving publisher principals from the registry
   listing (`core/buyer/src/core_buyer/introductions.py:53`, `:67`;
   `core/storefront/src/core_storefront/auth.py:282-340`). No shipped client treats it as optional.
8. **Replay discipline around `X-Market-Request-ID`** — an exact retry replays the recorded
   response, a changed reuse is 409 (`core/storefront/src/core_storefront/auth.py:223-249`).
9. **`option_id` derivation**, only if the consumer wants to verify an advertised option rather
   than echo it — serializer (4) over `{mechanism, asset, rates, params}`
   (`core/src/market_core/schemas.py:531-547`).
10. **Its own deal state.** The shipped buyer path keeps a local signed run log; the protocol needs
    only `seller_url`, `negotiation_id`, `obligation_ref` and the buyer key.
11. **Nothing for delivery.** A non-Python buyer never runs a sink: the contact arrives in the
    `POST /api/v1/introductions` response body and can be re-read at will. The sink plugin contract
    is a Python entry-point contract (`sinks.py:21`, `discovery.py:42-59`), not reachable from
    another runtime except by receiving a webhook from a Python process that already delivers.

Two traps a port will not discover from the wire. First, the transmitted bytes are irrelevant —
the server re-parses the JSON and re-canonicalizes, so only the parsed value matters
(`core/buyer/src/core_buyer/negotiation_client.py:566-571` sends non-JCS bytes and still
verifies). Second, what the server re-canonicalizes is a *pydantic-normalized* value, not the raw
body: `negotiate_new` hashes `body.model_dump(mode="json", exclude_none=True, exclude_unset=True)`
(`domains/bare_metal/.../api.py:374`), so a client must omit nulls and unset fields entirely and
match the declared field types. The introduction start route is the well-behaved one — it hashes
`start.model_dump(mode="json")` with no exclusions over a three-field `extra="forbid"` model
(`kit/contact-exchange/src/market_contact_exchange/introduction_routes.py:239`, `:22-38`).

Identity creation itself needs nothing from this repo: an Ed25519 key pair generated locally is
sufficient, and there is no buyer registration endpoint. The buyer's key is bound trust-on-first-use
by appearing as `buyer_principal` in the `negotiate_new` body, which the server pins for that
request (`domains/bare_metal/.../api.py:370-377`) and persists as the agreement's
`payer_principal`; the introduction routes then authorize against that stored principal
(`introduction_routes.py:236-241`, `:311-316`).

There is **no signing conformance corpus anywhere in the repo** — consistent with
[#181](https://github.com/arkhai-io/simple-compute-market/issues/181)'s decision to decline golden
vectors. The only cross-language conformance artifact,
`domains/apicredits/middleware/conformance/session.json`, covers API-credit gating, not signing:
the TypeScript and Rust middleware under `domains/apicredits/middleware/` port bearer-token
extraction, a verify cache, and batched credit consumption over three *unsigned* POSTs, and contain
no `X-Market-*` header at all
(`domains/apicredits/middleware/typescript/src/client.ts:77-82`, `:111`, `:132`, `:157`).

Not available over HTTP at all, in any language:

- re-delivery to sinks (local CLI on both sides — `domains/bare_metal/storefront/.../cli.py:60-85`,
  `domains/bare_metal/buyer/.../cli.py:810-834`);
- deletion of a revealed introduction (no caller anywhere, §7);
- seller-side configuration of the contact payload and profiles (operator config only).

Also relevant to a port, from `openspec/specs/settlement-configuration/spec.md` and the
registration itself: contact-exchange declares `roles={"buyer","seller"}` and
`negotiates_scalar_amount=False` (`settlement_config.py:394-395`), and reports the capability
`introduction.v1` in preflight (`settlement_config.py:185`). Per the map's standing vocabulary, a
capability a consumer cannot perform is a listing it cannot transact, not a gap in support.

## 9. Contradictions and unresolved items, as found

- `openspec/specs/settlement-configuration/spec.md` "Requirement: Peer mechanism configuration
  hierarchy" enumerates only the Alkahest and Stripe config-key mappings; the implementation adds
  `contact` → `contact-exchange.v1` (`settlement_config.py:28`, `:392`) and
  `docs/development/ARCHITECTURE.md:230` documents all three. The spec is behind the code.
- `openspec/specs/contact-exchange-settlement/spec.md` requires contact to be "deletable as part of
  the deal lifecycle" and describes teardown "at the end of its retention window". No lifecycle
  caller, route, or command exists, and no window is defined (§7).
- `kit/contact-exchange/src/market_contact_exchange/migrations.py:5` asserts payloads are "deleted
  as part of the deal lifecycle". No code performs that deletion.
- The introduction routes return `Mapping[str, Any]` with no response model, so the projection
  shape is absent from the storefront's OpenAPI document (`api.py:253-272`).
- The delivery event has no event id and no signature, while the downstream consumer's standing
  webhook rule assumes both (`events.py:44-51`, `webhook_sink.py:56`; `webapp:CONTEXT.md:215`).
- The spec's "An introduction completes a deal" reads as if acceptance settles; the code settles at
  introduction start (§6). Relatedly, the buyer run log ends an introduction run at `"agreed"`
  (`domains/bare_metal/buyer/.../cli.py:721-722`), which is not in the terminal-status set
  (`core/buyer/src/core_buyer/run_log.py:64-72`), and the reveal is recorded as an event only
  (`cli.py:805`) — so an introduction run's buyer-side log never reaches a terminal status.
- Contact option identities are not listing-unique (§6). Nothing traced here depends on it and
  nothing documents it.
- Whether an introduction option and a funded option may share one resource is settled by neither
  a permission nor a prohibition: the merge loop tolerates it, no test exercises it (§6).
- The delivery section is spelled `[Delivery]` in the kit docstring and the specs and looked up as
  `delivery` by the buyer loader (§4).
- A webhook sink configured without its own `timeout_seconds` gets no socket timeout; only the
  dispatcher's join bound applies (§4).
- No example `[Settlement.contact]` section exists anywhere in the repo outside test fixtures, so
  its deployment shape is inferable only from the pydantic model (`settlement_config.py:96-151`).
- `negotiated_context` — the mechanism's slot for carrying negotiated agreement into the
  introduction package — is supplied by no domain (§1).
