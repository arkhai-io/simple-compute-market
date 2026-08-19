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
      status and the state, which is what they were really about. Suite: core
      buyer 115.

## 2. The harness authenticates to its own private registry

- [ ] 2.1 The assembled storefront secrets carry the private registry's bearer
      authorization, keyed by the registry URL the storefront is configured with.
- [ ] 2.2 The buyer configuration carries the same authorization for discovery
      through that registry.
- [ ] 2.3 Evidence: the assembled material authorizes exactly the registries that
      demand it and no others; the key never reaches a committed file; and a run
      publishes to and discovers through the private registry without a `401`.

## 3. Find out what the lane is actually refusing

- [ ] 3.1 Run one interactive `card.v1` lane locally against the real Stripe test
      account and record what buyer status polling names once it can speak.
- [ ] 3.2 Correct it here if it is a marketplace defect or another harness
      omission; record it for `add-bare-metal-hosted-settlement` if it belongs to
      the hosted matrix. A development run qualifies no lane either way.

## 4. Closeout

- [ ] 4.1 Hygiene clean, strict validation, suites for every touched package, and
      the ROADMAP updated if the hosted-settlement status changes shape.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A fail-closed refusal names the status and whether the response was authenticated, and never the body | `openspec/specs/storefront-publication/spec.md` (promote at synchronization) |
| A development run authenticates to the private registry it configures | `docs/development/HOSTED_CREDENTIAL_PAYLOAD.md` |
