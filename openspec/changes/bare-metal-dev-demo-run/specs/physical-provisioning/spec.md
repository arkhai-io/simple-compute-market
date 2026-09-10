## ADDED Requirements

### Requirement: Whole-host access acts on a derived lease account

The executing authority MUST determine the operating-system account a whole-host
grant or reclaim names, and MUST refuse the action before dispatch unless that
account is the canonical marketplace lease form derived from the settlement
identity. Where the settlement identity is recoverable, the account MUST equal
that derivation exactly; otherwise it MUST match the canonical form. The
settlement identity MUST be used exactly as accepted, without trimming or other
normalization, so that two persisted identities differing only in surrounding
whitespace derive distinct accounts.

Buyer input MUST NOT determine the account, and provider-specific access
metadata MUST NOT be treated as authority for it. A refused reclaim MUST surface
rather than report the Capacity Reservation as released.

This constrains which account an action may name. It is not host-side ownership
and does not establish that the named account was created by this marketplace.

#### Scenario: Access metadata names an account outside the derived form

- **WHEN** a grant or reclaim carries an account that is not the canonical lease
  form, including a system or operator name
- **THEN** the action fails before dispatch and no job is submitted

#### Scenario: Access metadata names another settlement's account

- **WHEN** the account is a well-formed lease account derived from a different
  settlement identity
- **THEN** the action fails before dispatch

### Requirement: Whole-host access returns the tenant-facing endpoint

A Physical Resource MUST be able to record a tenant-facing address and port
distinct from the address and port the provisioner connects through, and both
MUST persist across inventory import and be emitted by every rendering of that
resource's inventory row. A successful whole-host access result MUST report the
tenant-facing endpoint when one is recorded, and the provisioner's endpoint
otherwise.

#### Scenario: Provisioner and buyer reach the host differently

- **WHEN** the provisioner reaches a host through a management path and the
  resource records a separate tenant-facing endpoint
- **THEN** the buyer receives the tenant-facing endpoint, not the management one

#### Scenario: One endpoint serves both

- **WHEN** no tenant-facing endpoint is recorded
- **THEN** the access result reports the provisioner's endpoint unchanged
