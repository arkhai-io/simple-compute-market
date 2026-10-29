# Settlement Configuration Architecture

The [normative contract](spec.md) defines the configuration, readiness, migration, publication, and selection invariants shared by settlement mechanisms. This document explains why one typed hierarchy composes distinct mechanisms without merging their authorities or runtimes.

## One hierarchy, peer mechanisms

Marketplace roles use one `[Settlement]` root. Its `priority` list contains canonical mechanism IDs and its typed peer subsections contain only mechanism-owned policy and public client inputs:

```toml
[Settlement]
priority = ["arkhai.payments.v1", "alkahest.v1"]

[Settlement.arkhai_payments]
enabled = true

[Settlement.alkahest]
enabled = false
```

Configuration keys are stable operator vocabulary: `arkhai_payments` maps to `arkhai.payments.v1`, and `alkahest` maps to `alkahest.v1`. Canonical IDs remain the wire and runtime vocabulary. A quoted table keyed directly by the canonical ID would make dotted-path editing and environment overlays awkward; a generic list of dictionaries would discard typed validation.

Identity, wallet, and chains remain siblings of settlement. Identity authenticates marketplace roles. Wallet and chain resources support explicitly selected EVM effects. Neither is mechanism policy, and a non-EVM payment role must not need placeholder EVM resources.

New defaults select nothing. An operator must explicitly enable and order mechanisms, while migration preserves the previously effective selection. This avoids silently publishing a financial option merely because its package is installed.

## Registration and ownership

Each installed mechanism explicitly registers its canonical ID, config key and schema, applicable roles, preflight, client factory, listing-option builder, buyer compatibility hook, typed public clause projections, and optional operator commands. Mechanism-qualified clause fields stay under the config-key namespace and declare their roles, operators, and value types. Shared configuration code owns grammar integration, ordering, exact option correlation, and common status; it does not interpret chain, arbiter, condition, provider, or financial-authority fields.

A composition root injects only the resources a registration declares. Alkahest may receive wallet and chain clients. Arkhai payments resolves owner-scoped WorkOS credentials and trusted receipt policy through `market_arkhai_payments.settlement_config`. The buyer's payer account is domain input, independent of marketplace identity and service policy: `[vms].payer_account` or `[apicredits].payer_account`. Seller clients use the accepted option's payee account. API-credit seller clients are request-scoped and close after polling, attachment, and any reversal; there is no startup-global payment account. Omitting a registration removes that mechanism from status, publication, and selection rather than installing a placeholder.

Registration shares configuration, readiness, option construction, and selection,
not execution or a universal lifecycle. Fresh publication and buyer compatibility
intersect registrations with the corresponding supported role table. Registration
alone grants no execution support. Accepted work retains its Agreement-selected
entry independently of current priority or enablement; unavailable accepted support
refuses before effects rather than falling through to escrow.

