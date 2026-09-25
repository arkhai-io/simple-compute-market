# Development identities for the local compose stack

Every file in this directory is a **well-known deterministic development
value**. None of it is secret, none of it was ever secret, and none of it may
ever be used on a public network or against a real chain, registry, or
settlement authority.

The directory exists because `docker-compose.yml`, `compose.vms.yml`, and
`domains/apicredits/compose.yml` guard their signer and wallet mounts with
`${VAR:?...}`, so `docker compose up` refuses to start until each one is
supplied. Committing the development values is what lets anyone — a
contributor, a fork, or a CI job with no repository secrets — run
`make -C e2e-tests test-e2e`.

## Why the credential files carry no comment

`core/registry/src/main.py` reads a credential file with
`read_text().strip()` and passes the whole result to `create_signer`. A `#`
comment line inside one of those files would become part of the credential and
fail the signer construction. The fixture statement `AGENTS.md` requires
therefore lives here, and in the shell-format `*.env` files where a comment is
syntactically allowed. `api-credits-admin-key` is bare for the same reason:
`apicredits_middleware/config.py` reads it with `read_text().strip()` and
compares the whole value.

So the rule for this directory is: if a file is consumed as a single opaque
value, it holds only that value and its provenance is documented here; if it
is consumed as shell-format key/value pairs, it carries the statement inline.

## What this directory has to satisfy

`docker compose up` resolves `include:` transitively, so the required variables
come from five files, not from the root `docker-compose.yml` alone:
`docker-compose.yml`, `compose.vms.yml`, `compose.dev.yml`,
`domains/vms/compose.yml`, and `domains/apicredits/compose.yml`. Eighteen
variables over twenty guard occurrences. `make e2e-dev-identities-env` supplies
all of them.

Not all are paths. `VMS_REGISTRY_ADMIN_API_KEY` and
`VMS_REGISTRY_BOOTSTRAP_API_KEY` are bearer tokens for `registry-b`, which runs
with read and write gates both on. The bootstrap token must be byte-equal in
three places — the registry's seed, `bob.storefront.secrets.toml`, and
`buyer.config.toml` — so all three derive from one `Makefile` constant. A
mismatch shows up as a `401` during discovery or publication, well away from
its cause.

## Where each value comes from

`*.eip191` credentials are the standard Anvil development accounts from the
default `test test test ... junk` mnemonic. Their private keys are published in
Foundry's own documentation and already appear in this repository — for example
`domains/vms/storefront/.env.bob.docker` and
`core/registry/tests/integration/conftest.py`. The compose files pin the
matching addresses, and `core/registry/src/main.py` refuses to start if a
credential does not derive the pinned identifier, so these assignments are not
interchangeable:

| File | Anvil account | Pinned as |
|---|---|---|
| `registry-a.eip191` | 3 (`0x90f79bf6…`) | `compose.vms.yml` `registry-a` |
| `registry-b.eip191` | 4 (`0x15d34aaf…`) | `compose.vms.yml` `registry-b` |
| `provisioning.eip191` | 0 (`0xf39fd6e5…`) | `compose.vms.yml` `provisioning` |
| `bob.env` | 2 (`0x3c44cddd…`) | `storefront.bob.toml` |
| `alice.env` | 4 (`0x15d34aaf…`) | `storefront.alice.toml` |
| `buyer.eip191` | 1 (`0x70997970…`) | not pinned; the buyer declares its own profile |
| `provisioning-admin.eip191` | 5 (`0x9965507d…`) | `compose.local-identities.yml` `PROVISIONING_ADMIN_IDENTITY__IDENTIFIER` |
| `storefront-bob-admin.eip191` | 6 (`0x976ea740…`) | `storefront.bob.toml` `[Identity.administrators.operator]` |
| `storefront-alice-admin.eip191` | 7 (`0x14dc7996…`) | `storefront.alice.toml` `[Identity.administrators.operator]` |
| `api-credits.identity.env` | 3 (`0x90f79bf6…`) | `[identity]` in `storefront.credits.toml` |
| `api-credits.wallet.env` | 3 (`0x90F79bf6…`) | `[wallet].address` in `storefront.credits.toml` |

The three administrator credentials are separate principals from the sellers
and services they administer. A storefront's `Identity.principal` publishes
listings; its `Identity.administrators.operator` performs the system controls
that are not part of a deal. Provisioning draws the same line between its own
signing identity (account 0, which signs responses), the storefront principal
it accepts callbacks from (account 2), and the administrator that operates it
(account 5). Holding the wrong one of a pair authenticates as the wrong caller
and is refused on authorization, not at construction, so the failure surfaces
as a `403` some distance from the mistake.

