# CLI redesign plan

Splits the current 2-CLI surface (`market`, `market-storefront`) into 4
CLIs separated by concern: buyer runtime, seller runtime, policy
authoring, and market-operator infra.

## Motivation

The current split is by buyer-vs-seller role only, which mixes three
different concerns:

1. **Runtime concerns** — what a buyer or seller does at execution time
   (`buy`, `negotiate`, `provide`, `claim`).
2. **Infrastructure concerns** — what the market operator does once per
   market (run the chain, deploy contracts, run the registry indexer,
   admin the ZeroTier network).
3. **Tooling concerns** — what a policy author does occasionally
   (train/eval/export RL strategies).

Today, infra is split across both runtimes (`market dev test-env` lives
in the buyer, `market-storefront registry start` and `network create`
live in the seller), and policy training is hidden inside the seller
runtime even though buyers also negotiate with trained policies. This
plan separates the three concerns into their own binaries.

## Final surface

### `market` — buyer runtime
Pip: `market-buyer`. Pure HTTP client.

```
market buy                     # full pipeline (1-5)
market negotiate                # stage 2 only — stops at agreement
market settle                   # stages 3-5: create_if_needed + submit + poll
market escrow create            # stage 3 only (chain ops, no server interaction)
market escrow reclaim           # post-expiration tokens-back
market escrow show              # EVM read of escrow state (TODO: needs EAS ABI)
market order list / show
market network join / get-peers
market config init / init-user / path / show / set / get
market logs runs / show / tail
```

The deal pipeline has five conceptual stages:
1. **discover** — registry query
2. **negotiate** — signed `/negotiate/...` rounds
3. **escrow.create** — alkahest approve + escrow.create on-chain
4. **submit settlement** — POST `/settle/{escrow_uid}` to seller
5. **poll settlement** — GET `/settle/{escrow_uid}/status` to terminal

`market buy` runs all five in one process. `market negotiate` stops
at stage 2; `market settle --run <id>` resumes from stage 3 using a
buyer run-log. `market escrow create` is the standalone stage 3
escape hatch for advanced operators (e.g., pre-fund a deal before the
seller is reachable). `market escrow reclaim` covers the
"escrow expired unclaimed → pull tokens back" recovery path.

Inspection follows the source-of-truth split:
- "What did the buyer's CLI do?" → `market logs show <run_id>` (the
  JSONL run-log already records every stage event).
- "What's the escrow's on-chain state?" → `market escrow show`
  (TODO; alkahest-py does not yet expose `attestation.get(uid)`,
  needs either an upstream addition or an inlined EAS ABI + web3
  read).
- "What's the seller's job state?" → not a buyer-side command; runs
  inside `market settle` while polling, and the result lands in the
  buyer's run-log.

### `market-storefront` — seller runtime
Pip: `market-storefront`.

```
market-storefront register             # in-process port of scripts/register_onchain.py
market-storefront serve                # in-process uvicorn (replaces broken `start`)
market-storefront provide
market-storefront escrow claim         # regrouped from top-level
market-storefront escrow refund        # regrouped from top-level (post-claim manual return)
market-storefront escrow show          # EVM read of escrow state (TODO: shared EAS gap with buyer)
market-storefront portfolio import-csv
market-storefront network join / get-peers
market-storefront config init / path / show / set / get   # NEW (symmetric with buyer)
market-storefront logs show / status
```

### `market-policy` — policy authoring tool
Pip: `market-policy[rl]`. Already a workspace package; just needs an
entrypoint.

```
market-policy train
market-policy eval
market-policy export
```

### `chain deploy-contracts` — per-suite flags

`market-infra chain deploy-contracts` toggles three contract suites
independently so operators can deploy onto chains where some subset
already has canonical deployments:

```
market-infra chain deploy-contracts
  --rpc-url URL
  --erc8004 / --no-erc8004     # default on
  --alkahest / --no-alkahest   # default on (replays alkahest-transactions.json)
  --eas / --no-eas             # default on (today bundled with --alkahest)
  [--deployer-key 0x...]       # env: ANVIL_PRIVATE_KEY
```

Today's behaviour:

- `--alkahest` runs `market-contract-deployer/deploy_alkahest.py`,
  which replays the canned alkahest-transactions.json. EAS is
  deployed as part of that replay — so `--alkahest` and `--eas` must
  match. The CLI warns when they diverge and treats them as both
  enabled.
