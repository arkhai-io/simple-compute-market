## 1. The browser reaches the provider

- [x] 1.1 Chromium is launched with the run's HTTP proxy when one is configured,
      and with none when none is.
- [x] 1.2 Loopback is never proxied, whatever `NO_PROXY` says.
- [x] 1.3 `ALL_PROXY` is not consulted.
- [x] 1.4 Evidence: unit coverage for all three. Verified against the live page
      a failed run left open: launched as the harness launched it, the session
      reports no card field and an empty body; launched with the proxy, the
      complete form.

## 2. A payment says whether it happened

- [x] 2.1 A successful payment claims its outcome only after Checkout leaves
      its own page.
- [x] 2.2 A form Checkout silently rejected is reported at the browser, naming
      the payment, not as a later funding timeout.
- [x] 2.3 The decline, insufficient-funds, and authentication outcomes keep
      their existing waits and are not required to leave.
- [x] 2.4 Evidence: unit coverage for a payment that leaves, one that does not,
      one that names the setup rather than the payment, and a development run
      quoting the page's own validation text. Suite: e2e unit 138 passed.

## 3. Prove the card profile locally

- [x] 3.1 Run the interactive `card.v1` collection lane against the real Stripe
      test account and record the result.

      `environment` at stage `browser_checkout`, code `chromium_unavailable`:
      "Stripe Checkout requires an interactive CAPTCHA". The provider is
      answering repeated automated sessions with an hCaptcha, which is the
      documented constraint on this lane and not a defect. What changed is that
      the run says so: the same lane previously reported
      `convergence_timeout` at stage `funding`, three minutes and three steps
      downstream, naming neither the page nor what it did there.

      Confirmed three times across the evening, so it is the account's
      standing state rather than one unlucky session. The harness's
      `--visible-browser` option, which exists because a headless browser is
      itself the signal the provider answers, is not a way around it from an
      unattended session: Playwright's non-headless launch blocks indefinitely
      with no GUI session to attach to — twenty-seven minutes with the stack up
      and no output — rather than failing inside any of the run's timeouts.
- [x] 3.2 Record the proxy requirement in the testing documentation.
