## ADDED Requirements

### Requirement: The credits service's site authority admits the administrator on every route

The API-credits service's site authority, serving the credits ledger and capacity routes, MUST admit the `admin` role on every route contract beside the roles the contract names, as every site authority does, since the keys, balances, grants and ledger it holds are its operator's. Its system status and time routes MUST admit the `admin` role alone.

#### Scenario: The administrator reads a credits route

- **WHEN** a request signed under the `admin` role by an active administrator principal calls a credits route whose contract names another role
- **THEN** it is authorized

#### Scenario: Another role reads system status

- **WHEN** a request signed under a role other than `admin` calls the credits service's system status
- **THEN** it is refused
