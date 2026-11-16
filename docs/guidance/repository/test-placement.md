---
tags: [repository, testing, python]
---

# Test placement

Where this repository's tests at each level live and how they take their seams, as
instances of [`test-levels.md`](../engineering/test-levels.md),
[`test-seams.md`](../engineering/test-seams.md), and
[`testing-python.md`](../engineering/testing-python.md). The levels as this
repository runs them are
[`TESTING.md`, "Four-Level Hierarchy"](../../development/TESTING.md#four-level-hierarchy).

## Unit tests

Unit tests take their doubles through the constructor
([`test-seams.md`](../engineering/test-seams.md); its Python form in
[`testing-python.md`](../engineering/testing-python.md)).

**Command modules.** A storefront's operator commands and a domain's buyer commands
are command modules, whose factories are their one seam
([`testing-python.md`, "A command module's factories are its seam"](../engineering/testing-python.md#a-command-modules-factories-are-its-seam)).
The bare-metal buyer CLI
(`domains/bare_metal/buyer/src/arkhai_bare_metal_buyer/cli.py`) has this shape:
its tests replace `fresh_identity`, `recovery_identity`, `registry_client`, and
`payment_approval`. The other CLIs' tests, and one unit test in the bare-metal buyer
package, do not follow the rule: they replace library names and names the module
imports, an unowned gap in
[`ROADMAP.md`](../../development/ROADMAP.md), and are no model for a new test.

## Integration tests

A service's integration tests drive its in-process application through its typed
client ([`integration-tests.md`](../engineering/integration-tests.md);
the setup in [`testing-python.md`, "Integration test setup"](../engineering/testing-python.md#integration-test-setup)).
A kit library's are library integration, in its `tests/integration`
([`test-levels.md`, "Integration tests"](../engineering/test-levels.md#integration-tests)).

## Registration and traffic are different proofs

**Registration and traffic are different proofs**
([`testing.md`](../engineering/testing.md#registration-and-traffic-are-different-proofs)).
The frps admission plugin's real-frp tests
(`tools/frp-grant-admission/tests/frp/`) hold to this: an admitted proxy
carries bytes from frps's remote port to a listener behind frpc, and a
proxy that outlives a reload carries traffic on a held connection and a
new one. Those tests are external-process integration tests, run in a gate
that fails on a skip, as the native Ansible checks are
([`ansible-gates.md`](ansible-gates.md)).

## Contract fixtures

Contract fixtures follow [`contract-fixtures.md`](../engineering/contract-fixtures.md),
placed as [`testing-python.md`, "Contract fixtures"](../engineering/testing-python.md#contract-fixtures)
says. A same-package fixture here is
`domains/vms/storefront/tests/fixtures/publication_cycle.py`; a cross-package one
is `core/storefront-client/src/storefront_client/fixtures/escrow.py`, imported as
`from storefront_client.fixtures.escrow import build_claim_response` alongside
`from storefront_client import SyncStorefrontClient`.

## Test file layout

A service's and a kit library's tests split into `unit/` and `integration/`
([`testing-python.md`, "Test layout"](../engineering/testing-python.md#test-layout)).
System-level tests live in the separate `e2e-tests` package, itself
split into `unit/` (its own helper logic), `smoke/`, and `e2e/`. A Helm
chart's render tests live in its own `tests/` directory
([`chart-render-tests.md`](chart-render-tests.md)).