The API-credits **storefront** and the API-credits **registry** are different
principals with different schemes: the storefront signs `eip191` as Anvil 3, the
registry signs `ed25519` as `_NUDEN…`. The shared name prefix makes them easy to
conflate, and `create_signer` refuses the wrong scheme outright rather than
producing a subtly wrong signature.

`bob.storefront.secrets.toml` and `buyer.config.toml` are configuration rather
than identity, and both carry their own explanation inline.

`api-credits-registry.ed25519` is the one value that had to be generated. The
identity previously pinned in the compose files had no committed private half
and could not be recovered, so this replaces it. It is derived deterministically
so any reader can reproduce it and confirm no secret is involved:

    python -c "import hashlib,base64; \
      print(base64.urlsafe_b64encode( \
        hashlib.sha256(b'arkhai-development-api-credits-registry-v1').digest() \
      ).rstrip(b'=').decode())"

Its public identifier `_NUDENxVX6u4cMd0xzoYyQAt10QDI47bfnYnu2lTVho` is pinned in
`docker-compose.yml`, `compose.apicredits.yml`, and
`domains/apicredits/storefront/storefront.credits.toml`. All three must agree or
the registry fails startup on the identity assertion.

## The API-credits site authority and its gated application

`api-credits-service.ed25519` and `api-credits-gated-app.ed25519` are the two
identities the API-credits service's signed boundary needs. Derived the same
deterministic way as the registry credential above, so any reader can
reproduce them and confirm no secret is involved:

    python -c "import hashlib,base64; \
      print(base64.urlsafe_b64encode( \
        hashlib.sha256(b'arkhai-development-api-credits-service-v2').digest() \
      ).rstrip(b'=').decode())"

    python -c "import hashlib,base64; \
      print(base64.urlsafe_b64encode( \
        hashlib.sha256(b'arkhai-development-api-credits-gated-app-v2').digest() \
      ).rstrip(b'=').decode())"

Their public identifiers:

| Credential | Public identifier | Role |
|---|---|---|
| `api-credits-service.ed25519` | `MheGyI4OZPRUijPSgdBucxha4zXw5mJ5hSELYon6x_c` | the authority itself — signs every response |
| `api-credits-gated-app.ed25519` | `w75DsOFODAFDR0gVcITNTSeEvG_SRQU9GyTulF2w7IM` | `service` — consumes and verifies credits |

`-v2`, not `-v1`, for a mundane reason worth recording: the `-v1` labels derive
a seed and a public identifier beginning with `-`, which shells, `getopt` and
compose variable expansion all read as the start of an option. A credential
that cannot be passed on a command line without quoting gymnastics is a
credential that will eventually be passed wrong.

The authority's identifier is pinned in `domains/apicredits/compose.yml` and in
`domains/apicredits/storefront/storefront.credits.toml`'s
`[capacity.sites.default.expected_authorities]`. Both must agree or the
storefront refuses the responses it receives.

The `service` role is narrow on purpose: it may spend credits and check them,
and may not mint or revoke. The storefront holds `seller` and does the
converse. That distinction is the reason there are two identities here rather
than one shared secret — `api-credits-admin-key` could not express it, and
every caller holding it could do everything.

Note the storefront's own principal is **eip191**, not ed25519: it signs with
`ARKHAI_IDENTITY_CREDENTIAL` from `api-credits.identity.env`, and the
authority's trust set names it with an explicit scheme for that reason.

## The bare-metal lane

The bare-metal end-to-end lane (`make -C e2e-tests test-e2e-bare-metal`) is a
separate stack on its own dev chain, so it reuses the committed credentials
above rather than adding more. `make e2e-bare-metal-dev-env` binds them, and the
lane's settings in `e2e-tests/config/config-docker.yml` pin the same identifiers:

| File | Anvil account | Bare-metal role |
|---|---|---|
| `registry-a.eip191` | 3 (`0x90f79bf6…`) | `bare-metal-registry`, authority `bare-metal-registry` |
| `provisioning.identity.env` | 0 (`0xf39fd6e5…`) | the site authority, `bare-metal-provisioning` |
| `bob.identity.env` | 2 (`0x3c44cddd…`) | the bare-metal storefront's principal and seller wallet |
| `provisioning-admin.eip191` | 5 (`0x9965507d…`) | the site's administrator |
| `storefront-bob-admin.eip191` | 6 (`0x976ea740…`) | the bare-metal storefront's administrator |
| `buyer.eip191` | 1 (`0x70997970…`) | the buyer |

The names are the VM stack's; the roles are the same kind in both stacks, which
is what makes the reuse safe. `dev-env/bare-metal/` holds the lane's other
development files — an empty host inventory, a pool document containing only the
required `default` pool with no deliverable or advertisable modes (scenarios
declare their own pools against the provisioning mock profile), and placeholders
for files the stack requires but the lane never uses — each explaining itself
inline.
