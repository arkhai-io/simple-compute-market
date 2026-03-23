# Role Entry Points

Use this page as the first navigation layer when you are deciding how to
approach SMS from a live production or local development context.

If you are completely new to the repo, start with [Get Started](get-started.md)
before you choose a role-specific path.

Canonical newcomer-routing path: `docs/get-started.md`

## Choose Your Path

### Buyer

Choose this path if you want to purchase compute from a live production
environment.

- Primary doc: [Buyer Quickstart](standup/buyer-quickstart.md)
- Current entrypoint: `scripts/run_human_buyer_purchase.py`
- Install first: [CLI Installer](../cli/INSTALLER.md)
- Notes:
  - this is the default buyer-facing production path
  - the installed `market` CLI is still generic today, so the production buyer
    flow currently uses the role wrapper script instead of `market buyer ...`
  - canonical doc path: `docs/standup/buyer-quickstart.md`

### Seller

Choose this path if you want to join an existing marketplace as a seller.

- Primary doc: [Seller Onboarding](standup/seller-onboarding.md)
- Current entrypoint: `scripts/run_human_seller_publish.py`
- Notes:
  - start with onboarding if you do not already have a deployed seller agent
  - move to [Seller Quickstart](standup/seller-quickstart.md) once you have a
    live seller agent and `/resources/portfolio`
  - canonical doc paths: `docs/standup/seller-onboarding.md`,
    `docs/standup/seller-quickstart.md`

### Platform Operator

Choose this path if you stand up, verify, or canary the live environment.

- Primary doc: [Platform Quickstart](standup/platform-quickstart.md)
- Current entrypoint: `scripts/run_platform_standup.py`
- Notes:
  - if you are starting from zero, begin with
    [Deploy Your Own Marketplace](standup/deploy-your-own-marketplace.md)
  - this is the production orchestration surface for deploy, verify, and canary
  - it composes the existing render, chain-profile, rollout, and canary scripts
  - canonical doc path: `docs/standup/platform-quickstart.md`

### Compute Host Operator

Choose this path if you validate or enroll a KVM host into the provisioning
surface.

- Primary doc: [Host Quickstart](standup/host-quickstart.md)
- Current entrypoint: `scripts/enroll_compute_host.py`
- Notes:
  - this is operator-facing and privileged
  - it layers over the checked-in `compute-provisioning-iac` validation and
    acceptance surfaces
  - canonical doc path: `docs/standup/host-quickstart.md`

### Support Operator

Choose this path if you need to inspect a real run, correlate its order and job
IDs, or reclaim infrastructure safely.

- Primary doc: [Support Quickstart](standup/support-quickstart.md)
- Current entrypoint: `scripts/run_market_support.py`
- Notes:
  - this is the inspection and cleanup surface for completed or broken runs
  - it uses the shared live artifact and correlation contract
  - canonical doc path: `docs/standup/support-quickstart.md`

### Local Developer

Choose this path if you are developing locally, running the local dual-agent
stack, or working on the repo rather than operating the live environment.

- Primary docs:
  - [README](../README.md)
  - [Production Stand-Up Overview](standup/overview.md)
- Notes:
  - use the root README for local chain and local e2e flows
  - use the stand-up overview only when you are moving into the deployed path
  - canonical doc paths: `README.md`, `docs/standup/overview.md`

## Important Distinction

[Human Buyer Walkthrough](standup/human-buyer.md) is an operator-friendly
test harness for the isolated live environment. It is not the default buyer
entrypoint. Use it when you need the manual tunnel-and-sandbox path for live
validation, not when you simply want the buyer-facing production flow.

Canonical operator-harness path: `docs/standup/human-buyer.md`

## Installation

If you are starting from a clean machine, install the CLI first:

- [CLI Installer](../cli/INSTALLER.md)

After install, come back here and choose the role path you actually need.

Canonical installer path: `cli/INSTALLER.md`
