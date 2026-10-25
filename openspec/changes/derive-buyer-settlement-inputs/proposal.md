## Why

The API-credits buyer's normal `buy`, `negotiate`, and `settle` commands accept
`--evm-private-key`, `--evm-address`, `--chain`, `--token-contract`,
`--token-decimals`, and `--escrow-uid`, which the buyer-side Alkahest stage
contributes to them. `buyer-orchestration`'s "Buyer mechanism utilities are
namespaced" requires normal commands to derive mechanism inputs from the
selected option, the persistent buyer profile, and the accepted run, and to
accept no chain-, token-, or provider-specific override flag. A private key on
the command line also reaches shell history and process inspection.

The flags are a documented interface: the API-credit end-to-end scenario passes
`--chain`, and the vLLM seller cookbook shows it, so removing them is a
compatibility migration rather than a cleanup.

## What Changes

- Derive each value the flags supply instead: the chain from the selected
  option and typed configuration, the token and its decimals from the selected
  option and the chain, the buyer's address from its wallet, and the escrow
  identity from the accepted run.
- Resolve the EVM signing key through a wallet provider that never takes a
  secret on the command line.
- Define non-interactive selection when a listing accepts several configured
  chains.
- Decide whether non-secret overrides, `--chain` first, are removed outright or
  pass through a deprecation window, and remove `--evm-private-key` without
  one.
- Migrate `test_credits_deal_buyer_cli.py` and the vLLM seller cookbook.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `buyer-orchestration`: the API-credits buyer's normal commands derive
  Alkahest inputs from the selected option, the buyer profile, and the accepted
  run, and accept no override flags.
- `api-family`: the buyer-side Alkahest stage contributes no override options to
  normal commands.

## Non-Goals

- No change to `market settlement alkahest` utilities, where raw mechanism
  commands belong.
- No change to where delivered credentials are kept; that is
  `keep-buyer-credentials-private`'s.
- No change to the VM or bare-metal buyers' flags.

## Impact

- Code: `domains/api/buying-alkahest` (the stage's options, buy session, and
  resume), the wallet provider's home, and the API-credits buyer plugin's
  tests.
- Docs and scenarios: the vLLM seller cookbook and
  `test_credits_deal_buyer_cli.py`.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification — `openspec/specs/buyer-orchestration/spec.md`;
  the `api-family` specification.
- [ ] New subsystem specification

### Knowledge to promote

- Where the buyer's Alkahest inputs derive from, and the wallet provider —
  `openspec/specs/buyer-orchestration/spec.md`.

## Dependencies and Related Changes

- Depends on `compose-api-family-kit`, whose buyer-side Alkahest stage it
  changes, and follows `keep-buyer-credentials-private` on the same commands;
  opened by `compose-api-family-kit`'s section 10 review, which records this as
  an owned deferral.
