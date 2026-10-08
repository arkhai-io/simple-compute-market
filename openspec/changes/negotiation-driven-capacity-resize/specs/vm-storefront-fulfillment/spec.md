## ADDED Requirements

### Requirement: The agreed shape is reserved

When a VM negotiation concludes with a capacity shape other than the listing's
advertised shape, the accepted artifacts and the settlement order MUST carry the agreed
shape, the capacity claim MUST be built from it, and the committed reservation MUST
carry its dimensions. The listing's advertised shape MUST NOT be substituted at
acceptance, settlement, or fulfillment. Where a hold is placed at acceptance, it MUST
hold the agreed shape.

#### Scenario: A smaller shape is agreed

- **WHEN** a negotiation agrees a shape with fewer quantities than the listing
  advertises
- **THEN** the settlement order, the claim, and the committed reservation all carry
  the agreed quantities, and the VM is built to them

#### Scenario: No revised shape was agreed

- **WHEN** a negotiation concludes without any round revising the shape
- **THEN** the listing's advertised shape is reserved, as before
