# Two-sided contact delivery contract — final review candidate 2

Status: frozen design candidate, not an implemented wire or an authorization to
send. Mechanism remains `contact-exchange.v1`; marketplace request/response
identity envelope remains version 2. Unknown carrier/policy versions fail closed.
The final contract gate must approve this exact document before implementation.

## Ownership and eligibility

- Contact kit owns policy, review/finalize carriers, immutable exchange and
  recipient-intent semantics. Bare-metal role owns accepted-party authorization,
  accepted-plan lookup, SQLite transaction and worker composition. Generic core
  remains mechanism-opaque; no payment bypass or general callback framework.
- Storefront owns **both** recipient intents and SMTP dispatch. Buyer application
  owns account settings, human authority and its frozen outbound request intent;
  it supplies only its authenticated buyer's own route/contact, not seller input.
  Seller independently configures contact and route through operator settings.
  A seller self-service console or account-to-storefront sync is not required.
- Acceptance binds public terms and pending bookkeeping only. Explicit buyer
  finalization is the later contact-sharing mutation, not another acceptance,
  payment confirmation, off-platform completion attestation or provisioning.
- Missing delivery policy remains pull-only under this new contract. Historical
  no-outbound terms, unstarted acceptances and revealed records acquire zero new
  jobs. Existing explicitly local delivery compositions are not reclassified by
  this absence rule; they do not acquire two-sided jobs. Never backfill, rewrite
  old accepted terms, republish old IDs or use current sinks to resend old copies.
- New eligible agreements must accept the exact public policy below. A legacy
  start body against an eligible agreement fails **before capture**. Unknown or
  malformed policy never downgrades to pull-only. Old clients may refuse new
  options; a server must not let an old client's lack of understanding authorize
  disclosure. Source validation must preserve old policy-absent option hashes.

## Public policy

Optional `params.delivery_policy` on the public contact option; absent is omitted,
not serialized as null. Exact object for this increment:

```json
{
  "kind": "contact-delivery.v1",
  "mode": "two-sided-contact",
  "channel": "email",
  "trigger": "explicit-finalization",
  "recipient_authority": "each-party-own-route"
}
```

Include the complete object in option content addressing, accepted obligation
params and `service_terms["contact-exchange.v1"]` introduction package. Preserve
all existing profile/channel/terms/claimant/payer/listing/option fields. Public
`channel` outside this policy remains descriptive and is NOT a delivery selector.
No address, contact, token or credential enters these public carriers.
Configured `ContactProfile` adds optional `delivery_policy` with this exact
object; omission is policy-absent and explicit null is invalid. Preserve existing
profile channel/terms and global private `contact_payload` ownership. A profile
with this policy is eligible; no separate global setting enrolls old profiles.

## Private route and contact values

`contact_payload` remains an opaque nonempty string map: at most 16 entries,
key 1–64 Unicode code points, nonblank value 1–512 code points. Count Unicode scalar values, reject lone surrogates, do not trim or normalize
keys/values, and require at least one non-whitespace scalar per value. Bind
objects with the existing marketplace JCS canonical JSON; preserve string bytes
after JSON decoding. Shared vectors cover astral characters and escaping. Do not narrow contact
keys to email/Slack/Telegram; personal details and route are independent concepts.

