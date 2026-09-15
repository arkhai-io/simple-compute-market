## Why

`docker compose up` cannot start the local stack, and has not been able to since
mid-August. The root `docker-compose.yml` and the two compose files it includes
guard every signer, wallet, and buyer-path mount with `${VAR:?...}` — seventeen
guard occurrences over fifteen distinct variables — and nothing in the
repository supplies them. `.github/workflows/e2e.yml` sets exactly two
environment variables, neither of them one of these, so the nightly E2E job
fails at `compose up` before any scenario runs.

A developer's local run works only from an untracked `.env`, which is why the
gap was invisible: it fails for CI and for anyone cloning the repository, and
succeeds for whoever happens to have the file.

The values are not secret and never were. The public half of every identity is
already committed — the compose files pin the addresses, and
`core/registry/src/main.py` refuses to start if a credential does not derive its
pinned identifier. Five of the six identities are standard Anvil development
accounts whose private keys are published in Foundry's documentation and already
appear in this repository. Committing the private halves therefore discloses
nothing and makes the stack runnable by anyone, which is the property the E2E
suite needs.

## What Changes

- Add `dev-env/identities/`, holding the committed development credential,
  identity-env, wallet-env, admin-key, and buyer-config fixtures, with a
  `README.md` carrying the statement `AGENTS.md` requires for public
  development material.
- Add a `make e2e-dev-identities` target that prints shell exports pointing
  every guarded variable at those fixtures, and call it from
  `make -C e2e-tests test-e2e` so local and CI runs use one path.
- **Split the compose overrides out of the `include` files.** The development
  bindings move to `compose.local-identities.yml` and are layered with `-f`,
  because `include` refuses to let an including file redefine an imported
  service. The base topology stays `include`d, which is what preserves
  per-file relative-path resolution. Reached only after the identities were
  supplied, since every earlier run failed at interpolation first.
- **Replace the API-credits registry identity.** It is the one identity whose
  private half was never committed and cannot be recovered from its public
  identifier. A deterministically derived replacement is committed, and its
  three pins are updated together: `docker-compose.yml`,
  `compose.apicredits.yml`, and
  `domains/apicredits/storefront/storefront.credits.toml`.

## Non-Goals

- Do not weaken the `${VAR:?...}` guards to defaults. The guard exists so a
  deployment cannot come up with the wrong signer; relaxing it in the shared
  compose files to satisfy CI would trade a real safety property for
  convenience.
- Do not give the E2E workflow access to repository secrets. A suite that
  cannot be run by a contributor or on a fork is a suite whose failures only
  one person can reproduce.
- Do not change what any service does. This supplies configuration that was
  always required and never provided, and rearranges how compose files are
  combined without altering any service's definition.
- Do not fix `compose.apicredits.yml`, which has the same `include`-plus-override
  shape. It is a separate entry point, not on the e2e path, and the compose
  stack is being replaced by a Tekton pipeline over the Helm charts.

## Impact

- Affected configuration: `docker-compose.yml`, `compose.apicredits.yml`,
  `domains/apicredits/storefront/storefront.credits.toml`, the root `Makefile`,
  and `e2e-tests/Makefile`.
- Affected deployment: none. Every added file is development material read only
  through the compose stack.
- Affected identity: the API-credits registry's principal changes, so anything
  pinning the retired identifier must move with it. Three pins are known and
  updated; a fourth would fail startup loudly on the identity assertion rather
  than silently.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification
- [ ] New subsystem specification
- [x] No permanent documentation change

The convention this establishes — committed, obviously-labelled development
identities for the local stack — is durable, but `AGENTS.md` already states the
rule it follows ("use a well-known deterministic development value and say in a
comment that it is one"). This change supplies the values rather than the rule,
so `dev-env/identities/README.md` is the right permanent home and no
specification changes.
