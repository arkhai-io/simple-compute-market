## MODIFIED Requirements

### Requirement: A bare-metal delivery that conflicts with its recorded result is refused

When the site reports, for an active bare-metal fulfillment, a delivery other than the
result the storefront recorded, the buyer's status, result, and access reads MUST answer a
typed 409 `delivery_conflict`, and the recorded result MUST stand. The storefront MUST NOT
answer such a read with an unhandled error. A buyer's end of the deal MUST NOT be refused
for the conflict: it MUST terminate the lease through the lifecycle `end`, and the recorded
result MUST stand. Once the lease is ending, the buyer's reads MUST report the ending as for
any ended lease, not the conflict.

#### Scenario: The site reports a different delivery

- **WHEN** a buyer reads the status of a fulfillment whose site now reports a delivery that
  differs from the recorded result
- **THEN** the read answers 409 `delivery_conflict` and the recorded result is unchanged

#### Scenario: A buyer ends a deal while the site reports a different delivery

- **WHEN** a buyer ends a bare-metal deal whose site reports a delivery that differs from the
  recorded result
- **THEN** the end is not refused and the lease is terminated through the lifecycle `end`;
  afterwards the status read reports the lease ending, the result read answers the recorded
  result unchanged, and the access read is refused as outside an active lease, none of them
  answering `delivery_conflict`

## ADDED Requirements

### Requirement: A bare-metal result read answers the recorded result while its lease ends

From delivery through release, a buyer's bare-metal result read MUST answer the recorded
result and receipt once both are recorded, including while the lease is `terminating`
before the site reports a teardown state. It MUST answer that the result is not ready only
while no result or receipt is recorded.

#### Scenario: A buyer reads the result of a deal whose lease is ending

- **WHEN** a buyer reads the result of a delivered bare-metal deal whose lease the buyer has
  ended and whose site has not yet begun the teardown
- **THEN** the read answers the recorded result and receipt

#### Scenario: A lease ends before delivery

- **WHEN** a buyer reads the result of a bare-metal deal whose lease ended before any result
  was recorded
- **THEN** the read answers that the result is not ready
