# Discuss and design

## Inspected current seams

Source baseline: `e01f383371e9d8827de04c0159674e4a3d7f7bc1`.

- `kit/contact-exchange/src/market_contact_exchange/introduction_routes.py`:
  strict `IntroductionStart` has negotiation ID, obligation reference and buyer
  contact only. Start loads/authenticates, persists contacts, completes, then
  invokes optional seller delivery. GET is party-scoped and side-effect-free.
- `kit/contact-exchange/src/market_contact_exchange/migrations.py` persists
  immutable buyer/seller contacts and introduction package. It has no delivery
  intent/claim table. Load-before-insert delivery detection is not an atomic
  claim: concurrent starts can both schedule, and a crash after persistence can
  lose scheduling. Completion failure can also strand delivery.
- `kit/contact-exchange/src/market_contact_exchange/settlement_config.py` owns
  public profiles and option/accepted-obligation construction. Optional policy
  can enter option params and their hash without teaching generic core a mechanism.
  Existing legacy option hashes must remain byte-identical. Current buyer
  compatibility alone checks mechanism/asset/rates; new-policy admission needs
  explicit support validation, never silent stripping.
- `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/` owns `api.py`,
  `introduction_routes.py`, `sqlite_client.py`, `delivery.py` and `runtime.py`.
  Accepted binding/party authority is here, not in the SMTP sink.
- `kit/delivery/src/market_delivery/events.py` builds full counterparty-contact
  events; `dispatch.py` abandons bounded daemon threads, not durable work.
  `builtin/smtp_sink.py` uses static recipients and `starttls()` without an
  explicit verifying SSL context. It permits disabling TLS. This is not safe
  enough for the new route and gives no exactly-once or inbox-delivery guarantee.
- `contact_offers.py` in the bare-metal storefront validates schema version 1
  and refuses a delivery callback. The packaged five-offer example remains
  unchanged; a global delivery flag cannot override signed no-outbound terms.
- `helm/charts/bare-metal-storefront/values.yaml` has settlement/identity Secret
  inputs but no delivery Secret hook. Consumers cannot invent private chart keys.

Current specs accurately describe process-local, self-addressed, optional
best-effort delivery. The new centralized two-recipient sender deliberately
changes the process boundary **only for explicit new policy**: self-addressed
means route chosen by its recipient, not an address harvested from contact data.
No permanent present-tense rewrite before implementation.

## Decisions for the candidate

See [contract.md](contract.md) for exact names and fields. Retain the existing
mechanism ID with an exact versioned accepted policy and strict review/start
carrier. Old client refusal is safe; old-client legacy start of an eligible deal
is refused before disclosure. Versioned policy must be content-addressed and
returned in accepted context, not a local Boolean or unsigned UI promise.

The storefront owns both durable recipient intents and SMTP. The client owns
its local consent intent and identity authority, and supplies only buyer-owned
configuration. Seller owner config supplies seller contact/route. A signed
buyer route assertion is not independent mailbox ownership verification.

Acceptance/preview persist no obligation contact. The human separately finalizes
contact sharing. The client freezes its own snapshot at local consent commit;
SCM atomically checks seller drift at its capture transaction. Later edits affect
future consent, not frozen in-flight work. No distributed transaction or database
lock across a network request. A stable finalization ID and signed outcome read
resolve HTTP uncertainty; ambiguous mail delivery never retries blindly.

New finalization requires both configured nonempty profiles and supported valid
routes before capture. Provider unavailability after capture cannot undo sharing.
GETs, ordinary notifications and agents never cause contact mutation or new jobs.
Personal details may include opaque keys other than email. Route supports email
only now; Slack/Telegram delivery and alternate-address verification are deferred.
No implicit sign-in-email contact, no implicit delivery enrollment.

Revisit these decisions only if required by demonstrated carrier ambiguity,
identity/atomicity constraints, or an explicit changed product requirement; not
because a legacy client or general plugin expects weaker behavior.

## Alternatives

- New mechanism `contact-exchange.v2`: clearer old-client incompatibility but
  conflates settlement semantics with optional delivery. Prefer exact accepted
  policy plus strict start gate; escalate if source cannot fail closed.
- Status-only/seller-only mail: rejected; does not deliver each counterparty's
  configured contact. Ordinary link-only notifications remain separate.
- BFF sends buyer mail, seller sends seller mail: rejected for this increment;
  two independent effect authorities complicate one finalized snapshot and ACK
  recovery. Hosted client does not run buyer CLI sinks today.
