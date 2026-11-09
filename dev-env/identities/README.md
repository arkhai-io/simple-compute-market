# Development identities for the local compose stack

Every file in this directory is a **well-known deterministic development
value**. None of it is secret, none of it was ever secret, and none of it may
ever be used on a public network or against a real chain, registry, or
settlement authority.

The directory exists because the base compose files hold topology only and
give no service a fallback identity: each stack's development overlay binds the
files here, so its services start, and without an overlay they refuse to.
Committing the development values is what lets anyone — a contributor, a fork,
or a CI job with no repository secrets — run `make -C e2e-tests test-e2e`.
Beside it, `dev-env/registry/` holds the registries' profiles and
`dev-env/provisioning/` the provisioning services' site profiles, public
development values of the same kind, each labelled inline.

## Why the credential files carry no comment

`core/registry/src/core_registry/main.py` reads a credential file with
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

## What each stack binds

`docker compose up` resolves `include:` transitively and merges every `-f`
overlay in order. Every stack's configuration is in its committed files: the
overlays bind this directory's files by paths relative to the repository root,
the registries load their profiles from `dev-env/registry/` by
`ACTIVE_PROFILES`, and the provisioning services load their site profiles from
`dev-env/provisioning/`. The one value a run supplies is `PROVISIONING_MODE`,
`mock` unless it says `real`, which the provisioning services take as their
last profile.

| Stack | Files | Registry profiles | Site profiles | Secret overlays |
|---|---|---|---|---|
| VM lane | `compose.vms.yml` (with `compose.dev.yml` and `domains/vms/compose.yml`), `compose.vms-local.yml`, `compose.payments-double.yml`, `compose.vms-lane.yml` | `registry-a`, `registry-b`, each with `payments-lane` | `vms-bob-site`, `vms-alice-site` | `bob.storefront.secrets.toml`, `alice.storefront.secrets.toml` |
| API-credit lane | `compose.apicredits.yml` (with `compose.dev.yml` and `domains/apicredits/compose.yml`), `compose.apicredits-local.yml`, `compose.payments-double.yml`, `compose.apicredits-lane.yml` | `api-credits-registry`, `compute-registry`, each with `payments-lane` | — | `api-credits.storefront.secrets.toml` |
| Bare-metal lane | `compose.bare-metal.yml`, `compose.dev.yml`, `compose.payments-double.yml`, `compose.bare-metal-local.yml` | `bare-metal-registry` with `payments-lane` | `bare-metal-site` | `bare-metal.storefront.secrets.toml` |
| Full local stack | `docker-compose.yml`, `compose.vms-local.yml`, `compose.apicredits-local.yml` | `registry-a`, `registry-b`, `api-credits-registry` | `vms-bob-site`, `vms-alice-site` | `bob.storefront.secrets.toml`, `alice.storefront.secrets.toml`, `api-credits.storefront.secrets.toml` |

Not every value is a file. `registry-b` runs with read and write gates both on,
and its admin and bootstrap bearer tokens are in its profile,
`dev-env/registry/config-registry-b.env`. The bootstrap token must be byte-equal
in four places — that profile, `bob.storefront.secrets.toml`,
`buyer.config.toml`, and the test runner's `registry.bootstrap_api_key` in
`e2e-tests/config/config-docker.yml`. A mismatch shows up as a `401` during
discovery or publication, well away from its cause.

A storefront's secrets — its wallet key, and where it settles payments, its
payments key and dispute credentials — are settings in its secret overlay,
`storefront.secrets.toml`, never variables in its environment. The one secret
in the environment is the signing credential, `ARKHAI_IDENTITY_CREDENTIAL`,
which each `*.identity.env` here carries and which the loader never reads.

## Where each value comes from

`*.eip191` credentials are the standard Anvil development accounts from the
default `test test test ... junk` mnemonic. Their private keys are published in
Foundry's own documentation and already appear in this repository — for example
`core/registry/tests/integration/conftest.py`. The registry and site profiles
pin the matching addresses, and `core/registry/src/core_registry/main.py`
refuses to start if a credential does not derive the pinned identifier, so these
assignments are not interchangeable. Repository tests
(`scripts/tests/test_committed_stack_values.py`) hold each profile's pins to the
credential its stack binds:

