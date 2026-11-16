## ADDED Requirements

### Requirement: Registry time is configured and set on its system surface

The registry MUST install its process time source from `TIME_SOURCE`, `"wall"` by default or `"injected"`. Under injected time it MUST serve `POST /api/v1/system/time` behind its administrator authentication, taking `{"now": <Unix seconds>}`, answering `{"source": "injected", "now": <Unix seconds>}` and refusing an earlier instant with `409 time_moves_forward`; its system status MUST carry the time section. Publisher authentication and listing decisions MUST read the process time source. The registry client MUST offer the setting call.

#### Scenario: A storefront publishes after an advance

- **WHEN** the lane sets the registry and a storefront to the same instant, 1800 s past their previous one, and the storefront publishes
- **THEN** the registry accepts the publication's signed timestamp
