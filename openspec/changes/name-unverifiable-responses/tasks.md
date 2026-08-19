## 1. A refusal says what it refused

- [x] 1.1 The authenticated-response reader reports the HTTP status it received
      and whether the response carried response authentication at all, for every
      refusal it raises, and continues to exclude the body, header values, and
      any credential.
- [x] 1.2 Evidence: an unauthenticated error answer is refused with its status
      and its unauthenticated state named; a response missing one header reads
      as a protocol fault and names the header, never its value; neither report
      contains the body; and every response accepted today is still accepted.
      The two existing tests that asserted the old sentence now assert the
      status and the state, which is what they were really about.

      A second reader carried the same sentence: the storefront client's own
      response verification, which the requirement names as directly as the
      buyer's. It already distinguished an absent header from an unreadable
      one; it now carries the status into both. Its suite could not run on a
      machine with a proxy configured either. Suites: core buyer 115,
      storefront client 30.

## 2. The harness authenticates to its own private registry

- [x] 2.1 The rendered storefront configuration carries the private registry's bearer
      authorization, keyed by the registry URL the storefront is configured with.
- [x] 2.2 The buyer configuration carries the same authorization for discovery
      through that registry.
- [x] 2.3 Evidence: the fill authorizes exactly the registries the template
      declares and no others, leaves the rest of the configuration untouched,
      and leaves the declaration empty when the run holds no key rather than
      inventing one; the committed templates declare their private registry and
      carry no key. One correction folded in: the declaration lives in the
      committed template and the fill in the driver, not in the local assembler,
      because the protected workflow writes the same empty secrets file and had
      the identical gap — both paths render their configuration through the
      driver. Suite: e2e unit 97.

## 3. Find out what the lane is actually refusing

- [ ] 3.1 Run one interactive `card.v1` lane locally against the real Stripe test
      account and record what buyer status polling names once it can speak.
      **Blocked:** the lane no longer reaches that stage. Stripe now answers
      Checkout with an interactive hCaptcha, which the harness detects and
      classifies as an environment failure at payer setup — earlier runs today
      passed the same step, so this is provider anti-automation responding to
      repeated sessions rather than a defect. Solving it is not something a
      harness should do. What section 2 fixed is confirmed independently: the
      storefront now publishes to the private registry with `200`/`201` where
      every earlier run answered `401`.
- [ ] 3.2 Correct it here if it is a marketplace defect or another harness
      omission; record it for `add-bare-metal-hosted-settlement` if it belongs to
      the hosted matrix. A development run qualifies no lane either way.
      **Blocked by 3.1.** The interactive lanes depend on the provider not
      challenging automation, which bounds how often the matrix can be run and
      is recorded for `add-bare-metal-hosted-settlement`.

## 4. Closeout

- [ ] 4.1 Hygiene clean, strict validation, suites for every touched package, and
      the ROADMAP updated if the hosted-settlement status changes shape.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A fail-closed refusal names the status and whether the response was authenticated, and never the body | `openspec/specs/storefront-publication/spec.md` (promote at synchronization) |
| A development run authenticates to the private registry it configures | `docs/development/HOSTED_CREDENTIAL_PAYLOAD.md` |
