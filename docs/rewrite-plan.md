# Rewrite planning: current state and target architecture

This document captures the state of the codebase as the current maintainer
(yz@mmon.co) takes ownership from contractors, and the intended direction
for a rewrite that prioritizes shippability and clean separation of concerns.

Written: 2026-04-16.

## The four parties

The market has four distinct parties, each with their own responsibilities
and deployment unit:

1. **External chain** — an EVM chain with Alkahest + ERC-8004 contracts
   deployed. Run by nobody in this repo in production.
2. **Market operator** (infra provider) — deploys and runs a registry
   service that indexes agents and orders. Single responsibility.
3. **Sellers** (compute providers) — each runs their own agent plus a
   provisioning service on their own machine. Many independent sellers.
4. **Buyers** (compute renters) — each runs their own agent. Many
   independent buyers.

The existing docker-compose bundles all four for local dev, which obscures
the topology. The split in `compose/*.yml` makes it explicit.

## Findings on the current implementation

### 1. Chain-agnosticism: none

The stack hardcodes Anvil:

- `deploy_alkahest.py:22`: `RPC_URL = "http://anvil:8545"`
- `deploy_alkahest.py:27`: deployer address is Anvil account #0
- `deploy-local.sh:6-8`: `ANVIL_PRIVATE_KEY` is the well-known test key
- `deploy-local.sh:12-14`: ERC-8004 contract addresses are CREATE2 vanity
  addresses deterministic only on chain 31337
- Agent env files (`core/agent/.env.*.docker-compose`): RPC URL hardcoded
  to `ws://anvil:8545`

Changing env vars alone does not point the stack at a real chain. The
vanity addresses won't exist on any other chain; the deployer key won't
match; the RPC URLs are baked into Python source.

**What's needed to be chain-agnostic:**
- Template env files to read RPC/contract addresses from a single source
  (e.g. `shared-env/.env`, generated per deployment)
- Parameterize `deploy_alkahest.py` to take RPC URL + deployer key as args
- Drop the vanity-address requirement (or accept per-chain addresses) so
  ERC-8004 contracts work on any chain
- Add `scripts/deploy-contracts.sh <rpc-url> <deployer-key>` (or CLI)
  as the single entry point for deploying to a new chain

### 2. Non-docker-compose APIs: partial

Each party's deployment unit needs a way to launch natively without
docker-compose. Today:

| Party | Native launch | Gap |
|-------|---------------|-----|
| Market operator | `uvicorn src.main:app` in `erc-8004-registry-py/` | No CLI wrapper |
| Seller agent | `market start --env <path>` | Works |
| Seller provisioning | `python -m async_provisioning_service.main` + `python -m async_provisioning_service.worker` | Two processes, no CLI wrapper |
| Buyer agent | `market start --env <path>` | Works |
| Infra deployer | `market-contract-deployer/deploy-local.sh` | No CLI wrapper, hardcoded to Anvil |

**What's needed:**
- `market serve registry` (wraps uvicorn)
- `market serve provisioning` (wraps both processes)
- `market deploy-contracts --rpc-url <url> --deployer-key <key>`

Compose files should then be thin YAML wrappers around these commands,
not independent implementations. Real users run the commands; tests and
dev convenience use compose.

### 3. The current implementation is event-driven, not stage-driven

There are no "stages" in the agent code. Instead there are event types
(`ORDER_CREATE`, `MAKE_OFFER`, `ACCEPT_OFFER`, `RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT`,
etc.), each dispatched through a policy engine to an action handler. The
handlers decide what to do based on the combination of incoming event +
current DB state.

Specifically, **settlement is a side effect of the negotiation `ACCEPT_OFFER`
action**: when negotiation reaches terminal agreement, `accept_offer` fires
and immediately creates the Alkahest escrow. There is no point in the code
where you could pause and ask "what stage is this deal in?". The closest
thing to a stage cursor is the combination of `orders.status` (`open`,
`matched`, `accepted`, `closed`) + `negotiation_threads.terminal_state`
+ presence/absence of escrow_uid and attestation fields.

**What a stage-aligned model would need:**
- A `deals` table (distinct from orders — deals are per-matched-pair) with
  a `current_stage` enum: `discovery | negotiation | settlement | provision
  | post_settlement`
- Action handlers guard on input stage and emit output stage explicitly
- `ACCEPT_OFFER` splits into `FINALIZE_NEGOTIATION` (stage → negotiation_complete)
  and `CREATE_ESCROW` (stage → settlement_complete)
- Stage transitions emit events on the A2A channel so both parties see
  the same stage

### 4. Most of the stateful event-driven complexity is accidental

**What's truly stateful** (must persist across process restarts):
- Escrow UIDs — on-chain commitments; needed to claim refunds/arbitrate
- Credentials — SSH info for provisioned machines
- Seller's resource leases — "this machine is rented until T"

**What's currently stateful but doesn't need to be:**
- `orders` table (both sides) — orders already live in the registry.
  The local mirror exists to support the event-driven dispatcher, not
  because the buyer or seller logically needs "an order" as a persistent
  entity.
- `negotiation_threads` + `negotiation_messages` — only useful because
  negotiation state survives process restarts. A synchronous negotiation
  inside a single CLI invocation doesn't need this.
- `decisions`, `resource_transition_events` — audit logs. Useful for
  debugging, but belong in a structured log file, not a relational table.
- `policies`, `policy_composites` — pluggable policy storage. Only needed
  if policies are user-configurable at runtime; if policy is just code,
  these tables disappear.

**Why the accidental complexity exists:**
- ADK/A2A framework is event-shaped, forcing event-shaped code
- Agents designed as daemons that must survive restarts mid-flow (true for
  sellers, false for buyers)