| File | Anvil account | Pinned as |
|---|---|---|
| `registry-a.eip191` | 3 (`0x90f79bf6…`) | `dev-env/registry/config-registry-a.env` |
| `registry-b.eip191` | 4 (`0x15d34aaf…`) | `dev-env/registry/config-registry-b.env` |
| `provisioning.identity.env` | 0 (`0xf39fd6e5…`) | `identity` in `dev-env/provisioning/config-vms-bob-site.yml` |
| `bob.identity.env` | 2 (`0x3c44cddd…`) | `storefront.bob.toml`, and `storefront_identity` in `config-vms-bob-site.yml` |
| `alice.identity.env` | 4 (`0x15d34aaf…`) | `storefront.alice.toml`, and `storefront_identity` in `config-vms-alice-site.yml` |
| `buyer.eip191` | 1 (`0x70997970…`) | not pinned; the buyer declares its own profile |
| `provisioning-admin.eip191` | 5 (`0x9965507d…`) | `admin_identity` in each site profile |
| `storefront-bob-admin.eip191` | 6 (`0x976ea740…`) | `storefront.bob.toml` `[Identity.administrators.operator]` |
| `storefront-alice-admin.eip191` | 7 (`0x14dc7996…`) | `storefront.alice.toml` `[Identity.administrators.operator]` |
| `api-credits.identity.env` | 3 (`0x90f79bf6…`) | `[identity]` in `storefront.credits.toml` |
| `api-credits.storefront.secrets.toml` | 3 (`0x90F79bf6…`) | `[wallet].address` in `storefront.credits.toml` |
| `bob.storefront.secrets.toml` | 2 (`0x3C44CdDd…`) | `[Wallet].address` in `storefront.bob.toml` |
| `alice.storefront.secrets.toml` | 4 (`0x15d34AAf…`) | `[Wallet].address` in `storefront.alice.toml` |
| `bare-metal.storefront.secrets.toml` | 2 (`0x3C44CdDd…`) | `[Wallet].address` in `domains/bare_metal/storefront/storefront.dev.toml` |

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

The `*.storefront.secrets.toml` overlays, `buyer.config.toml`, and
`api-credits-buyer.config.toml` are TOML configuration, and each carries its own
explanation inline.

`api-credits-registry.ed25519` is the one value that had to be generated. The
identity previously pinned in the compose files had no committed private half
and could not be recovered, so this replaces it. It is derived deterministically
so any reader can reproduce it and confirm no secret is involved:

    python -c "import hashlib,base64; \
      print(base64.urlsafe_b64encode( \
        hashlib.sha256(b'arkhai-development-api-credits-registry-v1').digest() \
      ).rstrip(b'=').decode())"

Its public identifier `_NUDENxVX6u4cMd0xzoYyQAt10QDI47bfnYnu2lTVho` is pinned in
`dev-env/registry/config-api-credits-registry.env`, `domains/apicredits/storefront/storefront.credits.toml`,
and the buyers' pins (`api-credits-buyer.config.toml` and the e2e settings). The
registry fails startup unless its credential derives the identifier its profile
pins, and the storefront and buyers refuse a registry that answers as another.

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
above rather than adding more. `compose.bare-metal-local.yml` binds them, with
the registry's profile `config-bare-metal-registry.env` and the site's
`config-bare-metal-site.yml` pinning their identities; the storefront's
development configuration
(`domains/bare_metal/storefront/storefront.dev.toml`, with
`bare-metal.storefront.secrets.toml` as its secrets overlay) names the public
principals, and the lane's settings in `e2e-tests/config/config-docker.yml` pin
the same identifiers:

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
development files — an empty host definitions document, a pool document containing only the
required `default` pool with no deliverable or advertisable modes (scenarios
declare their own pools against the provisioning mock profile), and placeholders
for files the stack requires but the lane never uses — each explaining itself
inline.

## The API-credit lane

The API-credit end-to-end lane (`make -C e2e-tests test-e2e-apicredits`) is a
separate stack on its own dev chain. Its credits scenario routes discovery by
schema across two registries, so the lane runs a compute-schema registry of its
own, `compute-registry`, declared in `compose.apicredits-lane.yml`, beside the
API-credit registry. It reuses a committed credential rather than adding one:

| File | Anvil account | API-credit lane role |
|---|---|---|
| `registry-a.eip191` | 3 (`0x90f79bf6…`) | `compute-registry`, authority `compute-registry` |

Anvil 3 is also the credits storefront's principal, as it is in the full local
stack, where VM's `registry` signs with the same key: a registry and a storefront
authenticate different roles, so sharing a development key does not let either
stand in for the other. `compose.apicredits-lane.yml` binds the credential, its
profile `dev-env/registry/config-compute-registry.env` pins the identifier, and
the lane's settings in `e2e-tests/config/config-docker.yml` pin the same one. The full local stack has VM's compute registry and never layers
`compose.apicredits-lane.yml`.

## The payments lane double

