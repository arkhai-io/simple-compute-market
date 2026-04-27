# Buyer/storefront split — plan and context

Working notes for splitting the buyer client and provider storefront
into separate installable packages, and the related cleanups that fall
out of that work. Written 2026-04-27.

This is an intermediate-resolution working doc, intended to survive
context compactions. Sections include enough background that picking
up mid-flow doesn't require re-deriving conclusions from a fresh
codebase read.

A note on terminology: this codebase grew up around Google ADK / A2A
and inherited names like "agent", "core", "common" from that era. The
A2A runtime is gone (`core/agent/app/server.py:18-20` says so
explicitly: *"no A2A or Google ADK machinery runs underneath it
anymore"*). The plan moves naming away from those:

- "core" → unused; the seller's runtime is now a **storefront**.
- "agent" (the seller server) → **storefront**.
- "common" + "service" (which were a muddy split) → collapsed into
  **infra** ("how to talk to the shared infra").

Concretely the four user-visible components are:

1. **Configurable, deployable shared infra** — chain, contracts,
   off-chain registry indexer, plus the client libraries that all
   parties use to talk to those.
2. **Learned policy** — symmetric engine + (eventually) trained
   models. Used by both buyer and provider.
3. **Provider services** — provisioning service, storefront server,
   provider admin CLI.
4. **Buyer client** — buyer CLI.

---

## Origin

Two questions surfaced in conversation that turned out to be linked:

1. **Config**: a coworker pointed out that `provisioning-service/` and
   `integration-tests/` already have a profile-based YAML config
   system (Dynaconf). They suggested the storefront migrate the new
   `~/.config/arkhai/config.toml` (XDG/TOML) onto it for Helm
   friendliness.
2. **Packaging**: would it make sense to ship buyer and provider as
   separate binaries so install/setup can diverge, with provider+buyer
   users installing both?

These compose: the storefront wants Helm-friendly mounted YAML
profiles in prod; the buyer wants a single user-level TOML on a
developer laptop. That's two different config use cases, which lines
up cleanly with two different installables.

A third thread emerged while investigating:

3. **Policy engine**: the policy engine in `core/agent/app/policy/` is
   designed symmetric (buyer or provider can drive negotiation through
   it). The `cli/market/buyer_client.py` stub policy and the
   `core/agent/app/utils/sync_negotiation.py` hand-inlined
   `decide_response` bypass the engine for incidental reasons
   (decoupling from `DecisionContext`/`InvocationContext` during the
   A2A removal), not because the engine is incompatible with the
   request/response transport. This reinforces the case for a shared
   `market-policy` package.

---

## Current code shape (as of commit 13e3547 on `fix/quickstart-mac-compat`)

### Packages and their dependencies

```
cli/pyproject.toml          → market-cli       (buyer-shaped CLI)
core/pyproject.toml         → market-core      (storefront server + orchestrator)
service/pyproject.toml      → market-service   (chain/alkahest clients)
agent-client/pyproject.toml → arkhai-agent-client (async HTTP client to local storefront)
provisioning-service/pyproject.toml → provisioning_service
integration-tests/pyproject.toml    → (test harness)
erc-8004-registry-py/pyproject.toml → erc_8004_registry (off-chain registry server)
```

Operator-run deployables (not Python deps):

- `erc-8004-registry-py/` — FastAPI + SQLAlchemy off-chain registry
  indexer. Has its own `Dockerfile`, `docker-compose.yml`, and
  `helm/charts/registry/` chart. This is the non-blockchain shared
  deployable: the operator runs it; everyone else queries it via
  HTTP.
- `market-contract-deployer/` — operator tool to deploy ERC-8004 +
  Alkahest contracts to a chain.
- `compute-provisioning-iac/` — **git submodule** at
  `https://github.com/arkhai-io/compute-provisioning-iac.git`,
  currently checked out on branch
  `codex/full-stack-production-deployment` (`+85c6013`). Terraform +
  Ansible for KVM VM lifecycle (multi-tenant, GPU passthrough, FRP
  remote SSH). It's a **runtime dependency of provisioning-service**,
  not the storefront. `provisioning-service/src/settings.toml:34-36`
  hardcodes paths under `/opt/compute-provisioning-iac/ansible/...`;
  `provisioning_service.py:77` shells out to `ansible-playbook`
  against this submodule. The storefront never touches it directly —
  it talks HTTP to provisioning-service.

Dependency edges (today, Python only):

- `core` → `cli` (!)  — runtime dep, only because
  `core/agent/app/utils/config.py:43` imports
  `market.config_loader.{get_dotted, load_user_config}`.
- `core` → `service`
- `core` → `provisioning-service` (client side)
- `core` → `arkhai-agent-client`
- `cli` → `service`

Helm charts (operator + provider deployments):

```
helm/charts/registry/        — operator: off-chain registry indexer
helm/charts/provisioning/    — provider: provisioning service
helm/charts/agents/          — provider: storefront (will be renamed)
helm/charts/validate-contracts/  — operator/CI: contract validation
helm/charts/test-env/        — CI: bring up a full stack for tests
```

### Server shape (the "agent")

`core/agent/app/server.py` re-exports `a2a_app` from `agent.py`.
The name is historical — `core/agent/app/server.py:18-20` says
explicitly *"no A2A or Google ADK machinery runs underneath it
anymore."* It's a plain Starlette ASGI app and what we're calling the
**storefront**.

Endpoints (`core/agent/app/agent.py`):

- `/orders/{create,close,refund,claim,reclaim,arbitrate,discover}`
- `/negotiate/new`, `/negotiate/{neg_id}` (continue)
- `/settle/escrow`, `/settle/status`
- `/alerts/resource`
- `/.well-known/erc-8004-registration.json`,
  `/.well-known/agent-wallet.json`

Dead deps to drop later: `google-adk[a2a]`, `a2a-sdk` in
`core/pyproject.toml`. Only residue is a historical comment at
`core/agent/app/agent.py:357`.

### Policy engine shape

`core/agent/app/policy/__init__.py`: *"Domain-agnostic policy
utilities for core agent runtime."*

Engine pieces (role-agnostic):

- `registry.py` — `@policy_callable` + `CALLABLE_REGISTRY`
- `discovery.py` — module import for decorator side effects
- `store.py`, `composite.py`, `manager.py` — register/compose/evaluate
- `evaluator.py`
- `action_builders.py:21` — explicit symmetric assumption
  (*"Sorts the IDs so both sides of a bilateral negotiation always
  produce…"*)
- `negotiation_thread.py` — symmetric data model
  (`round`, `sender`, `our_price`, `their_price`, `proposed_price`,
  `action_taken`)

Asymmetric pieces (today):

- `seeding.py` — `ComputePolicySeeder`, three provider-side triggers:
  `ORDER_CREATE`, `ORDER_CLOSE`, `RESOURCE_IMBALANCE`. The file's
  docstring (lines 16–30) is the smoking gun for *why* it's
  provider-only: *"After the A2A removal and the buyer-as-client
  refactor, the surviving policy triggers are the local events a
  seller still reacts to…"*

### Sync negotiation bypass

`core/agent/app/utils/sync_negotiation.py` (383 lines) implements the
provider's negotiation decision inline (`decide_response`,
`SellerDecision` dataclass) instead of going through the policy
engine.

Top-of-file comment (lines 21–25) makes the intent explicit:

> *"The decision logic (decide_response) is a thin port of the legacy
> policy callable at `domain/compute/agent/app/policy/store.py`, with
> no dependency on the event pipeline, DecisionContext, or
> InvocationContext."*

And lines 38–41:

> *"Same constants as the legacy policy path. Keeping them local so
> the sync path is self-contained; when we eventually delete the
> legacy respond_to_make_offer function we can pull any tuned values
> forward."*

Constants: `DEFAULT_MAX_ROUNDS = 10`, `DEFAULT_CONVERGENCE_RATIO = 0.01`.

The `/negotiate/new` and `/negotiate/{neg_id}` endpoints in
`agent.py` (lines 1606–1745) call `start_sync_negotiation` and
`continue_sync_negotiation` directly. The engine is never consulted
on the negotiation path.

### Buyer-side policy

`cli/market/buyer_client.py:121` ("Pure buyer-side policy"). Simple
ceiling-with-midpoint-counter; comment notes *"Fancier buyer
strategies [TBD]."* Used inline by `cli/market/groups/negotiate.py:71`.
Does not touch the engine.

### Two config systems

**System A — XDG TOML** (the new one):

- Loader: `cli/market/config_loader.py` (~280 LOC, Python stdlib
  `tomllib` + hand-rolled writer).
- Path: `$XDG_CONFIG_HOME/arkhai/config.toml`.
- Sections: `[wallet]`, `[chain]`, `[registry]`, `[seller]` (with
  nested `[seller.provisioning]`, `[seller.redis]`,
  `[seller.negotiation]`).
- Consumers: CLI directly; storefront via
  `core/agent/app/utils/config.py:43` (the cross-package import).
- Tests: `cli/tests/test_config_loader.py` (~250 LOC),
  `core/tests/unit/test_config_toml_fallback.py` (~260 LOC).
- Recent commits: `9659f8f` (Apr 24, "feat(config): XDG-aware user
  config.toml + unified resolver"), `9046b6a` (Apr 24, "feat(config):
  seller agent reads from same user TOML").

**System B — Dynaconf profiles** (the coworker's):

- Loaders: `provisioning-service/src/config.py` and
  `integration-tests/src/settings.py` (~100 LOC each, copy-pasted, not
  shared as a library).
- Profile selection: `ACTIVE_PROFILES` env var (comma-separated),
  `CONFIG_DIRECTORY` env var. Integration tests also expose pytest
  flags `--profile` / `--config-dir` (registered in
  `integration-tests/conftest.py:18-42`).
- Layering (deep-merged in order): `settings.toml` (defaults) →
  `.secrets.toml` (optional) → `config.yml` (base) →
  `config-<profile>.yml` per active profile → env vars
  (`PROVISIONING_*` / `ARKHAI_*`, with `__` for nested keys).
- Helm integration:
  `helm/charts/provisioning/templates/configmap.yaml` renders
  `Values.config` into `config-production.yml`. Deployment mounts it
  at `/app/config/`, sets `ACTIVE_PROFILES=production,
  provisioning-secrets`. Secrets ride in via a separate Helm Secret
  as a sibling YAML file.

**Verdict for split**: keep both. They solve different problems
(developer-laptop config vs. deployment-environment config). The
Helm-mount story is what the storefront in production needs; the
user-level TOML stays right for the buyer CLI.

### Install footprint

`install.sh` flow:

- Always: `uv sync --no-dev` on `core/` (installs both `market-cli`
  and `market-core` into one venv).
- Default (buyer): `market install` sets a role marker, prints env
  checklist, exits.
- `market install --seller`: also runs `make install` in
  `core/agent/`, `erc-8004-registry-py/`,
  `erc-8004-contracts/` (`npm install`), and optionally ZeroTier.

Sizes (rough):

- Buyer-only venv: ~500–700 MB (alkahest-py wheels + web3 + typer +
  YAML).
- Provider addition: ~2–3 GB (Torch, Pufferlib, ADK [dead], Uvicorn,
  psycopg2, FastAPI, Wandb, google-cloud-*) plus registry indexer
  (~400 MB) plus contracts (~200 MB Node modules).

Buyer-only heavy deps: `pyinstaller` (binary build), `alkahest-py`
(wheel).
Provider-only heavy deps: Torch + Pufferlib + Wandb (`[rl]` extras),
psycopg2, Redis client, FRP/Ansible glue, google-cloud-*, otel.

---

## Target architecture

Five Python packages with downward-only dependencies:

```
                  ┌──────────────────┐
                  │   market-infra   │  config (TOML+Dynaconf), role marker,
                  │                  │  chain/alkahest/token clients,
                  │                  │  registry-indexer client
                  └────────┬─────────┘
                           │
                  ┌────────┴─────────┐
                  │  market-policy   │  symmetric engine: registry, discovery,
                  │                  │  store, composite, manager, evaluator,
                  │  + [rl] extra    │  negotiation_thread, action_builders
                  └────┬─────────┬───┘
                       │         │
            ┌──────────┘         └────────────┐
            │                                  │
    ┌───────┴────────┐              ┌──────────┴──────────┐
    │  market-buyer  │              │ market-storefront   │  Starlette server +
    │   (CLI)        │              │  (server + provider │  provider admin CLI
    │                │              │   admin CLI in one  │  + ComputePolicySeeder
    │                │              │   pkg)              │  (provider-domain seeding)
    └────────────────┘              └─────────┬───────────┘
                                              │ HTTP
                                    ┌─────────┴──────────────┐
                                    │ provisioning-service   │  separate deployable
                                    │  (existing, Helm/IaC)  │
                                    └────────────────────────┘
```

Operator-run deployables, not Python deps anyone installs into a
venv:

- `erc-8004-registry-py/` — off-chain registry indexer (FastAPI +
  SQLAlchemy). Helm chart: `helm/charts/registry/`.
- `market-contract-deployer/` — operator tool to deploy chain
  contracts.
- `erc-8004-contracts/` — Solidity sources + ABIs.
- `compute-provisioning-iac/` — Ansible/Terraform applied by
  provisioning-service to KVM VMs.

A user who is provider-only installs `market-storefront` (which pulls
in `market-infra` + `market-policy` transitively). A user who is
buyer-only installs `market-buyer`. A user who's both installs both —
they share `market-infra` and `market-policy` so there's no
duplicated download.

`provisioning-service`, `integration-tests`, `erc-8004-registry-py`,
`agent-client` keep their current package boundaries.

### Naming rationale

- **`market-infra`** — replaces both the old `market-service` and the
  briefly-considered `market-common`. Captures everything to do with
  *talking to the shared infra*: chain RPC + contract clients
  (alkahest, token registry), the off-chain registry indexer client,
  shared config loader, role marker. Earlier draft split this into
  "common" (config + role) and "service" (chain clients), but the
  distinction wasn't real; both are "stuff every party needs to
  participate in the market."
- **`market-policy`** — the symmetric negotiation engine. Domain-
  agnostic by design; both buyer and storefront call into it.
- **`market-buyer`** — was just `market` in earlier drafts. Renamed
  for symmetry with `market-storefront` and to make the install
  surface unambiguous.
- **`market-storefront`** — replaces "market-agent". Says what it
  does: hosts the provider's order book and accepts buyer requests.
  The provider admin CLI (currently `market provide` / `start` /
  `register`) folds in here as a console_script — same package
  because it shares config, identity, and SQLite state with the
  server.

### Why this shape

- The `core → cli` runtime dep (config loader import) is the single
  load-bearing coupling that makes "buyer-only" actually impossible
  today. Extracting `config_loader.py` + `role.py` into
  `market-infra` cuts it.
- The policy engine is already domain-agnostic
  (`policy/__init__.py` literally says so) and symmetric in its data
  model. Both buyer and storefront would benefit from going through
  it. Putting it in its own package makes that explicit.
- Config systems A and B both live in `market-infra`, but each is
  used by the right consumer: TOML for the buyer CLI, Dynaconf
  profiles for the storefront in containerized/Helm contexts.

### What about a separate provider admin CLI package?

Considered briefly. Rejected: the admin CLI shares its SQLite state,
identity (wallet/agent_id), and config with the server it manages.
Splitting them into separate packages would mean re-implementing
that shared state across a package boundary for no real win.
`market-storefront` ships both as one wheel with two console scripts
(`market-storefront serve`, `market-storefront register`, etc.).

### What about training vs. inference of learned policies?

Open question; deferred. Two options:

- Keep all of it in `market-policy`, with `[rl]` for training-only
  deps (Pufferlib, Wandb) and Torch in the base deps for inference.
  Simple, but means buyer CLI installs Torch.
- Split: `market-policy` (engine, no Torch) and `market-policy-rl`
  (training + inference, optional install on either side). Buyers
  who want a learned policy install the extra; basic buyers stay
  light.

Default to the second once we actually have a buyer-side trained
policy. Until then, all training stays provider-side.

---

## Plan (ordered)

Each step is independently mergeable. Stop after any of them and the
codebase is still in a consistent state.

### Step 0 — drop dead deps

- Remove `google-adk[a2a]` and `a2a-sdk` from `core/pyproject.toml`.
- Update the historical comment at `core/agent/app/agent.py:357`
  (or remove it).
- Re-run `uv sync` and the test suite to confirm nothing imports
  them.

Unblocks: nothing strictly, but cleans noise before the bigger moves.
Effort: 30 min.

### Step 1 — create `market-infra`, break `core → cli` import

- New package `infra/pyproject.toml` (or pick a directory name —
  `market-infra/` is fine).
- Move into it:
  - Everything currently in `service/` (chain/alkahest/token clients,
    indexer client). Rename Python module from whatever it is today
    to `market_infra`.
  - `cli/market/config_loader.py` →
    `infra/market_infra/config_loader.py`.
  - The role marker logic (`cli/market/role.py` if separate, or
    wherever `market install --seller` writes the marker file) →
    `infra/market_infra/role.py`.
- Update `cli/market/__init__.py` to re-export from `market_infra`
  for backward compatibility (CLI users importing
  `market.config_loader` still work during transition).
- Update `core/agent/app/utils/config.py:43` to import from
  `market_infra.config_loader` directly.
- Drop `market-cli` from `core/pyproject.toml`'s deps; add
  `market-infra`.
- Existing `service/` consumers in `core/` and `cli/` repoint to
  `market_infra` imports.
- Update the existing tests
  (`cli/tests/test_config_loader.py`,
  `core/tests/unit/test_config_toml_fallback.py`) to import from the
  new location, or keep them where they are if the re-export shim
  works.

Verify: `uv run python -c "import core.agent.app.agent"` from a venv
that has only `market-core` + `market-infra` installed (no
`market-cli`).

Unblocks: separately installable buyer / storefront wheels.
Effort: half a day to a day (collapsing the old service/ package
into infra adds ~half a day on top of the original common-extraction
plan).

### Step 2 — extract `market-policy`

- New package `policy/pyproject.toml`.
- Move `core/agent/app/policy/` (entire directory) →
  `policy/market_policy/` **except** for `seeding.py` (the
  `ComputePolicySeeder` is genuinely provider-domain and stays in
  the storefront package).
- `negotiation_thread.py` currently imports `CONFIG.agent_id` /
  `CONFIG.base_url_override` from `core/agent/app/utils/config.py`.
  Change it to take these as constructor/init args, or as a small
  `Identity` dataclass injected by the caller, so the engine has no
  dep on storefront runtime config.
- Update all `from core.agent.app.policy.X import Y` to
  `from market_policy.X import Y` (lots of touch points; mechanical).
- Add `market-policy` as a dep in `core/pyproject.toml` and
  `cli/pyproject.toml`.
- Tests: any `core/tests/` that exercise the engine in isolation
  move to a `policy/tests/` directory.

Verify: existing storefront integration tests pass unchanged. Buyer
CLI imports run.

Unblocks: rewiring `sync_negotiation` through the engine; buyer-side
learned policies.
Effort: 1 day (mostly mechanical rename, plus the
`negotiation_thread` decoupling).

### Step 3 — re-front `sync_negotiation` through the engine

- Convert the `decide_response` body in
  `core/agent/app/utils/sync_negotiation.py` into a registered policy
  callable (e.g. `negotiation.seller_default.v1`) living in
  `core/agent/app/policy_callables/` (a new module that gets imported
  for its decorator side effects, mirroring how the existing seeders
  work).
- Add a `NEGOTIATION_ROUND` (or similar) trigger type to the engine
  if one doesn't already fit.
- Build a small sync-friendly context object in the
  `negotiate_new_endpoint` / `negotiate_continue_endpoint` handlers
  and call `policy_store.evaluate_policy(trigger=…, context=…)`.
- Delete the inline `decide_response`, `SellerDecision` dataclass,
  and the duplicated constants. The file's own comment at lines
  38–41 anticipates this cleanup.
- Same `DEFAULT_MAX_ROUNDS = 10` and `DEFAULT_CONVERGENCE_RATIO =
  0.01` values, just sourced from the policy callable instead of the
  sync module.

Verify: existing negotiation integration tests pass. Round-trip a
negotiation locally and confirm the action sequence matches the
pre-rewiring behavior.

Unblocks: buyer-side use of the same engine for its own negotiation
policy. Lets us swap in trained policies on either side without
touching transport code.
Effort: 1 day.

### Step 4 — buyer adopts the engine

- Convert `cli/market/buyer_client.py:121`'s ceiling+midpoint logic
  into a `@policy_callable("negotiation.buyer_default.v1")` registered
  in a buyer-side seeder.
- Have `cli/market/groups/negotiate.py:71` call
  `policy_store.evaluate_policy(...)` instead of the inline function.
- Buyer's policy store can be in-memory (no SQLite) since the buyer
  CLI is short-lived; or use a tiny SQLite file under the XDG state
  dir if persistence (round history, etc.) turns out to be needed.

Verify: `market negotiate` from the CLI behaves identically to
today.

Unblocks: future learned-policy work on the buyer side without
touching CLI plumbing again.
Effort: half a day.

### Step 5 — split into `market-buyer` and `market-storefront`

The packaging step. Up to here, the codebase still ships as one
venv; this is where we break the install.

- Rename current `cli/` to `buyer/` (Python package
  `market_buyer`). Drop provider subcommands (`market provide`,
  `market start`, `market register`) — those move to the storefront
  package.
- Rename `core/` to `storefront/` (Python package
  `market_storefront`); the inner `core/agent/app/` collapses
  toward `storefront/market_storefront/server/` (or similar — pick
  a layout during the move). This package depends on
  `market-infra`, `market-policy`, `arkhai-agent-client`, and a
  client portion of `provisioning-service`. Exposes the `[rl]`
  extra. Provider admin CLI subcommands live here as a
  console_script.
- Two console scripts:
  - `market` (buyer) — points at `market_buyer.cli:main`.
  - `market-storefront` (provider) — points at the provider CLI /
    server launcher.
- `install.sh` becomes either two scripts (`install-buyer.sh`,
  `install-storefront.sh`) or a single script with `--role`
  (cosmetic choice; either works).
- Update `README.md`, `docs/`, Helm charts (`helm/charts/agents/` →
  `helm/charts/storefront/`) to reflect the new install surface.

Verify: clean install of `pip install market-buyer` produces a
working buyer CLI with no Torch/Redis/Starlette. Clean install of
`pip install market-storefront` produces a working provider. Install
of both shares `market-infra`, `market-policy`.

Effort: 1–2 days, mostly chasing import paths and docs.

### Step 6 — storefront adopts Dynaconf for runtime config

Optional, but the original prompt that started this asked about it.

- Decide whether the provider-side `[seller]` table in
  `~/.config/arkhai/config.toml` is the canonical source on dev
  laptops, with Dynaconf YAML profiles taking over only in
  containerized/Helm contexts; or whether dev laptops also move to
  Dynaconf.
- Recommended: keep TOML on dev laptops (zero migration cost); add
  a Dynaconf path for the storefront that reads
  `$CONFIG_DIRECTORY/config.yml` + profile files when present, and
  falls back to TOML otherwise. The Dynaconf path is what Helm
  fills in.
- While we're here: deduplicate the Dynaconf bootstrap between
  `provisioning-service/src/config.py` and
  `integration-tests/src/settings.py` by moving the shared loader
  into `market-infra`. Both sites import from there instead of
  copy-pasting.

Verify: storefront runs unchanged on dev laptops; runs in a
production Helm deploy reading `Values.config` via ConfigMap.

Effort: 1 day for the storefront path, half a day to dedupe the
bootstrap.

---

## Open questions

- Does the buyer ever need persistence for negotiation rounds (to
  resume after CLI restart)? If yes, step 4 needs a SQLite store; if
  no, in-memory is fine.
- The `[rl]` extras boundary: should buyer-side learned-policy use
  call for a separate `[inference]` extra (Torch but no Pufferlib /
  Wandb)? Defer until we actually have a buyer-side trained policy.
- Naming prefix: `market-*` vs. `arkhai-*`. The XDG path uses
  `arkhai/` and the GitHub org is `arkhai-io`, but the existing
  packages are `market-cli`, `market-core`, `market-service`. Plan
  uses `market-*` for continuity. Worth aligning later.

## Resolved questions

### `agent-client/` — keep separate, bundle into provider side later

Investigation (2026-04-27) found that `agent-client/` is effectively a
provider's admin SDK for its own storefront, not a general-purpose
agent client. Three of its four methods (`send_resource_alert`,
`create_order`, `close_order`) sign with the storefront's own private
key — only the storefront owner can call them. The fourth
(`get_registration`) is a public unauthenticated discovery GET, but
nothing in the buyer CLI imports it today; buyer discovery flows go
through `service.clients.indexer` against the off-chain registry
server, not against individual storefronts.

Real call sites today: storefront's own integration tests, and the
black-box `integration-tests/` harness that simulates both sides each
running their own storefront. Zero buyer-CLI consumers.

Decision:
- **Keep `agent-client/` as a standalone package for now.** Don't
  fold it into `market-infra` (it's not infra) and don't fold it
  into `market-buyer` (the buyer doesn't use it).
- **In Step 5, bundle it with the storefront admin surface.** When
  `core/` becomes `market-storefront`, `agent-client/` can either
  merge into it or stay sibling-but-explicitly-paired. Naming should
  also move away from "agent" — `storefront-admin-client` or similar.
- This is being communicated to the coworker who introduced the
  package (commit `8f1f256`); he's still doing follow-up shim
  cleanup, and the rename / re-pairing can ride alongside Step 5.

## Things explicitly out of scope

- Migrating the buyer's TOML config to Dynaconf. Different problem
  shape; user-level config is fine on TOML.
- Replacing the policy engine's persistence (SQLite). Works fine.
- Anything to do with the smart contracts or the registry indexer.
- The ZeroTier integration. Stays provider-side, behind its current
  flag.
- Splitting trained-policy training/inference into a separate
  package (`market-policy-rl`). Defer until there's a buyer-side
  trained policy.

## Reference: file paths cited in this plan

```
cli/market/config_loader.py
cli/market/buyer_client.py:121
cli/market/groups/negotiate.py:71
cli/market/groups/buy.py
cli/market/groups/provide.py
cli/tests/test_config_loader.py
core/pyproject.toml
core/agent/app/agent.py
core/agent/app/agent.py:357               (dead ADK comment)
core/agent/app/agent.py:1606-1745         (negotiate_new/continue endpoints)
core/agent/app/server.py:18-20            ("no A2A or Google ADK machinery")
core/agent/app/utils/config.py:43         (the cross-package import to break)
core/agent/app/utils/sync_negotiation.py
core/agent/app/utils/sync_negotiation.py:21-25  (engine-bypass rationale)
core/agent/app/utils/sync_negotiation.py:38-41  (anticipates cleanup)
core/agent/app/utils/sync_negotiation.py:65-106 (decide_response)
core/agent/app/policy/__init__.py
core/agent/app/policy/seeding.py:16-30    (provider-only triggers rationale)
core/agent/app/policy/action_builders.py:21 (symmetric ID derivation)
core/agent/app/policy/negotiation_thread.py
core/tests/unit/test_config_toml_fallback.py
service/pyproject.toml                    (collapses into market-infra)
provisioning-service/src/config.py
provisioning-service/src/settings.toml:34-36  (compute-provisioning-iac paths)
integration-tests/src/settings.py
integration-tests/conftest.py:18-42       (--profile/--config-dir flags)
helm/charts/registry/                     (operator: registry indexer)
helm/charts/provisioning/                 (provider: provisioning service)
helm/charts/agents/                       (provider: storefront, will rename)
helm/charts/provisioning/templates/configmap.yaml
compute-provisioning-iac/                 (submodule, dep of provisioning-service)
install.sh
docs/rewrite-plan.md                      (related, broader doc)
```
