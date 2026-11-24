## ADDED Requirements

### Requirement: The site decides by its process's time source

The site MUST read every instant it records or compares — hold expiry, lease due, activation, release requests and lease-ended reports — from the time source of the process hosting it, and MUST supply from that source every stored time its logic reads. In each process that hosts the site ledger, the provisioning service and the API-credits service, the site's decisions MUST follow that process's injected time when it is configured.

#### Scenario: A hold expires at the set instant

- **WHEN** a hold with expiry 1794822300 sits in a site whose process is injected at 1794822299, and the process is set to 1794822300
- **THEN** the next sweep lapses the hold, and no wall-clock passage before the set does