- Symmetric buyer/seller design — both sides run identical code, which is
  elegant but overcorrected; buyers and sellers have fundamentally different
  shapes in practice
- Registry coupling — orders exist in the registry, so local agents mirror them

## Target architecture

### Buyer

A buyer is a **CLI command**, not a daemon. One invocation per purchase:

```python
def buy_compute(constraints: ComputeSpec, max_price: int) -> Credentials:
    offers = registry.query(constraints)                   # stateless
    chosen, final_price = negotiate(offers, max_price)     # in-proc state only
    escrow_uid = alkahest.escrow(chosen.seller, final_price)
    credentials = wait_for_fulfillment(escrow_uid)
    db.save_credentials(escrow_uid, credentials)           # persist for later use
    return credentials
```

Persistent local state (maybe a flat JSON file, doesn't need SQLite):
- `{escrow_uid: {seller, final_price, credentials, collected_status}}`

If the CLI dies mid-negotiation, no escrow exists yet → user re-runs.
If it dies after escrow creation, the escrow_uid is recoverable from
the chain → user runs `sms recover <escrow_uid>`.

No `orders` table, no `negotiation_messages`, no policy engine, no event
dispatcher. The buyer is ~500 lines of imperative code.

### Seller

A seller **is** a daemon — they need to listen for incoming buyer offers
and survive restarts mid-provisioning. But it's a much smaller daemon:

Persistent local state:
- `resources`: `{resource_id, vm_host, state: available|reserved|leased,
  lease_end, escrow_uid}`
- `fulfillments`: `{escrow_uid: {fulfillment_uid, tenant_credentials,
  arbitration_status}}`

The seller listens for incoming negotiation requests, runs a synchronous
negotiation per request (in-memory state), and if agreed, provisions.
Settlement and provision are tightly coupled from the seller's POV (once
the escrow exists, provision immediately) and that's fine because both
happen on the seller's machine.

No `orders` table locally either — orders are just registry state. Seller
publishes and updates the registry directly.

Probably ~2000 lines.

### Market operator (registry)

Largely unchanged. It's already a well-scoped FastAPI app. The only
change is ensuring it can be launched via a clean CLI (`market serve
registry --port 8080 --rpc-url ...`).

### Infrastructure deployer

A one-shot command: `market deploy-contracts --rpc-url <url>
--deployer-key <key>`. Deploys Alkahest + ERC-8004 contracts on any
EVM chain, writes addresses to a local env file. This is what a new
market operator runs once to bootstrap.

### Role-separated CLIs

The single `market` CLI can grow role-scoped subcommands:

```
market buy [constraints] --max-price <amount>         # buyer: one-shot
market sell [inventory-csv]                           # seller: daemon
market serve registry                                  # market operator
market deploy-contracts --rpc-url ...                 # infra deployer
```

These are the **public APIs** of the system. Each is usable without the
others (buyer doesn't need to know anything about provisioning internals;
seller doesn't need a registry installation).

## Test joints in the current (coupled, event-driven) implementation

Given that negotiation → settlement → provision runs automatically without
pause points, tests can't halt execution at stage boundaries. But they
can **observe state transitions** via SQLite and the registry, which are
written synchronously by the action handlers. The natural observation
points are:

| Stage transition | Observable signal |
|------------------|-------------------|
| Discovery → negotiation | `seller_order.status == "open"` in registry AND a buyer order with matching resources is created (triggers make_offer) |
| Negotiation → settlement | `negotiation_threads.terminal_state == "success"` in buyer or seller DB |
| Settlement → provision | `orders.status == "accepted"` AND `escrow_uid IS NOT NULL` on both sides |
| Provision → post-settlement | `orders.taker_attestation IS NOT NULL` AND `fulfillment_resource IS NOT NULL` on buyer side |
| Post-settlement complete | `orders.status == "closed"` on both sides |

Each observation point is reachable by polling (buyer/seller SQLite, registry
HTTP). The existing `tests/helpers/polling.py` + `sqlite_reader.py` provide
the primitives.

**Implication for stage-separated tests:** tests trigger a stage's *input*
(e.g. "buyer creates matching order" to enter negotiation) and then poll
for the *output* observable signal (e.g. "escrow_uid appears on buyer's
order"). They can't assert "nothing after this point has happened yet" —
the stages run to completion in one go. But they can assert "this stage's
output is what we expect."

For tests against the *rewritten* architecture, these signals become
redundant because the stage cursor makes it explicit. The tests' assertions
(token balance changed by agreed price, buyer can SSH in, etc.) remain
identical — they are user-property tests, framework-independent.

## Recommended sequencing

The user's stated goal: customer-releasable in weeks, full rewrite in months.

### Weeks (stabilize + package)

1. **CLI wrappers for the missing launch paths.** `market serve registry`,
   `market serve provisioning`, `market deploy-contracts`. Thin wrappers;
   no behavior change. Customers get a real interface for running a node.

2. **Chain-agnostic deployment.** Make `deploy-contracts` take RPC URL
   and key as arguments; drop Anvil hardcodes. Customers can bootstrap
   against real chains.

3. **Compose files become thin wrappers** around the CLI commands.

### Months (rewrite)

4. **Buyer rewrite** as synchronous CLI command with minimal local state.

5. **Seller rewrite** as small daemon with minimal local state.

6. **Stage-aligned state machine** if still desired after the buyer/seller
   split — by that point it may not be necessary because most of the
   stateful flow is the negotiation between peers, not within one peer.

### Tests throughout

The role-separated integration tests we're building assert user-visible
properties that are invariant under the rewrite. They run against the
current coupled implementation today and will run unchanged against the
rewritten implementation tomorrow. This is why the tests are worth
building *now*, before the rewrite — they guard the rewrite against
regression.
