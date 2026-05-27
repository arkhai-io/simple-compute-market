# Multi-chain refactor — in-progress handoff

Branch: `refactor/multi-chain` (off `dev`). Commits so far:

- `67b9609` service+storefront config: chains-by-name foundation
- `36876b9` storefront: dispatch settle path on chain_name (partial Phase 3)
- `34c57d1` storefront/listing_service: per-chain dispatch for refund/claim/reclaim/arbitrate

Goal: a single storefront process serves listings across N chains, a single buyer process can buy on N chains. The on-chain part of the deal (escrow → fulfillment attestation → claim) is fully derivative of the listing's chosen `accepted_escrows[].chain_name` — no "primary chain" concept, no on-chain action that isn't tied to a specific escrow.

## Config shape (committed)

```toml
[wallet]
private_key = "0x..."          # one key signs for every configured chain

[chains.ethereum_sepolia]
rpc_url = "https://..."
chain_id = 11155111            # optional; falls back to KNOWN_CHAIN_IDS
# alkahest_address_config_path = "/etc/arkhai/alkahest.json"  # anvil only
# identity_registry_address = "0x..."  # falls back to KNOWN_IDENTITY_REGISTRY
# onchain_agent_id = 42        # add this field in Phase 5

[chains.base_sepolia]
rpc_url = "https://..."

[registry]
urls = ["http://localhost:8080"]
```

The legacy `[chain]` shape is **gone** — no backwards-compat shim. Every operator config that was on `[chain]` needs to be migrated to `[chains.<name>]`. Operator-facing tooling (`market-storefront config init-user` template + helm chart values + compose configs + integration test fixtures) still ships old shape — see Phase 7.

`service/config_loader.py` exports:

- `ChainConfig(name, rpc_url, chain_id, alkahest_address_config_path, identity_registry_address)` dataclass
- `chains_from_config(cfg) -> dict[str, ChainConfig]`
- Removed: `chain_name()`, `chain_rpc_url()`, `alkahest_address_config_path()`, `identity_registry_address()` (all the singulars)
- Kept: `KNOWN_CHAIN_IDS`, `KNOWN_IDENTITY_REGISTRY`, `query_chain_id_via_rpc`, `chain_name_for_rpc`, `derive_wallet_address`, `wallet_address`, `private_key`, `ssh_public_key`, `registry_urls`

`storefront/utils/config.py` exports:

- `settings: Dynaconf` (no more `settings.chain.*`)
- `CHAINS: dict[str, ChainConfig]` — built once at import from `settings.chains` (dynaconf nested table). Empty dict + warning if no `[chains.<name>]` configured.
- Removed: `chain_id()` function. Per-chain id is now `CHAINS[name].chain_id`.

`storefront/container.py` exports:

- `resolved_alkahest_clients: dict[str, AlkahestClient]` (dict, not singleton)
- `get_alkahest_client(chain_name) -> AlkahestClient | None`
- `configured_chain_names() -> list[str]`

`storefront/services/alkahest_service.py`: `build_clients() -> dict[str, AlkahestClient]` iterates `CHAINS`, builds one client per entry, drops any that fail to init.

## Design decisions (locked in)

1. **One storefront process per N chains** — no "primary chain"; every on-chain action dispatches on the proposal/escrow's `chain_name`.
2. **One signing key for all chains** — `wallet.private_key` shared. No per-chain keys.
3. **Identity registration is per-chain and asynchronous** — startup kicks off background tasks. Auto-write registered IDs back to `[chains.<name>].onchain_agent_id` so subsequent boots are no-ops. Manual writes only for "bringing an identity from elsewhere". See Phase 5.
4. **Buyer chain selection** — interactive prompt by default; `--chain` is required only when `--yes` is set. First-match-in-config is the suggested default in the prompt.
5. **Listing schema unchanged** — `accepted_escrows[].chain_name` already carries everything needed; no `Listing.chain` field.
6. **Registry stays chain-agnostic** — buyer filters `accepted_escrows` client-side. A `?chain=` query would be a perf optimization, not added now.

## What's left

### Phase 3 — remaining storefront dispatch sites (~8 files)

Grep `settings\.chain\.` and `settings\.registry\.identity_registry_address` to find them. Current count: 31 lines across 8 files.

