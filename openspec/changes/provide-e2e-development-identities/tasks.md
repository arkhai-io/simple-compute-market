# Tasks — provide E2E development identities

## 1. Survey

- [x] 1.1 Enumerate every `${VAR:?...}` guard across `docker-compose.yml` and
      the compose files it includes, not just the one the failure reported.
      Fifteen distinct variables over seventeen guard occurrences.
- [x] 1.2 For each guarded mount, establish what the consumer actually reads: a
      single opaque credential, shell-format key/value pairs, a bearer string,
      or a path that must exist and be writable.
- [x] 1.3 For every identity, find the committed public pin and derive whether a
      known development key produces it. Five of six resolve to standard Anvil
      accounts; record the account number per identity, because the assignments
      are not interchangeable.
- [x] 1.4 Attempt recovery of the API-credits ed25519 identity from the
      deterministic seeds this repository uses elsewhere before concluding it
      must be replaced. Eleven candidates tried, none derive the pinned
      identifier.

## 2. Committed development identities

- [x] 2.1 Add `dev-env/identities/` with the four eip191 credentials, the
      replacement ed25519 credential, the four identity-env files, the
      API-credits wallet-env file, the admin-key file, and the buyer config.
- [x] 2.2 Carry the fixture statement `AGENTS.md` requires. Inline in every
      shell-format file; in `README.md` for the files whose loader reads the
      whole contents and would reject a comment. Record that distinction in the
      README so an absent comment reads as a constraint rather than an omission.
- [x] 2.3 Verify every credential derives its pinned identifier through
      `create_signer`, rather than assuming the Anvil mapping.
- [x] 2.4 Write the buyer config against the default stack's **eip191** registry
      authorities. `e2e-tests/config/hosted-buyer.toml` pins ed25519 and cannot
      be reused; record why in the file.

## 3. Replace the API-credits registry identity

- [x] 3.1 Derive the replacement deterministically from a labelled string and
      document the one-line command that reproduces it.
- [x] 3.2 Update all three pins together: `docker-compose.yml`,
      `compose.apicredits.yml`, and
      `domains/apicredits/storefront/storefront.credits.toml`.
- [x] 3.3 Confirm no occurrence of the retired identifier remains anywhere in
      the repository.

## 4. Wiring

- [x] 4.1 Add the identity targets: `e2e-dev-identities-env` printing
      `VAR=value` for `docker compose --env-file`, and `e2e-dev-identities`
      wrapping it as `export` lines for a human to eval. The second derives from
      the first so they cannot drift. Both create the writable buyer
      directories.
- [x] 4.2 Call it from `e2e-tests`' `test-e2e` so local and CI runs use one
      path, with a comment stating why the guards require it.
- [x] 4.3 Confirm `.github/workflows/e2e.yml` needs no change: `test-e2e`
      supplies the variables itself. Confirmed by the run — it reached
      `compose up` and failed inside the recipe, not for want of workflow
      environment.
- [x] 4.4 **Fix the eval-capture defect the first CI run exposed.**
      `eval "$($(MAKE) -s e2e-dev-identities)"` failed with
      `/bin/sh: 1: eval: make[1]:: not found`. A recursive make implies `-w`, so
      the sub-make printed `Entering directory` on stdout and `$(...)` captured
      it into the eval'd string; `-s` does not suppress that. Every recursive
      invocation now passes `--no-print-directory`, and the recipe writes a file
      for `docker compose --env-file` instead of eval'ing captured output, so
      nothing has to survive a shell round-trip. See `design.md`.
      - **Also fixed:** `${VAR:?...}` written inside a recipe comment was
        expanded by make before the shell saw it, which is why the CI log shows
        "`` guarded". Recipe comments now avoid `$` and are `@`-prefixed so they
        are not echoed.
- [x] 4.5 Gitignore the generated artefacts — `.e2e-buyer/` and
      `.e2e-identities.env` — and say in `.gitignore` that the values they point
      at are tracked, so a reader does not conclude the identities are secret.

## 5. Validation

- [x] 5.1 Assert every `:?` guard is satisfied and every exported path exists,
      evaluated the way compose evaluates it. 17 of 17, resolved from the env
      file alone rather than from the ambient environment — which is what
      compose does with `--env-file`.
- [x] 5.5 Reproduce the CI failure locally before fixing it, and confirm the fix
      against the same shape: a nested make invoking the target through
      `$(MAKE)`, which is what implies `-w`. The generated env file contains 15
      lines and no `make[` noise.
- [x] 5.2 Confirm each credential file is byte-exact for its loader: no trailing
      newline where the value is read with `read_text().strip()` and compared or
      parsed whole.
- [ ] 5.3 **Run `docker compose config` and then `make -C e2e-tests test-e2e`.**
      Not runnable in the authoring environment, which has no Docker. This is
      the check that actually closes the change; everything above is necessary
      and not sufficient.
- [ ] 5.4 Confirm the API-credits registry starts and its descriptor reports the
      replacement principal, which exercises the identity assertion the three
      pins feed.

## 6. Closeout

- [ ] 6.1 **Comment hygiene.** Run `make check-comment-hygiene`.
- [ ] 6.2 **Import placement.** No Python added; record that disposition.
- [ ] 6.3 **Documentation compliance.** The proposal records no permanent
      documentation change because `AGENTS.md` already states the rule this
      follows; re-check that judgement against `openspec/README.md`'s placement
      table rather than assuming it.
- [ ] 6.4 **Narrative compression.** Reduce task notes to final state and the
      unrun checks.
- [ ] 6.5 **Roadmap currency.** Assess `docs/development/ROADMAP.md`; expected
      to own nothing here. Record the disposition either way.
- [ ] 6.6 **Campaign index currency.** Add this change's row to
      `openspec/changes/README.md`, including that it unblocks
      `settle-listing-vocabulary`'s system-level validation.
- [ ] 6.7 **Promotion.** Complete the design-promotion record below.

## Design promotion record

| Accepted decision | Permanent location |
|---|---|
| Local-stack development identities are committed, labelled, and reproducible | `dev-env/identities/README.md` |
| Which Anvil account backs each pinned service identity | `dev-env/identities/README.md` |
| The replacement API-credits principal | `docker-compose.yml`, `compose.apicredits.yml`, `domains/apicredits/storefront/storefront.credits.toml` |

Classified as **temporary** and deliberately not promoted:

| Decision | Disposition |
|---|---|
| The rule that a development fixture must say so | Already stated in `AGENTS.md`; this change supplies values, not the rule |
| Whether the VM wallet env files should move into `dev-env/identities/` | **Deferred**, recorded as an open question: tidiness, not correctness |
