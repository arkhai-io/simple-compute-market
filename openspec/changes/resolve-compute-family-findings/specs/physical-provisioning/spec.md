## ADDED Requirements

### Requirement: The provisioning service answers an unroutable request by what failed to match

The provisioning service's authentication middleware MUST answer a request that resolves to
no route contract, without signing it, with 404 when no contract names its path, 405 naming
the allowed methods when a contract names its path under another method, and 400 naming the
field when its route's body resource cannot be bound. Composing the route table MUST refuse
two contracts that claim one method and path. Such an answer is unsigned because no contract
supplies the operation and resource a response proof binds.

#### Scenario: An unknown path is requested

- **WHEN** a request names a path no route contract matches
- **THEN** the service answers an unsigned 404 before checking authentication

#### Scenario: A known path is requested with another method

- **WHEN** a request uses a method no contract binds to a path a contract names
- **THEN** the service answers an unsigned 405 whose `Allow` names the contract's methods

#### Scenario: A route's body resource is missing

- **WHEN** a request matches a route whose bound resource is a body field it omits
- **THEN** the service answers an unsigned 400 naming the field

#### Scenario: Two contracts claim one route

- **WHEN** the route table is composed from contributions whose patterns both match one
  method and path
- **THEN** composition is refused before the service accepts traffic

### Requirement: The family client names an unauthenticated answer

The compute provisioning client MUST report an answer that carries no response
authentication as unauthenticated, with its status, distinctly from one whose
authentication is malformed or from another principal. It MUST still refuse the answer,
and the report MUST contain no part of the response body and no header value.

#### Scenario: The client and service route tables differ

- **WHEN** the client sends a request the service's table does not route and receives an
  unsigned 405
- **THEN** the client refuses it and reports an unauthenticated 405

### Requirement: An operator-named VM guest satisfies provisioning's naming rules

VM's operator route that creates a VM by name MUST refuse, with 422 and before anything is
prepared, a guest name that is not a valid hostname label or whose login, stripped to
letters and digits, is not at most 32 characters starting with a letter.

#### Scenario: An operator names a guest whose login is too long

- **WHEN** an operator creates a VM named so that its login exceeds 32 characters
- **THEN** the request is refused with 422 naming the rule, and no job is submitted
