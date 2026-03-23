# Get Started

Use this page if you are new to SMS and need the shortest path to the outcome
you actually want.

## Choose The Outcome You Want

### Deploy your own marketplace

Choose this path if there is no existing marketplace yet and you need to stand
up your own live deployment.

- Primary doc: [Deploy Your Own Marketplace](standup/deploy-your-own-marketplace.md)
- Canonical doc path: `docs/standup/deploy-your-own-marketplace.md`
- What this assumes:
  - you are willing to operate the platform infrastructure
  - you can provision cloud, networking, registry, provisioning, and agent
    dependencies
- What you get:
  - a full operator-managed SMS marketplace that you can verify and canary

### Join an existing marketplace as a buyer

Choose this path if a marketplace already exists and you only need to purchase
compute from it.

- Primary doc: [Buyer Quickstart](standup/buyer-quickstart.md)
- Canonical doc path: `docs/standup/buyer-quickstart.md`
- What this assumes:
  - the marketplace operator has already published a live registry, buyer
    agent, and provisioning surface
  - you control a buyer private key
- What you get:
  - one buyer-facing purchase wrapper that discovers an offer, creates the
    buyer order, waits for provisioning, and writes a structured artifact

### Join an existing marketplace as a seller

Choose this path if a marketplace already exists and you want to publish your
inventory into it as a seller.

- Primary doc: [Seller Onboarding](standup/seller-onboarding.md)
- Canonical doc path: `docs/standup/seller-onboarding.md`
- What this assumes:
  - you need help getting to a valid seller agent and inventory state before
    you can publish offers
- What you get:
  - a seller onboarding path that leads into the existing seller publish
    wrapper in [Seller Quickstart](standup/seller-quickstart.md)

### Develop locally

Choose this path if you are working on the repo itself rather than joining or
deploying a live marketplace.

- Primary doc: [README](../README.md)
- Canonical doc path: `README.md`
- What this assumes:
  - you want local chain, local compose, repo tests, or local e2e work
- What you get:
  - the local developer and validation surface documented in the root README

## Installation

If you are starting from a clean machine and need the installed CLI first, use
[CLI Installer](../cli/INSTALLER.md). After install, come back here and choose
the outcome you want.