- `storefront/cli.py:103` — `_query_chain_id(settings.chain.rpc_url)` in some CLI helper.
- `storefront/cli_publish.py` — lines 353, 354, 360, 364, 570. The `accepted_escrows` build needs to iterate `CHAINS.values()` and emit one entry per chain. Part of Phase 4.
- `storefront/agent.py` — lines 79, 87, 96, 140, 149, 157, 177, 192, 195, 270, 276, 277, 280, 281, 308. The big one. Three things going on:
  - Identity ownership/registration check (lines 79–125 for pinned ID, 140–179 for auto-register). Must become per-chain: for each `c in CHAINS.values()`, check ownership / look up by owner / register fresh. Persist via `_AGENT_IDS: dict[str, int]` (per-chain) instead of `_AGENT_ID: int`.
  - Heartbeat at line 195 — `_start_heartbeat()` takes single chain params. Either start N heartbeat tasks (one per chain) or change the heartbeat to be a list-of-chain-contexts. Look at `service/clients/erc8004/heartbeat.py` to see what shape is friendly.
  - `_probe_chain_addresses` at lines 260–308 — probes the alkahest + identity registry addresses on the configured RPC. Iterate `CHAINS`, probe each.
- `storefront/groups/escrow.py:243–262` — admin CLI command that talks to alkahest directly. Take a `--chain` flag, look up `CHAINS[chain_name]`. (Manual ops tool — keep simple.)
- `storefront/commands/register.py:91–93` — `perform_registration()` for one chain. Add `chain: ChainConfig` parameter; agent.py calls it once per chain.
- `storefront/utils/action_executor.py:308` — `_canonical_agent_id()` or similar. Reads `identity_registry`; needs to be per-chain. Trace the caller(s).
- `storefront/services/system_service.py:193` — `identity_addr = (settings.registry.identity_registry_address or "").lower()` in some health-check / lookup. Per-chain.
- `storefront/controllers/identity_controller.py:39–40` — `/.well-known/erc-8004-registration.json` returns one `(chain_id, identity_registry, agent_id)` triplet. Spec allows multiple registration entries — emit one per registered chain. See `utils/agent_card.py:build_erc8004_registration_file` (already supports `registrations` array; just feed it the per-chain entries).

### Phase 4 — publish iteration

Already partially-done via `sqlite_client.synthesize_accepted_escrows_from_demand` (legacy backfill). The active publish flow is `cli_publish.py` and `listing_service.create_listing` / similar. For each configured chain, emit one `AcceptedEscrow` with that chain's escrow_obligation address. Pricing (per-hour) is the same across chains for a given listing — same offer, same dollar amount.

### Phase 5 — per-chain identity registration

Design from user:

> isn't registration async in the background anyway? and isn't similar state to what lazy registration needs already present to prevent re-registering every startup? (we can have writing registered ids to the config be automatic, so manual writes are just for bringing an identity from somewhere else)

Implementation plan:

- Add `onchain_agent_id: Optional[int]` to `ChainConfig` (read from `[chains.<name>].onchain_agent_id`).
- `_AGENT_IDS: dict[str, int]` module-level state in `agent.py`. Per-chain `_ensure_agent_identity_for_chain(c: ChainConfig)` coroutine.
- At startup, spawn `asyncio.create_task(_ensure_agent_identity_for_chain(c))` for each `c in CHAINS.values()`. They run in parallel; any single chain's RPC being slow doesn't block others.
- Each task:
  - If `c.onchain_agent_id` is set: validate ownership; populate `_AGENT_IDS[c.name]`. Skip registration.
  - Else: lookup-by-owner on identity_registry. If found, populate `_AGENT_IDS[c.name]` AND auto-write the discovered ID back to `storefront.toml` (so next boot is fast).
  - Else: register fresh; populate `_AGENT_IDS[c.name]` AND auto-write.
- Auto-write via `service.config_loader.write_user_config()` — read current TOML, `set_dotted(doc, f"chains.{name}.onchain_agent_id", id)`, write back. Race condition: if two processes try this simultaneously, last write wins; that's fine because the ID itself is the same for a given wallet.
- The `/.well-known/erc-8004-registration.json` endpoint reads `_AGENT_IDS` and emits one `registrations` entry per `(chain_id, identity_registry, agent_id)` triple.

Heartbeat needs the same per-chain spread — N heartbeat tasks, one per chain.

### Phase 6 — buyer

The buyer's `[chain]` references are in TOML-path strings inside `resolve_config_value(toml_path="chain.rpc_url")` calls. Each needs to migrate to "pick a chain by name, then read from `chains_from_config()[name]`".

Files (sites):

