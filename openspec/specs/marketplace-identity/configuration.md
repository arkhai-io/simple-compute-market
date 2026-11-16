---
tags: [repository, configuration]
---

# Marketplace identity configuration

How services and buyers configure their marketplace identities, as this repository's
instance of [`configuration.md`](../../../docs/guidance/engineering/configuration.md).
The services' signing credential, `ARKHAI_IDENTITY_CREDENTIAL`, is the exception to
its secrets rule that
[`AGENTS.md`, "Exceptions to shared guidance"](../../../AGENTS.md#exceptions-to-shared-guidance)
declares.

Services configure canonical public principals and trust pins in ordinary
configuration, with service-owned credentials supplied through their Secret
boundary. Buyers are different because they require durable local lifecycle:
public buyer TOML references `[BuyerProfile].store_path`, while the versioned
XDG data store holds stable profile UUIDs, canonical principal history,
redacted credential references, selection, lifecycle, and authority-scoped
opaque payer bindings.

Buyer providers are exact: OS keyring, an absolute owner-only regular secret
file, or one explicitly named environment variable. There is no fallback.
Profile metadata, run state, public config, and provider secrets use separate
mounts. Compose/Helm set `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and
`XDG_STATE_HOME`, persist the profile directory, and mount the selected
credential only into the buyer process. Invalid owner/mode, symlink, missing
secret, unsupported store version, or principal mismatch fails before buyer
work.

Ed25519 is the wallet-free default. Optional EIP-191 wallet/RPC/chain inputs are
separate mechanism resources and never determine profile selection. ConfigMaps,
arguments, image layers, run logs, evidence, output, and examples contain no
resolved signing value.
