## ADDED Requirements

### Requirement: A lease view shows the lease's activation deadline

The compute contract's lease view MUST carry a nullable activation deadline, the instant the site recorded at commit, null for a lease on which the site recorded none. It MUST NOT default or infer the instant. The field MUST be optional on the contract's current major, so a reader that predates it reads the view unchanged.

#### Scenario: A lease with a deadline is read

- **WHEN** a VM or bare-metal caller reads a lease the site committed with an activation deadline
- **THEN** the lease view carries that instant beside `activated_at_utc`

#### Scenario: A lease with no deadline is read

- **WHEN** a caller reads a lease whose pool resolved no delivery deadline, or one committed before the site recorded deadlines
- **THEN** the view's activation deadline is null
