## ADDED Requirements

### Requirement: Storefront time is configured and set through one kit route service

Every storefront MUST install its process time source from `[Time] source`, `"wall"` by default or `"injected"`. Under injected time, every storefront MUST bind one framework-free route service from the storefront kit at `POST /api/v1/admin/time`, behind its administrator authentication, taking `{"now": <Unix seconds>}` and answering `{"source": "injected", "now": <Unix seconds>}`, refusing an earlier instant with `409 time_moves_forward` and an invalid body with `422 invalid_time`. Every storefront's signed system status, `GET /api/v1/system/status`, MUST carry the time section. The canonical storefront client MUST offer the setting call and read the time section through its system status read for every domain.

#### Scenario: A lane sets a storefront's time

- **WHEN** an administrator sets an injected storefront to 1794822300
- **THEN** it answers source `injected` and now 1794822300, and its servicing, admission and signed responses read 1794822300

#### Scenario: Both compute storefronts bind one route

- **WHEN** the harness sets time on the VM and the bare-metal storefront through the canonical client
- **THEN** both answer at the same path with the same shape

#### Scenario: A wall-time storefront

- **WHEN** a storefront runs with `[Time] source` unset
- **THEN** its status reports source `wall` and it mounts no time-setting route
