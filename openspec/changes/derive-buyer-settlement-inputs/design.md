## Context

### What exists

`AlkahestBuyerStage.options` (`domains/api/buying-alkahest/src/arkhai_api_buying_alkahest/stage.py`)
adds these options to the API-credit buyer's normal commands through the buying
library's `StageOption` mechanism:

| Command | Options |
|---|---|
| `buy` | `--token-contract`, `--token-decimals`, `--chain`, `--evm-address`, `--evm-private-key` |
| `negotiate` | `--evm-address`, `--evm-private-key`, `--token-contract`, `--token-decimals`, `--chain` |
| `settle` | `--escrow-uid`/`-u`, `--evm-address`, `--evm-private-key`, `--chain` |

`buyer-orchestration` "Buyer mechanism utilities are namespaced" forbids
chain-, token-, and provider-specific override flags on normal commands, and a
private key on the command line reaches shell history and process listings.

Each value has a source the stage already reads when the option is absent:

| Value | Source today without the flag |
|---|---|
| address, signing key | `core_buyer.buyer_config.resolve_buyer_wallet` — `[wallet]` in the buyer's configuration, address derived from the key |
| chain (negotiate) | the configured chains the listing's accepted escrows name; one is taken, several prompt, `--yes` refuses |
| chain (buy) | chosen once before discovery among *all* configured chains, the same way |
| chain (settle) | the accepted proposal's or escrow's `chain_name`, then the run log's `escrow_created` |
| token | the selected accepted escrow |
| decimals | the token's `decimals()` on the chain (negotiate); `buy` instead requires `--token-contract` when prices are explicit and resolves before discovery |
| escrow identity | the run log's `escrow_created` (`deal.escrow_uid`) |

So removing the options is mostly deletion, except in `buy`, which settles the
chain and the price scale before it has seen a listing.

A documented compatibility promise for these flags would make this the owner's
decision. None exists: `compose-api-family-kit`'s compatibility decision covers
wire shapes, digests, data, configuration, and the service and package
identities, not the buyer's flags; the API-credits baselines record no buyer
command line; the buyer CLI is not published as a stable surface. The flags
appear in one end-to-end scenario and in the vLLM seller cookbook, which this
change migrates.

The owner delegated each decision below to the implementer; each records its
rationale and the alternatives rejected.

## Goals / Non-Goals

Goals: the stage contributes no option to a normal command; every value comes
from the selected option, the buyer's configuration, or the accepted run; a
multi-chain buyer gets a deterministic outcome under `--yes`.

Non-goals: the `market settlement alkahest` utilities, where raw mechanism
commands belong; the VM and bare-metal buyers; delivered credentials
(`keep-buyer-credentials-private`).

## Decisions

### D1. The stage contributes no options; the mechanism stays

`AlkahestBuyerStage.options` is empty. `StageOption` and the composition's
option plumbing remain, as the place a mechanism adds an option the
specification allows.

Rejected: deleting `StageOption` — no rule forbids a mechanism option as such,
and the payments stage or a later mechanism may need a legitimate one.

### D2. The wallet comes only from configuration

Address and signing key come from `resolve_buyer_wallet()` with no overrides:
the buyer's `[wallet]` configuration, with the address derived from the key when
only the key is set. A missing value names its configuration key
(`wallet.address`, `wallet.private_key`).

Rejected: a key file flag or an environment variable read by the stage — the
configuration path already resolves the key, and a second source would need its
own precedence rules.

### D3. The chain comes from the listing and the configured chains

The chain is chosen per listing from the configured chains its accepted escrows
name, in the buyer's configuration order: one candidate is taken; several prompt
interactively; under `--yes`, several refuse, naming the listing and the
candidates. `buy` now selects per listing in its proposal step rather than once
before discovery, and builds the escrow adapters from the accepted proposal's
chain when it settles. `settle` reads the accepted proposal's chain, then the
run log's.

The brief preferred an explicit configuration default where one exists. None
does: `AlkahestSettlementConfig` forbids extra keys and has no chain field, and
the buyer's `default_chain` resource is set only when exactly one chain is
configured, which the one-candidate rule already covers. Adding a configuration
key is new configuration surface this change does not need; it is deferred
until a multi-chain buyer asks for unattended selection.

Rejected: the first configured chain under `--yes` — configuration order is not
a stated preference, and a silent choice can settle on an unintended chain.
Rejected: skipping an ambiguous listing under `--yes` — the buyer would not
learn why a listing it can settle with was passed over.

### D4. Token and decimals come from the selected option

The token is the selected accepted escrow's. Decimals are read on chain through
`resolve_token`, as `negotiate` does today. Explicit display prices in `buy` are
scaled after selection, from the tokens of the selected proposals:
`BuySession.scale_explicit_prices` gains the selected matches. When the selected
Alkahest proposals use tokens of different decimals, one display price has no
single base-unit value, so `buy` refuses, naming them. A token whose decimals
cannot be read refuses with the token and chain.

Rejected: keeping `--token-contract` as a listing filter — it is a token flag,
which the requirement forbids; the buyer's settlement policy is where a token
preference belongs.

### D5. Escrow identity comes from the run log

`settle` creates the escrow unless the run log records `escrow_created`, as it
did without `--escrow-uid`. An escrow created outside the run is out of scope for
a normal command; `market settlement alkahest escrow` inspects one.

### D6. The flags are removed without a deprecation window

`--chain` and the other non-secret flags go at once, as does
`--evm-private-key`. The buyer CLI is not a published stability surface, and
the specification forbids the flags. Typer refuses an unknown option, so a
script still passing one fails loudly rather than being misread.

Rejected: a warning-only window for the non-secret flags — keeping them,
even with a warning, leaves the normal commands out of compliance for the
window's length, and no external user relies on the flags.

### D7. Migrations

`test_credits_deal_buyer_cli.py` stops passing `--chain anvil`; its buyer
configures only `[chains.anvil]`, so the one-candidate rule picks it. The cookbook's buy command loses `--chain` and states
that the chain comes from the listing and `[chains.<name>]`. The plugin tests
(`test_negotiate_cli.py`, `test_settle_credentials.py`) and the Alkahest
library tests drop the options and inject the wallet and chains instead.

## Versions

| Distribution | Version | Why |
|---|---|---|
| `arkhai-api-buying` | 0.3.0 | `BuySession.scale_explicit_prices` takes the selected matches |
| `arkhai-api-buying-alkahest` | 0.2.0 | options removed; per-listing chain; floor `arkhai-api-buying>=0.3.0` |
| `arkhai-api-buying-arkhai-payments` | 0.1.1 | the new session signature; floor `arkhai-api-buying>=0.3.0` |
| `arkhai-apicredits-buyer` | 0.8.0 | floors on the above; tests |

## Risks / Trade-offs

- A buyer with several configured chains whose listings accept more than one
  of them cannot run `buy --yes` unattended until a default-chain setting
  exists. It can run interactively, or keep only the chains it settles on.
- `buy` may prompt once per listing rather than once per run when several
  listings accept several configured chains.

## Deferred

- A buyer configuration setting naming a default settlement chain (D3).

## Open Questions

None.
