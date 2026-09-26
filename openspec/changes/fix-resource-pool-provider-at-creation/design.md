# Design

## Context

`ResourcePoolService` (`kit/resource-pools/src/market_resource_pools/service.py`)
holds one immutability rule, `_require_backing_unchanged`, applied on
`replace_pool` and on `update_pool` when `policy_tags` are supplied. It refuses
the request before any write and leaves the pool untouched. The provider swap
sits in the same two methods: `replace_pool` deletes the old handler's
configuration when `old_provider != data.provider`; `update_pool` does the same
when `data.provider` names a different provider.

## Decisions

### Refuse, do not coerce

A differing provider is refused with the same shape as a differing backing
declaration, before any write. It is not silently ignored and it is not treated
as "same provider, new configuration": an operator who sent a different provider
meant something, and the only correct answer is that this pool cannot do it.

### The refusal is read-only

Rejection happens before `delete_config`. The current code deletes the old
provider's configuration first and writes the new provider's afterwards inside
one transaction; a refusal between the two would roll back, but a refusal before
either is simpler to prove and matches `_require_backing_unchanged`'s placement.

### `PoolUpdate.provider` stays on the wire

Removing the field from the patch model would turn a refused request into a
validation error with no explanation. The field stays; a value equal to the
pool's own provider is a no-op and any other value is refused. Whether to retire
the field later is not this change's question.

## Migration path

Inventory that must be delivered by another executor moves through a second
pool declaring that provider. The drain invariant forbids a member from leaving
a pool under a live obligation, which is what makes that path safe; the refusal
message names it so an operator reaching the rule learns the supported path
rather than only the prohibition.
