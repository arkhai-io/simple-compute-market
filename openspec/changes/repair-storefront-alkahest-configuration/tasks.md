# Tasks — repair-storefront-alkahest-configuration

## Implementation status

**Implemented, unverified against the stack.** All three gaps are closed and
each fix is verified against the real packages at unit level. The e2e run that
confirms settlement becomes ready has not happened yet.

## 1. Supply the EVM credential

- [x] 1.1 Add `STOREFRONT_WALLET__PRIVATE_KEY` for `bob-storefront` and
      `alice-storefront` to `compose.local-identities.yml`, `@str`-marked.
      Anvil 2 for Bob and Anvil 4 for Alice, each derived and checked against
      the `Wallet.address` its own storefront config declares.
- [x] 1.2 Record at the call site why the name differs from the `AGENT_PRIV_KEY`
      the adjacent env files supply, so the next reader does not "fix" it back.

## 2. Make the address configuration reachable

- [x] 2.1 Bind-mount `alkahest_anvil_addresses.json` to
      `/app/alkahest_anvil_addresses.json` for both VM storefronts in
      `domains/vms/compose.yml`, matching the API-credits convention.
- [x] 2.2 Point `Settlement.alkahest.address_config_path` at the mount in
      `storefront.bob.toml` and `storefront.alice.toml`.
- [x] 2.3 Add `Chains.anvil.alkahest_address_config_path`, which client
      construction reads separately from the readiness preflight, and note
      that the two reads are independent.

## 3. Validation

- [x] 3.1 `build_alkahest_clients` reproduces the production symptom with no
      credential and proceeds past address-config resolution with one, failing
      only on DNS for the compose-internal RPC host.
- [x] 3.2 `alkahest_preflight` carries `alkahest.address_config_invalid` for
      the current path and not for the mounted one.
- [ ] 3.3 `make -C e2e-tests test-e2e`: confirm `checks.alkahest` reports
      `anvil`, that no `[SETTLEMENT] option suppressed` line names
      `alkahest.v1`, and that the seven listing-create refusals are gone.
      Compare failure *causes*, not counts — the escrow phases have never run,
      so new failures downstream of a now-publishing listing are the expected
      result and are findings for classification, not regressions.
- [ ] 3.4 `make test` stays green. No production Python changed, so nothing is
      expected here; run it rather than assume.

## 3r. The Alice stages, handed over

- [x] 3r.1 **Declared, not deleted.** `test_06b` and `test_06c` skip with the
      reason at the call site: provisioning's storefront principal is a single
      identity, so Alice is never a trusted caller and never loads capacity.

      Only these two. The scenario's subject -- registry isolation, Alice's
      absence from registry-B, fan-in across two storefronts, resilience to a
      dead registry -- does not touch provisioning and keeps running. `00g`
      reads system status and `02b` imports a storefront-local CSV, so both are
      expected to pass; neither has been *observed* passing, because the whole
      scenario was skipped until this week, so the successor change widens the
      skip set on evidence rather than on my expectation.

- [x] 3r.2 **Not a regression, and worth being precise about why.** The Aug 15
      green run skipped every Alice stage, and the skip was incidental:
      `ALICE.*` was absent from configuration and `_require_setting` skips on an
      empty value. This change configured Alice while repairing the identity
      plumbing, which turned silent absences into real runs. The auth work made
      a pre-existing limitation visible; it did not cause it.

      The configuration stays. Reverting it would restore the silence that let
      this scenario go unexercised for months.

- [x] 3r.3 Handed to `repair-multi-storefront-scenario`, which owns letting
      provisioning trust more than one storefront principal. ROADMAP Goal 1's
      open-gap table names the gap and that change as its owner -- the goal
      already argues that consolidating physical authority is what makes a
      storefront replaceable by another front-end over the same hardware, so
      the fact that it cannot yet serve two belongs in its current state rather
      than only in a skip string.

## 3t. Prior-head run: 11 failed, 75 passed, 28 skipped

From 10/72/32. Four fewer skips and three more passes; the claims-name fix is
not in this head.

- [x] 3t.1 **The pause could never be observed: loop intervals were lost.**
      Four failures reported loops `pausing` -- mid-cycle when the bounded wait
      expired. `storefront.bob.toml` and `storefront.alice.toml` used to carry
      `negotiation_watchdog_interval`, `claims_sweep_interval` and
      `fulfillment_resume_sweep_interval` at 2 seconds, with a comment saying
      exactly why: a pause is observed only when a loop next reaches its gate,
      and the shipped defaults (60s watchdog, 30s sweeps) exceed the pause's
      own 5s wait, so every loop reports `pausing` forever. All three settings
      were gone from both files; `poll_interval = 1` survived.

      Restored with that reasoning. This is the same class as every other
      config loss this session, and it is why the restored pause stages could
      not pass however correct the gate was.

- [x] 3t.2 **A malformed log call, not a product defect.**
      `TypeError: not enough arguments for format string` in
      `test_full_deal_buyer_cli.py`: three placeholders, two arguments -- a
      stray `listing_resource=%s` the equivalent call in `test_full_deal.py`
      does not have. Swept every e2e module for lazy-log
      placeholder/argument mismatches; this was the only one, and it is now
      zero.

