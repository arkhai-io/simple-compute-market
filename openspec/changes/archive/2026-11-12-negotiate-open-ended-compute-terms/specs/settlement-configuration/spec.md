## ADDED Requirements

### Requirement: Rate servicing is a composition capability

The composition MUST declare, per mechanism, the `settles_through` treatments it has qualified
against that mechanism's payment authority, and whether it services a setup charge (`setup`).
An absent or empty declaration means no rate servicing. All three doors — publication,
acceptance of a cached selection before persistence, and materialization — MUST read that one
declaration and refuse an option naming any undeclared treatment on an entitlement or at the
term end, or bearing a setup charge where `setup` is not declared. An option is admitted only
where the mechanism's helper supports a treatment and the composition declares it.
Materialization and continuation consumers MUST receive the same declaration, not an
option-local copy; accepted-deal continuation MUST NOT read it. Continuation execution remains
the servicing consumer's responsibility. A seller's `[Settlement]` root holds the declaration as
`rate_servicing`, one table per installed mechanism keyed by its configuration key
(`[Settlement.rate_servicing.arkhai_payments]`), holding `treatments`, named as the payment
authority names them (`charged`, `returned`, `prorated`), and `setup`, false when absent. A
buyer's root MUST refuse `rate_servicing`, and a table naming no installed mechanism, an unknown
key or an unknown treatment MUST fail validation.

#### Scenario: A treatment the composition has not qualified

- **WHEN** a composition declares `treatments = ["charged"]` for `arkhai_payments` and a recurring option's payee entitlement settles through `last_boundary`
- **THEN** publication omits the option, and a cached selection of it is refused before acceptance persists

#### Scenario: Setup is not yet declared

- **WHEN** the declaration for a mechanism has `setup = false` and an option carries a setup charge
- **THEN** each of the three doors refuses it

#### Scenario: No declaration

- **WHEN** a composition declares no rate servicing
- **THEN** no recurring option publishes, and accepted deals continue to be serviced

#### Scenario: A buyer's root declares rate servicing

- **WHEN** a buyer's `[Settlement]` root contains a `rate_servicing` table
- **THEN** configuration fails validation naming the unknown key

### Requirement: Terms expose servicing declaration without enabling rate execution

Terms publication and acceptance MUST expose one composition-owned declaration contract
for rate materialization and continuation to consume. Terms alone MUST NOT enable recurring
execution; its qualification MUST remain distinct from consumer materialization/startup evidence.

#### Scenario: Terms are qualified before rate consumers

- **WHEN** declaration, publication and acceptance fixtures pass but rate continuation is not composed
- **THEN** terms can qualify those fixtures without claiming materialization/startup readiness or enabling deployed rate offers