- `--erc8004` runs the three hardhat scripts in `erc-8004-contracts/`:
  `deploy-create2-factory.ts` → `deploy-vanity.ts` →
  `upgrade-local.ts`.
- `--no-eas` independent of `--alkahest` is a TODO in upstream
  alkahest. The deploy fixture would need to accept an existing EAS
  address rather than always deploying its own. Until then,
  `--no-eas --alkahest` falls back to the bundled behaviour with a
  warning.

### `market-infra` — market-operator tools
Pip: `market-infra`. New package, or fold into a re-purposed existing
one if a 4th binary is unwanted.

```
market-infra chain up                  # was: market dev test-env
market-infra chain deploy-contracts    # was: market dev deploy-registry
market-infra registry start            # was: market-storefront registry start
market-infra network install
market-infra network create
market-infra network add <member>
```

## Semantics: reclaim vs refund

- **`market escrow reclaim`** (buyer): tokens were never claimed by a
  seller and the deadline passed; buyer pulls them back from escrow.
- **`market-storefront escrow claim`** (seller): seller pulls escrowed
  tokens after fulfilling.
- **`market-storefront escrow refund`** (seller): seller manually
  returns tokens to the buyer *after* claim (dispute / out-of-band
  resolution).

The buyer has no `refund` because pre-claim the tokens are still
escrowed (→ `reclaim`), and post-claim they aren't the buyer's to send.

## ZeroTier split

- `network join` / `get-peers` — per-operator action; lives in **both
  runtimes** (one membership per agent process).
- `network install` / `create` / `add` — network-owner action; lives in
  **infra**.

## `register` / `serve` in the CLI vs entrypoint.sh

Both move into the CLI as in-process Python (no subprocess, no make,
read `CONFIG` directly). Deployment shells just compose CLI verbs.

**`storefront/entrypoint.sh`** collapses to:

```sh
#!/bin/sh
set -e
zerotier-one -d || true   # the only thing that has to stay outside the CLI:
                          # a side-process daemon that runs alongside `serve`.
market-storefront register
exec market-storefront serve
```

**Helm**:
- init container: `command: [market-storefront, register]`
- main container: `command: [market-storefront, serve]`

Wins:
- `storefront/scripts/register_onchain.py` body moves into the
  `register` command and the script is deleted.
- `entrypoint.sh` shrinks to the zerotier daemon line + two CLI calls.
- One canonical orchestration surface — deployment composes verbs.
- Direct testability without docker.

## Migration table

| Was | Becomes |
|---|---|
| `market dev test-env` | `market-infra chain up` |
| `market dev deploy-registry` | `market-infra chain deploy-contracts` |
| `market-storefront registry start` | `market-infra registry start` |
| `market-storefront network create / add / install` | `market-infra network ...` |
| `market-storefront network join / get-peers` | both runtimes |
| `market-storefront policy train / eval / export` | `market-policy ...` |
| `market-storefront register` (broken stub) | `market-storefront register` (rewritten in-process) |
| `market-storefront start` (broken stub) | `market-storefront serve` (rewritten in-process) |
| `market-storefront claim / refund` | `market-storefront escrow claim / refund` |
| (none) | `market escrow reclaim` |
| (none) | `market-storefront config ...` |

## `market settle` design (composite stages 3-5)

```
market settle --run <run_id>
  [--escrow-uid 0x...]           # skip stage 3 if escrow already on-chain
  [--token-contract 0x...]       # ERC-20 contract; default from token registry
  [--token-decimals N]           # default 18
  [--duration-hours N]           # default 1; pulled from registry order in future
  [--expiration N]               # escape-hatch deadline (seconds from now); default 1h
  [--rpc-url URL]                # default chain.rpc_url
  [--chain-name NAME]            # default chain.name
  [--alkahest-addr-config PATH]  # default chain.alkahest_address_config_path
  [--ssh-public-key KEY]         # default wallet.ssh_public_key
  [--buyer-address 0x...]        # default wallet.address
  [--buyer-priv-key 0x...]       # default wallet.private_key
  [--poll-interval F]
  [--settlement-timeout F]
```

