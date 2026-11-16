# Section 2 final implementation validation

## Revision and scope

Rebased the eight implementation/checkpoint commits from `a6a30d5cc` onto
`origin/dev` at `20aa47dfe`, without conflicts. The hosted-payment correction
`cb5c8c83e` is `30d370e4e` after rebase. Permanent promotion and archival remain
post-review, not completed by this packet.

## Task 2.15 — unobservable

Required: a deployed negotiation agreeing less capacity than the listing, followed
through settlement to the VM's agreed sizing. **Not observed.** No deployed scenario,
registry seller-proof verification, or real guest sizing is claimed. The focused
SQLite/signed-site reservation regression and provider sizing suite are separate,
lower-level evidence, not a substitute.

Prepared target: checkout-owned VM lane, Compose project `scm-resize-525-d`,
provisioning mode `mock`, images suffixed `-resize-525-d` built from the rebased
checkout. Bob is the seller and the lane buyer uses committed public development
identities; lane payments use the committed double and CA. No external account,
secret, existing deployment selector, persistent seed, or real KVM target was reused.
The intended scenario surface is `e2e_listing_shapes`, particularly its
shape-priced stage; no smaller-shape scenario was added or run after setup failed.

### Commands and results

The host has Podman 5.7.0, no Docker executable, and Podman Compose 1.6.0.
The explicit provider works:

`PODMAN_COMPOSE_PROVIDER=$HOME/.local/bin/podman-compose podman compose version`

It prints `podman-compose version 1.6.0`, rather than the previous unconfigured
mise shim failure. A temporary PATH-local executable named `docker`, containing
`exec podman "$@"`, lets the existing Make targets use Podman without changing
host-global configuration. With that wrapper first on PATH:

`PODMAN_COMPOSE_PROVIDER=$HOME/.local/bin/podman-compose make build-e2e-vm IMAGE_SUFFIX=-resize-525-d`

**Passed.** Built fresh dev-chain, e2e-runner, registry, VM storefront, provisioning,
and payments-double images. The build's leftover `anvil -p 0` was explicitly stopped.

[vm-lane-images.yml](vm-lane-images.yml) records the image bindings used for the
attempt (the actual invocation used an identical temporary overlay).
The startup command, from the checkout root, was:

`PODMAN_COMPOSE_PROVIDER=$HOME/.local/bin/podman-compose PROVISIONING_MODE=mock podman compose -p scm-resize-525-d -f compose.vms.yml -f compose.vms-local.yml -f compose.payments-double.yml -f compose.vms-lane.yml -f docs/attachments/resize-shape-pricing/vm-lane-images.yml up`

**Failed with exit 1 before readiness**, in Podman Compose's `container_to_args`:

`raise ValueError(f"Env file at {i} does not exist")`

`ValueError: Env file at <checkout-parent>/core/registry/.env.docker-compose does not exist`

Only the machine-specific absolute checkout prefix is replaced above. The file
exists at `<checkout>/core/registry/.env.docker-compose`. The included
`domains/vms/compose.yml` states `../../core/registry/.env.docker-compose`;
the provider resolves it against the including root directory instead of the
included file's directory. This is a Compose-provider include/path failure,
not a failed negotiated-size assertion.

Readiness was not reached. No pytest/browser run was started against the down
stack. Cleanup used the same project and file list with
`down -v --remove-orphans` (exit 0); post-cleanup checks found no project
containers, networks, or volumes. The six suffixed image tags were also removed.
No server, browser, tunnel, or deployment remains.

Next deployment attempt needs a provider honoring Compose `include` paths and
the registry carrier/seller-proof dependency
[PR #349](https://github.com/arkhai-io/simple-compute-market/pull/349).
The current provider limitation was recorded with the existing host-tooling owner;
no registry implementation or host-global tool configuration was changed here.

## Final focused validation

All commands ran after the rebase, against verified checkout-built wheels.
No full-suite or typing result is claimed.

| Command / scope | Result |
|---|---|
| `make check-packaging` | Passed: installs, locks, Python declaration, layout, layer/scope/dependency/kind rules |
| `make check-change CHANGE=negotiation-driven-capacity-resize CHANGE_BASE=origin/dev` | All twelve checks passed, including comment hygiene, touched imports, citations, task/index consistency and pinned strict OpenSpec |
| `make check-architecture-change CHANGE=negotiation-driven-capacity-resize` | Passed; no owned exception/override |
| VM decoder, seller policy, multiplier, rate selection, escrow normalization, holds, order/planner, buyer/controller, payment and lifecycle-admission suites | 144 passed |
| Packet's `first_use.py` after storefront `reinit` | Passed; reference remains 10,000 through shape change/resume; derived quotes 80 → 120 → 120; distinct refusals and exit remain available |
| Negotiation-runtime `tests/unit` | 62 passed |
| Core-buyer selected-option negotiation and orchestrator | 25 passed |
| VM-buyer client, resume, orchestrator and stage-dispatch suites | 69 passed |
| VM provisioning adapter `test_vm_fulfillment_plan.py` | 52 passed |
| Core-storefront `test_domain_binding_migrations.py` | 14 passed |
| Policy kit's existing `tests` | 97 passed |
| Core `test_rate_helpers.py` | 18 passed, unchanged truncation semantics |
| `bunx @fission-ai/openspec@1.14.0 validate negotiation-driven-capacity-resize --strict` | Passed explicitly, as well as through `check-change` |

Total: **481 focused cases passed**, plus the observational first-use replay.
One setup invocation incorrectly tried `make -C core reinit`, a target core does
not define. The corrected declared `uv run --frozen --find-links ../.dist pytest
 tests/unit/test_rate_helpers.py -q` invocation passed. The failed setup did not
run the rate-helper tests or the following strict validator; both were then run
successfully.

Reproduce the main VM encounter using the preparation and one-command entry point
in [index.md](index.md#setup-and-reproduction). It uses fresh temporary SQLite,
deterministic public fixture principals and injected advertised-listing evidence,
not the failed Compose deployment.

## Review and deployment boundary

- **D-d:** consume the registry listing's top-level rate structure with retained
  seller proof, dependent on PR #349.
- **D-e:** pin the structure digest at opening and refuse changed/missing pins on
  continuation or acceptance with `rate_structure_changed_reopen`; exit stays open.
- **Hosted payments:** verify the monetary Agreement's mandate, not equality with
  the transcript's basis-point scalar; mismatched mandates still refuse.
- **Release note:** drain incompatible in-flight negotiations before deployment,
  and before rollback across the absolute-amount/basis-point boundary.
