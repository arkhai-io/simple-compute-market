# Design — provide E2E development identities

## Context

The compose guards were introduced with the storefront domain-bindings work in
mid-August; the E2E job has failed at `compose up` since. The failure reported
only the first unsatisfied variable, `APICREDITS_REGISTRY_IDENTITY_CREDENTIAL_FILE`,
which made it look like an API-credits problem. It is not: fifteen variables are
unsatisfied across both domains, and the API-credits one is simply the first
compose evaluates.

## Decisions

### Commit the development values rather than provision secrets

The alternative was to mirror `hosted-stripe-test.yml`, which pulls a JSON blob
from a repository secret, writes each credential to a file, and masks every
value. Rejected: it keeps the suite unrunnable for contributors and on forks,
which means its failures can only be reproduced by someone holding the secret.
A nightly suite that one person can debug is a suite that decays.

Committing costs nothing in confidentiality. The compose files already pin every
public identifier, and `core/registry/src/main.py` asserts that a supplied
credential derives its configured principal, so the public half is load-bearing
configuration that had to be committed anyway.

### Reuse the Anvil accounts rather than mint new ones

Five of the six identities resolve to standard Anvil accounts from the default
`test test test … junk` mnemonic:

| Identity | Anvil account |
|---|---|
| `registry-a` | 3 |
| `registry-b` | 4 |
| `provisioning` | 0 |
| `bob-storefront` | 2 |
| `alice-storefront` | 4 |

This was established by deriving each key and comparing against the pinned
address, not by inspection. It matters because it means **no pin changes** for
the VM domain and no new material enters the repository: those private keys are
in Foundry's published documentation and already in
`domains/vms/storefront/.env.bob.docker` and
`core/registry/tests/integration/conftest.py`.

The assignments are not interchangeable. `registry-a` and `registry-b` are
accounts 3 and 4 respectively, and swapping them fails startup on the identity
assertion.

### The API-credits identity is replaced, not recovered

Its pinned public identifier had no committed private half. Eleven deterministic
seeds the repository uses elsewhere were tried — `bytes(range(32))`,
`bytes(range(1,33))`, zeros, ones, `sha256("api-credits-registry")`, and others
— and none derive it, so it was generated randomly and never committed. It
cannot be recovered from a public key.

The replacement is derived deterministically from a labelled string so any
reader can reproduce it and confirm no secret is involved:

    sha256("arkhai-development-api-credits-registry-v1")

Three pins move together. The third,
`domains/apicredits/storefront/storefront.credits.toml`, is a trust pin rather
than a service identity and is the one a reader is most likely to miss; leaving
it stale fails the registry's startup assertion rather than degrading quietly,
which is the right failure but an obscure one to diagnose.

### Where the fixture statement lives, and why not in every file

`AGENTS.md` requires that a development fixture say so in a comment. Two of the
file shapes here cannot hold one:

- Credential files are read by `core/registry/src/main.py` with
  `read_text().strip()` and passed whole to `create_signer`. A `#` line would
  become part of the credential.
- `api-credits-admin-key` is read the same way by
  `apicredits_middleware/config.py` and compared whole.

So the rule for the directory is: a file consumed as a single opaque value holds
only that value and its provenance is documented in
`dev-env/identities/README.md`; a file consumed as shell-format key/value pairs
carries the statement inline. `AGENTS.md`'s concern is that a reader can tell
whether a value is safe to remove, and a README covering every file in one place
satisfies that better than a comment the loader would reject.

### The buyer config could not be reused

`e2e-tests/config/hosted-buyer.toml` looks like the obvious template but pins
**ed25519** registry authorities, because the fiat stack signs with ed25519
identities. The default stack's registries run as Anvil **eip191** accounts, so
a reused file would fail response verification against `registry-a`. The new
`buyer.config.toml` pins the eip191 principals and records why it is separate.

### The values reach compose through `--env-file`, not an eval

The first wiring had the e2e recipe run `eval "$($(MAKE) -s e2e-dev-identities)"`.
It failed in CI with `/bin/sh: 1: eval: make[1]:: not found`, and the cause is
worth recording because it is a property of make rather than a typo: a
recursive make implies `-w`, so the sub-make prints
`make[1]: Entering directory '…'` on **stdout**, and `$(...)` captures it into
the string being eval'd. `-s` suppresses command echo and does not suppress
that.

