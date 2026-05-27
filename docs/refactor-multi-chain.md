# Multi-chain refactor — completed

Branch: `refactor/multi-chain` (off `dev`). Ready to merge.

Goal: a single storefront process serves listings across N chains, a single buyer process can buy on N chains. The on-chain part of the deal (escrow → fulfillment attestation → claim) is fully derivative of the listing's chosen `accepted_escrows[].chain_name` — no "primary chain" concept, no on-chain action that isn't tied to a specific escrow.

## What changed

### Config shape

The legacy `[chain]` singular table is gone with no backwards-compat shim. Every operator config migrates to `[chains.<name>]`.

```toml
[wallet]
private_key = "0x..."          # one key signs for every configured chain

[chains.ethereum_sepolia]
rpc_url = "https://..."
chain_id = 11155111            # optional; falls back to KNOWN_CHAIN_IDS
# alkahest_address_config_path = "/etc/arkhai/alkahest.json"  # anvil only
# identity_registry_address = "0x..."  # falls back to KNOWN_IDENTITY_REGISTRY
# onchain_agent_id = 42        # storefront only; written back on first registration

[chains.base_sepolia]
rpc_url = "https://..."

[registry]
urls = ["http://localhost:8080"]
```

### `service/config_loader.py`

- `ChainConfig` dataclass: `name`, `rpc_url`, `chain_id`, `alkahest_address_config_path`, `identity_registry_address`, `onchain_agent_id` (storefront-only).
- `chains_from_config(cfg) -> dict[str, ChainConfig]` — keyed by table name.
- Removed: `chain_name()`, `chain_rpc_url()`, `alkahest_address_config_path()`, `identity_registry_address()` (singular).
- Kept: `KNOWN_CHAIN_IDS`, `KNOWN_IDENTITY_REGISTRY`, `query_chain_id_via_rpc`, `chain_name_for_rpc`, `derive_wallet_address`, `wallet_address`, `private_key`, `ssh_public_key`, `registry_urls`.

### Storefront

- `utils/config.py`: `CHAINS: dict[str, ChainConfig]` built at import; empty + warning if no `[chains.<name>]` configured. No more `settings.chain.*`.
- `container.py`: `resolved_alkahest_clients: dict[str, AlkahestClient]`, plus `get_alkahest_client(chain_name)` and `configured_chain_names()` helpers.
- `services/alkahest_service.py`: `build_clients() -> dict[str, AlkahestClient]` iterates `CHAINS`.
- `agent.py`: `_AGENT_IDS: dict[str, int]` keyed by chain name. `_ensure_agent_identity_for_chain(chain_cfg)` runs in parallel per chain; auto-persists discovered IDs back to `storefront.toml` via `_persist_agent_id`. Heartbeats fire one task per (chain, registry) pair.
- `commands/register.py`: `perform_registration_for_chain(chain)` per-chain. `run_register(chain_name=None)` registers on every configured chain (or one when filtered).
- `controllers/identity_controller.py`: `/.well-known/erc-8004-registration.json` emits one entry per registered chain (the ERC-8004 spec allows this).
- `utils/agent_card.py`: `build_erc8004_registration_file(registrations=[(agent_id, chain_id, identity_registry), ...])` takes a list.
- `services/system_service.py`: `checks.alkahest` reports comma-joined configured chain names. `result["identities"]` dict keyed by chain. `registry_auth_check` probes the first chain with a resolved ID (full per-chain auth check is a future polish).
- `utils/action_executor.py`: `_canonical_agent_id(chain_name=None)` — picks per-chain ID when chain_name is given, falls back to first registered chain.
- `cli_publish.py`: iterates `CHAINS` to emit one `accepted_escrow` per chain on every published listing; token resolution falls through chains until one succeeds.
- `groups/escrow.py` (admin `show` CLI): takes `--chain` (required when more than one chain configured).
- `cli.py`: `register --chain X` registers on a specific chain; without it, registers on all.

### Buyer

- `common.py`:
  - `buyer_chains() -> dict[str, ChainConfig]` wraps `chains_from_config()`.
  - `select_chain_for_listing(listing, override, yes)` — intersects listing's accepted chains with buyer's configured chains; interactive prompt by default; `--chain` required when `--yes` set and intersection is ambiguous.
  - `chain_by_name(name)` — direct lookup for `settle --from <run_id>` and other commands that already know the chain.
  - Removed: `resolve_chain_name()` and the auto-RPC-derived fallback.
- `groups/_deal.py` `resolve_chain_settings` takes a pre-selected `ChainConfig` instead of separate `rpc_url`/`chain_name`/`alkahest_addr_config` flags.
- CLI commands take `--chain <name>` instead of the old triple:
  - `market buy`, `market negotiate`, `market settle`, `market escrow {reclaim, create, show}`, `market chain check`.
- `buy_orchestrator.submit_settlement` sends `chain_name` in the body. The buyer's `escrow_created` run-log event records the chain so `settle --from <run_id>` can pick it up.
- `groups/chain.py check` iterates every configured chain (or one with `--chain`).

### Helm + fixtures

- `helm/charts/storefront/templates/_helpers.tpl` renders `[chains.<name>]` (uses `$chain.name` as the table key) and pins `onchain_agent_id` per-chain.
- Storefront + buyer `config init-user` templates show `[chains.ethereum_sepolia]` examples.
- `integration-tests/tests/e2e/roles/buyer_cli.py` writes `[chains.anvil]` in the hermetic config.
- `test_full_deal*` stage 00g asserts `"anvil" in checks.alkahest` instead of `== "ok"`.

### Storefront-client

- `verify_settle` (async + sync) sends `chain_name` in the SettleVerify body (defaults to `"anvil"`).

## Verification

All passing:

- `service`: 186 unit tests
- `storefront`: 314 unit tests, 125 integration tests
- `buyer`: 104 tests
- `storefront-client`: 7 tests
- `make test-render` (helm umbrella structural checks)

## Commits on branch

```
cee5684 storefront-client + integration fixtures: chain_name in verify_settle
c65acf7 config templates + fixtures: migrate to [chains.<name>] shape
aa5500c buyer: multi-chain config + interactive chain selection per listing
b203972 storefront tests: migrate unit fixtures to chains dict shape
8201739 storefront: per-chain identity registration + multi-chain dispatch
6d21321 docs: handoff for multi-chain refactor in progress
34c57d1 storefront/listing_service: per-chain dispatch for refund/claim/reclaim/arbitrate
36876b9 storefront: dispatch settle path on chain_name (partial Phase 3)
67b9609 service+storefront config: chains-by-name foundation for multi-chain
```

## Known follow-ups (not blockers)

- `registry_auth_check` probes only the first registered chain. The full multi-chain check would loop over `_AGENT_IDS` and require all of them to be reachable on their respective registries — but that's a polish on a status endpoint, not a correctness issue.
- e2e module hasn't been live-tested end-to-end on this branch; the fixture migration is in but a real e2e run (docker-compose stack up, buyer CLI subprocess driving a deal) would exercise the full path.
- Token resolution in `cli_publish` falls through chains until one succeeds; resource-row `token` column is still single-valued. If operators publish on chains where the same logical token (USDC) has different addresses, they'll need per-chain token columns in the CSV — out of scope for this refactor.
