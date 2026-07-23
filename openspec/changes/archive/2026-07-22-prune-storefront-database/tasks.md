## 1. Audit and disposition

- [x] 1.1 Verify legacy policy and decision tables are already absent from current storefront persistence.
- [x] 1.2 Verify `negotiation_messages`, `resource_transition_events`, and `stage_events` retain production continuation, idempotency, or observability roles.
- [x] 1.3 Reject the broad production-read-only persistence criterion and record the evidence in `design.md`.
- [x] 1.4 Archive without synchronizing the pruning delta.
