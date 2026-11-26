---
tags: [repository, persistence, testing]
---

# Migration chains

This file lists this capability's exceptions to the shared guidance on migration
chains, as
[`rules.md`, "When an exception is expected"](../../../docs/guidance/engineering/rules.md#when-an-exception-is-expected)
admits them. How each chain runs is
[`migrations-at-startup.md`](../../../docs/guidance/repository/migrations-at-startup.md).
How each chain is proven is
[`migration-chain-tests.md`](../../../docs/guidance/repository/migration-chain-tests.md).
Why the chains are shaped as they are is the companion's
["The baseline and adoption"](architecture.md#the-baseline-and-adoption).

## Exceptions to shared guidance

| Shared rule | Kind | Here | Reason |
|---|---|---|---|
| [`migration-tests.md`](../../../docs/guidance/engineering/migration-tests.md), "The chain": the baselines alone reproduce the fixture's snapshot exactly | overrides | The API-credit service's baselines reproduce its v0.3.0 floor fixture except for one index, `uq_capacity_buckets_host_id`. The site ledger's repair `20261126_001_capacity_bucket_host_index` creates it after the baselines. Its test in `domains/apicredits/service/tests/integration/test_migrations.py` names that difference exactly, and its adoption test shows an adopted database ending with a fresh database's schema and ledger | The site ledger's baseline is shared with compute provisioning, whose v0.3.0 schema names the index, and a kit contributes the same migrations to every chain composing it. The v0.3.0 API-credit service built the ledger from its models without the index. The table's own `UNIQUE (host_id)` already enforced the same rule |
