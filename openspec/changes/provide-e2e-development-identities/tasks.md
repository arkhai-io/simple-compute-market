# Tasks — provide E2E development identities

## 1. Survey

- [x] 1.1 Enumerate every `${VAR:?...}` guard across the **transitive**
      `include:` closure of `docker-compose.yml`, resolved the way compose
      resolves it rather than by listing the files I knew about. Five compose
      files, eighteen distinct variables, twenty guard occurrences.
      - **Correction:** the first pass scanned three files and reported fifteen
        variables. `compose.vms.yml` has its own `include:`, so three required
        variables sat one level deeper and the second CI run failed on one of
        them. See `design.md`.
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
- [x] 2.3 Verify every credential derives **the identifier its consumer
      declares**, read out of that consumer's own configuration — not merely
      that it derives some identifier. The weaker check passed while
      `api-credits.identity.env` held the ed25519 *registry* credential for a
      storefront that declares eip191, and the container failed at startup.
      All four identity files now pass the stronger check.
- [ ] 2.5 `storefront.credits.toml` pins
      `ed25519 My6-jSfLcyOzpAHBwTtd1kvMwOEOzaHCtdEaA3eaheU` as the `default`
      capacity site's expected authority, but that site is the provisioning
      service, which signs eip191. Pre-existing, no committed private half, and
      not satisfiable by supplying a credential. Either the pin is stale or
      that site is meant to run an ed25519 identity that was never committed —
      a topology question, so raised rather than guessed.
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
- [x] 4.6 Pass `--env-file` to **every** compose invocation, not only `up`.
      `down` and `logs` interpolate the same config, so the guards block them
      too. The env file is now generated as the recipe's first action, and the
      workflow's `always()` teardown and log-collection steps regenerate it
      before their own compose calls — which is also why the first two runs
      produced a 148-byte log artefact instead of container logs.
- [x] 4.5 Gitignore the generated artefacts — `.e2e-buyer/` and
      `.e2e-identities.env` — and say in `.gitignore` that the values they point
      at are tracked, so a reader does not conclude the identities are secret.

## 4b. Compose topology

Reached only once the identities were supplied: with interpolation succeeding,
compose got to the merge stage and rejected `include`-plus-override. Scoped into
this change rather than a separate one because this change exists to make the
stack startable, and the compose stack is being replaced by a Tekton pipeline
over the Helm charts — a third change document for a subsystem on its way out
would be ceremony.

- [x] 4b.1 Move the development bindings out of `compose.vms.yml` and
      `docker-compose.yml` into `compose.local-identities.yml`, layered with
      `-f`. Keep the base topology `include`d: the two base files resolve
      relative paths against their own directories and sit in different
      directories, so no single project directory could replace `include`, and
      rewriting their paths would break the `hosted-stripe-test` flow that
      depends on the project directory being `domains/vms`.
- [x] 4b.2 Pass both files from the e2e recipe and from the workflow's
      `always()` steps.
- [x] 4b.3 State in both `include` files that a bare `docker compose up` now
      omits the bindings, and give the two-file invocation.
- [ ] 4b.4 `compose.apicredits.yml` has the same `include`-plus-override shape
      and will fail identically. Not on the e2e path, so not fixed here.
      Raise separately or leave until the Tekton migration retires it.

## 4c. Make a failure diagnosable from the job log

- [x] 4c.1 On `up --wait` failure, print `compose ps -a` and each service's
      last 120 log lines **in the failing step**, then exit non-zero.
      `up --wait` reports only *which* container went unhealthy, never why, and
      leaving the answer to the `always()` collection step puts it in an
      uploaded artifact that has to be downloaded separately. Verified against
      a stub `docker` that fails `up`: the groups print and the recipe still
      exits 1.
- [x] 4c.2 `tee` the collection step's output so container logs land in the job
      log as well as the artifact, wrapped in a collapsible group.

## 4d. Environment values that are not strings

- [x] 4d.1 Mark the three `PROVISIONING_*_IDENTITY__IDENTIFIER` values with
      Dynaconf's `@str`. An eip191 address is a valid TOML hexadecimal integer
      literal, so Dynaconf delivered it as a 48-digit decimal and identity
      validation refused it. Reproduced against `parse_conf_data` rather than
      inferred from the traceback.