`delivery_route` is a strict object `{kind: "email", address: string}`. One
mailbox only: reject display-name lists, CR/LF/control injection, empty/invalid
addresses and unsupported kinds. Admit ASCII dot-atom local parts of 1–64 characters: nonempty atoms made
from letters, digits and `!#$%&'*+-/=?^_`{|}~`, separated by single dots.
The domain has at least two DNS labels, each 1–63 ASCII letters/digits/hyphens,
with alphanumeric ends; no trailing dot. Total address length is at most 254.
Reject quoted local parts, address literals, display names, whitespace, controls
and non-ASCII forms; no SMTPUTF8 or implicit IDNA conversion. Preserve supplied
case/spelling rather than silently normalizing it. Never derive it from the other party's contact or infer consent from
an account's sign-in email. A buyer application may explicitly select its
verified sign-in mailbox. The storefront trusts a signed buyer assertion of its
own route, not independent proof of inbox ownership. Seller configuration is
operator authority. Configured/validated does not mean reachable.

Slack and Telegram can appear as unavailable future choices in a client; they
are not admissible `delivery_route` variants in this version.

## Signed HTTP interfaces (candidate)

All paths are seller API paths. Authorized responses are request-bound signed and
no-store; pre-authentication refusals retain the existing unsigned refusal contract.
Authorization uses the accepted complete canonical principal, not a body identity.
The BFF account ID never crosses this wire.

| Method/path | operation / role / resource | Request or response |
|---|---|---|
| POST `/api/v1/introductions/reviews` | `introduction_review` / buyer / obligation_ref | Review input below; returns review below |
| POST `/api/v1/introductions` | `introduction_start` / buyer / obligation_ref | Legacy input OR strict version-2 finalize input; discriminate, never drop fields |
| GET `/api/v1/introductions/{obligation_ref}` | `introduction_read` / accepted party / obligation_ref | Existing counterparty-only reveal or signed pending409; no jobs |
| GET `/api/v1/introductions/{obligation_ref}/finalizations/{finalization_id}` | `introduction_finalization_read` / buyer / finalization_resource | Request-bound outcome for that exact intent; no jobs |
| POST `/api/v1/introductions/{obligation_ref}/finalizations/{finalization_id}/cancel` | `introduction_finalization_cancel` / buyer / finalization_resource | Strict `{schema_version: 2, obligation_ref, finalization_id, consent: "fence-unresolved-finalization.v1"}`; returns authoritative outcome, never undoes capture |
| GET `/api/v1/introductions/{obligation_ref}/delivery` | `introduction_delivery_read` / accepted party / obligation_ref | Only the requesting recipient's intent/status; no other route/contact and no jobs |

No query parameters are admitted. Marketplace envelope v2 signs protocol,
role/principal, method, operation, resource, request ID, timestamp and canonical
body hash; it does **not** sign the HTTP path. Define `finalization_resource` as
exact ASCII `introduction-finalization:{obligation_ref}:{finalization_id}` with
the canonical identifiers below. Finalization-status GET and cancel POST use
this resource, not obligation_ref alone. The server reconstructs it from the
validated path and requires exact signed-resource equality; response signing and
verification use that same resource. Review/start use obligation_ref because
the signed POST body binds the UUID. Reveal/delivery use obligation_ref and their
distinct operations. No envelope-version change or identity-core path retrofit.
GET has no body (existing empty-body hash); POST signs exact JSON, and path/body
IDs must agree. Malformed/noncanonical paths fail without echoing their values.
Response verification binds the request fields, seller trust and HTTP status.
Use fresh transport request IDs for fresh status reads, not cached replay reads.

All new objects forbid unknown fields and coercion. UUIDs are lowercase canonical
hyphenated UUIDv4, timestamps are nonnegative integer Unix seconds, and
`negotiation_id` is 1–128 ASCII letters/digits/underscore/hyphen. Tokens are
unpadded base64url of 32 random bytes (43 characters); snapshot revisions are
lowercase 64-hex keyed fingerprints. Contact/public context shapes retain their
existing accepted-package types; do not accept arbitrary replacement context.

Review input (strict): `schema_version: 2`, `negotiation_id: nonempty string`,
`obligation_ref: 64 lowercase hex`, `finalization_id: UUID`, `contact_payload`,
`delivery_route`. The buyer creates the finalization ID before review and reuses
it for finalization/reconciliation. Review validates accepted policy and both
profiles/routes without materializing either contact for the obligation or
creating delivery jobs. A review must not dispatch or advance settlement.

Review response (strict): `schema_version: 2`, `obligation_ref`, `finalization_id`,
`review_token: opaque string`, `expires_at: Unix seconds`,
`seller_snapshot_revision: opaque string`, `delivery_policy` and `introduction`
(the exact accepted public package). Buyer shows its own submitted contact/route
alongside this context. Response contains NO seller raw contact, seller route,
or unsalted contact hash. Tokens must be unpredictable (at least 256 random bits)
and authenticated by the server's private review record, bound to request intent,
party, agreement, policy, buyer input and seller resolved configuration.
Persist a per-review cryptographically random 32-byte salt and HMAC-SHA256
fingerprints, using that salt as the HMAC key over JCS binding objects, not raw buyer/seller contact or routes.
The buyer binding object has exact keys `kind: "buyer-review.v1"`,
`negotiation_id`, `obligation_ref`, `finalization_id`, `buyer_principal`,
`seller_principal`, `delivery_policy`, `introduction`, `contact_payload`,
`delivery_route`, `expires_at`. Principals use their existing canonical JSON.
The seller binding object is `{kind: "seller-review.v1", contact_payload,
delivery_route}` resolved from operator settings. Domain-separate with these
literal kinds. The returned seller_snapshot_revision is this seller HMAC. The
seller fingerprint binds both contact and route; compare it in the capture
transaction against the resolved seller snapshot. Persist a token digest, not
the raw token in the review table. These are confidential pseudonymous metadata,
not categorically non-PII. Never place them in listing/index/log material. TTL is
300 seconds, capped at accepted obligation expiry; at equality it is expired.
Persisted reviews survive restart. If a binding cannot be restored, serialize
`rejected/review_invalid` before serving; never discard its identity as unknown.

Version-2 finalize input (strict): all review input fields plus `review_token` and
`consent: "exchange-contacts-and-deliver.v1"`. Signing a request does not prove a
human clicked: the buyer application owns that authority check. Server checks
all bindings and expiry, and atomically compares seller resolved configuration
against the review before capture. No malformed/missing route, profile, policy,
consent or token can leave contact rows or delivery intents. Drift requires a new
review, not a silent substitution. Different input under the same ID conflicts.

Success returns the existing counterparty-only reveal with
`finalization: {schema_version: 2, finalization_id, status: "committed"}`. The
legacy reveal shape is unchanged for legacy work. Registered unstarted GET
continues signed HTTP409 `introduction has not been started`; older unregistered
opaque references remain 404 without scans. New finalization errors use a strict
`detail: {code: string}` with bounded codes: `delivery_policy_required`,
`delivery_configuration_unavailable`, `review_invalid`, `review_expired`,
`review_changed`, `finalization_conflict`, `finalization_cancelled`. Use 409 for state/consent conflict,
422 for malformed carrier and 503 for temporary service unavailability. No raw
validation/provider messages or offending values escape. Unauthorized/unknown
behavior remains privacy-preserving; no privileged pending semantics for outsiders.

Finalization read: `{schema_version: 2, obligation_ref, finalization_id, status}`
where status is `reviewed`, `committed`, `rejected`, `expired`, `cancelled` or `unknown`;
`rejected` additionally carries a bounded `code`. No contact/route/token. A
`committed` result is recovered through the ordinary introduction GET at the
path above (no extra response field). `unknown`
or `reviewed` is NOT evidence that an in-flight call cannot still commit.
Terminal rejection/expiry must serialize with finalize, so an authoritative
terminal read cannot race with a later successful commit for the same intent.
An expired review authorizes no new submission. A changed seller after review
can reject; a completed exchange is always served from the frozen record.
Successful review/finalize/status/cancel/delivery responses use HTTP200. A
rejected outcome carries only a code from the bounded error set above; other
outcomes omit `code`. Unknown means an authorized new-policy obligation has no
record for that ID, not permission for fresh consent. It is HTTP200, not a
privileged 404. The existing unknown-obligation/unauthorized behavior is unchanged.

Delivery read: `{schema_version: 1, obligation_ref, recipient_role, status,
intent_id, attempts, next_attempt_at, failure_code}`; nullable scheduling/failure
fields contain no provider text. Status is `not_requested` for legacy/pending
work, otherwise one of the states below. No route address is needed in this
projection. A seller cannot query buyer delivery by supplying `role=buyer`.
All listed fields are required: `recipient_role` is buyer or seller; `intent_id`
is UUIDv4 or null only for `not_requested`; `attempts` is an integer 0–3 (zero
for `not_requested`); `next_attempt_at` is integer Unix seconds only in
`retry_wait`, otherwise null. `failure_code` is null except failed/retry/review
outcomes, where it is one of `tls_required`, `tls_verification_failed`,
`authentication_rejected`, `recipient_rejected`, `message_rejected`,
`transport_unavailable`, `provider_temporary`, `acceptance_unknown`,
`attempt_abandoned`, `configuration_unavailable`. No provider text is returned.

## Local consent and durable state

Buyer application: short transaction validates exact account contact/route
revisions and displayed review, verifies human consent, and freezes a durable
request-bound intent. Send outside the transaction. No database lock is held
across HTTP. Edits committed before this boundary require new consent; later
edits affect future confirmations, not the frozen in-flight request or messages.
Do not permit a second conflicting consent while the first outcome is unknown.
After lost HTTP ACK, read that exact finalization identity and the authoritative
reveal; never blindly create a new finalization or mail send. A definitively
rejected/expired/cancelled intent permits fresh preview and human confirmation.

### Finalization fencing and restart liveness

Use one durable row per `(obligation_ref, finalization_id)` with the accepted
buyer binding, reviewed expiry/binding metadata or a terminal tombstone. Review
creation, finalize/capture, rejection, expiry and cancellation serialize through
the same SQLite write transaction (`BEGIN IMMEDIATE` or equivalent existing
transaction seam); never validate a mutable binding outside this transaction
and later insert on trust. One committed finalization per obligation is unique.
Reviewing a tombstoned ID fails, as does changed input under an existing ID.
An exact HTTP-envelope replay may use its existing recorded review response; a
fresh review request for an already reviewed ID returns `review_invalid`, never
issues a replacement token or extends expiry. A lost review response therefore
uses authoritative expiry or explicit cancel before a new ID, not token guessing.
No transition leaves committed/rejected/expired/cancelled. An exact committed
retry returns the frozen outcome, never creates jobs; a different finalization
for an already captured obligation conflicts and cannot deliver again.

The contact recovery loop sweeps reviewed expiries at startup before serving and
at most every 5 seconds while running. Finalize itself checks the deadline under
the same transaction and writes expired if it loses that race. Binding drift or
invalidated review writes rejected under the same fence. A malformed or
unauthorized request cannot terminate someone else's intent. GET only observes
committed state; it never performs expiry, capture, completion or dispatch. This
is bounded recovery while the service/database are available, not an availability
promise during outage.

Cancellation is only for a buyer application's unresolved intent when status is
unknown/reviewed and a prior review/finalize HTTP call may still arrive, or the
user wants to abandon that uncommitted consent. Require a separate human control
explaining that this fences the attempt, not the accepted deal. Its signed POST
creates a cancelled tombstone even when the ID is not registered yet, after
accepted-buyer/policy authorization. A late review and a late finalize both
honor it. If that intent already committed, return committed instead; if another
intent captured the obligation, return `finalization_conflict` and require the
ordinary authoritative reveal rather than claiming cancellation of the exchange.
Existing rejected/expired/cancelled returns identically. A lost cancel ACK uses
fresh signed status GET, then an idempotent same-ID cancel if still unresolved
under that human authorization. No automatic new ID, blind finalize resend or
SMTP action follows. Persist the BFF's cancellation authorization as metadata so
recomposition cannot switch back from cancel to finalize. Normal reviewed expiry
needs no cancel: use the sweeper and authoritative read. No second conflicting
consent until one durable terminal outcome is known.

Storefront: one local transaction persists immutable exchange, finalization
identity and exactly two intents keyed uniquely by `(obligation_ref,
recipient_role, policy kind)`. Each intent references the frozen exchange and
stores only its own route snapshot. Buyer intent renders seller contact; seller
intent renders buyer contact; neither includes the counterparty's route. Sender
configuration and credential references stay operator-local and are not per-party
wire input. The worker sends only after existing materialize/check/collect
completion has converged; a durable `awaiting_completion` state bridges failure
between capture and completion. Recovery operates on these explicit new intents,
not a scan of old introductions. Provider failure never rolls back disclosure.

States: `awaiting_completion → pending → sending → accepted | retry_wait |
failed | needs_review`; `retry_wait → sending` is bounded. Unique claims and
compare-and-swap prevent concurrent worker ownership. Persist attempt identity
before the provider call; an abandoned/expired `sending` claim becomes
`needs_review`, not automatic resend, because the provider may have accepted it.
An acknowledged SMTP acceptance is `accepted`, NOT inbox delivery. A lost ACK
also becomes `needs_review`. Automatic budget: 3 total attempts,
60 then 300 seconds after each proven nonaccepted transient outcome; each
network operation is capped at 10 seconds. A complete attempt has a hard
120-second monotonic deadline including name resolution, connect, TLS, auth,
MAIL/RCPT/DATA and cleanup. Claim expiry is 150 seconds after durable claim,
never extended by another worker; a 5-second recovery pass may stop it only
after that bound. All provider operations share the deadline and abort/close
the socket at it; no unbounded DNS or abandoned sending thread qualifies. Check
ownership/deadline before initiating DATA, with no second sender for a stopped
claim. The extra 30 seconds is persistence/cleanup margin, not permission to
continue network work. A scheduler/process pause beyond the deadline cannot
authorize new DATA. Expired claims stop at needs_review, never transfer send
ownership. Wall-clock anomalies cannot enable another send of an ambiguous
claim; monotonic attempt deadlines bound an active worker.
Only demonstrably non-accepted transient failures retry; permanent failures stop.
After a positive final DATA acknowledgement, record accepted even if QUIT or
socket cleanup fails. Failure before recording that acknowledgement durably can
still leave needs_review on crash; no exactly-once guarantee follows. No automatic
retry for ambiguous DATA acceptance or partially known outcomes.
No manual resend/route-edit endpoint in this increment: `needs_review` honestly
stops; later explicit resend requires its own consent and ambiguity decision.

### Retention of new copies

The buyer application clears its frozen contact/route/token on authoritative
committed/rejected/expired/cancelled reconciliation in the same local transaction
that records terminal status. It retains only account/deal/finalization identity,
status, bounded code, consent/cancel authorization marker and necessary timing;
never seller contact or route. While unresolved it retains its own frozen request
for recovery; unavailable service means no false terminal cleanup claim.

SCM clears each intent's route snapshot atomically at accepted/failed/needs_review.
Only awaiting_completion/pending/sending/retry_wait retains an executable route.
Keep opaque intent/attempt/message IDs, bounded codes and timing, with no rendered
mail body or contact copy in attempts. Review salts, fingerprints and token digest
are cleared on terminal rejection/expiry/cancellation. For committed identities,
retain only the private binding fingerprint/salt needed to refuse changed same-ID
retries, not raw route; clear the consumed token digest. Tombstone identifiers
persist so late writers cannot recreate an expired/cancelled intent. Existing
identity replay storage may retain responses; no shared replay clearing is added.
These column deletions do not erase authoritative exchange contacts, replay
copies, storage backups or recipient-owned delivered mail. Wider retention and
deletion remain #197/#203. No resend endpoint may reconstruct erased routes from
current settings; future resend requires its own consent/ambiguity design.

## SMTP, configuration and publication

Reuse the existing delivery package's SMTP boundary and event rendering; do not
extend daemon-thread best-effort dispatch into a claimed durable queue. Require
`ssl.create_default_context()` with certificate/hostname verification, STARTTLS
before auth/DATA, finite timeout, no plaintext fallback. No STARTTLS, untrusted
certificate or hostname mismatch fails closed. One recipient per message/SMTP
transaction; no shared To/CC/BCC list. Ignore no `send_message` refusal result.
Use stable message identity for diagnostics, never an exactly-once claim.

Runtime config in existing `BARE_METAL_STOREFRONT_DELIVERY`:
strict `{schema_version: 2, mode: "two-sided-contact", seller_route,
smtp: {host, port, sender, username, password, timeout_seconds}}`.
All fields required; `seller_route` uses the strict route type above. `host` is
a DNS hostname of at most 253 ASCII characters with 1–63 character labels and
alphanumeric label ends (no URL, whitespace, literal address or trailing dot);
`port` is integer 1–65535; `sender` uses the same mailbox grammar; username and
password are nonempty strings of at most 1024 characters, without NUL/CR/LF;
`timeout_seconds` is integer 10. Authentication is required in this new mode.
No STARTTLS-off switch is admitted. Legacy config stays a separate parser. No arbitrary
recipient list or per-deal provider selector. New-mode validation is separate
from legacy local plugin config, which is not silently upgraded. SMTP credential
material is private; no schema/config exception may include it. Public chart `deliveryConfigSecret: null | {name, key}` projects this env solely
through `secretKeyRef`; null preserves byte/semantic baseline. Require nonempty
Kubernetes-valid Secret name/key and reject extra fields; only the main runtime
container receives this env, not a migration or health hook. No extraEnv escape
hatch, plaintext values or generated credential ConfigMap.

Retain old file schema/example/no-outbound profiles unchanged. Version 2 is a
strict public file `{schema_version: 2, delivery_policy: <exact policy above>,
offers: [<ContactOffer>, ...]}`. `ContactOffer` keeps the version-1 required field
set/types/bounds: listing_id, name, machine_id, physical_host_id, profile,
gpu_model, gpu_count, region, vcpu_count, ram_gb, disk_gb; no extra fields. Keep
1–5 offers, unique IDs, 128-KiB maximum, synthetic notice and no-access/supply
constraints. Version-2 listing IDs additionally require the prefix
`synthetic-contact-delivery-` followed by nonempty lowercase letters/digits/hyphens,
at most 128 total. Every referenced configured profile must have the exact policy,
matching the root policy; no missing/null policy or mixed pull-only file. Private
contact and seller route/credentials remain exclusively resolved config.

First use of a version-2 ID requires absent local ID; subsequent reconciliation
is permitted only for the identical version-2 immutable local publication intent.
Store version 2 in that new local intent, never retrofit it to an old envelope.
Reject any old-ID collision, preserve v1 option hashes and its callback-absent
requirement, and leave the packaged five-offer v1 example byte-identical. Version
2 requires the new valid runtime composition, never legacy plugin delivery.
Validate the whole file, all profiles, contacts, private routes, credential syntax,
policy and resolved delivery config before constructing an outbound client;
validate signed registry schema and every existing-ID conflict before any local
intent or registry POST. Preflight is structural, not a real SMTP login/send.
Retain the existing bounded publication retry/immutable intent behavior for the
new IDs; no actual publication is part of local qualification. A global mail
configuration cannot authorize retained IDs or old agreements. Public privacy checks recurse through decoded JSON keys/values,
including escaped/non-ASCII/control canaries; diagnostics must not echo an
unsafe listing ID or private value. Guards remain literal detection, not general
DLP. No actual publication is part of local qualification.

## Required tests and outstanding gate

1. Shared Python/TS vectors for full public policy hashes, exact signed routes,
   version rejection, privacy-safe errors and old option identity stability.
2. Real typed HTTP + real disposable SQLite: accept/pending/review/finalize/read,
   zero capture/jobs before finalization, stranger/seller mutation refusal,
   drift/expiry/conflict, lost HTTP ACK, completion failure, concurrent starts,
   restart and immutable per-recipient payload/route parity.
3. Worker with fake SMTP boundary: unique claims, pre-send crash, lost DATA ACK,
   restart, bounded retries, partial-recipient independence, TLS refusals and
   no plaintext/auth before verified TLS. No real provider/inbox action.
4. Buyer application disposable database + mounted UI: separate settings,
   no default sharing/enrollment, exact preview, initially disabled consent,
   local snapshot races, unknown-outcome recovery, human-only POST and allowed
   already-shared delegate GET/no-store; link-only notification privacy.
5. Old accepted-but-unstarted/revealed fixtures and no-outbound file publication
   never acquire jobs under activation/restart/manual-redelivery attempts.
   Whole-file privacy/config failure makes zero remote POSTs.
6. Internal installed wheels, package boundaries/type checks, baseline/opt-in
   chart renders, and a loopback cross-language journey. These are not release,
   live authentication, cloud, browser-routing or inbox evidence.

7. Fencing races: finalize versus expiry/cancel, cancel before late review, lost
   cancel ACK and restart, unknown never unlocks conflicting consent; positive
   DATA ACK followed by QUIT failure remains accepted; paused/deadline-overrun
   workers cannot initiate new DATA or cause a resend. Assert terminal route and
   local consent-copy cleanup without claiming exchange/replay/mail erasure.

8. Python/TS request/response/replay vectors must reject cross-UUID,
   cross-obligation and GET-versus-cancel substitution; malformed/noncanonical
   paths reject privately. No test may assume the HTTP path itself is signed.

This exact candidate and proposed normative deltas require final approval before
implementation. Broader retention/deletion (#197/#203), connectors, alternative
email verification, production release/activation and future resend remain out
of scope, not implementer choices. Demonstrated incompatibility with the existing
identity, transaction or package seam requires a new decision, not a fallback.
