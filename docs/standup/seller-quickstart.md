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

If you do not yet have a deployed seller agent or seller env file, start with
[Seller Onboarding](seller-onboarding.md) first. This quickstart is the
post-onboarding publish surface.

Canonical onboarding path: `docs/standup/seller-onboarding.md`

## This Path Assumes

- you already have a deployed seller agent
- the seller agent serves a real `/.well-known/agent-card.json`
- the seller agent serves a live `/resources/portfolio`
- you already have the seller env file that contains the canonical auth and
  request URLs

## How To Get These Values

- `--env`:
  - use the seller agent env file produced by your seller deployment path
  - for self-hosted sellers, follow [Seller Onboarding](seller-onboarding.md)
    and then [Seller Agent Deployment](agent-seller.md) until the env file is
    present
- `AGENT_URL` and `AGENT_AUTH_URL`:
  - these are written into the seller env file by the deployed seller runtime
  - use the canonical auth URL for signing, not a transport-specific proxy URL
- `AGENT_PRIV_KEY`:
  - use the seller-owned private key that controls the seller agent
- `/resources/portfolio`:
  - this must already reflect the resource inventory you intend to publish
  - if it does not, stop and fix seller inventory before using the publish
    wrapper

## Required Inputs

- a seller env file with `AGENT_URL`, `AGENT_AUTH_URL`, and `AGENT_PRIV_KEY`
- a reachable seller agent endpoint
- access to the seller's live portfolio through `/.well-known/agent-card.json`
  and `/resources/portfolio`

## Repo Checkout Invocation

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
- The current production entrypoint is the script wrapper above; this is a
  repo-checkout surface today, not an installed `market seller ...`
  subcommand.
- For operator deployment instructions, continue using
  `docs/standup/agent-seller.md`.
