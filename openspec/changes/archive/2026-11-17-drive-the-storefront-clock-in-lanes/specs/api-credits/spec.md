## ADDED Requirements

### Requirement: Credits service time is configured and set by its administrator

The API-credits service MUST install its process time source from `time.source`, `"wall"` by default or `"injected"`. It MUST serve `GET /api/v1/system/status`, a signed route admitting the `admin` role, carrying the time section, in either mode. Under injected time it MUST serve `POST /api/v1/system/time`, a signed route admitting only the `admin` role, taking `{"now": <Unix seconds>}`, answering `{"source": "injected", "now": <Unix seconds>}`, refusing an earlier instant with `409 time_moves_forward` and an invalid body with `422 invalid_time`. Both routes MUST have route contracts beside the service's others. Its key consumption, verification, issuance and the site ledger it hosts MUST read the process time source for every instant they record or compare. The credits service's client MUST offer the setting call and the status read.

#### Scenario: The lane sets the credits service's time

- **WHEN** the administrator sets an injected credits service at 1794822300 to 1794823200
- **THEN** it answers source `injected` and now 1794823200, signed at 1794823200, and its status reports the same

#### Scenario: A gated service tries to set the time

- **WHEN** a request signed in the `service` role reaches `POST /api/v1/system/time`
- **THEN** it is refused as unauthorized and the service's time is unchanged
