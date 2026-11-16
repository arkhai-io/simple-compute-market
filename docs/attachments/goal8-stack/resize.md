# Resize stack replay

Parent: the replayed registry PR. Backup: `pre-rebase/resize-multiplier`
at `ba77a3b30`. The nine original commits are retained in order.

Conflict resolutions:

- Core's client keeps dev's removal of schema creation at open. Transcript terms
  remain read/written by the client and are added by
  `core_storefront.migrations.MIGRATIONS`, after the immutable baseline. All three
  storefront chains compose `20261106_001_negotiation_message_terms`; core's test
  database helper composes it too. The deleted `sqlite_migrations.py` stays deleted.
- Payment settlement imports the new accepted-order helper, without restoring
  obsolete delivery imports removed by dev's shared compute-delivery extraction.
- The smaller-shape regression now exercises VM's delivery ports and the real
  capacity reserve/commit API instead of the deleted private fulfillment helper.
  It retains the persisted shape, hold and leased-reservation dimension assertions.
- The already-authored `52748cb8a` import-guard correction moves here from the terms
  PR: resize already introduces a permitted core-carrier import. It is not replayed
  twice. Role-package import restrictions remain; the old carrier restriction was
  stricter than the repository's architecture rules.
- Refresh `domains/compute/delivery/uv.lock` for core storefront's newly declared
  `typing-extensions` dependency.

No negotiation or pricing semantics changed during replay. Migration timing now
follows dev's explicit packaged-command contract.

Validation used fresh wheels and each project's `reinit`, then
`uv run --frozen --no-sync pytest tests -q --tb=short`:

| Package | Result |
|---|---|
| Core buyer | 169 passed |
| Core storefront | 222 passed |
| VM domain | 60 passed |
| VM buyer | 216 passed |
| VM storefront | 1724 passed, 1 skipped |
| Bare-metal storefront | 610 passed |
| API-credit storefront | 274 passed |
| Negotiation runtime | 62 passed |
| VM storefront `mypy src` | 136 errors in 33 files, matching the dev count |
| `make check-comment-hygiene` | passed |
| `make check-packaging` | passed |

Packages without their own locked test project (VM listings and negotiation) are
covered by their storefront/buyer consumers. Other packages above declare no
independent typing check. Shell proxy variables were removed for pytest: inherited
SOCKS settings otherwise fail HTTP client construction before a request.
No end-to-end deployment or browser run was performed.

First use:

```sh
make dist
make -C domains/vms/storefront reinit
(cd domains/vms/storefront && PYTHONPATH=src:. uv run --frozen --no-sync python ../../../docs/attachments/resize-shape-pricing/first_use.py)
```

Observed multiplier 10000 with quotes 80, 120 and 120 across opening, shape change
and resume; inadmissible shapes refuse before pricing and withdrawal still exits.
The committed script owns temporary SQLite, fixture principals and state and
removes them on exit; no deployment or credentials are needed.
