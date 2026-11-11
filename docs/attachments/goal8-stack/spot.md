# Spot-deals stack replay

Parent: the replayed terms PR. Backup: `pre-rebase/spot-deals` at `73871d286`.
The publication-fixture correction `cd5050158` is inherited from the terms PR,
where its declaration gate first appears. The other three commits are replayed
in order, with no duplicated registry or resize history and no merge commit.

The campaign-index conflict keeps dev's archived delivery-path status and related
current dependencies while recording spot's implementation of sections 1–3 only.
Sections 4–6 and maintainer design review remain pending. The composition conflict
keeps the incoming typed `selected_clause` local alongside the terms PR's current
publication inputs. A joined argument line from that resolution is split again.
There is no rate-library behavior change beyond the original three commits.

Validation follows fresh wheels and each consumer's `reinit`. Complete existing
`tests` trees run with `uv run --frozen --no-sync pytest tests -q --tb=short`, with
shell proxies removed for HTTP application tests:

| Package | Result |
|---|---|
| Arkhai payments | 221 passed |
| Deal lifecycle contracts | 37 passed |
| Deal servicing | 70 passed |
| VM storefront | 1724 passed, 1 skipped |
| Bare-metal storefront | 610 passed |
| Payments `make test` | passed: typing including examples, vectors, generated models and all 221 tests |
| Deal servicing `make typecheck` | passed, 12 source files |
| VM storefront `mypy src` | 129 errors in 32 files; dev has 136 in 33 files |
| VM settlement composition focused mypy | passed, 1 file |
| Bare-metal settlement composition focused mypy | passed, 1 file; existing untyped dependency imports excluded |
| `make check-comment-hygiene` | passed |
| `make check-packaging` | passed |

Deal lifecycle contracts declares no independent typing target. Whole-project VM
typing remains owned by [`type-core-packages`](../../../openspec/changes/type-core-packages/).
The existing spot commit narrows and types the composition path, reducing its
baseline diagnostics. No new permanent tests were added during replay. No deployed
end-to-end or browser qualification was performed; the rebase does not enable an
installed recurring declaration or implement the remaining spot scope.

First use:

```sh
make dist
make -C kit/arkhai-payments first-use-rate
```

The committed [prepared target](../spot-deals-sections-1-3/index.md#scope-and-prepared-first-use)
owns in-process state, deterministic development payer/payee accounts, fixture
signing and an injected clock. Rerun observations were authorization `allow`, lost
start response `unknown`, same-key retry `accepted`, disclosure `allow`, notice
`accepted` and payer stop `accepted`. It uses no secrets, server, container or
persistent external state and does not qualify live payment or mediation.
