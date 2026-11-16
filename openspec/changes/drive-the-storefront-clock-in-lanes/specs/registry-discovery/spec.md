## ADDED Requirements

### Requirement: Registry time is configured and set on its administrator surface

The registry MUST install its process time source from `TIME_SOURCE`, `"wall"` by default or `"injected"`. Under injected time it MUST serve `POST /admin/time` behind its administrator bearer key, `REGISTRY_ADMIN_API_KEY`, as its other `/admin` routes are, taking `{"now": <Unix seconds>}`, answering `{"source": "injected", "now": <Unix seconds>}`, refusing an earlier instant with `409 time_moves_forward` and an invalid body with `422 invalid_time`. It MUST serve `GET /admin/status` behind the same key, carrying the time section, in either mode. Publisher authentication and listing decisions MUST read the process time source. The registry client MUST offer the setting call and the status read, sending the administrator key.

#### Scenario: A storefront publishes after an advance

- **WHEN** the lane sets the registry and a storefront to the same instant, 1800 s past their previous one, and the storefront publishes
- **THEN** the registry accepts the publication's signed timestamp

#### Scenario: The time is set without the administrator key

- **WHEN** a request to `POST /admin/time` carries no bearer key or a wrong one
- **THEN** it is refused `401` and the registry's time is unchanged
