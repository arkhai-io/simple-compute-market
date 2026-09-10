# Plan — implementation candidate, independent review pending

- [x] Inspect source, owning specs/architecture/testing/configuration guidance and
  scoped issue bodies/comments; record current vs intended behavior and alternatives.
- [x] Resolve every design Open question and approve the exact contract, including
  public export, before implementing any following task. Proposed filenames below
  are a scoped file plan, not authority to select an unresolved design.
- [x] In `kit/contact-exchange/src/market_contact_exchange/settlement_config.py`,
  add the approved public policy/config carriers, capability validation and exact
  option/accepted-context hashing; preserve absent-policy serialization.
- [x] In that package's `introduction_routes.py`, `migrations.py`, `__init__.py`
  and new `delivery_contract.py`, `delivery_routes.py` and `delivery_state.py`, add approved review/finalize/status carriers,
  private review binding, signed cancel/expiry fencing, transactional capture/intent persistence and old-policy
  refusal. Extend the existing schema-opaque
  `core/buyer/src/core_buyer/introductions.py` transport with signed operations;
  contact-kit carriers own policy validation, never core dispatch.
- [x] Update bare-metal storefront `api.py`, `introduction_routes.py`,
  `sqlite_client.py`, `runtime.py` and `delivery.py` for accepted-party callbacks,
  atomic commits, route contribution, startup/5-second recovery and sender wiring with hard attempt/claim bounds. Put
  contact-specific durable worker code in new contact-kit `delivery_runtime.py`,
  not a generic core callback or a separate notification service. Preserve old
  explicit local plugin composition and gate all redelivery paths by policy.
- [x] Update `kit/delivery/src/market_delivery/builtin/smtp_sink.py` and the
  narrow sink/event interfaces only where required for verified TLS, finite
  bounds, one recipient and accepted/nonaccepted/ambiguous outcomes. Do not use
  abandoned daemon-thread status as durable provider evidence.
- [x] After exact-contract approval, change bare-metal `contact_offers.py`
  for a separate opt-in version and whole-file preflight; leave v1 and
  `domains/bare_metal/storefront/examples/contact-offers.json` untouched.
- [x] Update `helm/charts/bare-metal-storefront/values.yaml`,
  `values.schema.json`, `templates/deployment.yaml` and owning chart tests for
  optional `deliveryConfigSecret`; absence preserves defaults, no plaintext value.
- [x] Extend contact-kit tests `test_settlement_config.py`,
  `test_accepted_obligation.py`, `test_introduction_routes.py`, `test_migrations.py`,
  `test_contact_value_protection.py` and new delivery contract/runtime tests;
  delivery-kit `test_builtin_sinks.py`; bare-metal tests
  `test_http_introductions.py`, `test_introduction_delivery.py`,
  `test_contact_only_runtime.py`, `test_contact_publication.py`. Use deterministic
  clocks/barriers and fake SMTP at the actual external boundary. Add shared
  sanitized vectors consumed by typed-client tests, not hand-maintained wire mocks.
- [x] Build internal wheels into an isolated external wheelhouse and explicitly
  reinstall changed packages with uv into isolated test environments; preserve
  active environments and normal Make reinit paths. No editable-sibling/source-path bypass.
  Run focused typing/package boundaries, typed HTTP SQLite restart/concurrency,
  privacy negatives, chart tests and loopback client integration. Use temporary
  isolated state and synthetic credentials only; disclose all unrun suites.
- [ ] Prove terminal route/consent-copy cleanup, late-review/finalize fencing,
  bounded expiry recovery and positive-DATA-ACK/QUIT-failure behavior against
  the proposed contact/delivery/publication normative deltas. Service route cleanup,
  fencing and SMTP behavior are tested; buyer-application consent-copy cleanup
  and independent cross-language execution remain consumer qualification.
- [ ] Independent code/contract review before permanent promotion. No release,
  real SMTP, publication or deployment task is authorized by this plan.

## Bounded remediation plan

- [x] In storefront `introduction_routes.py`, require successful runtime outcomes
  before returning from completion; document the unchanged callback contract in
  contact-kit `introduction_routes.py`. Leave generic settlement runtime untouched.
- [x] Extend storefront `tests/test_http_contact_delivery.py` with real durable
  lease contention and non-success results, success/failure/restart convergence,
  frozen retries and exactly two intents. Preserve legacy/plugin/pull-only tests.
- [x] In delivery-kit `tests/unit/test_smtp_attempt.py`, combine spawned positive
  DATA ACK with blocked QUIT and joined-child evidence using existing fake seams.
- [x] Build fresh candidate wheels and isolated environments, verify installed/source
  parity, run focused and affected contact/delivery/storefront/buyer regressions,
  and freeze full current patch plus original-candidate-to-fix delta and logs.
- [x] Remediation closeout: run comment hygiene and touched-import checks; verify
  source-state annotation and document placement, compress notes and preserve
  history. Roadmap/campaign status remains candidate/review-pending; no currency
  or permanent promotion is authorized while the full contract remains blocked.
  Retain the existing post-review promotion destinations below.

## Closeout (last task)

- [ ] Run `make check-comment-hygiene`; inspect changed comments/import placement
  (including TYPE_CHECKING) against actual dependency rules. Recheck doc ownership,
  preserve completed-task history, compress narrative, resolve cited paths/anchors,
  reconcile Goal 6 and active-change/capability indexes, and complete promotion
  below only after reviewed behavior exists. Exact-tree/message human review is
  required before any commit. No push or issue state transition is part of closeout.

## Design promotion record

| Material decision | Permanent destination | State |
|---|---|---|
| Explicit versioned policy, review/consent, old eligibility and protected projections | `openspec/specs/contact-exchange-settlement/spec.md` and `architecture.md` | Proposed; post-code-review |
| Durable two-recipient lifecycle, TLS and ambiguous acceptance | `openspec/specs/introduction-delivery/spec.md` and new `architecture.md` | Proposed; post-code-review |
| Versioned opt-in publication and immutable old IDs | `openspec/specs/storefront-publication/spec.md` and `architecture.md` | Candidate v2; post-code-review |
| Shared carrier/owner boundaries | `docs/development/ARCHITECTURE.md` | Proposed; post-code-review |
| Exact private config/optional Secret hook | `docs/development/DEPLOYMENT_AND_CONFIG.md` | Proposed; post-code-review |
| Goal 6 current state/gaps and sequencing | `docs/development/ROADMAP.md`, `openspec/changes/README.md`, `openspec/specs/README.md` | Index registration in docs stage; behavior currency after code review |

## Appended service qualification disposition

The service-side source and owning permanent contracts are reviewed/promoted.
`qualify-declared-contact-exchange` supplies the joined local installed-wheel
publication/exchange evidence and owns its own post-review archival closeout.
The original completed tasks above are preserved; unchecked consumer qualification
and broader closeout are not marked done by service-only evidence. No frozen
contract, original task history or activation boundary changes here.
