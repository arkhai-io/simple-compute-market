# Seller Onboarding

Use this path when you want to join an existing SMS marketplace as a seller and
you do not already have a deployed seller agent or a ready-to-publish seller
env file.

This is the newcomer seller path. It gets you to the point where the seller
publish wrapper in [Seller Quickstart](seller-quickstart.md) becomes valid.

## Who This Is For

- a new seller joining an existing marketplace
- a service or coordinating agent that needs to prepare a seller for first
  publication

## What You Need From The Marketplace Operator

Before you can publish a seller offer, obtain or provision all of the
following:

- the marketplace registry URL
- the provisioning service URL
- the marketplace chain and registry contract values
- a seller-owned private key
- a plan for where the seller agent will run

For a self-hosted seller agent, the next step is
[Seller Agent Deployment](agent-seller.md). That deployment path produces the
seller runtime values that [Seller Quickstart](seller-quickstart.md) expects,
including:

Canonical doc paths:

- `docs/standup/agent-seller.md`
- `docs/standup/seller-quickstart.md`

- `AGENT_URL`
- `AGENT_AUTH_URL`
- `AGENT_PRIV_KEY`

## Bring The Seller Agent Up

Follow [Seller Agent Deployment](agent-seller.md) until the seller agent is up,
registered, and able to serve:

- `/.well-known/agent-card.json`
- `/resources/portfolio`

Do not continue until the deployed seller env contains a canonical seller URL
and the runtime has written back the seller identity values.

## Seed Or Verify Inventory

The seller publish flow derives its offer payload from the seller's live
portfolio. Before you try to publish, make sure the seller's
`/resources/portfolio` endpoint already reflects at least one resource that you
actually want to offer.

If you are operating the environment yourself, continue with the resource
seeding and seller deployment steps from the stand-up docs before you try to
publish.

## Publish The First Offer

Once the seller agent is reachable and `/resources/portfolio` is populated,
switch to [Seller Quickstart](seller-quickstart.md). That wrapper uses the
seller's canonical `AGENT_AUTH_URL` and live portfolio state to call
`run_human_seller_publish.py` without hand-written JSON.

The first successful publication should leave you with:

- a seller agent that serves `AGENT_URL` and `AGENT_AUTH_URL`
- a live `/resources/portfolio` response
- a publish artifact and returned seller order id
