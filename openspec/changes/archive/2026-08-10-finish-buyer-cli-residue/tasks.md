## 1. Define preference compatibility

- [x] 1.1 Inventory buyer policy implementations and current escrow-selection precedence, including interactive and noninteractive paths.
- [x] 1.2 Select the typed optional preference signature and backward-compatible default in `design.md`.
- [x] 1.3 Add protocol/unit tests for zero, one, and several candidates plus invalid, duplicate, exceptional, and nondeterministic policy output.

## 2. Integrate orchestration

- [x] 2.1 Invoke preference only after compatibility, chain, token, and other authoritative filtering.
- [x] 2.2 Validate policy output against the input candidate set and preserve explicit interactive user choice.
- [x] 2.3 Define and test noninteractive precedence among valid policy preference, positive balance, and deterministic fallback.
- [x] 2.4 Update concrete policies/examples only where they intentionally express preference.

## 3. Verify and promote

- [x] 3.1 Run kit policy, core buyer, VM/API-credit buyer, CLI, and current run-log compatibility suites.
- [x] 3.2 Promote behavior to `openspec/specs/buyer-orchestration/spec.md` and rationale to `architecture.md` without migration-history comments.
- [x] 3.3 Run typing/packaging and strict OpenSpec checks and archive before ratcheting the affected public interfaces.
