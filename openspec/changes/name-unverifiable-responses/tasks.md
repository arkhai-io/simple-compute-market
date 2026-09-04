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
      driver.

      A second correction, found by a run rather than a test: the fill
      validated the key with the pattern used for configuration identifiers,
      which requires a leading alphanumeric. A URL-safe token starts with
      whatever it starts with, and about one generated key in thirty starts
      with `_` or `-`, so roughly one run in thirty refused the key it had been
      handed. A bearer token is now validated as a bearer token — what matters
      is that it cannot break out of the string it is written into — and a
      value that would is refused rather than escaped. Suite: e2e unit 97.

## 3. Find out what the lane is actually refusing

- [x] 3.1 Run one lane locally against the real Stripe test account and record
      what buyer status polling names once it can speak.

      It names `GET /api/v1/settlements/{ref} -> HTTP 403 carried no response
      authentication`. Run on the `us_bank_transfer.v1` collection lane, which
      needs no browser: interactive mode returns no payer setup and bank
      funding goes through the test-helper simulation rather than a hosted
      page, so the lane reproduces the refusal headlessly and repeatably.

      Two corrections this produced. The first run still printed the old
      sentence, because the e2e environment resolves `core_buyer` from an
      installed wheel rather than the edited source — the improvement was real
      and not in effect. The second run refused its own registry key, which is
      recorded against 2.3.

      **Previously blocked:** the card lane could not reach this stage. Stripe
      answers Checkout with an interactive hCaptcha after repeated automated
      sessions, which the harness detects and classifies as an environment
      failure. An earlier reading of that as progress was wrong: the stage it
      reached, `browser_checkout`, is earlier than `funding`, so the card lane
      regressed rather than advanced. the lane no longer reaches that stage. Stripe now answers
      Checkout with an interactive hCaptcha, which the harness detects and
      classifies as an environment failure at payer setup — earlier runs today
      passed the same step, so this is provider anti-automation responding to
      repeated sessions rather than a defect. Solving it is not something a
      harness should do. What section 2 fixed is confirmed independently: the
      storefront now publishes to the private registry with `200`/`201` where
      every earlier run answered `401`. It did not, on its own, clear this
      refusal.
- [ ] 3.2 Correct it here if it is a marketplace defect or another harness
      omission; record it for `add-bare-metal-hosted-settlement` if it belongs to
      the hosted matrix. A development run qualifies no lane either way.

      The refusal is `buyer_auth._verify`: the request's already-authenticated
      principal is not the buyer the agreement records, or is not carrying the
      buyer role. It is raised inside the authentication middleware, before the
      wrapper that signs responses, which is why it reaches the buyer unsigned
      and unreadable. Whether the cached principal or the role is the mismatch
      is one storefront-side observation away and is the next step; that the
      same route accepts `POST /api/v1/settlements` from the same buyer moments
      earlier is the thing to explain. The interactive lanes depend on the provider not
      challenging automation, which bounds how often the matrix can be run and
      is recorded for `add-bare-metal-hosted-settlement`.

## 4. Closeout

- [x] 4.1 Hygiene clean, strict validation, lint clean on every touched file
      (five pre-existing errors remain in files this change does not touch).
      The provider's throughput constraint is recorded in
      `docs/development/TESTING.md` and in `add-bare-metal-hosted-settlement`.
      The ROADMAP hosted status is unchanged: the lane's blocker is the same
      response authentication, still undiagnosed, because the lane cannot
      currently reach it. Suites: core buyer 115, storefront client 30, core
      storefront 148, e2e unit 97, VM buyer 196, VM storefront 941, bare-metal
      buyer 11, bare-metal storefront 122.
- [ ] 4.2 **Campaign index currency** (part seven, added when
      `openspec/README.md#plan-closeout-requirements` was extended from six parts to seven).
      Appended rather than folded into an existing task, per `AGENTS.md`'s rule to amend
      rather than replace implementation history. This change has no row in
      `openspec/changes/README.md`; add one under the campaign that owns it with its status
      and acceptance boundary, or record here why it stands outside every campaign.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| A fail-closed refusal names the status and whether the response was authenticated, and never the body | `openspec/specs/storefront-publication/spec.md` (promote at synchronization) |
| A development run authenticates to the private registry it configures | `docs/development/HOSTED_CREDENTIAL_PAYLOAD.md` |
