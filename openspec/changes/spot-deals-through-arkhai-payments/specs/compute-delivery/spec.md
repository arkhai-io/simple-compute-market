## ADDED Requirements

### Requirement: Both compute storefronts mount the administrator interrupt route

The VM and bare-metal storefronts MUST each serve `POST /api/v1/admin/deals/{negotiation_id}/interrupt` for a committed `arkhai.payments.v1` deal, authenticated as the storefront's administrator under the canonical storefront client's `admin_interrupt_deal` operation, and MUST carry out the interruption through `kit/deal-servicing`'s seller-half classification, ending delivery through end service. A refusal of that classification MUST answer 409 with nothing recorded. A hosted interruption takes effect at receipt, so the route MUST refuse a caller-supplied interruption time. The canonical client's sync and async `admin_interrupt_deal` MUST expose the interruption kind and operation key.

#### Scenario: A bare-metal administrator preempts a spot deal

- **GIVEN** a committed bare-metal rate deal whose accepted option grants a payee entitlement
- **WHEN** the administrator interrupts it with kind preemption through the canonical storefront client
- **THEN** the route answers `notice_stop` with the authority's outcome, and the read shows the pending stop
- **AND** no end or filing is recorded

#### Scenario: A bare-metal administrator reports a failure

- **WHEN** the administrator interrupts a committed bare-metal deal with kind failure and a reason
- **THEN** the route answers `delivery_end_filing`, the end is recorded with the administrator's reason, and a `delivery_end` filing is journaled with cause payee

#### Scenario: An interruption the classification refuses

- **WHEN** a rate interruption omits its kind, or an unentitled deal is preempted
- **THEN** either storefront's route answers 409 and records nothing
