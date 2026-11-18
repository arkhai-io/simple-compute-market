## MODIFIED Requirements

### Requirement: A bare-metal delivery that conflicts with its recorded result is refused

When the site reports, for an active bare-metal fulfillment, a delivery other than the
result the storefront recorded, the buyer's status, result, and access reads MUST answer a
typed 409 `delivery_conflict`, and the recorded result MUST stand. The storefront MUST NOT
answer such a read with an unhandled error. A buyer's end of the deal MUST NOT be refused
for the conflict: it MUST terminate the lease through the lifecycle `end`.

#### Scenario: The site reports a different delivery

- **WHEN** a buyer reads the status of a fulfillment whose site now reports a delivery that
  differs from the recorded result
- **THEN** the read answers 409 `delivery_conflict` and the recorded result is unchanged

#### Scenario: A buyer ends a deal while the site reports a different delivery

- **WHEN** a buyer ends a bare-metal deal whose site reports a delivery that differs from the
  recorded result
- **THEN** the lease is terminated through the lifecycle `end`, and the status, result, and
  access reads still answer 409 `delivery_conflict` with the recorded result unchanged