- Delivery inferred from contact entries or automatic sign-in enrollment:
  rejected; reachability, sharing selection and delivery permission are distinct.
- Rebuild contacts/routes at retry: rejected; silently changes confirmed disclosure.
- Unbounded queue or lease-expiry resend: rejected; duplicates or uncertainty after
  SMTP DATA cannot be erased by a local lease. `needs_review` is an honest stop.
- Generic event/callback framework or global notification rewrite: not justified
  by this bounded contact-owned lifecycle.

## Final candidate decisions and alternatives

The exact contract selects ASCII dot-atom/DNS mailboxes, TTL300, three bounded
SMTP attempts, persisted per-review random salt and private keyed fingerprints,
serialized expiry/cancel/capture fencing and terminal route cleanup. A new
operator fingerprint secret is unnecessary. Fingerprints remain pseudonymous
private metadata. GET cannot make an unknown attempt terminal; a narrow signed
human-authorized cancel fences late review/finalize when normal expiry cannot
resolve an unregistered intent. It never cancels the deal or undoes sharing.

Publication schema v2 is separate, with explicit root/profile policy and new
versioned intent/IDs; v1 and its five-offer example stay unchanged. Automatic
resend from needs_review and retaining routes for a hypothetical resend are
rejected: erase stopped routes, preserve honest uncertainty, and decide any
future resend separately. Positive DATA acknowledgement dominates QUIT failure.
A hard attempt deadline plus longer claim bound prevents reclaiming a live
bounded sender. These exact choices and proposed normative deltas are a final
review candidate, not present runtime behavior.

## Open questions

The exact-contract and source/issue export gate is approved. Independent code
review remains required before permanent promotion. Marketplace envelope v2
does not sign paths; the exact composite finalization resource binds nested IDs
for status/cancel without an identity-envelope change. Revisit only on a
demonstrated existing-seam conflict; broader #197/#203 policy, connectors,
alternative-address verification and live release/activation remain separately
owned, not prerequisites silently assigned to this increment.

## Historical design-stage validation and current source state

The source/issue-only inspection described here preceded implementation; its
unimplemented-contract statements are historical, not the candidate runtime map.
This worktree now implements the candidate service paths and has partial synthetic
installed-wheel qualification. Independent review found a completion-gating defect
corrected in this candidate below. It is not release-qualified or installed/live evidence;
the older installed release is unchanged. Scheduled client reconciliation remains
blocked and unimplemented, so the full contract remains blocked. Permanent promotion
is withheld. Tests/file ownership and post-review promotion are in [tasks.md](tasks.md).
Actual issue bodies/comments were read for #167/#184/#188/#191/#197/#203/#219;
clarification will append rather than rewrite/close/reopen them. The closed
inventory's findings remain dated evidence, not current release qualification.

## Implementation seam decisions under review

The role's legacy dispatch check uses the accepted negotiation's `our_listing_id`
and immutable local listing binding. Historical file-publication intents contain
only `offer` and `settlement_options`; they have no inner schema version. The
outer source envelope stays version 1 for both file versions. Recognized file
intent, malformed/conflicting provenance, and any positively present new policy
cannot dispatch through current legacy seller sinks. This also protects a first
sharing after reconfiguration, without changing the reveal or accepted record.
Unrelated explicit local compositions remain supported. Buyer-owned legacy copies
have no trusted file provenance on their wire; their existing policy-absent local
forwarding remains a compatibility limit, not platform delivery authorization.
New-policy buyer local forwarding is refused. No prose parsing or new wire claim
is used to infer consent.

Capture distinguishes a new exchange from an exact committed retry inside the
same write transaction. Only the new capture attempts inline completion. An exact
committed retry returns the frozen reveal without revalidating current settings,
calling completion, resetting intents, or sending. The existing settlement runtime
may refuse concurrent lifecycle ownership; recovery retains `awaiting_completion`
until a complete materialize/check/collect pass succeeds. Committed describes
contact capture, not lifecycle convergence or SMTP acceptance. No new lock or
shared lifecycle semantics are introduced.

The SMTP boundary uses a joined, killable subprocess because synchronous DNS is
not bounded by a socket timeout or by abandoning a sending thread. Its monotonic
deadline includes child startup, DNS, TLS, authentication, DATA and cleanup. An
alarm and supervising-process kill stop the sole network owner. The role supplies
a read-only attempt-ownership check before DATA. Positive DATA acknowledgement is
sent to the supervisor before cleanup; QUIT failure cannot change that result.
A separate recovery pass is not delayed by pending completion work. Attempts
retain only opaque identities, bounded outcomes and timestamps, not rendered mail
or recipient routes.