Behaviour:
1. Open the buyer run-log for `<run_id>` and pull `seller_url`,
   `negotiation_id`, `agreed_price`, `seller_order_id`. If any are
   missing or the prior negotiation didn't reach `agreed`, exit
   non-zero.
2. If `--escrow-uid` not passed AND no `escrow_uid` event recorded:
   resolve seller wallet via `_resolve_seller_wallet(seller_url)`,
   build `AgreedTerms`, call `make_create_escrow_fn(...)`, log an
   `escrow_created` event. Otherwise reuse the recorded uid.
3. Submit `/settle/{escrow_uid}` (signed POST), log
   `settle_submitted`.
4. Poll `/settle/{escrow_uid}/status` until terminal
   (`ready` / `failed`), logging `settle_status` per attempt and
   `settle_terminal` on exit.
5. Exit 0 on `ready`, non-zero otherwise — same shape as `market buy`'s tail.

`market escrow create --run <run_id>` is the same path but stops
after step 2: it produces the on-chain escrow_uid, logs it, exits.
The operator can then run `market settle --run <run_id>` later
(the create event in the log will skip the create branch).

## `escrow show` (deferred)

Both `market escrow show --escrow-uid 0x...` and
`market-storefront escrow show --escrow-uid 0x...` need a way to
read an EAS attestation by UID and decode the
`ERC20EscrowObligationData` payload. `alkahest_py` currently exposes
`get_escrow_attestation(fulfillment_uid)` (wrong direction —
fulfillment → escrow) but no `attestation.get(uid)` /
`escrow.get(uid)`. Two unblocking options:

- **Upstream**: add `client.attestation.get(uid)` to alkahest-py.
  Cleanest; matches the existing client surface.
- **Local**: inline the EAS contract ABI + a `web3.py` call to
  `getAttestation(bytes32)`. Smallest scope but adds an EAS-flavored
  dep to both runtime CLIs.

Either path lands the same UX. Tracking under "follow-up" in the
plan rather than this commit.

## Run-log enrichment for `market negotiate` (follow-up)

`market settle --run <id>` currently relies on flags or config.toml
defaults for `duration_hours`, token contract + decimals, etc.
Enriching `market negotiate` to log `seller_wallet_address`
(returned by the seller's `accept` reply, or fetched from
`/.well-known/agent-wallet.json`), `duration_hours`, and the token
contract + decimals (resolved from the seller's order on the
registry) lets `market settle --run <id>` work flag-free. Tracking
as a follow-up; the flag-driven `settle` is already usable today.

## Suggested execution order

1. **Fix `register` / `serve` in `market-storefront`.** Rewrite as
   in-process commands; delete `scripts/register_onchain.py`; collapse
   `entrypoint.sh`; update Helm init/main container commands; verify
   docker-compose + `make test-integration` still pass.
2. **Add `market-storefront config` group.** Lift the buyer's
   implementation; share via `service` or a small `cli_common`.
3. **Regroup escrow.** Move `claim`/`refund` under `escrow` on the
   seller; add `market escrow reclaim` on the buyer.
4. **Add `network join` / `get-peers` to the buyer.** Move
   `network install / create / add` *out* of the seller.
5. **Extract `market-policy` CLI.** New `[project.scripts]` entry in
   `policy/pyproject.toml`; lift `cli_policy.py` from storefront into
   the policy package; delete from storefront.
6. **Extract `market-infra` CLI.** New workspace package
   `infra/`; move `chain up` / `chain deploy-contracts` (from buyer
   `dev`), `registry start` (from seller), and `network install /
   create / add` (from seller). Delete `dev` group from buyer.
7. **Drop dead deps.** Remove `Makefile.agent` references, retired
   make targets, anything else now orphaned.

Each step is independently mergeable.

## Open questions

- Should `market-infra` be a separate pip package or just a `dev` group
  in one of the existing packages? Separate package is cleaner but adds
  a 4th distributable.
- Does `market-policy` inference need any CLI surface (currently no —
  it's loaded as a library by the runtimes), or is `train/eval/export`
  enough?
- Is there a use case for `market-storefront serve` outside docker
  (i.e., bare-metal seller deploys)? If yes, entrypoint.sh stays
  meaningful only inside the image; `serve` becomes the canonical way
  to launch outside it.
