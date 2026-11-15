---
tags: [repository, configuration, deployment]
---

# Compose stacks

How this repository's Compose stacks — each end-to-end lane's and the full local
stack — are configured, as instances of
[`configuration.md`](../engineering/configuration.md). Which stacks there are, which
overlay binds what, and how the provisioning mode is chosen is
[`DEPLOYMENT_AND_CONFIG.md`, "Per-domain stack composition"](../../development/DEPLOYMENT_AND_CONFIG.md#per-domain-stack-composition).

## A stack's configuration lives in committed files

**A stack's configuration lives in committed files**
([`configuration.md`](../engineering/configuration.md#a-stacks-configuration-lives-in-committed-files)):
each end-to-end lane and the full local stack. Here the Makefiles choose the Compose
files, a profile, and the provisioning mode, and the committed files are the overlays,
profiles, and secret overlays `DEPLOYMENT_AND_CONFIG.md` lists.

Each base file — the domain files and `compose.bare-metal.yml` — composes topology
only: images, ports, volumes, health checks, the database paths, `REDIS_URL`, a
callback URL naming a service, and the container paths of definition documents.
It binds no identity, configuration file or secret and gives none a fallback, so a
service brought up without an overlay refuses to start for want of its
credential or document, rather than Compose refusing at parse time. Every
development binding lives in a root-level overlay layered with `-f`, stated
literally and relative to the repository root, the project directory of every
`-f` file.

## A lane target names only its files, its project, and its mode

Each end-to-end lane's target in `e2e-tests/Makefile` (`test-e2e-vm`,
`test-e2e-bare-metal`, `test-e2e-apicredits`) names only its compose project and
Compose files and the run's provisioning mode: every value its stack reads is in a
committed overlay, registry or site profile, or secret overlay, and the runner takes
the lane's committed profiles (`RUNNER_PROFILES`). Its `-down` and `-logs` targets
name the same.

## No fallback

Stack files carry public URLs, canonical principals, explicit Resource Pool
offering modes, and exact selected-site bindings. Signer, API-admin,
provisioning SSH, payment account, and buyer credentials are independent
service-scoped file references with no committed fallback. Missing identity,
inventory, pool declaration, site authority, or credential blocks startup or
scenario preflight; it never selects a test signer, default site, payload-
guessed domain, direct executor, or provider simulator.
