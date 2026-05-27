# Pluggable identity schemes — design + migration plan

## Problem

Seller identity is hard-coded into the protocol layer in two ways: wallet addresses appear directly in signed-request payloads + listings-registry storage + alkahest escrow data, and ERC-8004 specifically is baked into the registration / discovery flow (storefront publishes a registration file, registry indexer pre-resolves agents via `tokenURI`/`ownerOf`, listings join to `agent_id` rather than to a more abstract identifier).

This wedges out three things we want to support:

- **Settlement on non-EVM chains.** Solana, Cosmos, etc. have their own identity primitives (ed25519 keys, account addresses). The protocol layer can't treat them as first-class because everything assumes EVM addresses.
- **Fiat settlement.** A seller identifying via Stripe Connect or a business registration number has no on-chain wallet, but should still be able to publish listings, prove ownership of signed requests, and accumulate reputation.
- **Alternative identity schemes generally** — DIDs, OIDC, X.509, ENS-anchored identities, etc. These should each be addable without re-architecting the protocol layer.

The ERC-8004 integration is also currently buggy in known ways (the `ownerOf` tuple-return issue, the `ONCHAIN_AGENT_ID` clearing forcing re-registration on Anvil restarts, the indexer cold-start gate). Those bugs cost dev time even when nobody's actively using ERC-8004 because they fire on every fresh test-env startup.

## Locked-in design

### `Identity` as a scheme-tagged pair

```python
# service/src/service/schemas.py
class Identity(BaseModel):
    scheme: str         # e.g. "eip191", "did-key", "jwt-bearer", ...
    identifier: str     # scheme-specific (hex wallet, did:key URI, sub claim, ...)
```

Every place the codebase currently passes a wallet address as the seller's identity, it passes an `Identity` instead. The default — and, after Phase 4, the only built-in — scheme is `eip191`, whose identifier is the lowercase hex wallet address.

### Scheme registry + verifier interface

```python
# service/src/service/identity/registry.py
class IdentityVerifier(Protocol):
    name: str
    def verify_signature(
        self,
        identity: Identity,
        message: bytes,
        proof: bytes,
    ) -> bool: ...

_VERIFIERS: dict[str, IdentityVerifier] = {}

def register_identity_scheme(verifier: IdentityVerifier) -> None: ...
def get_identity_verifier(scheme: str) -> IdentityVerifier: ...
```

A scheme registers itself at import time. The storefront's auth middlewares and the registry's `verify_order_signature` / `verify_heartbeat_signature` dispatch through `get_identity_verifier(identity.scheme).verify_signature(...)`.

Built-ins after the refactor:

| Scheme | Identifier shape | Verifier |
|---|---|---|
| `eip191` | Lowercase 0x hex wallet address | Recovers signer via EIP-191 `Account.recover_message`, compares against `identity.identifier`. |

### Signed-request wire shape

Currently a signed request carries `agent_id` (ERC-8004 canonical ID) + `timestamp` + `signature` headers. Generalized:

```
X-Identity-Scheme: eip191
X-Identity: 0xabcd...                # scheme-specific identifier
X-Timestamp: 1716840000
X-Signature: 0x...                   # scheme-specific proof
```

The header format is scheme-pluggable too — schemes whose proof doesn't fit cleanly into a single hex `X-Signature` can use scheme-prefixed headers (`X-Signature-Jwt`, etc.) — but the default scheme's wire is exactly what it is today, just with the canonical-ID header swapped for `(X-Identity-Scheme, X-Identity)`.

Back-compat for one release: middleware accepts the old `X-Agent-ID` header and derives `(eip191, <owner_address>)` from the registry side. After that release we delete the back-compat path.

### Listings registry storage

Listings + agents keyed on `(scheme, identifier)` instead of `agent_id`. Schema change to `agents`:

```sql
-- before
CREATE TABLE agents (
  agent_id TEXT PRIMARY KEY,           -- eip155:<chain>:<registry>:<id>
  owner TEXT NOT NULL,                 -- wallet address
  token_uri TEXT,
  ...
);

-- after
CREATE TABLE agents (
  scheme TEXT NOT NULL,                -- "eip191"
  identifier TEXT NOT NULL,            -- wallet address
  scheme_metadata JSON,                -- optional, scheme-specific
  ...
  PRIMARY KEY (scheme, identifier)
);
```