## Candidate validation and promotion preparation

Implementation adds contact-owned `delivery_contract.py`, `delivery_routes.py`,
`delivery_state.py` and `delivery_runtime.py`; the role retains connection and
transaction ownership. Delivery kit adds `builtin/smtp_attempt.py`; generic buyer
transport remains schema-opaque. Shared synthetic JCS/signature/option traces are
packaged in `market_contact_exchange/fixtures/delivery_vectors.json`.

Focused installed-wheel tests cover real signed HTTP and SQLite, independent
recipient messages at a fake SMTP boundary, restart, loss/ambiguity, completion
refusal, deterministic held-completion retries, expiry/cancel fences, Unicode and
privacy, old publication provenance, and a killed hung network-owner process.
The storefront suite also uses the real signed loopback registry with an optional
`REGISTRY_TEST_PYTHON` interpreter seam. No live provider/inbox, release, deployment,
or UI qualification follows from these tests.

Permanent promotion is still withheld for independent code review. The proposed
capability deltas provide normative promotion text; the ownership, provenance
compatibility limit, completion-owner distinction, subprocess deadline and terminal
copy cleanup rationale belong in the architecture destinations listed in tasks.
Repository-wide architecture/configuration and Goal 6/index currency changes are
prepared for that same post-review gate, not claims of current released behavior.

## Bounded completion-gating remediation

Review found that the role callback discarded nonthrowing settlement outcomes. A concurrent
collector can return `busy` while another lease owner is still collecting; neither
inline finalize nor recovery may then release the two awaiting intents.

Keep the existing `Awaitable[None]` callback signature and make its success contract
explicit: return only after materialize, check and collect each report `succeeded`;
raise on every other outcome. The runtime journals these results before returning.
This corrects the role-owned adapter for both dispatch gates without changing generic
settlement semantics, adding locks, or teaching the worker mechanism states. An
alternative Boolean/result carrier would unnecessarily break local compositions.
Exact committed retries still bypass completion and return the frozen reveal.

Extend the signed HTTP test with a barrier inside the real mechanism client's
collect call, after the runtime has reserved its durable lease. Run recovery while
held, verify the real competing reservation is busy and no mail attempt exists,
then exercise first-owner success and failure/restart. Also exercise real runtime
pending/manual/terminal results and earlier-operation leases. The existing SMTP
factory seam permits a spawned positive-DATA-ACK/blocked-QUIT regression without
adding a product API. Fresh wheel/source-parity and regression evidence stays
separate from original receipts. No commits, live effects, or promotion are part
of this remediation. Durable completion rationale remains destined for the contact
and delivery capability documents listed in the promotion record after review.

The candidate now enforces that callback contract. Synthetic regressions cover real
materialize/check/collect leases, pending/manual/terminal outcomes, durable retry and
restart, and spawned DATA acknowledgement surviving killed blocked cleanup. Affected
suites pass: 106 contact-kit, 53 delivery-kit, 167 storefront, 15 buyer and 9 chart
tests; focused cases overlap these totals. Five candidate wheels match 77 installed
source files. Default chart renders match HEAD using local Helm 3.15.3. Comment
hygiene and six-module kit typing pass. Expanded role typing retains two original
callback-parameter-name errors; touched-test lint retains three original findings.
No assertion, timeout or test was weakened to accommodate these baselines.

Validation retained an initial stale-wheel install/test run, corrected by exact
local-wheel reinstall, an invalid test-result fixture corrected to include its
required mechanism reference, and an unselected Helm shim failure corrected with
an explicitly selected already-installed version. These failed runs are not passing
candidate evidence. This remains a bounded source fix pending independent review;
the scheduled-reconciliation gap and post-review promotion gate are unchanged.

## Current bounded service evidence

Service behavior is source-reviewed and promoted in contact-exchange-settlement,
introduction-delivery and storefront-publication. The repository-owned
`domains/bare_metal/storefront/tests/test_declared_contact_qualification.py` joins
real local general publication and signed discovery to installed buyer/seller
exchange and fake recipient delivery. Shared Bun vectors prove scalar/canonical
parity, not a complete independent consumer implementation. Historical incomplete
consumer tasks remain incomplete; source qualification does not establish consent-
copy cleanup, scheduled client reconciliation, physical supply, release or activation.
No completed task or frozen carrier is replaced by this clarification.
