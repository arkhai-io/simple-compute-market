## Why

The nightly E2E workflow has failed every run since it was added on
2026-06-18 — 54 consecutive failures against both `main` and `dev`. The
first failure diagnosed is a packaging defect:

```
[market] skipping buyer domain 'vms': failed to load
         (No module named 'domains.vms.listings.listing_mode')
`market buy` needs a buyer market domain and none is installed.
```

`domains/vms/{listings,negotiation,settlement}` has `__init__.py` files but
no `pyproject.toml`. No distribution owns it. Its two consumers therefore
obtain it two incompatible ways: the storefront copies the source tree into
its image and sets `PYTHONPATH=/app`, while the buyer — which must be
genuinely distributable, including as a PyInstaller binary — reassembles the
namespace inside its own wheel through a hand-maintained
`[tool.hatch.build.targets.wheel.force-include]` table, one entry per file.
Five modules added during the POOLS work were never added to that table, so
`arkhai-vms-buyer` has shipped an unimportable package.

Two structural causes make that manifest necessary, and both must be fixed
for the packaging fix to hold:

**Eager cross-package facades.** The buyer needs six formatting helpers from
one module, `listings/buyer_cli.py`. But `listings/__init__.py` eagerly
re-exports from eight modules including `reconciler.py`, which the buyer
never calls and which imports the three modules the wheel was missing. The
buyer's true dependency is two files; the facade makes it twenty-four.

**Negotiation policies resolve through mutable global state.** Policy names
in operator configuration resolve against a module-level `_REGISTRY` in
`market_policy`, written by decorators at import time, by lazy RL
registration, and by an unconditional scan of `~/.config/arkhai/policies` —
and written *again* during resolution, which caches entry-point lookups into
the same dict. Nothing declares the entry-point group the resolver reads, so
in practice registration depends on import order, which is why the storefront
image must copy the source tree at all. Kit's own error message instructs the
operator to "ensure the VM policy package is imported", placing a domain
reference inside kit's diagnostics.

The consequence of that error message is not cosmetic. Because
`core_buyer.plugins` catches every load exception, prints to stderr, and
continues, a broken install reports "none is installed" instead of failing.
That is how a packaging defect stayed invisible for 54 nightly runs.

`domains/bare_metal` already demonstrates the target shape: it imports
`escrow_shape_guard` and `listed_price_middleware` as modules and composes
them as objects, touching no registry.

## What Changes

- Kit gains a negotiation policy source protocol, concrete loaders, and a
  builder that produces one immutable, validated catalogue. Kit gains no
  knowledge of domains, domain contracts, or capabilities.
- Loading is fatal on failure, strict on name conflict, and validated for
  callable shape — all at `build()`, before a role serves requests.
- `market_core` gains an optional `NEGOTIATION` capability whose hook returns
  policy *sources*, so each domain chooses its own discovery mechanisms.
  Neither `market_core` nor `market_policy` gains a dependency; the capability
  is satisfied structurally.
- The composed catalogue is injected into the seller round hook. It is not a
  module-level singleton, so a single process can compose more than one role
  and tests can compose deliberately broken catalogues.
- The decorator's implicit cross-package discovery path, the entry-point
  cache write during resolution, and the `market_policy` compatibility
  monkey-patch are removed. `market_policy.buyer_policy`'s parallel global
  registry is converted to the same composed form.
- `domains/apicredits` is brought to the same pattern: it declares the
  negotiation capability, offers its four guards as an inline source, and its
  own `force-include` manifest is replaced by owned packaging. Its manifest
  audited complete at proposal time, but a complete hand-maintained manifest is
  what `vms/buyer` had before the POOLS work, so it is corrected rather than
  left to drift.
- `domains/vms/{listings,negotiation,settlement}` is split by consumer:
  storefront-only modules move into `market_storefront`, the buyer's
  formatting helpers move into the buyer, and genuinely shared models move
  into `arkhai_vms`. `force-include` is removed from
  `domains/vms/buyer/pyproject.toml`, and the storefront image stops copying
  `domains/` and relying on `PYTHONPATH=/app`.
- Confirmed dead code is deleted: two unreferenced functions and the
  compatibility monkey-patch, which no caller reads.
- State: **Proposed. Scopes the first diagnosed cause of the E2E failure.
  Further defects found on the same build chain are amended here rather than
  opened as separate changes.**

## Impact

- Affected specs: `market-composition`, `negotiation-protocol`
- Affected code: `kit/policy`, `core/src/market_core/domain_contract.py`,
  `core/buyer` (plugin loading, policy surface), `core/storefront`
  (composition), `domains/vms/{buyer,domain,storefront}`,
  `domains/vms/{listings,negotiation,settlement}`,
  `domains/apicredits` (negotiation, storefront, and root packaging),
  `domains/bare_metal/storefront`, the VM storefront `Dockerfile` and
  `compose.yml`
- Behaviour change to record: `~/.config/arkhai/policies` is scanned
  unconditionally today. The directory loader remains available in kit, but
  no domain registers it, so that path is no longer scanned. No repository
  configuration sets `extra_policy_paths`; its declared default is empty.
- `domains/bare_metal` declares no `NEGOTIATION` capability. This is correct,
  not an omission: it composes middleware objects directly and exposes no
  policy names to configuration.
- Related but separate: `remove-relative-uv-sources` enforces wheel-only
  resolution by removing parent-path `tool.uv.sources` entries. This change
  removes a different mechanism — an unowned namespace assembled by
  cross-project file manifests — and neither supersedes the other.
