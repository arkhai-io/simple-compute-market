# Design — check storefront environment reads

Design phase; nothing decided.

## Context

Opened 2026-10-15 from design review 02 of `share-site-projection-state` (finding §8.1),
which asked for its open question about such a check to be settled. The owner chose to give the
check a change of its own rather than grow that change further.

The inventory taken during that triage, at `share-site-projection-state`'s reviewed design
commit, outside the bare-metal storefront (which that change rewrites onto file-based
configuration):

| Storefront | Read | Kind |
|---|---|---|
| VM | `ARKHAI_IDENTITY_CREDENTIAL` (`market_storefront/utils/config.py`) | the signing credential |
| VM | `K_SERVICE`, `K_REVISION` (`market_storefront/utils/logging_config.py`) | platform metadata selecting the log format on a managed runtime |
| VM | `os.environ.copy()` (`market_storefront/cli_common.py`) | the environment passed whole to a subprocess |
| VM | `environ=os.environ` (`market_storefront/groups/config.py`) | handed to the configuration migration's diagnostics, which name legacy variable names |
| API credits | `ARKHAI_IDENTITY_CREDENTIAL` (`apicredits_storefront/utils/config.py`) | the signing credential |

Every other setting reaches each storefront through its Dynaconf loader, whose environment
prefix is the documented override layer. Once bare metal complies, the tree passes a check
allowing exactly these reads.

The rule the check enforces is `deployment-state`'s "A storefront's configuration reaches it
through its configuration system", as `share-site-projection-state` states it: every
configuration value is supplied through the configuration files and the loader's override
layer, and a value is supplied outside that system only when it controls which configuration
is loaded (the configuration directory, the profiles to layer) or must be kept from the loader
(the signing credential). Platform facts such as `K_SERVICE`, an environment passed whole to a
subprocess, and legacy names quoted by a migration diagnostic are not configuration values. A
storefront never refuses to start because a value reached it through its environment: the check
is a compliance check of source and charts, and the loader's override layer stays available to
an operator.

## Questions to settle before planning

- **Where an allowed read is declared.** A table in the reading package's `pyproject.toml`,
  following the runtime-dependency precedent in `AGENTS.md`, or rows in a repository rules file
  such as `docs/development/ARCHITECTURE.toml`.
- **What counts as a read.** `os.environ`, `os.getenv`, `os.environ.copy()`, `environ`
  parameters defaulting to `os.environ`, and indirect access; and whether a read through
  `kit/config` (which resolves `XDG_CONFIG_HOME`) is the kit's to declare rather than each
  storefront's.
- **Scope.** Storefront packages only, or every service composition that reads application
  settings (the registry, the provisioning service, the API-credits service).
- **Enforcement point.** Its own target run by `make check-packaging`, or a rule inside
  `make check-architecture`.
- **Signing material.** Raised in `share-site-projection-state`'s design review 03 (F4). The
  marketplace credential is correctly kept from the loader, but it travels in
  `ARKHAI_IDENTITY_CREDENTIAL`, the weakest of `market_identity.credentials`' providers: an
  environment variable is inherited by every subprocess (VM's `run_step` copies the environment
  into the subprocesses it launches), readable from `/proc/<pid>/environ` by the same user, and
  prone to appear in dumps; the identity kit's strict owner-only file provider would keep it out
  of the environment as well, with only its path in configuration. Meanwhile the EVM wallet's
  private key, which signs fund-moving transactions, travels through the loader in
  `storefront.secrets.toml`, reachable by `config show` and `config migrate`. Decide whether this
  change's rule, written as a check, accepts both as they stand, or whether resolving storefront
  signing material through the identity kit's providers must precede it; as stated, the rule
  expects a value kept from the loader to have a reason, and the wallet key's inclusion has
  none on record.