Two changes follow. Every recursive invocation passes
`--no-print-directory`, which removes the cause. And the recipe no longer
evals at all: it writes the resolved paths to a file and passes
`docker compose --env-file`, so compose reads the values itself and nothing has
to survive a shell round-trip. Capturing a sub-make's stdout is fragile for the
general reason that any tool writing to stdout on the way — a hook, a warning,
a `$(shell …)` side effect — silently corrupts the result, and this repository
already emits unrelated `git` noise during make parsing.

The target keeps two forms because they have different consumers:
`e2e-dev-identities-env` prints `VAR=value` for compose, and
`e2e-dev-identities` wraps it as `export` lines for a human to eval. The second
is derived from the first so the two cannot drift.

### The variable set is enumerated from the include closure, not from the files I knew about

The second CI run failed on `VMS_REGISTRY_ADMIN_API_KEY`, a variable the first
enumeration never saw. The cause was a bad assumption rather than a bad regex:
the survey scanned `docker-compose.yml` and the two files it includes, and
stopped. `compose.vms.yml` has its own `include:` — `compose.dev.yml` and
`domains/vms/compose.yml` — so the real closure is five files, not three, and
three required variables live in the level I did not look at.

The count is 18 required variables over 20 guard occurrences, and it is now
derived by resolving `include:` transitively the way compose does, rather than
by listing files. That is the difference between checking a set and checking
the set.

The three missed variables are also a different shape from the first fifteen.
Two are bearer tokens rather than paths, so "the path exists" was never going
to catch them; the verification now checks path existence only for variables
whose name marks them as a path, and presence for the rest.

### registry-b's bearer token has to agree in three places

`domains/vms/compose.yml` starts `registry-b` with both
`REGISTRY_REQUIRE_READ_API_KEY` and `REGISTRY_REQUIRE_WRITE_API_KEY` true, and
seeds it with `REGISTRY_BOOTSTRAP_API_KEY` so a fresh `compose up` needs no
out-of-band mint. `storefront.bob.toml` fans publishes and heartbeats to both
registries, and the buyer discovers from both. So the same token must appear as
the registry's seed, in the storefront's secret overlay, and in the buyer's
config.

All three come from one `Makefile` constant, because three hand-maintained
copies of a token that must be byte-equal is a latent failure: a mismatch
surfaces as a `401` during discovery or publication, several steps after the
thing that is actually wrong.

The storefront's copy lives in a secret overlay rather than in
`storefront.bob.toml`, matching the split that file already documents — which
registries demand a key is public and declared in the profile, the key itself
is not. For the buyer there is no overlay: its config file is the only one the
container mounts, so the development token sits in it and says so.

### Every compose invocation gets the env file, not just `up`

`docker compose down` and `docker compose logs` read and interpolate the same
config as `up`, so a required-variable guard blocks them too. The first wiring
passed `--env-file` only to `up`, leaving `down` — the recipe's own first line,
and the workflow's teardown and log-collection steps — able to fail on an
interpolation that has nothing to do with the run being cleaned up.

So the env file is generated as the recipe's first action and passed to every
compose call, and the workflow's `always()` steps regenerate it before their
own `down` and `logs`. That last part matters for debugging rather than
correctness: the log-collection step was producing a 148-byte artefact because
it could not read the config, which is why the first two failures had to be
diagnosed from the job log alone.

### The generated artefacts are ignored, the fixtures are tracked

`make e2e-dev-identities-env` creates `.e2e-buyer/{profile,state}` — compose
mounts them read-write into the buyer container — and writes
`.e2e-identities.env`. Both are generated and gitignored. The values they point
at are committed. That distinction is stated in `.gitignore` itself, because a
reader seeing `dev-env/identities` ignored alongside them would reasonably
conclude the identities were secret after all.

### `include` composes; `-f` overrides. The stack was using `include` for both

With the identities supplied, interpolation finally succeeded and compose got far
enough to fail on merge:

    services.registry conflicts with imported resource

`compose.vms.yml` `include`s `domains/vms/compose.yml` and then redefines five
services from it; `docker-compose.yml` does the same to
`domains/apicredits/compose.yml` for two more. `include` does not permit the
including file to redefine an imported service — that is `-f` layering's job,
where later files merge over earlier ones. Both files are byte-identical to the
original archive, so this is pre-existing and was simply unreachable: every run
failed at interpolation first.

The repository already demonstrates the correct split. The `hosted-stripe-test`
flow, which works, composes the same domain file as
`-f domains/vms/compose.yml -f compose.hosted-settlement.yml -f compose.vms-fiat.yml`,
and `compose.hosted-settlement.yml` uses the `!reset` tag, which only has meaning
in an `-f` overlay.