Arkhai payments leaves conditional-escrow client and obligation hooks unset;
domain composition consumes the exact Agreement and signed receipt. Alkahest and
contact exchange use the shared obligation runtime. A stage convention lives in
a kit, chosen when concrete reuse justifies it; the one implemented is
`kit/storefront`'s refusal of settle and fulfillment requests for a deal settled
by introduction (see the [market composition
architecture](../market-composition/architecture.md#settlement-runtime-composition)).
There is no required convention protocol or speculative adapter dependency,
including for seller-first or fused stages.

## Readiness, publication, and selection

Preflight normalizes mechanism-owned checks into a public-safe result: canonical ID, configured, enabled, ready, blocker codes and messages, capabilities, and contract/schema versions. Mechanism detail is allowlisted. Status is observational: it does not publish, create transient browser actions, submit transactions, or mutate provider or settlement state.

The storefront evaluates every enabled registration, then combines ready registrations with validated publication clauses. Only a clause owned by an enabled, ready mechanism with a supported seller entry can produce an option. Options follow configured mechanism priority and source clause order. One unready mechanism is suppressed and remains visible through sanitized status; a ready peer with a valid clause remains usable. An enabled mechanism without a clause does not inherit another mechanism's price or publish an implicit option. Arkhai payment clauses include the payee account and asset explicitly. The shared payment builder scales hourly prices from decimal major units by asset precision and accepts generic integer base-unit prices per unit without scaling. Domain adapters own unit vocabulary: API credits accepts `credit`, `token`, or `request`.

A clause is read in full apart from configuration, through `parse_settlement_publication_clause`, before its mechanism's enablement is judged. A clause that does not read — a stated `mechanism_input` that is not a mapping among such faults — is a payload failure that leaves its listing as it is, so a malformed clause never delists anything. A readable clause naming a mechanism whose section is absent or disabled is dropped and rules that mechanism out, wherever it is stated: a pool's hint, a storefront override, or the storefront's own configured clauses. Disabling a mechanism is a deliberate operator act, so a listing that mechanism alone priced closes rather than holding every listing open, and configuration migration accepts a result whose clause names a disabled mechanism, as the storefront starts with one.

A storefront must not need any one mechanism to function, so a configured section that parses but cannot settle makes its mechanism unready rather than stopping startup: it costs the seller that mechanism, not the storefront. For Alkahest that covers an oracle-gated section with no trusted oracle, an oracle equal to the seller wallet's address or to the account its key signs as, a wallet with neither an address nor a key to derive one from, a missing key where the role signs, a seller's address that is not the account its key signs as (`alkahest.wallet_address_mismatch`), no chains, an address book named for a chain the role does not configure (`alkahest.address_book_chain_unknown`), an interruptible section with no interruptible oracle, and a configured release model its domain cannot deliver. A section that does not parse still stops startup, as all configuration does, and so does configuration that is incoherent rather than unusable, such as Alkahest inputs supplied with no Alkahest section. A disabled section reports, after `disabled`, the configuration blockers its mechanism's preflight finds, so an operator sees what enabling it would need; each preflight decides what that is. Arkhai payments' reports nothing for a disabled section, while bare metal services its accepted payment deals whatever `enabled` says, so a disabled payments section missing a credential those deals need goes unreported.

Every readiness blocker states its kind, `configuration` or `reachability`, because the publication runner acts differently on each. A mechanism with any configuration blocker is ruled out: the storefront's own configuration excludes it, and an oracle-gated section with no oracle cannot settle even once its chain answers, so an open listing it alone priced closes. A mechanism whose every blocker is a reachability blocker is unknown: its readiness could not be determined, so a listing it priced is held at its last terms rather than closed for an outage (see the [storefront publication architecture](../storefront-publication/architecture.md#reconciliation)). The runtime's own `not_configured` and `disabled` blockers are configuration blockers, and Arkhai payments and contact exchange contact nothing during readiness, so every blocker they report is one too. Reachability comes from Alkahest's chain probe.

The probe, `AlkahestChainProbe` in `kit/alkahest`, runs apart from readiness because readiness is evaluated per candidate, per status read, and at startup: probing inside the preflight would call each chain once per candidate per cycle. Each storefront composing Alkahest registers the probe's step as its `alkahest-chain-probe` lifecycle loop, whose timer runs it once per probe interval, 30 seconds by default, with the pause and explicit step every loop has; each step probes every chain, so an operator's step always acts on the chain as it is, and the timer bounds how often a chain is called. A step reads each chain's ID and then the code at each contract address its address configuration requires, every call bounded by the RPC timeout: an error or timeout is the reachability blocker `alkahest.chain_unreachable`, while a different chain ID or a required address with no code is the configuration blocker `alkahest.chain_id_mismatch` or `alkahest.contract_missing`. The preflight reads each chain's last result and calls no chain. A chain not yet probed since start reads as reachability, so a fresh storefront holds its open listings rather than closing them, and a result does not expire, so while the loops are held readiness reads the last one however old. The probe also owns the live chain-client map every consumer is handed: startup constructs no client, since a websocket client connects while it is built and an endpoint that never upgrades the connection would hold startup for good, and each probe constructs a missing client, bounded by the RPC timeout and at most one construction per chain, and fills the map in place, so a storefront recovers without a restart. Servicing settles through the client, so a chain whose client could not be built reads unreachable whatever its JSON-RPC calls answer. A websocket `rpc_url` is probed over HTTP at the same host, port, and path, so a provider serving the two on different endpoints reads unreachable. Status reports each chain's last result and when it was taken, within the mechanism-neutral `settlement` readiness list every storefront's status carries.

What readiness judges depends on what is asked. Publication judges the chains a candidate's escrows name; status asks with no publication input and so judges every configured chain, since servicing an accepted deal needs whichever chain it was accepted on, and status's `ready` means every configured chain is reachable and deployed. Readiness stays per mechanism, so one unreachable chain makes Alkahest unready for every chain a publication names together, and a candidate's Alkahest options on all its chains wait for that one; per-chain readiness would change the readiness contract every mechanism shares.

Readiness governs publication only, which leaves known limits. An Alkahest address, chain, or key removed while obligations are open leaves the seller unable to service or collect them, and an address book that stops naming the escrow contract an accepted deal funded leaves that deal neither verifiable nor collectable, since verification finds the contract's codec and the SDK client collects through the same address configuration. In each case the buyer's escrow stays reclaimable at expiry, so the exposure is the seller's own; refusing startup on open obligations would make startup depend on stored deal state and restore the dependency on Alkahest. And an API-credit listing's options are fixed when it is created, so one whose Alkahest becomes unready keeps advertising its Alkahest option until its seller closes it, while deals accepted on it verify against their committed plan and settle as before.

Priority is pre-acceptance policy only. The buyer first filters advertised options by installed/enabled compatibility and authoritative resource constraints. Explicit repeatable settlement clauses then act as ordered alternatives; every predicate in a clause must match one option. Configured priority ranks survivors only when no explicit clause supplies order. Accepted Terms pin one exact option. Later enablement, readiness, ordering, or clause changes cannot switch or reinterpret an accepted or in-flight obligation.

### One seller account

A seller's wallet address and key name one account. The address is what published release conditions name as the recipient, and the key signs every chain transaction the seller makes: the fulfillment attestation, collection, reclaim, arbitration requests, oracle decisions, and refunds. Two accounts would make collection revert after delivery under the recipient release model, or pay the key's account rather than the named one under the oracle-gated model, and would let an oracle that is the seller's signing account pass a check that compared only the address. So a mismatch is an Alkahest readiness blocker in `kit/alkahest`'s wallet checks, for every storefront, and the oracle check compares the oracle with the signing account as well as the address. It is a readiness blocker rather than a startup refusal because the wallet serves only Alkahest. A seller that states no address uses its key's (`wallet_account_address`, through `kit/config`'s `derive_wallet_address`), wherever the seller's address is named. Buyers are not judged: a buyer's address names nothing an escrow pays. Paying a seller into a separate account, such as a multisig or treasury, would need a payout setting, attestations naming that recipient, and refunds from it; no such setting exists.

### Alkahest address books

An address book is one deployment's Alkahest contract addresses, overriding the SDK's built-ins for a chain such as a local Anvil. A role names each chain's book in `[Settlement.alkahest.address_books]`, a table from configured chain name to book, and a chain it does not name uses the built-in addresses. The table belongs to the Alkahest section because a book is Alkahest's data about a chain, and `[Chains]` holds only chain resources; it is per chain because one section-wide path cannot express a seller on a local chain with a book beside a public chain without one, and applying one book to every chain would service one chain's claims against another's contracts.

A chain's book is resolved by one `kit/alkahest` operation, `alkahest_address_book`, and only composition roots, the storefronts and buyer commands, call it. They hand the resolved chain-to-book mapping as data to the negotiation, policy, codec, and settlement packages, which take it through their existing `chain_config_paths` parameters and so gain no dependency on `kit/alkahest`.

The two keys the table replaced, `[Chains.<name>].alkahest_address_config_path` and `[Settlement.alkahest].address_config_path`, are refused by name with a diagnostic naming the table, before a role resolves its settlement section, rather than ignored, since an ignored key would leave its chain on a book the operator did not mean. Settlement configuration migration moves either into the table: a per-chain key to its own chain, and the section key to the one configured chain, or to the chains whose per-chain keys named the same book. Where it cannot tell which chains the section key served, or two different books would land on one chain, migration refuses and names both keys. Only claim servicing and readiness read the section key, so on another configured chain claims move to the book the chain's other readers already used, its own or the built-in addresses; a seller's migration names each such chain in its report before anything is written.

## Role-appropriate operator surfaces

The storefront owns seller settlement administration under one command tree:

```text
market-storefront settlement status
market-storefront settlement alkahest check
market settlement status
market settlement alkahest escrow show
```

Mechanism subcommands remain asymmetric. Arkhai payments has no marketplace payer setup, instrument, or Stripe onboarding surface. Buyer templates expose selection inputs and omit seller account, onboarding, authority-administration, publication, and provider fields.

## Precedence and secret boundaries

Resolution order is explicit CLI override, environment or Secret overlay, role/user configuration files — for a storefront, `storefront.toml` then a chart-rendered `storefront.json` — then committed defaults. Lists replace lower-layer lists in full. Typed metadata drives role templates, dotted-path validation, environment schema fragments, the VM storefront chart's generated values-schema definition, and reference output so these surfaces drift together. That definition refuses secret-marked and role-inapplicable fields and closes typed sections; it carries no defaults, because a chart passes the configuration through and the storefront owns them.

Public principals, payment receipt trust pins, fee/dispute policy, account references, assets, condition profiles, chain names, and deployed addresses may be ordinary configuration. Private identity, wallet, or request credentials cross only approved Secret or environment boundaries. Payment-provider, administrator, webhook, ledger database, and service-migration configuration belongs to the payments service and is rejected by marketplace schemas.

## Configuration migration and recovery

Settlement configuration migration is explicit, previewable, conflict-rejecting, validated, backed up with restrictive permissions, and atomically replaced. Storefront publication migration separately converts legacy scalar pricing in storefront configuration into complete typed clauses. A source that would require one ambiguous price to construct multiple mechanism options is rejected for manual resolution. Both migrations preserve unrelated TOML bytes where possible, require an explicit backup before writing, and are no-ops when repeated. Runtime accepts only the typed hierarchy and publication inputs. Legacy Stripe settings are rejected with removal diagnostics, not mapped to a payment account, credential, mandate, or transaction.

Deployment stages migration tooling before the rejecting runtime, previews and backs up every role file, publication config, and inventory, quiesces publication and config automation, migrates all surfaces, validates them, and then activates the clean-cutover release. Before activation, rollback restores matching configuration, inventories, and artifacts together. After new publication or settlement effects begin, recovery rolls forward.

Run logs may retain the public configuration schema version and mechanism-set fingerprint, but exact accepted Agreement bytes, settlement data, and domain/obligation progress remain authoritative. Recovery uses the accepted canonical mechanism and stable operation identities even when that mechanism is disabled for new deals.


## Related contracts

- [Settlement servicing](../settlement-servicing/spec.md)
- [Storefront publication](../storefront-publication/spec.md)
- [Buyer orchestration](../buyer-orchestration/spec.md)
- [Market composition](../market-composition/spec.md)
- [Deployment and state](../deployment-state/spec.md)
