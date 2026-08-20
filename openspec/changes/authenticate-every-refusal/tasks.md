## 1. See the defect from the wire

- [x] 1.1 Exercise the hosted settlement routes through the mounted VM
      storefront application with requests signed the way `core_buyer` signs
      them and responses verified the way `core_buyer` verifies them.
- [x] 1.2 Evidence: a signed buyer completes start and status and both answers
      verify; repeated status polls verify; and a refused caller's answer fails
      to verify because it carries no response authentication at all — the
      exact shape the real lane reported.

      The happy path passed on the first run, which narrows the real lane's
      refusal: a plain signed status poll against an accepted obligation is
      not what fails. What reproduced deterministically is the second half —
      the refusal arrives with no `X-Market-*` response headers, so the
      buyer's `AuthenticatedResponse` validation fails on the absent timestamp
      before any verification runs.

## 2. The VM storefront signs what it refuses

- [x] 2.1 A refusal on a buyer contract route is signed over the route's
      operation and resource, the caller's request identity, the status, and
      the refusal body, whether the refusal was raised during authentication
      or escaped the route afterwards.
- [x] 2.2 A refusal on a seller listing mutation is signed on the same terms.
- [x] 2.3 A request that carries no request identity, or names no contract, is
      still refused unsigned.
- [x] 2.4 No replay outcome is recorded for a refusal that never authenticated.
- [x] 2.5 Evidence: the wire tests from 1.2 pass, including the refused caller;
      a caller that sends no request identity is still refused bare; a refusal
      raised before dispatch reserves no replay identity, so a later honest
      request with the same identity inherits nothing. Suite: VM storefront
      1101 passed, 1 skipped.

## 3. The other storefronts sign what they refuse

- [ ] 3.1 The bare metal storefront's response wrapper signs a refusal raised
      before its authentication context is bound.
- [ ] 3.2 The API-credits storefront does the same.
- [ ] 3.3 Evidence: wire-level coverage per storefront and both suites green.

## 4. Read the refusal the hosted lane was giving

- [ ] 4.1 Run the headless `us_bank_transfer.v1` lane against the real Stripe
      test account with a locally bound authority, and record what buyer status
      polling now names.
- [ ] 4.2 Correct the cause it names, or record it against the change that owns
      it if it is not this one.
