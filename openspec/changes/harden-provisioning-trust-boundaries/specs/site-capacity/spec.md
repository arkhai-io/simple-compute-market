## ADDED Requirements

### Requirement: A site authority admits the administrator on every route

A site authority MUST admit the `admin` role on every route contract it serves, beside the roles the contract names, without each contract enumerating it, since every reservation, declaration and ledger entry it holds is its operator's. A contract MUST name at least one caller role, or none for a route the administrator alone may call. The administrator's role MUST be held by the operator's own principals; a service component calls under its own role.

#### Scenario: The administrator calls a seller route

- **WHEN** a request signed under the `admin` role by an active administrator principal calls a capacity route whose contract names only `seller`
- **THEN** it is authorized

#### Scenario: A route the administrator alone may call

- **WHEN** a request signed under the `seller` role calls the capacity definitions import, whose contract names no caller role
- **THEN** it is refused, and the same request under the `admin` role is authorized
