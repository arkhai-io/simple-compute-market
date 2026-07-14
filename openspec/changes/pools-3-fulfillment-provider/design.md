## Context

This content previously lived in `docs/development/ARCHITECTURE.md`'s
"Physical Settlement Scheduler and FulfillmentProvider Architecture"
section, recovered the same way as `pools-2`'s design.md (see that
document's Context for the provenance note — the migration ledger pointed
at a change directory that was never created).

`pools-3` builds directly on `pools-2`: the scheduler answers "which
resource," the provider answers "what do I do with it." Verified against
current code before writing this down: `AnsibleJobService`,
`AnsibleService`, and `ProgrammableMockAnsibleService` still exist as
described in `domains/vms/provisioning/service/src/services/`, and the
storefront's `settlement_claims`/`mechanism_state`/`ClaimsEngine` still
exist in `core/storefront/src/core_storefront/`.

## Goals / Non-Goals

See `proposal.md`.

## Decisions

### 1. Provider owns operations, not placement

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class FulfillmentResult:
    """Provider result persisted on the settlement record."""
    provider_metadata: dict[str, Any]
    credentials: dict[str, Any]

@dataclass
class ProviderStatus:
    state: str           # "running" | "stopped" | "gone" | "unknown"
    detail: str | None = None

class FulfillmentProvider(ABC):
    """Minimum contract for any physical settlement provider.

    The identity key is allocation_id. Infra-specific identifiers are
    provider metadata, not generic lifecycle identity.

    create() is idempotent on allocation_id: re-delivery must detect-or-create,
    not double-provision. teardown() is idempotent: no-op if already gone.
    status() and teardown() operate from the persisted settlement record.
    """

    @abstractmethod
    async def create(
        self,
        request: "PhysicalSettlementRequest",   # from pools-2
        resource: "SettlementResource",          # from pools-2
    ) -> FulfillmentResult: ...

    @abstractmethod
    async def teardown(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> None: ...

    @abstractmethod
    async def get_status(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus: ...
```

A provider may validate that the selected resource is usable, but must not
independently select or substitute a different resource without returning
to the scheduler boundary.

### 2. `ProviderRegistry` maps provider strings to instances

```python
class ProviderRegistry:
    def __init__(self, providers: dict[str, FulfillmentProvider]) -> None:
        self._providers = providers

    def require(self, provider: str) -> FulfillmentProvider:
        if provider not in self._providers:
            raise KeyError(f"No provider registered for '{provider}'")
        return self._providers[provider]
```

The VM service starts as a degenerate singleton
(`"ansible" -> AnsibleFulfillmentProvider`), constructed in the DI
container at startup. New provider implementations extend the registry
without adding provider branches to lifecycle code.

### 3. Ansible provider owns variable construction and pool-level variation

```python
@dataclass
class AnsiblePoolConfig:
    playbook_path: str
    inventory_group: str
    extra_vars: dict[str, Any]
```

Pool-level variation in data-center infrastructure (different FRP servers,
network bridges, firewall topologies, available utilities) is expressed via
`AnsiblePoolConfig`, resolved from `ansible_pool_configs` at execution
time. Different pools get different playbooks and extra vars without a new
provider type. The mock seam stays at this layer:
`ProgrammableMockAnsibleService` is selected by the `mockMode` profile flag
inside the Ansible provider, not promoted to `FulfillmentProvider`. The
`/test/*` controller and e2e gate pattern are unchanged.

### 4. `SettlementRecord` extends the `pools-2` binding identity

```python
@dataclass
class SettlementRecord:
    allocation_id: str
    agreement_id: str
    market: str
    pool_id: str
    provider: str
    resource: "SettlementResource"   # from pools-2
    provider_metadata: dict[str, Any]
    credentials_ref: str | None
    state: str
```

`resource` records what the scheduler selected; `provider_metadata` records
what the provider learned or created while executing settlement. Sensitive
access material should be referenced (`credentials_ref`) rather than stored
inline. This is the same `allocation_id`-keyed identity `pools-2`
establishes non-durably — `pools-3` is what makes it durable, not a second
parallel record.

### 5. `release_delegate` becomes a thin adapter over `teardown`

The `release_delegate` injected into `LeaseLifecycleService` wraps the
registry-resolved provider's `teardown(...)`. The lifecycle state machine
never learns whether the provider is Ansible, Kubernetes, storage, power,
bandwidth, or another mechanism.

## Error surface

Shared with `pools-2`'s design.md (same taxonomy, this change exercises
the fulfillment-side subset): `provider_not_found`,
`provider_unavailable`, `provider_config_invalid`,
`fulfillment_create_failed`, `fulfillment_status_failed`,
`fulfillment_teardown_failed`, `credentials_publish_failed`.

## Risks / Trade-offs

- **`SettlementRecord`/`settlement_claims` ownership boundary is still
  open.** See proposal.md's Open Design-Review Topic. Implementing
  `SettlementRecord` without resolving this risks a second, silently
  divergent settlement-tracking system if a future change tries to bridge
  them without an explicit contract.
- **Ansible-only.** The `FulfillmentProvider` boundary is designed to be
  provider-neutral, but only one implementation exists until a second
  domain needs a different provider.

## Migration Plan

Adds the `SettlementRecord` table (or extends `pools-2`'s table if that
change lands with one instead of staying process-local — reconcile at
implementation time against whatever `pools-2`'s task list actually
produced). No wire break: `AnsibleJobService`/`AnsibleService`'s existing
callers are wrapped, not replaced.
