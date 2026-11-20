---
tags: [repository, configuration, deployment]
---

# Settlement configuration

How marketplace roles configure their settlement mechanisms — the `[Settlement]`
root, Arkhai payments, Alkahest and its release models, and dispute authority
preferences — what a storefront refuses or reports of them, and how a retired
configuration migrates. The procedure that cuts a deployment over to a migrated
configuration is the operator handbook's
["Migrating settlement and publication configuration"](../../../docs/operator-handbook.md#migrating-settlement-and-publication-configuration).
The rules these apply are
[`configuration.md`](../../../docs/guidance/engineering/configuration.md) and
[`deployment.md`](../../../docs/guidance/engineering/deployment.md); the
[specification](spec.md) states the contract, and its
[companion](architecture.md) why.

## A storefront refuses Alkahest configuration its domain cannot deliver

A service refuses to start on its own incoherent state, never on a dependency
([`deployment.md`](../../../docs/guidance/engineering/deployment.md#a-service-refuses-to-start-on-its-own-incoherent-state-never-on-a-dependency)).
Every storefront refuses an Alkahest section, enabled or not,
listing a release model its domain cannot deliver (see
[Alkahest release models](#alkahest-release-models)),
and the bare-metal storefront
refuses Alkahest inputs — `[Wallet].address`, `[Chains]`, `[Wallet].private_key` —
stated with no Alkahest section.

## An Alkahest section that cannot settle makes Alkahest unready

A section that
parses but under which no deal could settle is reported through Alkahest readiness
blockers, its options are not published, and the storefront's other mechanisms run:
`oracle_gated` with no `trusted_oracle_addresses`, `interruptible` with no
`interruptible_oracle_addresses`, a release oracle equal to the seller wallet, a
seller wallet with no address, no private key where the storefront signs, no
`[Chains]` entry, an address configuration that cannot be loaded, or a release
model the storefront's domain does not deliver (bare metal delivers `recipient` and
`oracle_gated`). A section that does not parse stops startup, as all configuration
does. A disabled section reports, after `disabled`, the configuration blockers that
would keep it from settling. Readiness governs publication only: an address, chains,
or key removed while Alkahest deals are open leaves the seller unable to service or
collect them, the buyer's escrow staying reclaimable at expiry, and the blocker
naming what is missing is the operator's signal. Every readiness blocker states its
`kind`: `configuration`, which the storefront's own settings cause, or
`reachability`, when the mechanism's chain or service could not be reached;
publication reads the kind to decide whether an open listing left with no option is
closed or held (see
[`storefront-publication`'s "Storefront listing shapes and pool overrides"](../storefront-publication/configuration.md#storefront-listing-shapes-and-pool-overrides)).

## Alkahest probes its chains

Readiness makes no chain call. Each storefront
composing Alkahest runs an `alkahest-chain-probe` lifecycle loop that, once per
`[Settlement.alkahest].probe_interval_seconds` (30 by default), reads each
configured chain's `eth_chainId` and the code at each contract its address
configuration requires, each call bounded by `rpc_timeout_seconds` (5 by default);
both are seller settings and positive seconds. An RPC that errors or times out reads
as the reachability blocker `alkahest.chain_unreachable`; a different chain ID is
`alkahest.chain_id_mismatch`, and a required contract with no code
`alkahest.contract_missing`, both configuration blockers. A chain not yet probed
since start reads as unreachable, so a freshly started storefront holds its open
Alkahest listings rather than closing them; a result does not expire, so while the
loop is held readiness reads the last one however old. Startup constructs no chain
client: the probe constructs each at its first step, waiting no longer than the RPC
timeout, and again at each probe until one succeeds, so a storefront recovers
without a restart, and a chain whose client cannot be constructed reads
unreachable whatever its RPC answers. The probe calls a `ws://` or `wss://`
`rpc_url` over `http://` or `https://` at the same host, port, and path, so a
provider serving the two on different endpoints reads as unreachable. Status
readiness judges every configured chain, so `ready` there means every one is
reachable and deployed; publication judges the chains a candidate's escrows name,
and one unreachable chain among them withholds the candidate's Alkahest options on
all of them.

## Settlement consumer configuration and cutover

Marketplace roles resolve one strict `[Settlement]` root. `schema_version`
selects the configuration contract, `priority` orders mechanism IDs, and peer
`[Settlement.alkahest]`, `[Settlement.arkhai_payments]`, and `[Settlement.contact]` tables contain only
mechanism-owned consumer settings. Arkhai payments resolves trusted service origin, Ed25519 receipt identity, fee policy, an optional `ca_bundle_path`, and the API key through the shared kit's `settlement_config.py`. The key is stated in exactly one form: a storefront states it as `api_key`, a secret setting in its Secret overlay (`storefront.secrets.toml`, or the API-credit storefront's secret layer), never in public configuration; a buyer states `api_key_env`, naming the variable its own provider holds the key in. One resolution — `api_key`, otherwise the variable `api_key_env` names — serves the client builder, readiness and the payments check alike. `ca_bundle_path` names a PEM bundle the payments client alone verifies the service under, leaving the process's trust store as it is; a bundle that cannot be loaded fails when the client is built. The owner-scoped WorkOS credential reaches only its consuming process; HTTPS is required outside loopback. Buyer `payer_account` is separate domain input (`[vms].payer_account` or `[apicredits].payer_account`), carried in selection params and the accepted Agreement, not inferred from marketplace identity. API-credit sellers supply `payee_account` and `asset` in each payment publication clause; the accepted option determines the seller client's owner. Local development may use `development_auth = true` with a loopback service origin instead of a key; it is mutually exclusive with `api_key` and `api_key_env`, which are mutually exclusive with each other. A Compose or cluster service name is not loopback, so a stack's payments double is reached with a bearer key and a configured CA, as a deployment's service is. Buyer marketplace identity comes only from
the selected durable profile referenced by `[BuyerProfile]`; storefront and
service-role principals retain their own public identity configuration.
EVM credentials and networks remain in `[Wallet]` and `[Chains]`.
Generated TOML, ConfigMaps, status output, and run logs contain only public
configuration projections.

**The storefront payments check.** Payments readiness checks configuration only
and never contacts the service, so a storefront proves its payments access with an
authenticated read from its own process: `market-storefront check-payments
--account <id>`, `bare-metal-storefront check-payments --account <id>`, or
`apicredits-storefront check-payments --account <id>`. Each loads the storefront's
configuration exactly as `serve` does, takes its `[Settlement.arkhai_payments]`
section, builds the client the storefront would build, and reads the account's
balance (`GET /balances/{account}`). It starts no server, opens no database, and
contacts nothing but the payments service. The account is explicit because the
storefront's payments configuration does not name the seller's payee account, and
the service answers only for the key's own account. The command prints one JSON
line with no credential in it, and exits 0 on `ok`, 1 on a failed step, and 2 on a
malformed `--account`:

```console
$ bare-metal-storefront check-payments --account 00000000-0000-4000-8000-0000000000b2
{"check": "payments", "outcome": "ok", "service_url": "https://payments-double:8443", "account": "00000000-0000-4000-8000-0000000000b2", "assets": [], "held": 0}
```

A failure names its `step` and a fixed-text `detail`: `configuration` (no section,
an invalid or disabled one, no `service_url`, neither `api_key` nor `api_key_env`,
a configuration the storefront cannot read, or a `ca_bundle_path` that cannot be
loaded), `credential` (the variable `api_key_env` names is unset, empty, or not a
single-line key), `transport` (the service could not be reached over a trusted
connection, a certificate verification failure among them, or answered outside its
published contract), or `refused`, with the service's error `code` beside it. The
end-to-end lanes run it in each payment storefront's container after the stack is
up, and a storefront chart runs it as a Helm test pod
([`DEPLOYMENT_AND_CONFIG.md`, "Storefront agents: pass-through configuration"](../../../docs/development/DEPLOYMENT_AND_CONFIG.md#storefront-agents-pass-through-configuration));
the operator handbook's
["Payments access"](../../../docs/operator-handbook.md#payments-access) gives the
deployment's procedure.

`livemode` in a buyer's or storefront's Arkhai payments settings — `[Settlement.arkhai_payments]`,
or `[bare_metal.arkhai_payments]` in the bare-metal buyer's configuration file — is
the service mode whose receipts that process accepts. Receipts sign `livemode`, true only from a live payments service, and a
receipt verifies only when its signed mode equals the process's setting. The default,
`false`, accepts only test-mode receipts, so a process against a live service refuses
every receipt until it sets `livemode = true`, buyer and storefront alike. Mode, service origin, and receipt
identity change together, and changing them is a cutover: each receipt check,
including the revalidation of a stored receipt at restart, compares with the
current setting, so a payment deal accepted under the old mode never reaches
delivery or issuance afterwards. Open payment deals approved under the old mode or
identity are therefore drained, or refunded, before the change. Refunds come first:
once the old identity leaves configuration, each deal it approved stops verifying
everywhere — snapshot reads, admission, stored-receipt revalidation and the
storefront's refund, which then answers that no verified payment exists. Nothing
re-anchors a running deal to a new key. Buyers update their receipt identity before
approving after the change: a buyer checks the receipt only after approval has moved
its funds, so a buyer still naming the old identity has its funds approved and held
while its purchase fails. The operator handbook's
["Changing the payments service mode"](../../../docs/operator-handbook.md#changing-the-payments-service-mode)
gives the cutover's procedure.

For the moment of a signing-key switch, `receipt_identities` in
`[Settlement.arkhai_payments]` may list the current and the retiring identity pins, so
a fresh approval does not fail while clocks and configurations differ; it keeps no
deal alive past the removal of the retiring entry, which ends the cutover. Each entry has `identity`,
`valid_from` (inclusive Unix seconds, default zero), optional `valid_until`
(exclusive), and `retiring` (default false). A nonempty list must include the
current `service_identity` as a non-retiring entry. With no list, that identity
alone remains trusted. Receipt signatures are checked at `approvedAt`; snapshot
signatures at `observedAt`. A valid current-key snapshot may attest an embedded
receipt from a configured retiring identity valid at its approval, without
rewriting the receipt or its proof. Callers pass their durable minimum event
sequence to the shared snapshot verifier; wrong mode, deal or regressing state
is refused before authority state is consumed.

A storefront's `snapshot_freshness_seconds` in `[Settlement.arkhai_payments]`
(default 5, at most 300) bounds how far a verified snapshot's `observedAt` may lag the
storefront's clock and still decide a rate delivery phase; a snapshot observed ahead
of that clock is fresh. The payment authority's clock and the storefront's are
independent claims, so the window is a liveness allowance for skew and latency, not an
ordering: every stop, end and funding bound is still checked at the storefront's own
clock, and a staler snapshot answers pending until it is refreshed.

Agreement attachment is set on each side. A buyer's `attach_agreement` (default `false`)
attaches the exact Agreement when it approves a payment; setting it in a seller
configuration is a publication blocker. A seller that wants the Agreement on file sets
`deposit_agreement` on its payment option, and attaches the Agreement itself after
verifying the receipt and before delivering, whenever the buyer did not. The Agreement
discloses both principals, the listing, amount, timing, and provision terms, so enable
either only where that disclosure to the payments service is intended.

A selling composition declares which recurring treatments it services in its
`[Settlement]` root, one table per installed mechanism, keyed by the mechanism's
configuration key:

```toml
[Settlement.rate_servicing.arkhai_payments]
treatments = ["charged"]   # as the payment authority names them: charged, returned, prorated
setup = false              # whether a setup charge beside the rate is serviced
```

Absent or empty means no rate servicing, so no recurring option publishes; that is
every shipped configuration. Only the compute end-to-end lanes' storefront
configurations declare `charged` and `returned`, as a lane fixture. Publication omits
an option naming an undeclared treatment or an undeclared setup charge, a cached
selection of one is refused before acceptance, and materialization refuses it with
`settlement_option_withdrawn_refetch`, so its mandate is never derived. Withdrawing a
treatment therefore stops new offers and the materialization of a deal accepted under
it; a deal already materialized keeps being serviced. The declaration governs offers
and acceptances only: a rate deal it admitted is delivered and serviced by the
storefront's payments seller stage, as a once-only deal is, and a storefront whose
payments section lacks its servicing fields while it holds open payment deals starts
and reports them repair required
([storefront publication, "The servicing declaration and its three doors"](../storefront-publication/architecture.md#the-servicing-declaration-and-its-three-doors)).
Declaring any treatment also presupposes that the payment authority executes the
dispute authority's `chosen` stop, which hosted qualification has not yet shown. A buyer's root refuses `rate_servicing`, and a
table naming no installed mechanism, an unknown key or an unknown treatment fails
validation. The storefront charts' values schemas carry the same table definition
the loader parses.

Stripe consumer settings are rejected with removal diagnostics; they are not migrated to Arkhai accounts, credentials, or transactions. Role CLIs reject legacy settlement keys and expose the same explicit migration contract. The storefront additionally rejects legacy publication pricing that would synthesize options from `min_price`, `token`, or raw `accepted_escrows`. A check is read-only and reports paths and actions with values redacted. A write requires `--backup`, validates the complete candidate before mutation, creates a restrictive same-directory `.bak`, fsyncs, and atomically replaces the source. Conflicting old and new values fail rather than choosing one. Repeating a completed migration is a no-op.

An Alkahest address book — one deployment's contract addresses, overriding the
SDK's built-in addresses for a chain such as Anvil — is named per chain in
`[Settlement.alkahest.address_books]`, a table from chain name to path; a chain not
listed uses the built-in addresses, and a key naming no configured chain makes
Alkahest unready (`alkahest.address_book_chain_unknown`). `[Chains]` holds only
chain resources. Every role — storefront and buyer, seller and payer — resolves a
chain's book through `kit/alkahest` and uses it for client construction,
publication, release conditions, escrow verification, refunds, and claim
servicing alike. The two retired keys, `[Chains.<name>].alkahest_address_config_path`
and `[Settlement.alkahest].address_config_path`, are refused before the settlement
section is resolved, with a diagnostic naming the table. The settlement migration
commands, `market-storefront config migrate --scope settlement` and the buyer's
`market config migrate --scope settlement`, move them into it. Bare-metal sellers use
`bare-metal-storefront config migrate --config /path/storefront.toml --scope settlement`
with the same `--check` or `--write --backup` modes. The API-credit storefront has no
migration command; its operators move the key by hand. A chain's own key moves to that chain's entry, and the
section key to the one configured chain, or else to the chains whose own keys name
the same book. Where it cannot tell which chains the section key served, or a chain
would be given two different books, it refuses and names the keys; an empty key is
removed. The section key named the book claims were serviced against on every
chain, so on any other configured chain a seller's claims move to that chain's own entry, or to the
built-in addresses where it has none; a seller's migration report names each such
chain before anything is written. A release that predates the table refuses it,
since `[Settlement]` is strict.

A seller's `[Wallet].address` is the recipient its release conditions name, and its
`[Wallet].private_key` signs every chain transaction, so the two name one account.
The address is optional: absent, it is derived from the key. An address that names
another account than the key's makes Alkahest unready
(`alkahest.wallet_address_mismatch`) and leaves the storefront running. A buyer's
address names nothing an escrow pays, and is not compared with its key.

### Alkahest release models

`[Settlement.alkahest].release_models` is the ordered, nonempty, duplicate-free list
of release models offered by the seller: `recipient` (the default), `oracle_gated`,
and `interruptible`. Every published escrow shape gets one option per model.
Each option's `settlement.accepted_escrow.demand` pins its own chain, arbiter and
demand data; it has no `lifecycle` terms, since Alkahest has no lifecycle adapter.
Interruptibility is not a listing-resource attribute: choosing the splitter option
chooses that release condition, without changing the other options on the listing.

```toml
[Settlement.alkahest]
enabled = true
release_models = ["recipient", "interruptible"]
# Configure interruptible_oracle_addresses with a trusted third-party oracle.
```

`trusted_oracle_addresses` is valid only when `oracle_gated` is listed, and
`interruptible_oracle_addresses` only when `interruptible` is listed. Those models
need their respective oracle list before Alkahest is ready; the first address is
the release oracle, and it must not be the seller's wallet or signing account.
Wallet, address-book and chain readiness still apply to every offered model.
A domain refuses startup if any listed model is not one it can deliver, whether or not
the section is enabled: bare metal
accepts recipient and oracle-gated release, never interruptible; the API-credit
storefront accepts recipient release only. VM supports all three models.

The retired `oracle_gated` and `interruptible` boolean settings are rejected. The
settlement migration maps `oracle_gated = true` to `["oracle_gated"]`,
`interruptible = true` to `["interruptible"]`, and neither true (including both
absent) to `["recipient"]`, removing the flags. Both true is contradictory and
refused. A conflicting existing `release_models` list is refused without modifying
the file or backup. Dry-run lists redacted key changes; write validates the whole
candidate and preserves the existing atomic replacement and restrictive backup
contract. Repeating it is a no-op. Legacy boolean environment overrides must be
replaced with the corresponding `SETTLEMENT__ALKAHEST__RELEASE_MODELS` list override,
not copied as boolean values. A deployment runs the migration as the operator
handbook's
["Migrating settlement and publication configuration"](../../../docs/operator-handbook.md#migrating-settlement-and-publication-configuration)
sequences it.

### Dispute authority preferences

Dispute preferences are role-owned root configuration, independent of
`[Settlement.arkhai_payments]`. VM and API-credit buyers and storefronts read
these entries from their normal public TOML overlays. The bare-metal buyer reads
them at the root of its file selected by `BARE_METAL_BUYER_CONFIG`, beside
`[bare_metal]`; its storefront reads them through the normal storefront loader.

`use_registry_dispute_authorities` defaults to `true` for a storefront and
`false` for a buyer. Shipped buyer profiles and development fixtures state their
consent explicitly. Put this scalar before any TOML table header:

```toml
use_registry_dispute_authorities = true
```

With the setting enabled, each role resolves its ordered local `[[Dispute]]`
entries first, followed by the recommendations from the registry it works
through. Descriptors are fetched through the signed, pinned registry client at
buyer bootstrap and storefront startup. Multiple registries keep independent
lists: a recommendation from one is not a default for another, and work with no
source registry uses local entries only. A failed descriptor read contributes
no recommendations; local preferences remain usable. Disabling recommendations
does not disable local entries or resolve any authority credential.

A storefront reads again, each time it composes listing options, every registry
whose last descriptor read failed, and only those, until a read succeeds: at
each publication cycle's `compose` stage in the VM and bare-metal storefronts,
and in API credits, which runs no publication cycle, when a listing is created
or seeded. So a storefront that started before its registry offers the
authorities it recommends on the first options composed after it answers,
without a restart. A successful read is kept until the storefront restarts, so
a healthy registry is not read again. The re-read goes through the core
storefront client's selective descriptor read, which refuses a selection naming
a registry it is not configured with, or a string in place of a collection. Reads
are serialized, so overlapping compositions request a failed registry once and
a failure answered after a success cannot mark a read registry unread again.

While a registry is unread, each mechanism whose options name a dispute
authority — Alkahest and Arkhai Payments — reports it in its readiness's public
details as `dispute_authorities_unread`, each entry the registry and when its
read last failed; each mechanism allowlists the detail and copies it from the
readiness resources the storefront supplies. It is a report, not a blocker:
readiness, publication and open listings are unchanged, so the options a
seller's local entries allow still publish meanwhile. It is shown on the
storefront's system status route (`GET /api/v1/system/status`), which reads the
running process; the `settlement status` command checks configuration in its own
process, with no dispute policy, and does not carry it. `/health` does not
depend on it.

A local entry names one authority by all four of `interface`, `origin`,
`account`, and `record_key`. `params` belongs to that interface. The
`advertisement` copy states the supported payment mechanisms and minimum
dispute/case-hold windows; extra interface-owned advertisement fields are
retained. For example, this uses reserved example data, not a live authority or
a shipped role template:

```toml
[[Dispute]]
interface = "example.dispute.v1"
origin = "https://dispute.example"
account = "example-authority-account"
record_key = "example-public-record-key"
params = {}
not_offered = false
not_accepted = false

[Dispute.advertisement]
mechanisms = ["example.payment.v1"]
minimum_dispute_window_seconds = 60
minimum_case_hold_seconds = 3600
```

An omitted `minimum_case_hold_seconds` means the authority requires an unbounded
case hold; JSON descriptors may express that as `null`. TOML has no null literal.
An entry marked `not_offered` is excluded from the seller's offered list; one
marked `not_accepted` is excluded from the buyer's accepted list. Deduplication
uses full identity **before** those marks: a local veto cannot be undone by the
registry repeating that authority, and a registry copy cannot replace locally
accepted parameters. A different origin or record key is a different authority,
even when its payment account matches.

A role with an empty resolved list logs **No dispute authority is available**,
naming both remedies: configure `[[Dispute]]`, or enable
`use_registry_dispute_authorities` and arrange a registry recommendation. Merely
configuring a payments service chooses no dispute authority. The selected
option names its authority under `lifecycle.adjudication.dispute`; mandate
derivation reads that accepted authority, not a service-wide default.
`[Settlement.arkhai_payments].dispute_authority` is rejected, including when its
value is null in a JSON overlay. Remove it and configure preferences instead;
the bare-metal buyer's `[bare_metal.arkhai_payments]` uses the same validation.
No template supplies an authority's account, origin or record key.

Credentials are separate entries, each bound to an authority's whole identity and
stating its token in exactly one form: `api_key`, the token itself, a secret
setting stated in a secret overlay, or `api_key_env`, naming the environment
variable that holds it. A storefront states its entries whole in its Secret
overlay, `storefront.secrets.toml`, with `api_key`; its chart's values schema
refuses any `[[DisputeCredential]]` in public `config`. A buyer may name a variable
its own provider holds:

```toml
# A storefront's storefront.secrets.toml
[[DisputeCredential]]
interface = "example.dispute.v1"
origin = "https://dispute.example"
account = "example-authority-account"
record_key = "example-public-record-key"
api_key = "<the token>"

# A buyer's public TOML
[[DisputeCredential]]
interface = "example.dispute.v1"
origin = "https://dispute.example"
account = "example-authority-account"
record_key = "example-public-record-key"
api_key_env = "EXAMPLE_DISPUTE_API_KEY"
```

The binding must match all four identity fields. An entry stating both forms, or
neither, or an empty or multi-line `api_key`, is refused when the configuration is
validated. Credential resolution happens only when the authority is used: it
returns `api_key`, or reads the named variable, whose absence or empty value fails
with the variable's name, never its value; a storefront holding no usable
credential for a deal's authority reports the deal `repair_required`. The
mediation client receives the resolved token, never a variable name:
`MediationCredential(identity, *, token)` takes a `SecretStr` and refuses an empty
token, one with surrounding whitespace, or one containing a line break, at
construction. Duplicate bindings for an
identity are refused at lookup.

A credential may also name `ca_bundle_path`, under
[`configuration.md`'s private-CA rule](../../../docs/guidance/engineering/configuration.md#trust-is-configured-where-its-client-reads-it); the
[specification](spec.md#requirement-dispute-credentials-are-bound-by-identity-and-no-template-ships-an-authority)
states its rules, and its
[architecture](architecture.md#precedence-and-secret-boundaries)
why the credential carries the bundle and what an unloadable one does.

The Agreement pins origin/record key for the
deal's potentially unbounded case life: preference edits affect only new deals,
and credentials must still serve accepted identities. Dispute adapters follow no
mid-deal origin redirect or record-key rotation. Payment receipt identity overlap
does not solve that separate limitation. A resolved credential is a secret wrapper and
is not stored in the preference model. Public authority projections contain
neither credential references nor secret values; neither belongs in options,
Agreements, status or run logs. See the runnable
[configuration example](../../../kit/deal-lifecycle/examples/dispute_configuration.py)
for ordered resolution, local vetoes, per-registry isolation and secret handling.