**Converting everything to `-f` was rejected.** With multiple `-f` files, compose
resolves relative paths against one project directory, and the two base files
need different ones: `domains/vms/compose.yml` references
`../../core/registry/...` and `./storefront/...` relative to `domains/vms`, and
`domains/apicredits/compose.yml` does the equivalent relative to
`domains/apicredits`. No single project directory satisfies both, so pure `-f`
layering would require rewriting the relative paths in both base files — and
that would break the `hosted-stripe-test` flow, which depends on the project
directory being `domains/vms`.

So each mechanism keeps the job it is good at. The base topology stays
`include`d, which is what preserves per-file path resolution. The development
bindings move to `compose.local-identities.yml`, layered with `-f`, which is
what makes overriding an imported service legal. Every path in the overlay
arrives as an absolute value from `make e2e-dev-identities-env`, so the overlay
has no relative paths and is indifferent to the project directory.

One consequence worth stating: a bare `docker compose up` at the repository root
now starts the stack *without* the development bindings, and a service needing a
signing credential fails at runtime rather than at interpolation. That is a real
regression in a UX nobody reported using — the maintainer deploys via the Helm
charts, and this compose stack is slated for replacement by a Tekton pipeline
over those charts. Both `include` files say so in a comment and point at the
two-file invocation.

**A remaining instance, deliberately not fixed:** `compose.apicredits.yml` has
the same `include`-plus-override shape and would fail the same way. It is a
separate entry point, not on the e2e path, and fixing it is not needed to
unblock. Recorded here so the next person to run it knows the cause rather than
rediscovering it.

### An eip191 address delivered by environment variable arrives as an integer

With the stack finally starting, `provisioning` failed its healthcheck on:

    eip191 identifier must be a 20-byte hexadecimal address
      [input_value='139084929578607176827638...50238675083608645509734']

That 48-digit decimal is `0xf39fd6e5…` — Anvil account 0 — converted to an
integer. The provisioning service loads configuration through Dynaconf, which
parses each environment value as TOML before handing it over, and
`0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266` is a valid TOML hexadecimal
integer literal. `_principal` then `str()`s it and gets decimal digits.

Reproduced directly rather than inferred:

    parse_conf_data('0xf39f…', tomlfy=True)        -> int
    parse_conf_data('@str 0xf39f…', tomlfy=True)   -> str

The three `PROVISIONING_*_IDENTITY__IDENTIFIER` values now carry Dynaconf's
`@str` marker. Scope was established rather than assumed:

- **The registries need no marker.** `core/registry` reads settings with
  `pydantic_settings`, which does no TOML parsing — and both registries
  reported healthy in the same run, which is the proof rather than the theory.
- **The signing credentials need no marker.** `identity.py` reads
  `ARKHAI_IDENTITY_CREDENTIAL` from `os.environ` directly, bypassing Dynaconf.
  Worth checking, because those values are also `0x`-prefixed and fixing only
  the identifiers would have moved the failure one step later.
- **The api-credits registry identifier is base64url**, so it never looked like
  a number. That is also why the `hosted-stripe-test` flow never hit this: its
  registries are configured with ed25519 identifiers.

This is pre-existing and was unreachable. The `PROVISIONING_*` values live in
the override block that `include` rejected outright, so they had never been
delivered to a container before.

A durable alternative would be to stop the shared loader TOML-parsing values
that feed identity fields, in `kit/config`. Not done here: it changes a loader
every service shares, to fix a development compose stack that is being replaced
by a Tekton pipeline over the Helm charts.

## Risks / Trade-offs

- **[A committed key is later used against a real network]** → Every file states
  it must not be, the values are recognisably Anvil accounts, and the one
  generated key is derived from a string containing "development". The residual
  risk is the same one the repository already carries by committing
  `.env.bob.docker`.
- **[A pin is missed when the API-credits identity changes]** → Fails closed at
  registry startup on the identity assertion, with the configured and derived
  principals both named. Loud, and the three known pins are updated together.
- **[The exported paths drift from the files]** → `make e2e-dev-identities`
  creates the writable buyer directories and names every path in one place, so a
  missing file surfaces as a compose mount error on the next run rather than as
  a stale export somewhere else.

## Open questions

- **Should the VM storefronts' wallet env files move into
  `dev-env/identities/`?** They currently live at
  `domains/vms/storefront/.env.{bob,alice}.docker` and are referenced in place.
  Consolidating would put all development material in one directory; leaving
  them avoids touching files that other flows may reference. Deferred — it is a
  tidiness question, not a correctness one.
