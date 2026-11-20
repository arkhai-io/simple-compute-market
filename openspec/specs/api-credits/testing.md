---
tags: [repository, testing]
---

# API credits testing

How the API-credits integration suites stand to the shared rule on integration
tests, [`integration-tests.md`](../../../docs/guidance/engineering/integration-tests.md).

## Exceptions to shared guidance

| Shared rule | Kind | Here | Reason |
|---|---|---|---|
| [`integration-tests.md`, "No raw calls: the typed client is the contract"](../../../docs/guidance/engineering/integration-tests.md#no-raw-calls-the-typed-client-is-the-contract), its rejection-path tests | overrides | The compatibility baselines (`domains/apicredits/service/tests/integration/test_compat_baseline.py`, `domains/apicredits/storefront/tests/integration/test_compat_baseline.py`) diff each refusal's status and body against the recorded release, where a rejection-path test asserts on status alone | The refusal body is the compatibility surface the baselines hold ([the specification's "API credits composes the api family kit"](spec.md#requirement-api-credits-composes-the-api-family-kit)) |
