## ADDED Requirements

### Requirement: Provisioning time is configured and set on its system surface

The compute provisioning service MUST install its process time source from `time.source`, `"wall"` by default or `"injected"`. Under injected time it MUST serve `POST /api/v1/system/time` behind its administrator authentication, taking `{"now": <Unix seconds>}`, answering `{"source": "injected", "now": <Unix seconds>}` and refusing an earlier instant with `409 time_moves_forward`; its system status MUST carry the time section. Its lease watchdog, lease termination and job engine MUST read the process time source for every instant they record or compare. The provisioning client MUST offer the setting call.

#### Scenario: A truncated lease ends at the set instant

- **WHEN** a lease truncated to 1794822300 is held by the paused lease watchdog, provisioning is set to 1794822300, and one watchdog cycle is stepped
- **THEN** the lease ends by expiry with effective instant and claimed deadline 1794822300

#### Scenario: A termination is stamped in lane time

- **WHEN** an injected provisioning service at 1794822300 terminates a lease
- **THEN** the lease-ended report states effective instant 1794822300
