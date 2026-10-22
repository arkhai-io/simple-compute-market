## ADDED Requirements

### Requirement: A lease end keeps the requested instant

A site MUST record and return a truncated lease end at the instant requested, to at least one-second precision, and MUST NOT round it to a coarser unit.

#### Scenario: A lease is truncated mid-minute

- **WHEN** a storefront truncates a lease to 12:00:30
- **THEN** the site's lease end is 12:00:30, not 12:00 or 12:01
