## ADDED Requirements

### Requirement: Durable result-notification application

A storefront result receiver MUST authenticate the provisioning caller before applying a notification and MUST atomically persist stable event/result identity with the resulting local transition. Replays MUST return the prior outcome, and an older credential/result generation MUST NOT overwrite a newer applied generation.

#### Scenario: Notification is replayed

- **WHEN** the receiver accepts the same authenticated event identity more than once
- **THEN** it applies the local transition once and returns the recorded acknowledgment for subsequent deliveries

#### Scenario: Stale generation arrives late

- **WHEN** a result or credential generation lower than the storefront's applied generation is delivered
- **THEN** the storefront retains the newer state and records the stale delivery without replacing it