- [ ] 3t.3 **`500` on admin reservations, located.** The generic
      `"Storefront administrator request failed"` is the admin middleware
      wrapping a downstream error -- it does log the cause, and the traceback
      runs through `service_peer_auth.py:312`, the line after that
      middleware's claim test. `POST /api/v1/admin/portfolio/reservations` is
      not a callback and not the status read, so the middleware should pass it
      straight through; it is failing inside the branch that decides. Reading
      the body is the first thing past that point, and the outer frames show an
      `EndOfStream` on the request stream, which suggests the body is being
      consumed twice on this path. Needs the full frame list to confirm.

- [ ] 3t.4 **`409` on settle: "accepted provision terms have no SSH public
      key".** The scenario passes `ssh_public_key` to `settle`, but the key has
      to be in the *accepted* provision terms, which come from the negotiation.
      So `negotiate_new`'s `provision_terms` is missing it -- payload drift on
      the same axis as `capacity_source` and `offering_mode`.

- [ ] 3t.5 Unchanged: `market negotiate` exits 2, `market credits buy` exits 2,
      `market buy` exits 0 with no run-log.

## 3v. The admin reserve `500`, and what `resource_id` means for a pool

Run: **6 failed, 80 passed**. The gate-cadence fix cleared the four pause
failures.

- [x] 3v.1 **The `500` is `KeyError: 'resource_id'`** at
      `admin_controller.py:1254` in `reserve_capacity`. My earlier
      double-body-read hypothesis was wrong: the `EndOfStream` frames are
      starlette unwinding *after* an inner exception, and the three middleware
      frames are the chain the request passes through rather than where it
      fails. The loudest thing in the trace was the least informative.

- [x] 3v.2 **Discovery: what `resource_id` means per cardinality mode.**
      Settled from `openspec/specs/storefront-publication/spec.md`:

      | Mode | Candidate identity | `resource_id` |
      |---|---|---|
      | `specific_resource` | one per enabled member, each naming a physical resource; derivation key is resource-keyed | the node |
      | `fungible` | one pooled candidate, sized to what a single member can satisfy | absent -- pool-keyed |

      `resource-pool-management/spec.md` corroborates the optionality
      directly: every durable reference to a pool keys on
      `(site_id, pool_id[, resource_id])`. There is no `resource_id`-as-shape
      anywhere; a fungible candidate's shape is structural -- pool, slice size,
      and projected attributes. A named compute shape would come from ROADMAP
      Goal 2, whose dimensions Goal 1 records as not yet expressible, so it is
      a plausible future design rather than a current one.

      A fungible *reservation* is the separate question: the ledger does choose
      a member at reserve time, and records it as `member_id` plus a backing
      resource. So the likely contract answer is
      `ReserveCapacityResponse.resource_id: str | None` -- which is how the
      controller already treats `pool_id` two lines above, under the comment
      that pools are the aggregator's concept and not the ledger's.

- [x] 3v.3 **Root cause not settled statically, and the failure now says so.**
      Traced the payload through ledger, HTTP, site client and aggregator.
      Both ledger builders (`_match_payload`,
      `_reservation_payload_for_reserve`) always include `resource_id`, the
      transport is a passthrough `dict` that would carry a `None` rather than
      drop a key, and the only `exclude_none` in the path is on the *request*
      body. So a genuinely absent key is unexplained, and changing the response
      type on that basis would paper over a payload that should be complete.

      Extracted `require_reservation_fields`, which refuses such a payload with
      a `502` naming the missing field, the authority, and the keys the payload
      *did* carry. Absent and null stay distinct: a null `resource_id` is the
      authority saying there is no single backing resource, an absent key is
      the two sides disagreeing about shape, and collapsing them would turn the
      contract question into a silent empty string.

      Five tests against the extracted function -- not a copy of the guard,
      which is what my first draft did and is the antipattern this suite has
      already been caught by twice.

- [ ] 3v.4 The next run's failure text should name the actual shape and settle
      3v.2's contract question. Remaining: settle `409` for provision terms
      carrying no SSH key, and the three buyer-CLI exits.

## 4. Closeout

- [ ] 4.1 **Comment hygiene.** `make check-comment-hygiene`.
- [ ] 4.2 **Import placement.** No Python changed; record that disposition.
- [ ] 4.3 **Documentation compliance.** Confirm the no-permanent-change
      disposition still holds once the stack result is known.
- [ ] 4.4 **Narrative compression.** Reduce these notes to final state.
- [ ] 4.5 **Roadmap currency.** Expected to own nothing; record either way.
- [ ] 4.6 **Campaign index currency.** Move the alkahest item out of the
      campaign's unowned table into this change's row, and reconcile on
      archival.
- [ ] 4.7 **Promotion.** Complete the design-promotion record.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| *(none expected — configuration only; the conventions relied on are already demonstrated elsewhere in the repository)* | — |

## Deferred, carried out of this change

- [ ] 5.1 Converge compose configuration onto a single source shared with the
      tests, and reconcile it with the Helm charts, which express the same
      deployment more coherently. Accepted as follow-up during this change and
      deliberately not attempted here.
- [ ] 5.2 Stop the shared Dynaconf loader TOML-parsing environment values bound
      for string fields, so `0x`-prefixed credentials do not need `@str` per
      value. Second occurrence of the workaround; also carried as an inherited
      question from `provide-e2e-development-identities`.
- [ ] 5.3 Delete or rewrite `domains/vms/storefront/.env.{bob,alice}.docker`,
      which carry configuration for a layout that no longer exists, including a
      stale `ALKAHEST_ADDRESS_CONFIG_PATH`. Left in place because the compose
      files still reference them.
