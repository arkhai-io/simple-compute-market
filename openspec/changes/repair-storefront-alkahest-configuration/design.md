# Design — repair-storefront-alkahest-configuration

## How the three gaps hide each other

Each gap produces a different symptom, and the symptoms appear at different
layers, which is why the fault read as one defect for several rounds:

| Gap | Symptom | Where it surfaces |
|---|---|---|
| Credential never arrives | `checks.alkahest='unconfigured'` | a preflight assertion |
| Settlement path invalid | `blockers=alkahest.address_config_invalid` | mechanism readiness |
| Per-chain path unset | none yet | latent behind the first gap |

The listing failures name none of these. They return `400 no enabled settlement
mechanism is ready`, which is the *consequence*: composition suppresses an
unready mechanism and raises only when nothing survives. The link is in the
storefront's own log, which emitted `[SETTLEMENT] option suppressed
mechanism=alkahest.v1 blockers=alkahest.address_config_invalid` once per failed
listing. Reading the refusal alone suggests a missing mechanism; reading the
suppression shows a configured one that could not load a file.

## Two path settings, read by different code

`Settlement.alkahest.address_config_path` feeds the readiness preflight.
`Chains.<name>.alkahest_address_config_path` feeds client construction. They
are independent reads of the same fact, and nothing reconciles them, so both
are set. That duplication is not introduced here — it is the existing shape, and
it is part of what the deferred compose/Helm review should address.

## Why the credential goes in the compose identity file

The wallet env files are legacy: alongside `AGENT_PRIV_KEY` they carry
`AGENT_MODE`, `GEMINI_API_KEY`, `INDEXER_URL`, and paths under
`core/agent/app/data` from a layout that no longer exists — including a third
stale `ALKAHEST_ADDRESS_CONFIG_PATH`. Adding a correctly-named variable to those
files would extend an artifact that looks due for deletion, so the credential
goes where the other development identities already live.

The alternative was teaching the storefront's accessor to read `AGENT_PRIV_KEY`
as well. Rejected: it would spread one credential's name across two loaders
with different resolution rules, which is the condition that produced this bug.

`@str` is required because Dynaconf parses each environment value as TOML and a
bare `0x...` is a valid hexadecimal integer literal — verified directly, the
key arrives as a 48-digit decimal without it. This is the second place the
marker is needed, which is a signal the loader should stop TOML-parsing values
bound for string fields; recorded as deferred work.

## Verification available without the stack

The address file loads and the clients build, tested against the real
packages: `build_alkahest_clients` with no credential reproduces
`[ALKAHEST] Mechanism unavailable; required EVM settings are missing:
wallet.private_key` and returns no clients, and with the credential and path
supplied it proceeds through address-config resolution to RPC connection,
failing only on DNS for `ws://anvil:8545`, which resolves inside the compose
network. `alkahest_preflight` carries `alkahest.address_config_invalid` for the
current path and does not for the mounted one.

Both wallet credentials derive to the `Wallet.address` their storefront already
declares, which is the check that would have caught a swapped pair.

## Deferred

Compose configuration is assembled by hand across a root file, domain compose
files, an identity overlay, and legacy env files, with duplicated paths and
per-value TOML-parsing workarounds. The Helm charts express the same
deployment more coherently. Converging compose onto a single source shared with
the tests is accepted as follow-up work and deliberately out of scope here: the
immediate goal is a settling stack, and restructuring configuration while
settlement is still unproven would make both harder to judge.
