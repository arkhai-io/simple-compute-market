## 1. Bind the release that declares the capability

- [x] 1.1 Build the `0.4.0` client wheel from the producer's `.dist` and move the
      pin in `kit/hosted-settlement/pyproject.toml`, then `make
      fix-hosted-client-pin` to move both followers.
- [x] 1.2 Relock the affected projects against the built wheel and confirm the
      derived release coordinates follow with no Makefile edited.
- [x] 1.3 Evidence: `make check-hosted-client-pin` agrees, and the installed
      client exposes `ReclaimRequest.return_instructions_email`.

      The bump cascaded further than the pin: the storefronts resolve the
      settlement-runtime and hosted-settlement kits from built wheels, not from
      the source tree, so the route change could not even be executed until
      every package carrying a changed source got a version and every exact pin
      followed it. Locks refreshed with relative `--find-links`.

      Two locks were already behind before this change -- `core/storefront` and
      `domains/vms/domain`, both at `arkhai-kit-alkahest` 0.1.1 -- and are left
      alone rather than swept in here.

      `test_this_repository_currently_pins_an_unreleased_client` asserted the
      literal `0.3.0`. It now derives the version from the pin and asserts what
      it was really about: no trust manifest names the pinned version, so the
      channel is internal. Naming the version there was the third place stating
      it that the selector exists to remove.

## 2. The neutral layers relay options they do not read

- [x] 2.1 `ConditionalEscrowClient.reclaim_expired` in
      `kit/settlement-runtime/src/market_settlement_runtime/ports.py` gains
      `mechanism_options: Mapping[str, Any] | None = None`.
- [x] 2.2 `SettlementRuntime.reclaim` gains the same argument, passes it to
      `_reserve` as `request_values` and to the mechanism client, and stores
      nothing.
- [x] 2.3 `SettlementHostedRoutes.reclaim` accepts and forwards it.
- [x] 2.4 The other implementers of the port — the contact-exchange client and
      the Alkahest claim hooks — accept it and ignore it.
- [x] 2.5 Evidence: a unit test that the runtime dispatches the options
      verbatim, that they appear in no persisted row or projection, and that a
      second reclaim naming different options is refused.

      The refusal turned out to be an existing one: the repository already
      raises `settlement operation was reused with a different request` when a
      reservation's hash differs, which the route maps to 409. Binding the
      options into `request_values` is all that was needed to reach it.
      Mutation-checked by dropping that binding -- the conflict test fails and
      the mechanism receives the second address.

      Suites: settlement-runtime 90 (was 84), hosted-settlement 187 (was 183),
      core buyer 117 (was 115).

## 3. The hosted adapter names the address

- [x] 3.1 `HostedSettlementAdapter.reclaim_expired` reads
      `return_instructions_email` from the options and builds `ReclaimRequest`,
      falling back to a bare `OperationRequest` when absent.
- [x] 3.2 Evidence: a unit test that an address becomes a `ReclaimRequest`
      carrying it, that no address leaves the request bare, and that the receipt
      and mechanism state contain no address.

## 4. The buyer supplies it

- [x] 4.1 `HostedSettlementTransport.reclaim` accepts an optional options
      mapping and signs it into the body; the body stays absent when none is
      given, so existing signatures are unchanged.
- [x] 4.2 The storefront reclaim routes in `domains/vms`, `domains/apicredits`,
      and `domains/bare_metal` read the optional body and forward it.
- [x] 4.3 Evidence: a route-level test that a supplied mapping reaches the
      runtime and that a reclaim with no body behaves exactly as before.

      One thing the plan did not anticipate: `_authorize` passed `None` as the
      body for every record-scoped operation, so a signed non-empty body would
      have failed verification against `EMPTY_BODY`. The options are now the
      body `_authorize` verifies, which is also the right answer on its own --
      where a payer's money is returned to is part of what that payer
      authorized, not something read first and trusted after.

## 5. The bank-transfer lane closes

- [x] 5.1 The `us_bank_transfer.v1` reclaim lane supplies the connected
      account's own registered address.
- [x] 5.2 Evidence: e2e unit coverage that the lane sends an address and that a
      lane sending none reports the authority's refusal by its own name rather
      than a convergence timeout.

      The address is fetched by the driver, which already holds the credential,
      and handed to the buyer role as one environment value. Deriving it in the
      role would mean putting provider credentials in the buyer, which is the
      one place in this harness that must not have them. A bank-transfer lane
      started without it names the missing prerequisite rather than issuing a
      request it could not have completed.

      Confirmed against the account this run uses: it registers an address and
      reports `details_submitted=false` -- exactly the state where Stripe will
      mail the account's own address but not a third party's, which is why this
      path is exercisable now.

      Suites: e2e unit 182 (was 173).
- [ ] 5.3 Record the result in `docs/development/TESTING.md` and close the
      `us_bank_transfer.v1` reclaim cell in the coverage matrix, or state
      precisely what remains external if it does not close.
