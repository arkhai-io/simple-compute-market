## ADDED Requirements

### Requirement: API-credit system status is the administrator's signed read

The API-credit storefront's system status MUST be read only by its administrator,
through the same signed request and signed response every other administrator route
uses (operation `admin_system_status`, resource `system/status`), so the canonical
storefront client reads it and an unsigned request is refused. Beside its checks,
system status MUST report every lifecycle loop the storefront's loop controller holds,
by name: the loop's state and the outcome of its last cycle, in the shape the other
storefronts report.

#### Scenario: An unsigned status read is refused

- **WHEN** a caller requests the API-credit storefront's system status without the
  administrator's signature
- **THEN** the request is refused as unauthenticated and no status is returned

#### Scenario: The administrator reads every loop's state

- **WHEN** the administrator reads system status through the canonical storefront
  client
- **THEN** the signed response reports every lifecycle loop, the capacity-event
  pollers' sites among them, with its state and its last cycle's outcome
