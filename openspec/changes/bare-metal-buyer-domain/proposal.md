## Why

The marketplace has a versioned bare-metal schema, publication code, and executor components, but it has no installable buyer domain, so a real buyer cannot discover, negotiate, settle, recover, retrieve trusted whole-host access, or request teardown through the core `market` role. The buyer boundary must be fixed before hosted bare-metal settlement or the multi-domain topology proof can treat a script, direct provisioner call, or test-only client as a buyer.

## What Changes

- Add an independently buildable `arkhai-bare-metal-buyer` wheel that contributes `bare_metal.v1` through `market.buyer_domains`; the core-owned `market` executable remains the only buyer executable and does not import bare metal.
- Add a namespaced `market bare-metal` command surface for schema-driven discovery, exact lease demand construction, negotiation, settlement selection, run inspection/resume, trusted lease result/evidence/access retrieval, and idempotent teardown request/status.
- Reuse core buyer discovery, signed negotiation, settlement policy/transport, run-log, transient-action, and exact-principal recovery seams. Fresh commands use the selected persistent buyer profile; `--from` commands use the exact profile UUID and retained canonical principal recorded by the run.
- Define the buyer-visible bare-metal boundary as strict, versioned domain codecs: the buyer requests duration, one listed access method, and its SSH public key; seller/site-owned listing, Physical Resource, physical-host, machine, selected-site, executor, price, condition, and expiry values are never accepted as buyer routing authority.
- Consume only authority-authenticated storefront result, evidence, access, and teardown operations addressed from accepted run state. Portable result/evidence is allowlisted and credential-free; buyer-only SSH access data is retrieved separately and is never written to public evidence, JSONL, TOML, output intended for sharing, or diagnostics.
- Select one exact advertised `SettlementOption`/legacy Alkahest alternative through the shared settlement registry and preserve that choice through resume. Hosted-only Ed25519 operation works with wallet and chain settings absent; selecting Alkahest activates its explicit wallet/chain prerequisites.
- Make prerequisite acceptance mechanical: implementation is blocked until the persistent-profile/core buyer injection contract, storefront domain routing and authenticated lifecycle client contract, runnable bare-metal seller plus POOLS-7 selected-site fulfillment/result/teardown, and shared settlement-mechanism transport are implemented, promoted, and proven. No buyer-local seller/provisioner import, copied lifecycle, fake fulfillment, hard-coded resource/site, direct provider call, or test-only bypass may satisfy a missing seam.
- Wire the wheel into domain/root build and review scope, clean installation/reinitialization, configuration examples, and buyer-stack/E2E packaging. Prove ordinary installed-artifact operation against a real runnable storefront and real whole-host access/revocation lifecycle.
- **BREAKING**: no compatibility CLI, direct-provisioner buyer path, loose result/details dictionary, buyer-supplied `access_ref`, raw credential carrier, or alternate identity/settlement precedence is admitted. Any pre-existing test helper that impersonates a bare-metal buyer is removed when the real plugin replaces it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `buyer-orchestration`: Add the bare-metal domain plugin's exact discovery-to-teardown orchestration, recovery, transient-action, and trusted result/access behavior.
- `market-composition`: Require the bare-metal buyer to be an independently installable implementation of the versioned domain contract with one-way package dependencies and no seller/provisioner imports.
- `negotiation-protocol`: Define the exact buyer-owned bare-metal demand and seller-authoritative agreement/resource boundary carried by the existing versioned domain envelope.
- `deployment-state`: Package, install, reinitialize, configure, and release the bare-metal buyer plugin without creating a second buyer executable or requiring wallet/chain configuration for hosted-only operation.
- `test-compatibility`: Require shared domain conformance, installed-wheel, recovery, credential-redaction, and real whole-host buyer E2E evidence with no fake fulfillment path.

## Dependencies and acceptance gate

Implementation MUST stop at the gate until repository evidence, not active-change task marks alone, proves all of these contracts are accepted in permanent specifications and available from installed wheels:

1. `add-persistent-buyer-profiles`: `core.resolved-buyer-identity.v1`, version-3 run identity, selected-profile fresh resolution, and exact recorded-principal recovery.
2. `storefront-domain-parameterization` and `multi-domain-storefront-composition`, or an explicitly accepted successor: immutable domain dispatch, exact domain/listing routing, and bare-metal discovery identity with no fallback to another domain.
3. `market-platform-bare-metal-10-storefront-composition` plus `pools-7-storefront-fulfillment-cutover`: a runnable seller and authority-authenticated pull contracts for selected-site fulfillment status, typed result/evidence, buyer-only access retrieval, and durable teardown. Planning documents, injected fakes, and the current truthful `fulfillment_available=false` shell do not pass this gate.
4. The accepted settlement seams used by the buyer role: mechanism-neutral selection and recovery, Alkahest adapter, and `consume-expanded-stripe-funding` for hosted profiles, transient actions, and wallet-free `fiat.stripe.v1` operation. The bare-metal wheel does not copy VM settlement clients.

If an accepted producer contract differs from the exact consumer contract recorded in `design.md`, this change is updated before implementation; no adapter to a draft or obsolete route is added locally.

## Non-Goals

- Implementing, hosting, or importing seller publication, negotiation authority, site selection, Capacity Reservation, fulfillment scheduling, provisioning provider, evidence signing, access issuance, or teardown execution inside the buyer wheel.
- Adding a separate `market-bare-metal` executable, buyer daemon, reverse callback listener, buyer-owned database, or alternate run log.
- Letting the buyer choose or override a site, pool, Physical Resource, physical host, executor machine/provider, seller/claimant, condition, settlement amount, or accepted deadline.
- Returning private SSH keys, passwords, bearer tokens, raw provider/executor payloads, arbitrary `details`, provisioning URLs, or credentials through public evidence or normal command output.
- Adding new access methods beyond SSH, changing the seller's pricing policy, implementing hosted financial behavior, or completing the separate multi-domain seller topology.
- Supporting obsolete direct `[Identity]`/raw secret configuration, implicit settlement fallback, or automatic mechanism switching during recovery.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Promote the independently installable buyer-domain/plugin dependency boundary and core-owned executable rule to `openspec/specs/market-composition/{spec.md,architecture.md}` and `docs/development/ARCHITECTURE.md`.
- Promote bare-metal demand authority, trusted result/evidence/access retrieval, teardown, and exact recovery behavior to `openspec/specs/buyer-orchestration/{spec.md,architecture.md}` and the applicable `negotiation-protocol` architecture.
- Promote wheel/reinit/configuration and wallet-free hosted-only rules to `openspec/specs/deployment-state/{spec.md,architecture.md}`, `docs/development/DEPLOYMENT_AND_CONFIG.md`, `docs/buyer-quickstart.md`, and a new `docs/bare-metal-buyer-quickstart.md` if the standalone workflow cannot be expressed without obscuring the common buyer guide.
- Promote test-level jurisdiction and installed-artifact/whole-host evidence to `openspec/specs/test-compatibility/{spec.md,architecture.md}` and `docs/development/TESTING.md`.
- At completion, update the Compute-30 current state and remove or remap the `bare-metal-buyer-domain` gap in `docs/development/ROADMAP.md`; record every promotion in this change's design-promotion record.
