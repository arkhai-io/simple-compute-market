# Hosted rate library — sections 1–3 evidence

## Scope and prepared first use

This packet covers the interface gates, setup/rate mandate derivation, both compute publication helpers, and the stateless rate adapter. No installed recurring declaration is enabled. Seller notice CLI, re-anchoring, continuation and the complete qualification matrix are not part of this slice.

The prepared target is an invocation-owned in-process payment authority, not a Cloud or hosted deployment. Its persona is deterministic development payer/payee accounts; its authentication/signature method is the fixture signer, never production credentials. It starts with an approved setup/rate commitment, explicit fixture reservation state and an injected clock. No secret environment variables, server, container, tunnel or persistent external state are needed.

From a clean checkout:

```sh
make dist-ci && make -C kit/arkhai-payments first-use-rate
```

The entry point opens the rate library directly, not a shell/menu surface. The [JSON observation](rate-first-use.json) is fixture evidence: exact setup/rate mandate, pure authorization, lost start response, same-key recovery, disclosure, pending notice and winning final stop. It is not live payment or mediation qualification. No screenshots apply.

## Focused validation

- `make -C kit/arkhai-payments typecheck test-unit check-vectors check-generated first-use-rate`: 221 existing tests pass; typing, all published resource/vector checks and first use pass.
- `make -C kit/deal-servicing test typecheck`: 63 existing tests pass; typing passes.
- `make -C kit/arkhai-mediation test`: 77 existing tests pass, published contract/claim signature vectors and generated models pass, typing passes. This consumes foundation dispute behavior; no seller payment fallback or new filing journal is implemented.
- VM: `uv run --find-links ../../../.dist pytest tests/unit/test_settlement_publication.py tests/integration/test_payment_settlement.py tests/integration/test_publication_loop.py -q` in `domains/vms/storefront`: 104 pass, with `ENABLE_EVENT_QUEUE=true` and empty `AGENT_WALLET_ADDRESS`.
- Bare-metal: `uv run --find-links ../../../.dist pytest tests/test_http_publication_rates.py tests/test_http_publication_settlement.py tests/integration/test_payment_settlement_client.py -q` in `domains/bare_metal/storefront`: 21 pass.
- Loopback application tests run with `ALL_PROXY`, `all_proxy`, `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy` and `https_proxy` unset. The inherited SOCKS environment initially failed without socksio; the clean-environment rerun passes. No application dependency was changed for a host proxy.
- Composition-file typing: `uv run --find-links ../../../.dist --with mypy mypy src/<package>/settlement_composition.py --follow-imports=silent --check-untyped-defs` passes for VM and bare-metal. Bare-metal additionally skips `import-untyped` diagnostics for existing dependencies without py.typed; this is a focused file check, not whole-domain typing. Located stage-table narrowing and closure typing defects were repaired separately.
- `make check-packaging check-comment-hygiene`: passes, including wheelhouse/locks, package architecture and the amount-read inventory.
- `bunx @fission-ai/openspec@1.14.0 validate spot-deals-through-arkhai-payments --strict` and `make check-change-index`: pass. The delta retains the foundation's authority and previous-wire scenarios.

No permanent tests were added. The kept projection-descriptor expectation follows the deliberate public-field addition; the VM ordering fixture injects the new declaration seam without changing its ordering assertions.

## End-to-end deployment observation: unobservable

Attempt:

```sh
PODMAN_COMPOSE_PROVIDER="$HOME/.local/bin/podman-compose" make -C e2e-tests test-e2e-vm E2E_VMS_PROJECT=spot-deals-525
```

Exact failure: `/bin/sh: 1: docker: not found`; `make: *** [Makefile:240: test-e2e-vm] Error 127`. It failed on the invocation-owned project's first Compose command, before any stack setup or readiness. No SCM containers were started, no browser run or scenario was attempted, and no E2E result is claimed. Podman was available, but the repository's lane target invokes docker. The existing lane-double change owns deployment qualification; recurring continuation and hosted activation remain their separate changes.

## Review and closeout

The branch is stacked on open-ended-terms (PR #351), itself on PR #350 and PR #349. Maintainer design review is pending. The change remains in implementation; permanent specification promotion and archival wait for the remaining scope and post-code-review closeout. The kit README describes the delivered library and its caller-owned journal contract now.