- `buyer/market_buyer/common.py` — `resolve_chain_name()` (lines 66–93), `resolve_chain_id()` (lines 191–213). Delete `resolve_chain_name`. Add `chains_for_buyer() -> dict[str, ChainConfig]` and `select_chain_for_listing(listing, override=None) -> ChainConfig` (interactive prompt unless `--yes`).
- `buyer/market_buyer/groups/chain.py` — `--rpc-url` / `--chain` flags. Refactor: these flags become "which chain in `[chains]` to use." Drop the standalone RPC URL flag (or keep for one-off overrides).
- `buyer/market_buyer/groups/_deal.py` (line 195+) — `rpc = resolve_config_value(override=rpc_url, toml_path="chain.rpc_url")` → look up via `select_chain_for_listing(listing).rpc_url`.
- `buyer/market_buyer/groups/buy.py` (line 473+) — buy orchestrator. The listing intersect: `set(buyer_chains) & set(listing.accepted_escrows[].chain_name)` → first match or prompt.
- `buyer/market_buyer/groups/negotiate.py` (lines 250, 253, 293) — same pattern.
- `buyer/market_buyer/groups/settle.py` (line 174) — settle takes chain from the run-log (which already records the chosen chain at escrow-creation time).
- `buyer/market_buyer/groups/escrow.py` (lines 137, 147, 221+, 329, 369+, 406+) — `market escrow ...` ops. Take `--chain` (required when N>1 chains configured); look up via `chains_from_config()`.

Settle subprocess persistence: the buyer's run-log already records `chain_name` per escrow_created event. The `market settle --from <run_id>` flow reads it and dispatches.

Outbound HTTP: buyer must include `chain_name` in `SettleRequest` body (already added to the storefront's `settle_models.SettleRequest`). The buyer's settle group needs to emit it.

### Phase 7 — config templates + fixtures

Update these to the new shape:

- `storefront/src/market_storefront/settings.toml` — already cleaned of `[chain]` defaults; should be good.
- `storefront/src/market_storefront/groups/config.py` — `_INIT_USER_TEMPLATE` (lines ~110–224) still shows `[chain]`. Update to `[chains.ethereum_sepolia]` example.
- `buyer/market_buyer/groups/config.py` — `_INIT_USER_TEMPLATE` (lines ~101–148) likewise.
- `integration-tests/tests/e2e/roles/conftest.py` and `buyer_cli.py` — fixtures that write a buyer.toml / storefront.toml for the e2e suite.
- `compose/seller.yml` and any sample storefront.toml in `compose/` — operator-facing dev configs.
- Helm chart values templates if present (look in `charts/` or `helm/`).

### Phase 8 — verification

In order:

1. `cd service && uv run pytest tests/unit/test_config_loader.py` — already passing on commit 67b9609.
2. `cd storefront && uv run pytest tests/unit/ -q` — will need fixture/mocks updates for the chains dict pattern. Expect a lot of red until tests are migrated.
3. `cd storefront && uv run pytest tests/integration/ -q` — these spawn a real FastAPI server; should work once Phase 3 is complete.
4. `cd buyer && uv run pytest tests/ -q`.
5. `make test-render` (unrelated but part of the standard verification flow per memory note).
6. E2E module — likely needs the integration-test fixtures updated first.

The storefront unit tests will be the most painful because many of them likely build a `ListingService(alkahest_client=...)` or read `settings.chain.*`. Search-replace + dict-fixture pattern.

## Resumption checklist (for the next session)

1. `git log --oneline refactor/multi-chain` to confirm the three commits.
2. Read this file end-to-end.
3. Grep `settings\.chain\.` in `storefront/src/` to see the remaining touchpoints.
4. Pick up Phase 3 — agent.py is the next big one because it blocks proper startup. cli.py + cli_publish.py + groups/escrow + commands/register + identity_controller + action_executor + the last system_service line are mechanical after agent.py.
5. Then Phase 4 (publish iteration), then Phase 5 (per-chain registration + auto-persist), then Phase 6 (buyer), then Phase 7 (templates), then Phase 8 (verification).

## Open questions

- **Heartbeat protocol** — does the registry's per-agent heartbeat need to be per-chain? Or is one heartbeat with multi-chain registrations enough? Check `service/clients/erc8004/heartbeat.py`. The registry's chain_id check at heartbeat time may need updating to handle a multi-chain agent.
- **Single-chain dev ergonomics** — operators with only one configured chain will type `[chains.ethereum_sepolia]` instead of `[chain]`. Acceptable. The `market config init-user` template should default to scaffolding one named chain so most users don't have to think about it.
- **`/.well-known/erc-8004-registration.json` schema** — spec allows multiple `registrations` entries. Confirm the indexer (or any other consumer) handles a multi-entry response correctly.
