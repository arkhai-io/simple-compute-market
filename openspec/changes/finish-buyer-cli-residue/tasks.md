## 1. Define preference compatibility

- [ ] 1.1 Inventory buyer policy implementations and current escrow-selection precedence, including interactive and noninteractive paths.
- [ ] 1.2 Select the typed optional preference signature and backward-compatible default in `design.md`.
- [ ] 1.3 Add protocol/unit tests for zero, one, and several candidates plus invalid, duplicate, exceptional, and nondeterministic policy output.

## 2. Integrate orchestration

- [ ] 2.1 Invoke preference only after compatibility, chain, token, and other authoritative filtering.
- [ ] 2.2 Validate policy output against the input candidate set and preserve explicit interactive user choice.
- [ ] 2.3 Define and test noninteractive precedence among valid policy preference, positive balance, and deterministic fallback.
- [ ] 2.4 Update concrete policies/examples only where they intentionally express preference.

## 3. Verify and promote

- [ ] 3.1 Run kit policy, core buyer, VM/API-credit buyer, CLI, and current run-log compatibility suites.
- [ ] 3.2 Promote behavior to `openspec/specs/buyer-orchestration/spec.md` and rationale to `architecture.md` without migration-history comments.
- [ ] 3.3 Run typing/packaging and strict OpenSpec checks and archive before ratcheting the affected public interfaces.
