## 1. Bind the release that declares the capability

- [ ] 1.1 Build the `0.4.0` client wheel from the producer's `.dist` and move the
      pin in `kit/hosted-settlement/pyproject.toml`, then `make
      fix-hosted-client-pin` to move both followers.
- [ ] 1.2 Relock the affected projects against the built wheel and confirm the
      derived release coordinates follow with no Makefile edited.
- [ ] 1.3 Evidence: `make check-hosted-client-pin` agrees, and the installed
      client exposes `ReclaimRequest.return_instructions_email`.

## 2. The neutral layers relay options they do not read

- [ ] 2.1 `ConditionalEscrowClient.reclaim_expired` in
      `kit/settlement-runtime/src/market_settlement_runtime/ports.py` gains
      `mechanism_options: Mapping[str, Any] | None = None`.
- [ ] 2.2 `SettlementRuntime.reclaim` gains the same argument, passes it to
      `_reserve` as `request_values` and to the mechanism client, and stores
      nothing.
- [ ] 2.3 `SettlementHostedRoutes.reclaim` accepts and forwards it.
- [ ] 2.4 The other implementers of the port — the contact-exchange client and
      the Alkahest claim hooks — accept it and ignore it.
- [ ] 2.5 Evidence: a unit test that the runtime dispatches the options
      verbatim, that they appear in no persisted row or projection, and that a
      second reclaim naming different options is refused.

## 3. The hosted adapter names the address

- [ ] 3.1 `HostedSettlementAdapter.reclaim_expired` reads
      `return_instructions_email` from the options and builds `ReclaimRequest`,
      falling back to a bare `OperationRequest` when absent.
- [ ] 3.2 Evidence: a unit test that an address becomes a `ReclaimRequest`
      carrying it, that no address leaves the request bare, and that the receipt
      and mechanism state contain no address.

## 4. The buyer supplies it

- [ ] 4.1 `HostedSettlementTransport.reclaim` accepts an optional options
      mapping and signs it into the body; the body stays absent when none is
      given, so existing signatures are unchanged.
- [ ] 4.2 The storefront reclaim routes in `domains/vms`, `domains/apicredits`,
      and `domains/bare_metal` read the optional body and forward it.
- [ ] 4.3 Evidence: a route-level test that a supplied mapping reaches the
      runtime and that a reclaim with no body behaves exactly as before.

## 5. The bank-transfer lane closes

- [ ] 5.1 The `us_bank_transfer.v1` reclaim lane supplies the connected
      account's own registered address.
- [ ] 5.2 Evidence: e2e unit coverage that the lane sends an address and that a
      lane sending none reports the authority's refusal by its own name rather
      than a convergence timeout.
- [ ] 5.3 Record the result in `docs/development/TESTING.md` and close the
      `us_bank_transfer.v1` reclaim cell in the coverage matrix, or state
      precisely what remains external if it does not close.
