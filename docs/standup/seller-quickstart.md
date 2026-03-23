# Seller Quickstart

This is the seller-facing path for publishing a live offer in the isolated
production environment. It assumes the seller already has a deployed seller
agent, a seller-owned private key, and a live portfolio that the seller wants
to publish from.

The goal is simple:

- no manual JSON crafting
- no operator-only sandbox setup
- one command to publish or refresh a seller offer
- one structured artifact for support and follow-up

Who this is for:

- a seller publishing real inventory into the live production environment
- an agent or service that needs a stable seller publication wrapper

## Required Inputs

- a seller env file with `AGENT_URL`, `AGENT_AUTH_URL`, and `AGENT_PRIV_KEY`
- a reachable seller agent endpoint
- access to the seller's live portfolio through `/.well-known/agent-card.json`
  and `/resources/portfolio`

## One-Command Publish

Publish a fresh offer from the seller's live portfolio:

```bash
python scripts/run_human_seller_publish.py \
  --env /etc/simple-market-service/seller-agent.env \
  --amount 0.0001
```

Optional selectors:

- `--resource-id` to target one live resource
- `--gpu-model` to filter by GPU model
- `--region` to filter by region
- `--quantity` to require a minimum quantity
- `--token` and `--amount` to adjust the demand side
- `--duration-hours` to adjust the publication duration

The wrapper queries the seller's live `/resources/portfolio` output and derives
the offer payload from a real advertised resource. It then signs the publish
request with the seller's canonical `AGENT_AUTH_URL`, not a transport-specific
proxy URL.

## Output

The publish wrapper emits a structured artifact with:

- `schema_version`
- `role=seller`
- `action=publish`
- `status`
- `created_at`
- `endpoints.request_url`
- `endpoints.auth_url`
- `correlation.order_id`
- `correlation.vm_target` when available
- seller-selected resource details

The artifact shape is shared through `scripts/role_contracts.py`, so seller
publication artifacts line up with the buyer, support, platform, and host role
flows.

## Verification

After the command succeeds:

- confirm the returned `seller_order_id`
- verify the live portfolio still reflects the seller's available inventory
- if a buyer matches the offer, continue with the buyer-facing quickstart or
  the operator canary path

## Notes

- This quickstart is seller-facing, not operator-facing.
- It avoids hardcoded example JSON and instead uses the seller's live portfolio
  as the source of truth.
- The current production entrypoint is the script wrapper above, not an
  installed `market seller ...` subcommand yet.
- For operator deployment instructions, continue using
  `docs/standup/agent-seller.md`.
