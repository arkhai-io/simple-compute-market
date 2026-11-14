# Open-ended terms stack replay

Parent: the replayed resize PR. Backup: `pre-rebase/open-ended-terms` at
`7f1a72cf9`. Replay starts after `1edadbc0d`; that merge has no unique conflict
resolution, and its registry work is already in the first PR. The nine duplicate
resize commits are also inherited once, rather than replayed.

The listing-availability conflict is ported to
`core_storefront.migrations.MIGRATIONS` as
`20261107_001_listing_availability`, after the transcript migration. Every
storefront composes that tuple. Immutable baselines and floor fixtures are
unchanged; the deleted legacy migration module stays deleted.

The import-guard correction `52748cb8a` is in the resize PR, where its first core
carrier import appears. The existing publication-fixture gate repair `cd5050158`
moves from spot to this PR, which introduced that gate. Other changes from replay:

- The admin evaluation fixture explicitly projects its synthetic rated mechanism
  as total-billed. The selected-option reference assertion remains 1500.
- The amount-read inventory drops the deleted pre-floor synthesis function and
  classifies dev's mediation effect and funding-control reads. Guard behavior is
  unchanged.
- Rename an optional publication-clause local so it does not reuse a previously
  inferred nonoptional variable; this removes the one additional typing error
  exposed by the terms commits, without changing behavior.

Validation after fresh wheels and each consumer's `reinit`, with shell proxies
removed for pytest. Every row runs the package's complete `tests` tree with
`uv run --frozen --no-sync pytest tests -q --tb=short`:

| Package | Passed |
|---|---:|
| Core | 120 |
| Core buyer | 169 |
| Core storefront | 222 |
| VM domain | 60 |
| VM buyer | 216 |
| VM storefront | 1724 (1 skipped) |
| Bare-metal domain | 224 |
| Bare-metal buyer | 33 |
| Bare-metal storefront | 610 |
| API-credit buyer | 35 |
| API-credit storefront (shared migration consumer) | 274 |
| Alkahest | 463 |
| Arkhai payments | 221 |
| Contact exchange | 141 |
| Pool overrides | 82 |
| Resource-pool contracts | 426 |
| Resource pools | 141 |
| Settlement runtime | 182 |
| `scripts/tests/test_check_change.py` | 18 |

`mypy src` passes for core (9 files) and payments (22 files). VM storefront
reports 136 errors in 33 files, the same diagnostic count as dev and resize.
Other touched packages declare no typing target. VM listing/negotiation packages
have no independent locked test project; their consumer suites cover them.
`make check-comment-hygiene`, `make check-packaging`, and the production amount-read
guard pass. No deployed end-to-end or browser qualification is claimed.

First-use setup and commands are in
[the mixed-selection packet](../negotiate-open-ended-compute-terms/mixed-selection-checkpoint.md#committed-setup).
Both VM and bare-metal commands were rerun successfully: authenticated readiness,
publication, buyer selection/disclosure, bounded horizons and signed cached-option
refusal are observed against temporary ASGI/SQLite targets. Deterministic public
fixture identities and proposed injected recurring ports require no secret or
resident deployment. These observations do not claim a deployed recurring purchase.