`scheme_metadata` holds anything scheme-specific that needs to be persisted (for `eip191` it's empty; for a hypothetical `erc8004` scheme it would hold `agent_id`, `chain_id`, `identity_registry`, `tokenURI` if reintroduced).

Existing data migrates to `(eip191, <derived-from-owner>)`. The on-chain `agent_id` becomes ignorable — recorded in `scheme_metadata` during the migration window, then dropped in Phase 4.

### Settlement-module ↔ identity-scheme binding

Settlement modules declare which schemes they can bind to. Alkahest binds to `eip191` directly (the `identifier` is already an EVM address). Other schemes can register an EVM-wallet resolver if they want alkahest settlement — e.g. a `did:key` scheme could resolve to a wallet via a controller proof.

Today there's only one settlement module (alkahest) and one scheme (`eip191`), so this is one-line glue. The point of writing it down explicitly is so that adding a Solana settlement module later doesn't require touching the identity layer.

### Discovery (storefront URL → registry → buyer)

The listings registry stores the storefront URL as a field on each listing (or via a one-shot seller-announcement endpoint, depending on the deployment topology). Discovery is "fetch the listing, fetch the storefront URL." No tokenURI walk, no agent-card hop. `/.well-known/agent-wallet.json` stays — it's a scheme-agnostic settlement affordance, not an identity affordance.

## What's deleted

- `service/src/service/clients/erc8004/` (1145 LOC across `blockchain.py`, `heartbeat.py`, `registration.py`, `signing.py`)
- `storefront/src/market_storefront/commands/register.py` (221 LOC; the `market-storefront register` subcommand)
- `storefront/src/market_storefront/controllers/identity_controller.py` (64 LOC; the `/.well-known/erc-8004-registration.json` + `/.well-known/agent-card.json` endpoints)
- `storefront/src/market_storefront/utils/agent_card.py` (121 LOC; agent card + registration file builders)
- `storefront/src/market_storefront/agent.py::_ensure_agent_identity_for_chain` and `_AGENT_IDS` + `_persist_agent_id`
- `registry-service/src/contracts/identity_registry.py`, `contracts/abis.py`, `contracts/abi/IdentityRegistry.json`, `ReputationRegistry.json`, `ValidationRegistry.json`
- `registry-service/src/api/utils.py::ensure_agent_indexed`, `parse_erc8004_canonical_id`
- `identity_registry_address` and `onchain_agent_id` fields on `ChainConfig`
- The corresponding entries in TODO.md (`ownerOf` tuple-return, `ONCHAIN_AGENT_ID` clearing, registry indexer cold-start gate)

## What's kept

- `eth_account`-based EIP-191 verification logic (lifted into the `eip191` scheme's verifier)
- `verify_order_signature` and `verify_heartbeat_signature` (rewired through the scheme dispatcher)
- `/.well-known/agent-wallet.json` (scheme-agnostic settlement affordance)
- The submodule `erc-8004-contracts/` (left in place; just stops being a runtime dependency)
- The ZeroTier IP-substitution logic in `_resolve_base_url` (general; ERC-8004 was just a caller)

## Phases

### Phase 1 — Introduce `Identity` + scheme registry

**Goal:** scaffolding lands; no behavior change.

**Risk:** low. Pure additive.

**Changes:**

- Add `service/src/service/schemas.py::Identity` Pydantic model.
- Add `service/src/service/identity/registry.py` with `IdentityVerifier` protocol + `_VERIFIERS` registry + `register_identity_scheme` / `get_identity_verifier`.
- Add `service/src/service/identity/schemes/eip191.py` registering the EIP-191 verifier (logic lifted from the current `_verify_eip191_signature`).
- Import the `eip191` scheme module at package init so the default scheme is always available.

**Tests:** unit tests for the verifier (positive + negative cases, recover-address edge cases).

**Commit subject:** `service: introduce pluggable Identity abstraction + eip191 scheme (phase 1/4)`

### Phase 2 — Thread `Identity` through signed-request flows

**Goal:** storefront + registry auth dispatch by scheme. `eip191` is the only scheme in flight.

**Risk:** medium. Auth path is security-critical; signature verification regression would be bad.

**Changes:**

- Storefront `middleware/{seller_auth,buyer_auth,admin_auth}.py` dispatch via `get_identity_verifier(scheme).verify_signature(...)`. Request headers gain `X-Identity-Scheme` and `X-Identity`; back-compat shim derives `eip191` from a present-only `X-Agent-ID` for one release.
- Registry `api/utils.py::verify_order_signature` and `verify_heartbeat_signature` dispatch by scheme. Existing callers default to `eip191` if scheme isn't supplied (back-compat).
- Storefront-client + registry-client wheels: signed-request constructors accept `Identity` and emit the new headers. Bump wheels' minor versions.

**Tests:** end-to-end signed-request tests for both storefront and registry. Negative tests: wrong scheme rejected; unknown scheme returns 400; signature mismatch returns 401.

**Commit subject:** `auth: dispatch signed-request verification by identity scheme (phase 2/4)`

### Phase 3 — Listings-registry: scheme-tagged storage

**Goal:** persistence layer keys on `(scheme, identifier)`. ERC-8004-specific schema fields move into `scheme_metadata` ahead of deletion in Phase 4.

**Risk:** high. Schema migration. Existing rows have to be migrated cleanly, queries have to be rewritten, race conditions in the agent-indexing path have to be preserved.

**Changes:**

- Alembic migration: `agents` table replaces `agent_id` PK with `(scheme, identifier)` composite PK. Existing rows tagged `(eip191, owner_lowercase)`. ERC-8004 fields (`agent_id`, `chain_id`, `identity_registry_addr`, `onchain_agent_id`, `token_uri`) move to a `scheme_metadata` JSON column.
- `listings` table: foreign key updates from `agent_id` to `(scheme, identifier)`.
- `find_agent_by_id` and `ensure_agent_indexed` callers: rewritten to take `Identity` rather than the canonical ERC-8004 ID. `ensure_agent_indexed` keeps its JIT lookup *only* for the (now-soft-deprecated) `erc8004` scheme; for `eip191` the agent row is created lazily on first signed publication (signature recovery proves ownership; no on-chain lookup needed).
- Buyer + storefront clients: surface the `Identity` shape in seller-discovery responses.

**Tests:** Alembic migration tested against a snapshot of pre-migration data. New scheme-tagged query paths get integration coverage.

**Commit subject:** `registry: store agents + listings keyed by (scheme, identifier) (phase 3/4)`

### Phase 4 — Delete ERC-8004 paths

**Goal:** the codebase no longer contains an ERC-8004 implementation. The scheme adapter pattern is the documented extension point for anyone who wants to add it back.

**Risk:** medium-high. Lots of deletion across packages; tests get pruned in bulk; the registry's chain-side event-sync layer goes away.

**Changes:**

- Delete the source files listed under "What's deleted" above.
- Drop `identity_registry_address` and `onchain_agent_id` from `ChainConfig` and from `[chains.<name>]` TOML schemas.
- Drop the `register` subcommand from `market-storefront`. The `serve` subcommand is the only command storefronts need to operate (registry-side seller-row creation happens lazily on first signed listing publication).
- Drop the JIT lookup + on-chain `ownerOf`/`tokenURI` reads from the registry — there's no on-chain identity registry to read from.
- Drop the entries from `docs/TODO.md` (the ERC-8004 bugs disappear with the code).
- The `erc-8004-contracts/` submodule stays in the repo but is no longer a runtime dependency. The `market-contract-deployer` no longer deploys it. Test-env image regenerates without it.

**Tests:** prune ERC-8004-specific test files. Re-run all suites. Helm + compose configs: drop `IDENTITY_REGISTRY_ADDRESS` env vars and related secrets.

**Commit subject:** `core: drop ERC-8004 identity scheme, eip191 is the only built-in (phase 4/4)`

## What's deferred

### A second built-in scheme

Shipping the abstraction with only `eip191` means it's not exercised by a non-default scheme. The risk is that the interface looks general but is in practice tuned to EIP-191's specific shape. Two ways to validate this:

- Add a small second scheme as a follow-up (e.g. `did:key` for keypair-based identity, or `jwt-bearer` for OIDC-issued identity). Not load-bearing in the protocol layer but enough to stress the abstraction.
- Defer until a real second scheme is needed (Solana settlement, fiat settlement) and use that as the abstraction's first real test. Risk: interface drift between when it was designed and when it's first used.

Lean toward the first — add a small scheme as a confidence check after Phase 4 lands.

### Reputation scheme

ERC-8004's Reputation Registry goes away with Phase 4. Post-settlement reputation, if we want it as a feature, lands as an EAS schema (uniform aggregable feedback attestations keyed on the `Identity` of the rated party). Not part of this refactor — separate design conversation.

### Cross-scheme reputation aggregation

Probably we don't try to solve this. Reputation sources are scheme-specific. Buyers consult whichever sources they understand. If a seller publishes under multiple schemes, they accumulate separate reputation in each.

### Identity-scheme metadata in listings

ERC-8004's agent card was advertising A2A/MCP/etc. endpoints via the `services[]` array. We don't currently use that, but the affordance ("seller advertises capabilities beyond just compute") might be useful eventually. If/when it is, it lands as a field on the listing or on a one-shot seller-announcement endpoint, not as a separate well-known file walk.

## Estimated size

- Phase 1: ~+200 LOC (abstraction scaffolding + scheme registration)
- Phase 2: ~+150 / −100 LOC (middleware dispatch + back-compat shim)
- Phase 3: ~+400 / −300 LOC (storage layer changes + migration)
- Phase 4: ~−2000 LOC (deletion of ERC-8004 code, ABIs, tests)

Net: roughly −1700 LOC. The deletion in Phase 4 is the biggest single change.

## Estimated session count

- Phase 1: 1 session
- Phase 2: 1-2 sessions
- Phase 3: 2-3 sessions
- Phase 4: 1-2 sessions

So 5-8 sessions total. Each phase commits independently and keeps the branch green; back-compat shims in Phases 2-3 carry old call sites until they're rewritten.

## File map

```
service/src/service/schemas.py                                 Phase 1 — Identity model
service/src/service/identity/registry.py                       Phase 1 — verifier registry
service/src/service/identity/schemes/eip191.py                 Phase 1 — default scheme
service/src/service/identity/schemes/__init__.py               Phase 1 — auto-import default

storefront/src/market_storefront/middleware/seller_auth.py     Phase 2 — dispatch by scheme
storefront/src/market_storefront/middleware/buyer_auth.py      Phase 2 — dispatch by scheme
storefront/src/market_storefront/middleware/admin_auth.py      Phase 2 — dispatch by scheme

storefront-client/src/storefront_client/client.py              Phase 2 — emit new headers
registry-client/src/registry_client/client.py                  Phase 2 — emit new headers

registry-service/src/api/utils.py                              Phase 2 + 3 — dispatch + remove JIT lookup
registry-service/src/db/models.py                              Phase 3 — Agent schema
registry-service/alembic/versions/<new>.py                     Phase 3 — migration
registry-service/src/api/listing_routes.py                     Phase 3 — keyed lookups

service/src/service/clients/erc8004/                           Phase 4 — DELETE
storefront/src/market_storefront/commands/register.py          Phase 4 — DELETE
storefront/src/market_storefront/controllers/identity_controller.py  Phase 4 — DELETE
storefront/src/market_storefront/utils/agent_card.py           Phase 4 — DELETE
storefront/src/market_storefront/agent.py                      Phase 4 — strip _AGENT_IDS et al
registry-service/src/contracts/                                Phase 4 — DELETE

service/src/service/config_loader.py                           Phase 4 — drop identity_registry_address, onchain_agent_id
storefront/src/market_storefront/settings.toml                 Phase 4 — drop the related entries
helm/values.yaml                                                Phase 4 — drop the related values
compose/seller.yml                                             Phase 4 — drop IDENTITY_REGISTRY_ADDRESS env

docs/TODO.md                                                   Phase 4 — drop ERC-8004 latent bug entries
docs/ARCHITECTURE.md                                           Phase 4 — refresh identity section
```

## References

- ERC-8004 spec: <https://eips.ethereum.org/EIPS/eip-8004>
- Conditional Escrow ERC draft (the EAS-based standards-track direction the team is committing to): <https://gist.github.com/mlegls/5845452d847d78c758c83f4b37d0162e>
- TODO.md ERC-8004 bug entries (deleted in Phase 4): "SQLite INTEGER overflow", "perform_registration logs Invalid explicit agent ID", "ONCHAIN_AGENT_ID clearing", "Registry indexer cold-start gate"
