# Tasks

- [x] Update `core/storefront/src/core_storefront/domain_registry.py`,
  `sqlite_client.py`, and `sqlite_migrations.py` for validated unbacked provenance,
  versioned migration, and immutable nullable listing/thread bindings. Add focused
  core persistence tests proving preservation, refusal, rollback, and rerun.
- [x] Update bare-metal storefront `settlement_composition.py`, `runtime.py`,
  `negotiation_service.py`, and `sqlite_client.py` for composition-derived
  capabilities, site-free startup/health, and contact-only unbacked admission.
- [x] Exercise actual environment startup with synthetic Ed25519 identities,
  signed negotiation/start/read, party refusal, no acceptance-time reveal,
  restart persistence, and no external authority/sink construction. Preserve
  existing physical constructor and persistence coverage.
- [x] Build internal wheels with existing tooling; install through `.dist` and
  public PyPI. Run focused core and bare-metal tests and wheel entry-point checks.
- [x] Correct core buyer amountless input and bare-metal introduction CLI selected
  option forwarding; core/policy/buyer tests and typed HTTP evidence passed.
- [x] Add `contact_offers.py`, packaged five-offer JSON example, SQLite immutable
  publication intent, and CLI/server startup wiring. Validate signed schema and
  bounded upsert reconciliation; refuse changed IDs and inactive local offers.
- [x] Add chart optional offer ConfigMap/registry trust and API-key Secret inputs,
  nullable site Secret, and render tests; preserve physical defaults and PVC rules.
- [x] Add loader/registry integration covering Ed25519/key gate, flat filters,
  lost ACK/restart, intent-before-POST, leak refusal and accepted-context stability.
- [x] Run updated seller (140 passed), independent-process registry integration,
  installed-wheel startup/CLI, focused typing, chart and comment checks. Shared
  core/buyer evidence remains the separately checked first-stage wheel set.
  OCI build execution is unavailable locally; the non-pushing CI gate is added,
  not claimed run.
- [x] Promote reviewed binding and atomic-bookkeeping behavior to
  `market-composition`, absent-money negotiation to `buyer-orchestration`, file
  publication to `storefront-publication`, and introduction lifecycle/privacy to
  `contact-exchange-settlement`, with architecture companions. Update repository
  architecture, actual environment inputs, Goal 6, and capability/campaign indexes.
  Destinations are in the design-promotion record; image/live qualification stays open.

## Accepted pending reads

- [x] Extract transaction-scoped existing obligation upsert in settlement SQLite;
  add a local synchronous callback to core accepted-plan commit and register
  contact bookkeeping atomically from bare-metal acceptance. No lifecycle calls.
- [x] Qualify real signed authorized pending409, restart before start, explicit
  consent/reveal, refusal/signature/context negatives and transaction rollback.
- [x] Check installed dependency/seller wheels in an independent test environment;
  old unregistered accepts remain HTTP 404, with no scan/backfill or repair command.
- [x] Run checks: final installed seller 142 passed (including 14 focused
  contact-only tests), settlement runtime 91 passed, core storefront 153 passed
  with two skips, focused mypy and comment/diff checks passed.
- [x] Promote reviewed pending-read semantics to contact exchange and the atomic
  persistence contract to market composition; retain old-reference limitations.

## Literal configured-contact protection

- [x] Share one decoded-string traversal from contact-kit `settlement_config.py`
  across profile, option, accepted-obligation and loader checks. Protect literal
  configured values before immutable intent/publication; retain key-only/generic
  diagnostics and avoid general data-loss prevention.
- [x] Add full-file Unicode, quote, slash, backslash and newline regressions in
  `test_contact_publication.py`, including the last entry; prove no local
  listings/bindings or remote calls on rejection. Add contact-kit regressions for
  profiles, nested public option resources and accepted public terms/context.
- [x] Run installed seller (152 passed) and contact-kit (72 passed) checks with
  source-path injection disabled, wheel/source equality and hygiene. Freeze the
  matching contact-kit/seller replacement with unchanged core-storefront and
  settlement-runtime dependencies.
- [x] Promote reviewed literal protection and limits to the contact-exchange
  specification/architecture; preserve the existing campaign scope.

## Documentation and qualification closeout

- [ ] Independently review the permanent documentation delta against current
  source and its semantic evidence references.
- [ ] Verify installed-image dependency provenance and execute the image gate
  against reviewed release inputs. Local wheels are not a published release or
  verified runtime image.
- [ ] Qualify live publication and the accepted/pending/start/party-read lifecycle
  under separately authorized deployment inputs. No deployment or activation is
  asserted by this change's local checks.
- [x] Documentation closeout: comment hygiene passes; source import/comment
  placement reviewed without edits. Owning docs, Markdown links/anchors, public
  references, completed-task history, Goal 6, indexes, and promotion record checked.
  Strict validation passes this change and all 22 permanent specs; 12 unrelated
  active changes still fail repository-wide strict validation. No behavior,
  packaging, image, or deployment suite is rerun for this documentation batch.