Each lane runs the payments and mediation lane doubles
(`compose.payments-double.yml`). Its payment storefront — Bob's VM storefront,
the bare-metal storefront, the credits storefront — settles against the payments
double, and its registries recommend the mediation double as the dispute
authority. Each double's own values live with it, in
`tools/payments-lane-double/fixtures/` and `tools/mediation-lane-double/fixtures/`,
documented in their READMEs ([payments](../../tools/payments-lane-double/README.md),
[mediation](../../tools/mediation-lane-double/README.md)): the receipt-signing seed
and identity, the payments accounts and bearer tokens, the dispute authority's
identity and record key, and each party's mediation token. The lane CA both serve
under is generated in
`tools/lane-double-controls/tls/` ([README](../../tools/lane-double-controls/README.md#tls)).
Where a stack needs one of them, a
committed file here or beside a stack restates it, and repository tests hold
each restatement to its fixture:

| Restated value | Where | Role |
|---|---|---|
| the seller's bearer token | `[Settlement.arkhai_payments].api_key` in `bob.storefront.secrets.toml`, `bare-metal.storefront.secrets.toml` and `api-credits.storefront.secrets.toml` | each lane storefront's payments key at the payments double |
| the dispute authority | `dev-env/registry/config-payments-lane.env` | the lanes' registries' recommended dispute authorities, one JSON line, the mediation double's identity |
| the dispute authority's payments token | `[accounts.dispute_authority].token` in `tools/payments-lane-double/fixtures/accounts.toml` | the token the mediation double extends, reverses and lifts with at the payments double |
| the seller's mediation token | `[[DisputeCredential]]` in `bob.storefront.secrets.toml`, which `helm/scripts/topology-secrets.sh` copies into the local Helm release's `arkhai-bob-runtime` | Bob's credential toward the mediation double, bound to its identity, with the lane CA's path as its `ca_bundle_path` |
| the lane CA's path | `ca_bundle_path` in each lane storefront configuration and in Bob's dispute credential | where each lane overlay binds `tools/lane-double-controls/tls/lane-ca.pem` |

The test runner reads the lanes' payments and mediation settings from committed
profiles, which restate the doubles' values too:
`e2e-tests/config/config-payments-lane.yml` each double's target, CA path and
control token, the payments accounts and the buyer's payments token, and the
dispute authority's account and record key and the buyer's mediation token; and
each `config-<lane>-lane.yml` the seller credential of the lane's storefront, its
key in `bob.identity.env` or `api-credits.identity.env`.
`tools/payments-lane-double/tests/integration/test_lane_env.py` and
`tools/mediation-lane-double/tests/unit/test_lane_profile.py` hold each to its
source.

The lane values that are not the double's:

| Value | Where | Role |
|---|---|---|
| 32 bytes of `0xb1`, as unpadded base64url | `buyer_marketplace_credential` in `e2e-tests/config/config-payments-lane.yml` | the payment scenarios' wallet-free Ed25519 buyer marketplace seed |
| `bob.identity.env`, `api-credits.identity.env` | this directory, restated in each `config-<lane>-lane.yml` | the seller credential a payment scenario refunds with: each lane storefront's own key, in its own scheme |

The full local stack mounts the same secret overlays. There the storefront
configurations leave payments off, and its registries recommend no dispute
authority, so the payments key and Bob's dispute credential are never used.

The VM and API-credit lanes run their own copies of the storefront profiles the
full local stack runs, `domains/vms/storefront/storefront.bob.lane.toml` and
`domains/apicredits/storefront/storefront.credits.lane.toml`, which add payments
and nothing else, so the full stack keeps running without them; each lane
overlay mounts its copy in place of the profile. The bare-metal lane's
`domains/bare_metal/storefront/storefront.dev.toml` is the only deployment that
file configures, so it carries payments itself.

## Alice's provisioning authority

`provisioning-alice.identity.env` contains a public deterministic Ed25519 seed:
SHA-256 of the UTF-8 string `arkhai-development-alice-provisioning-v1`, encoded
as unpadded base64url. It must never be used on a public network. Its public
identifier is `3NPn0gInwKKqVkrFl5_C07yYcjLOfVszbq51kw6EnPw`.

Alice's site profile, `dev-env/provisioning/config-vms-alice-site.yml`, her
storefront profile, and the Docker test profile pin that identity. Alice's authority trusts Alice's seller principal
(Anvil 4) and the provisioning administrator (Anvil 5); Bob's authority retains
its own signer (Anvil 0). The two services have separate databases, process-local job queues,
and callback destinations. Sharing an administrator does not share a service
identity or authorize either storefront to call the other's authority.
