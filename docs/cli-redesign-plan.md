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
market buy
market negotiate
market escrow reclaim          # NEW: pull tokens back when escrow expired unclaimed
market order list / show
market network join / get-peers
market config init / init-user / path / show / set / get
market logs runs / show / tail
```

### `market-storefront` — seller runtime
Pip: `market-storefront`.

```
market-storefront register             # in-process port of scripts/register_onchain.py
market-storefront serve                # in-process uvicorn (replaces broken `start`)
market-storefront provide
market-storefront escrow claim         # regrouped from top-level
market-storefront escrow refund        # regrouped from top-level (post-claim manual return)
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
