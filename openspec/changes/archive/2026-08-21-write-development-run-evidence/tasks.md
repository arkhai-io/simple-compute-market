## 1. Record the producer half the way the gate bound it

- [x] 1.1 Producer identity evidence carries the image the run named and the
      build the authority reported, alongside the released coordinates.
- [x] 1.2 Each half's released coordinates are accepted when every one is
      exact, and when every one is the self-describing local marker.
- [x] 1.3 A half carrying some exact coordinates and some markers is refused.
- [x] 1.4 A locally built producer that names no image, or no reported build,
      is refused.
- [x] 1.5 Evidence: a development run's document is written and records the
      marker, the image, and the reported build; a half carrying one exact
      coordinate among markers is refused; a build naming no image or no
      reported build is refused; an attested half with a malformed run id is
      still refused exactly as before. Suite: e2e unit 131 passed.

## 2. Read the refusal the hosted lane was giving

- [x] 2.1 Run the headless `us_bank_transfer.v1` lane against the real Stripe
      test account with a locally built authority, and record what buyer status
      polling now names.

      The lane passes end to end and writes its evidence: `result: passed`,
      `stage: complete`, `release_mode: local`, the producer half recorded as
      the image `localhost/arkhai-hosted-settlement-service:0.3.0` and the
      build digest `sha256:22c1fd7f…` with `local` in place of every released
      coordinate. Before this change that same run raised
      `EvidenceValidationError` and wrote nothing.
- [x] 2.2 Correct the cause it names, or record it against the change that owns
      it. Recorded against `authenticate-every-refusal`, whose lane this is:
      the refusal does not reproduce against a rebuilt storefront image.
