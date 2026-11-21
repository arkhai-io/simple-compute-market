## Decisions

The neutral `OnceAccountingReader` capability returns the ordinary authority view plus an optional fixed projection from the same verified object. Legacy adapters retain one ordinary read. A malformed opt-in result is unknown and never retried. The concrete payments adapter verifies authority normally; generic servicing does not import payment wire models or receive complete signed snapshots. The optional accounting helper is loaded locally to bind its bounded source identity before interpreting amounts; this lazy import is intentional.

Only TEST once-only snapshots within the bounded parts, sequence and elapsed-time scope qualify. Held, stale, below-floor, rate, LIVE or unreadable observations do not become terminal accounting. Every result retains `returnAdmitted=false`. These limits bound optional capture, not normal lifecycle service.

An existing EvidenceItem stores a small seller assertion, containing hashes and scope metadata rather than the complete payment response. EvidenceSession encodes body bytes through the existing Base64Bytes contract. Repeated finance at one sequence retains the first item despite observation or signature refresh. Changed financial facts retain one stable conflict marker and suppress qualified accounting. Neither item is payment authority.

Capture runs in a nested savepoint inside the normal observation/final-stop/cursor transaction. Capture-only failure removes its partial insert and preserves normal servicing. Private qualification also requires the durable receipt to match the current semantic facts, using the same predicate as deduplication; absence of a conflict marker alone is insufficient if its insert failed. An outer rollback removes evidence and all corresponding normal changes. The next ordinary poll continues with the durable prior cursor. Existing retention owns evidence lifetime; no new table or session-issued DDL is introduced.

## Validation

Extend existing payments adapter tests with the signed deterministic authority fixture, and existing servicing fixtures with the neutral opt-in capability. Exercise immutable refresh/conflict, an actual SQLite post-insert savepoint failure and outer rollback, continuation, and legacy/malformed/unreadable fallback. Source-only cached-interpreter results are distinguished from standard wheel-installed package and lock proof.
