# Implementation Tasks

One implementation section, then closeout. Decisions are cited as `D<n>` from
`design.md`; requirements by the delta that states them (`buyer-orchestration`,
`api-family`). The end-to-end scenarios are run by validation, not on the
implementing machine.

**Dependencies.** `compose-api-family-kit`, whose buying library this changes.

## 1. The private store, the scrubbed run log, and retrieval

Touches `domains/api/buying/src/arkhai_api_buying/` (`credentials.py` new;
`stages.py`, `buy.py`, `common.py`, `commands.py`, `settle.py`,
`settlement_composition.py`), `domains/api/buying-alkahest/src/arkhai_api_buying_alkahest/stage.py`,
their tests, `domains/apicredits/buyer/tests/`, `e2e-tests/tests/e2e/roles/buyer_cli.py`,
both API-credit scenarios, and `docs/cookbooks/vllm-apicredits-seller.md`.

- [x] 1.1 Add `arkhai_api_buying.credentials`: the `CredentialStore` protocol,
      `FileCredentialStore` under `runs_dir().parent / "buy-credentials"`
      (`0700` directory, `0600` file, atomic write, symlink and run-ID refusal),
      `public_fields`, and `DeliveryRunLog` (D1, D2; `buyer-orchestration` "A
      buyer's private credential store"). Unit tests with a temporary
      `XDG_STATE_HOME`: modes, atomic replace, symlinked directory and file
      refused, unsafe run ID refused, nested `tenant_credentials` scrubbed.
      *Done.* `credentials.py` holds the store, `public_fields`, and
      `DeliveryRunLog`; the store directory is `buy-credentials` beside
      `buy-runs` (D1). Reads also refuse a symlinked directory and turn an
      unreadable record into a path-only `CredentialStoreError`.
      `domains/api/buying/tests/unit/test_credentials.py`: modes, a
      second save, a loose directory tightened, symlinked directory (write
      and read) and file refused, unsafe run IDs, missing record and foreign
      scheme, a failed `os.replace` keeping the old record and no temporary,
      unreadable records, nested scrubbing, and a real `RunLog` file free of
      the secret.
- [x] 1.2 Give `BuyerSettlementComposition` a `credential_store`; record
      delivery through one helper used by `SettlementResume.finish` and `buy`:
      `credentials_delivered` with `key_id`, `base_url`, `balance`,
      `delivery_ref`, or `credentials_unsaved` with the error class, panel, and
      exit 8 (D2, D4). Wrap `buy`'s and `SettlementResume.open_log`'s logs in
      `DeliveryRunLog`; print the Alkahest submit response through
      `public_fields`. Update `test_settle.py` and `test_settle_credentials.py`.
      *Done.* `record_delivery` and `end_run` in `credentials.py`; `finish`
      and `buy` use both. The run's end and `credentials_unsaved` tolerate a
      run-log write failure when the key went unsaved, so the panel still
      shows (D4). `negotiate` wraps its log too. `test_settle.py`: stored
      reference, unsaved key with exit 8, and a key reaching neither store
      nor log still shown once.
- [x] 1.3 Add `credentials show --from <run-id> [--json]` to the command group,
      with the legacy run-log fallback (D3, D5; `buyer-orchestration` "A buyer
      retrieves a delivered credential by run"). Application-integration tests
      in `domains/apicredits/buyer/tests/` through the plugin's app: stored
      key, `--json`, legacy run, no delivery.
      *Done.* `commands.py` `_credentials_app`. Plugin tests in
      `test_settle_credentials.py` through `arkhai_apicredits_buyer.cli.app`:
      stored key (panel and `--json`), legacy run left unchanged, no
      delivery, unknown run, a foreign-scheme reference, and a removed
      record — each refusal exits 1.
- [x] 1.4 Canary test: `credits settle --from` with the secret in the submit
      response, a poll body, and the terminal status; it appears only in the
      store and the panel, not in the run log, captured logging, or other output
      (D6). Failed-write test: a symlinked store directory gives
      `credentials_unsaved`, the panel, and exit 8.
      *Done.* `test_the_secret_reaches_only_the_store_and_the_panel` and
      `test_a_failed_private_write_shows_the_key_once_and_exits_8`. The fresh
      `buy` path is covered at unit level (`record_delivery`, `DeliveryRunLog`)
      rather than end to end through `run_buy`; its wiring is the same two
      calls. The submit, poll, and terminal bodies, which the proposal did not
      name, are in the canary; D2 records them.
- [x] 1.5 `BuyerCli.credentials`; migrate `e2e_credits_deal` and
      `e2e_credits_payment_deal` to it (D7). Add retrieval to the cookbook's
      buyer section.
      *Done.* Both scenarios still wait on `credentials_delivered` and read
      the key through `BuyerCli.credentials`; the payment re-drive reads the
      event's top-level `key_id`. Not run locally; validation runs them.
- [x] 1.6 Versions (design "Versions"), wheels, relocks of the buying
      libraries, `domains/apicredits/buyer`, `domains/apicredits/storefront`,
      and `e2e-tests`. Run `make test-api-buying`, `-alkahest`,
      `-arkhai-payments`, `make -C domains/apicredits test-buyer`,
      `make -C domains/apicredits/storefront test`; on a clean copy
      `make check-packaging`, `make check-comment-hygiene`,
      `make check-change CHANGE=keep-buyer-credentials-private`, and
      `make -k test`. One fresh-context compliance check of the diff.
      *Done.* `arkhai-api-buying` 0.2.0, `arkhai-api-buying-alkahest` 0.1.1,
      `arkhai-apicredits-buyer` 0.7.0, with floors on `arkhai-api-buying>=0.2.0`;
      six projects relocked. Suites: `test-api-buying` 40, `-alkahest` 12,
      `-arkhai-payments` 8, `test-buyer` 35, storefront 174, all passing. On
      a clean copy, `check-packaging` and `check-comment-hygiene` pass;
      `check-change` reports only the citations of
      `openspec/specs/api-family/spec.md` and `architecture.md`, the promotion
      destinations that exist once `compose-api-family-kit` archives.
      `make -k test` fails only where the tree is known to: the three IaC
      relay-teardown tests, the VM storefront's two Alkahest toolchain tests,
      and release tooling's GNU make `--eval` case. It ran before the
      compliance fixes, which the focused suites above cover. The
      fresh-context compliance check's fixes are in D1, D2, and D4; its
      Typer-locals finding is deferred (design "Deferred").

### Review round 1

The owner approved fixing the external review's findings. Each fix has a test
that fails on the section's commit `d5f855569`.

- [x] R1.1 **Secrets in error text.** `error_text` and `public_text` in
      `credentials.py`; `DeliveryRunLog` redacts strings and the secrets it
      has seen delivered; the payments stage, `payments.settle_negotiation`,
      the Alkahest resume's failure paths, and `buy` log and print through
      them (D2). `core_buyer` is unchanged. Tests:
      `test_error_text_never_quotes_a_seller_error_body`,
      `test_public_text_redacts_a_quoted_secret`,
      `test_the_delivery_run_log_redacts_secrets_inside_strings`, the
      payments library's
      `test_a_seller_error_body_never_reaches_the_settlement_events_or_reason`,
      and the plugin's
      `test_a_seller_error_carrying_the_secret_reaches_neither_log_nor_output`.
- [x] R1.2 **Check-then-use race.** A descriptor-relative walk, create,
      replace, and read; ancestors checked for ownership and others' writes;
      missing directories created `0700` (D1). Tests:
      `test_a_link_swapped_in_after_any_check_cannot_redirect_the_write`,
      `test_missing_directories_are_created_private`,
      `test_a_directory_others_can_write_is_refused`.
- [x] R1.3 **Orphaned credential.** `record_delivery` and `end_run` keep the
      panel and name the file when the run log refuses the append, exiting 9;
      `credentials show` finds the key by run ID (D4). Tests:
      `test_a_saved_key_whose_run_log_refuses_the_append_is_shown_with_its_location`,
      `test_credentials_show_finds_a_saved_key_its_run_log_never_recorded`.
- [x] R1.4 **Unsafe record permissions.** `load` refuses a file not owned by
      the user or open to group or others (D1). Test:
      `test_a_record_others_can_read_is_refused` (0644, 0640, 0604).
- [x] R1.5 **Versions and evidence.** `arkhai-api-buying-arkhai-payments`
      0.1.1, since it now imports `error_text`; the plugin's floor follows.
      The store and run-log probes (R1.2–R1.4) and the finish probe (R1.3)
      were run against `d5f855569`'s code and fail there; they pass now.
      Suites: buying 53, Alkahest 12, payments 9, plugin 37. The clean-copy
      checks and the fresh-context check are recorded in R1.6 and R1.7.
- [x] R1.6 **Fresh-context check of the fixes.** It found eleven items; ten
      are fixed and one is recorded:
      - an Alkahest status-poll error escaped uncaught with its body
        (`settle_status_failed`, exit 5;
        `test_a_status_poll_error_carrying_the_secret_reaches_neither_log_nor_output`);
      - `settle` printed the seller's reason unredacted
        (`test_a_seller_reason_is_printed_without_a_known_secret`);
      - a run log refusing a body that carries the key stopped the flow before
        the save (`DeliveryRunLog` best-effort for such bodies;
        `test_a_body_carrying_the_key_does_not_stop_the_flow_when_the_log_refuses_it`,
        `test_a_run_log_refusing_the_polled_body_still_saves_and_shows_the_key`);
      - walk errors other than refusals became tracebacks
        (`test_a_directory_that_cannot_be_opened_is_a_store_refusal`);
      - a failed directory `fsync` after the rename reported a saved key as
        unsaved (`test_a_failed_directory_sync_after_the_rename_still_counts_as_saved`);
      - interrupted saves left temporaries
        (`test_a_save_sweeps_temporaries_an_interrupted_save_left`);
      - a legacy copy won over a newer stored key
        (`test_credentials_show_prefers_the_stored_key_to_a_legacy_copy`);
      - `arkhai` was silently tightened, now refused when others can write
        (`test_a_group_writable_arkhai_directory_is_refused`);
      - this record's references and the plugin tests' blank lines.
      The text-redaction pattern's narrowness is recorded in D2 rather than
      widened: the body-carrying paths no longer depend on it.
- [x] R1.7 **Checks.** Suites: buying 59, Alkahest 12, payments 9, plugin 40,
      storefront 174, all passing. On a clean copy, `check-packaging` and
      `check-comment-hygiene` pass and `check-change` reports only the two
      promotion-destination citations, as before.

### Review round 2

The owner approved fixing the one remaining finding.

- [x] R2.1 **A torn delivery record hid a saved key.** A partial
      `credentials_delivered` line made `credentials show` refuse the run
      before its by-run-ID lookup. It now drops only a torn last record and
      validates the rest with core's own recovery resolution and `read_run`
      over a private copy (D4); `core_buyer` is unchanged. Tests:
      `test_credentials_show_recovers_a_key_whose_delivery_record_was_torn`
      (fails on `1541f5a3c`: exit 1, malformed run-log JSON),
      `test_credentials_show_still_refuses_a_torn_record_before_the_last`
      (the refusal it guards was already there; it fails on `1541f5a3c` only
      because it patches the new resolver), and the unit cases
      `test_only_a_torn_final_record_is_dropped` and
      `test_a_working_copy_never_holds_a_legacy_secret`.
- [x] R2.2 **Checks.** Suites: buying 64, Alkahest 12, payments 9, plugin 42,
      storefront 174. On a clean copy `check-packaging` and
      `check-comment-hygiene` pass; `check-change` reports only the two
      promotion-destination citations.

### Review round 3

The owner's review of round 2 found two defects in the torn-record fallback.

- [x] R3.1 **The migration lock was bypassable.** The fallback retried on any
      `RunLogError`, including `RunLogMigrationIncomplete`, and its working
      copy has no manifest. It now re-raises that error and checks
      `assert_migration_resolved` on the real directory before copying. Test:
      `test_credentials_show_honours_an_incomplete_migration_after_a_torn_append`
      (recovers the key on `fd1408b00`).
- [x] R3.2 **A completed malformed record was treated as torn.** Only an
      unterminated final fragment is dropped now. Test:
      `test_credentials_show_refuses_a_malformed_final_record_that_was_completed`
      (recovers on `fd1408b00`); the unit cases became
      `test_only_an_unterminated_final_fragment_is_dropped`.
- [x] R3.3 **Keeping a tear unterminated.** Narrowing the rule exposed that a
      later append (the run's end) completed the fragment into a malformed
      line, which the torn-record test showed. `DeliveryRunLog` now writes
      nothing after a failed append, dropping events once a key is seen and
      raising otherwise; a delivery after a failed append exits 9 (D4). Tests:
      `test_a_log_that_refused_an_append_writes_nothing_more`,
      `test_a_delivery_after_a_refused_append_is_reported_unrecorded`;
      `test_a_run_log_refusing_the_polled_body_still_saves_and_shows_the_key`
      now expects exit 9 and recovers the key through `credentials show`.
- [x] R3.4 **Checks.** Suites: buying 66, Alkahest 12, payments 9, plugin 44,
      storefront 174. The clean-copy checks are recorded in the PR's round-3
      section.

### Review round 4

- [x] R4.1 **Concurrent saves removed each other's temporary.** Each save
      swept every `.<run>.json.*.tmp`, including a live writer's, which then
      failed its rename and reported an unsaved key. Saves now hold an
      exclusive `flock` on the store directory from before the temporary is
      created until after the sweep (D1). Test:
      `test_concurrent_saves_of_one_run_never_remove_each_others_temporary`
      pauses one writer before its rename and runs the other; on `10abf23c8`
      the paused writer fails with `FileNotFoundError`, and now both succeed
      and one record remains.
- [x] R4.2 **Checks.** Suites: buying 67, Alkahest 12, payments 9, plugin 44,
      storefront 174. The clean-copy checks are recorded in the PR's round-4
      section.

## 2. Closeout

The eleven parts of `openspec/README.md#plan-closeout-requirements`, in order.
Closeout changes documentation only; a part needing a code edit returns the
change to implementation.

- [ ] 2.1 **Comment hygiene.** `make check-comment-hygiene` passes.
- [ ] 2.2 **Import placement.** The imports section 1 added are module-level,
      or their task note records why not.
- [ ] 2.3 **Documentation compliance.** Re-check D1–D7 against the placement
      rules and the record below.
- [ ] 2.4 **Narrative compression.** Shorten section 1's notes.
- [ ] 2.5 **Roadmap currency.** No roadmap goal names this gap; record that
      disposition.
- [ ] 2.6 **Campaign index currency.** Update this change's row in
      `openspec/changes/README.md`.
- [ ] 2.7 **Packaging.** `make check-packaging`, then
      `make check-architecture-change CHANGE=keep-buyer-credentials-private`
      (the change owns no exception row).
- [ ] 2.8 **End-to-end pipeline.** Record the run and that `e2e_credits_deal`
      and `e2e_credits_payment_deal` exercised retrieval.
- [ ] 2.9 **Promotion.** Write `openspec/specs/api-family/architecture.md`'s
      buyer-side note on the store and the scrubbed log (D1, D2); complete the
      record below.
- [ ] 2.10 **Documentation citations.** `make check-doc-citations
      CHANGE=keep-buyer-credentials-private`; then
      `openspec validate keep-buyer-credentials-private --strict`.
- [ ] 2.11 **Archival.** `openspec archive keep-buyer-credentials-private -y`,
      after `compose-api-family-kit`, whose `api-family` specification the
      delta extends.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| D1 — a private buyer credential store behind a scheme-naming interface; the file store's modes, atomic write, and refusals | `openspec/specs/buyer-orchestration/spec.md` ("A buyer's private credential store"); `openspec/specs/api-family/architecture.md` (the file store's location and injection point) |
| D2 — `credentials_delivered` without the secret; every recorded status body scrubbed | `openspec/specs/buyer-orchestration/spec.md` ("Buyer evidence is separate from private delivery"); `openspec/specs/api-family/spec.md` ("The buying library keeps a delivered credential private") |
| D3, D5 — retrieval by run, the legacy fallback, no rewrite | `openspec/specs/buyer-orchestration/spec.md` ("A buyer retrieves a delivered credential by run") |
| D4 — a failed write shows the key once, records `credentials_unsaved`, exits 8; a saved key the run log cannot record is shown with its path, exits 9, and is found by run ID | `openspec/specs/buyer-orchestration/spec.md` ("A failed private write does not lose a delivered credential") |
| D6 — the secret reaches only the panel | `openspec/specs/api-family/spec.md` ("The buying library keeps a delivered credential private") |
| D7 — scenarios retrieve through the command | Test code only (`e2e-tests/tests/e2e/roles/buyer_cli.py`) |
| Deferred — keyring store, legacy migration, `secret` in the core role's refused fields | `design.md` "Deferred" (no permanent home until a change takes them) |
