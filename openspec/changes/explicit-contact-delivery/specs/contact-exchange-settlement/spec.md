## ADDED Requirements

### Requirement: Explicit two-sided delivery is opt-in and owner-routed

A policy-bearing accepted introduction MUST require a private review, an exact
review token, explicit finalization consent, and the buyer's own delivery route.
It MUST bind the seller snapshot and origin-owned route, refuse ordinary start
bypass, and preserve the existing behavior of policy-absent introductions.

#### Scenario: Native policy-only finalization

- WHEN an authorized buyer finalizes the exact reviewed native contact option
- THEN the seller captures one immutable introduction and two unique role-owned intents
- AND the option stays rateless and adds no payment or provisioning
- AND retries recover the same finalization without duplicating intents.

### Requirement: Recovery preserves uncertainty and reader ownership

Recipient transmission MUST follow successful non-financial completion. Unknown
provider acceptance MUST remain non-replayable. Payload deletion MUST fence
pending transmission. A disabled migration-aware reader MUST continue servicing
accepted state; a reader unaware of the new migration MUST refuse the upgraded
ledger, and rollback MUST NOT discard committed or unknown fences and receipts.

#### Scenario: Unknown outcome survives admission disable

- WHEN transmission becomes unknown and new contact admission is disabled
- THEN the compatible reader reports the same unknown recipient outcome
- AND no new worker tick automatically resends it.
