## MODIFIED Requirements

### Requirement: The api family shares one vocabulary and one kit

The `api` family's vocabulary — the purchase shape and key disposition, the
issuance request and result, the fulfillment identity and request digest, the
signed secret-free issuance evidence and portable fulfillment reference, and the
issuance label type with its label-parameterized operations — MUST live once,
in the family vocabulary package under `domains/api`, and every domain selling
prepaid bearer access MUST bind it rather than define or copy its own. The vocabulary MUST
depend only on foundation kits, never on core, a domain, a role, or a
family-kit distribution, and MUST NOT name a sibling domain's label value. Every
distribution under `domains/api` MUST import no API-selling domain and no
role, except through an edge recorded as an exception row in
`docs/development/ARCHITECTURE.toml`;
[Current limits](architecture.md#current-limits) lists those edges.

#### Scenario: Two kind literals bind the purchase shape

- **WHEN** the API-credits binding and a binding under a second kind literal
  each construct provision terms for three credits onto a new key
- **THEN** both validate the payload through the vocabulary's one definition,
  differing only in the kind literal each binds

#### Scenario: A family package imports a domain

- **WHEN** the architecture check reads an import of `arkhai_apicredits`, or of
  any later sibling domain's package, from any project under `domains/api`
- **THEN** the check fails naming the import, and no exception row excuses it

#### Scenario: A label value is sought in the vocabulary

- **WHEN** the vocabulary package is searched for `api-credits` or `inference`
- **THEN** neither appears; each is passed in by its domain

### Requirement: A key is scoped to its first grant

The authority MUST bind a key to the service, resource, and accepted terms
digest of the grant that created it and MUST refuse an existing-key issuance
whose service, resource, or terms differ, naming the refusal, so a key's one
balance is only ever spent on what every one of its grants bought, at the
charge each was bought at. `verify`, `consume`, and each batched consume item
MAY carry the caller's expected service and resource; when present, the
authority MUST refuse a key whose first grant's scope differs, uncharged, with
a named status, and when absent it MUST behave as before the fields existed. A
gate with a configured scope MUST send it on every one of these calls, and
MUST NOT admit a charge on a verification the authority has since refused. The
authority MUST refuse, uncharged and naming the refusal `charge_mismatch`, a
`consume` or a batched consume item whose amount differs from the request
charge pinned on the key's first grant; a key whose first grant pins none MUST
be charged the amount sent. It MUST apply that refusal after the refusals of
the key itself — unknown, revoked, or out of scope — and before recognising
an idempotent replay or weighing the balance, and the refusal MUST carry the
key's balance.

#### Scenario: A key is topped up from another listing

- **WHEN** a buyer who holds a key issued for one listing purchases onto that
  key from a listing with a different service or resource
- **THEN** issuance is refused naming the key's scope, no grant is recorded,
  and the key's balance is unchanged

#### Scenario: A key is presented at another offering's gateway

- **WHEN** a funded key issued for one service and resource is presented to a
  gateway whose offering names another, under the same authority
- **THEN** the authority refuses the verification by scope, the gateway
  answers `403`, the model server receives nothing, and the key's balance is
  unchanged

#### Scenario: A pinned key is charged another amount

- **WHEN** a trusted caller consumes two credits from a key whose first grant
  pins a request charge of one
- **THEN** the authority answers `409 charge_mismatch` carrying the key's
  balance, which is unchanged

#### Scenario: A revoked pinned key is charged another amount

- **WHEN** a trusted caller consumes two credits from a revoked key whose
  first grant pins a request charge of one
- **THEN** the authority refuses it as revoked, not as a mismatch

#### Scenario: A request is repeated at another amount

- **WHEN** a trusted caller repeats an applied consume under the same
  idempotency key at an amount other than the key's pinned charge
- **THEN** the authority refuses it as `charge_mismatch`, not as a duplicate

#### Scenario: A batch carries one mismatched item

- **WHEN** a batched consume carries an item whose amount differs from its
  key's pinned charge among items that match theirs
- **THEN** that item's outcome is the refusal `charge_mismatch` in its place,
  and every other item is applied

#### Scenario: An unpinned key is charged the amount sent

- **WHEN** a trusted caller consumes any amount within its balance from a key
  whose first grant pins no charge
- **THEN** the amount is debited, as before the pinned charge existed