- [x] 4d.2 Establish the blast radius instead of fixing only what failed: the
      registries read settings with `pydantic_settings` (no TOML parsing, and
      both healthy in the same run), and `ARKHAI_IDENTITY_CREDENTIAL` is read
      from `os.environ` directly — so the credentials, which are also
      `0x`-prefixed, would not have failed next.
- [ ] 4d.3 Consider stopping `kit/config`'s shared loader from TOML-parsing
      values destined for identity fields. Not done here: it changes a loader
      every service shares to fix a stack being replaced.

## 4e. Stale deployment profiles

Reached once identities stopped being the blocker. All three storefronts failed
at startup on missing configuration keys, each different, none identity-related.
The mounted deployment profile **replaces** the shipped `settings.toml` rather
than layering over it, so a key the code began requiring after these profiles
were last touched is simply absent.

- [x] 4e.1 Add `[capacity.sites] default = "http://provisioning:8081"` to
      `storefront.bob.toml` and `storefront.alice.toml`.
      `_capacity_settings()` raises when the table is empty, and the shipped
      `settings.toml` only documents the table without defaulting it. The name
      matches each profile's `Identity.service_peers.provisioning_default.site_id`
      and the URL matches its own `[provisioning].service_url` — the comment
      already in those files describes an `authority_url` default from
      `provisioning.service_url` that the code no longer applies.
- [x] 4e.2 Add top-level `enable_registry_discovery = true` to
      `storefront.credits.toml`, matching the shipped default. Placed in the
      root namespace, where that file's `port`/`base_url`/`db_path` live —
      inserting it before `[registry]` would have made it a member of the
      preceding table instead.
- [x] 4e.4 **Fix the cause instead of the symptoms.** Ten root-level keys in
      `apicredits_storefront/settings.toml` sat *below* the
      `[identity.admin_principals]` header, so TOML made every one of them a
      member of that table and no `settings.<key>` lookup could reach them:
      `agent_id`, `agent_name`, `port`, `base_url`, `db_path`, `log_level`,
      `enable_registry_discovery`, `negotiation_timeout_seconds`,
      `negotiation_watchdog_interval`, `claims_sweep_interval`. That is why the
      credits storefront failed on one missing attribute per run — each startup
      reached one key further. Moved above the first table header, where root
      keys must be, and 4e.2's per-key patch to the deployment profile reverted
      as redundant.
- [x] 4e.5 `storefront.bob.toml` and `storefront.alice.toml` spelled
      administrator and service-peer trust as `principal = {...}` where
      `_trusted_identity_set` requires `principals = [...]` — it accepts one or
      two identities so an authority can rotate. Both fields in both profiles
      converted. `[Identity.principal]`, the storefront's own single identity,
      is correctly singular and left alone.
- [ ] 4e.3 `storefront.credits.toml` declares
      `[capacity.sites.default.expected_authorities]` but no authority **URL**
      for that site, so `capacity.sites.default` is a table where the loader
      expects a URL string. Whether the API-credits storefront should have a
      capacity site at all, and if so which service, is a topology question for
      the domain owner. Related to 2.5's unsatisfiable `My6-…` pin on the same
      table.

## 5. Validation

- [x] 5.1 Assert every `:?` guard is satisfied and every exported path exists,
      evaluated the way compose evaluates it. 17 of 17, resolved from the env
      file alone rather than from the ambient environment — which is what
      compose does with `--env-file`.
- [x] 5.7 Verify the merged stack the way compose merges it: every overlay
      service either overrides a base service or is newly introduced (seven
      override, `buyer-cli` is new), no `include` file defines services any
      more, and all 20 required guards resolve. Structural only — still not a
      run.
- [x] 5.6 Supply the three variables the deeper include level requires:
      `VMS_BOB_STOREFRONT_SECRETS_FILE` as a secret overlay carrying
      registry-b's bearer token, and `VMS_REGISTRY_ADMIN_API_KEY` /
      `VMS_REGISTRY_BOOTSTRAP_API_KEY` as development tokens. The bootstrap
      value is asserted byte-equal across the registry seed, the storefront
      overlay, and the buyer config, since a mismatch would surface as a `401`
      several steps from its cause.
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
