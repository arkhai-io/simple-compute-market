# arkhai-e2e-tests

End-to-end integration tests for Arkhai deployed blockchain environments.
Tests run against live (or local) EVM-compatible nodes and validate contract
state and wallet configuration for each target environment.

---

## Quick start

```bash
# 1. First build/init and install the full stack. A local cluster uses the
#    local overlay, so uninstalling discards the release's state
#    (docs/development/DEPLOYMENT_AND_CONFIG.md, "Stateful service persistence").
make build
make -C helm deploy-local

# 2. Run tests against local Anvil node.
make test ACTIVE_PROFILES=local
```

---

## Configuration system

Configuration is managed by [dynaconf](https://www.dynaconf.com/) and layered
from multiple sources.

### Resolution order

Highest priority wins.

| Priority | Source | Example |
|----------|--------|---------|
| 1 | `ARKHAI_*` environment variables | `ARKHAI_RPC__URL=https://…` |
| 2 | `config-<profile>.yml` files (secrets injected here) |
| 3 | `config.yml` (in `CONFIG_DIRECTORY`) | base env config |
| 4 | `.env` file | local development overrides |
| 5 | `.secrets.toml` | local secrets (gitignored) |
| 6 | `settings.toml` | project defaults / schema |

### Config directory and profiles

These environment variables affect which config files are loaded.

```
CONFIG_DIRECTORY=/path/to/config    # directory containing config.yml
ACTIVE_PROFILES=staging,secrets     # comma-separated; files loaded in order
```

The loader merges `config.yml` first, then each `config-<profile>.yml` in the
order listed in `ACTIVE_PROFILES`.  This lets you stack a base environment
profile with a separate secrets-only profile:

```bash
ACTIVE_PROFILES=staging,staging-secrets
# loads: config.yml → config-staging.yml → config-staging-secrets.yml
```

### Shared payment-scenario configuration

The payment scenarios — `e2e_credits_payment_deal`, `e2e_bare_metal_payment_deal`,
`e2e_vm_payment_deal` and `e2e_vm_payment_purchase`, and the qualification modules
`e2e_vm_qualification`, `e2e_bare_metal_qualification` and
`e2e_real_provisioning_reapply` — read the `PAYMENTS` section (environment prefix
`ARKHAI_PAYMENTS__`) through `tests/e2e/roles/helpers/payments.py`. SERVICE_URL
names the payments target; leave it blank and the scenario reports `blocked` and
skips. With it set, supply the other four: SERVICE_IDENTITY (public Ed25519
receipt signer), BUYER_ACCOUNT, BUYER_MARKETPLACE_CREDENTIAL and
SELLER_MARKETPLACE_CREDENTIAL (the storefront's own key, in its scheme, which the
refund stages sign with); a missing one fails the scenario, naming it.
Marketplace credentials are independent of payment account IDs. Dispute
authorities are role preferences or signed registry recommendations, not a
payments-helper setting; configure the seller and the buyer's registry
accordingly. The shared buyer profile writer explicitly opts into registry
recommendations.

The `MEDIATION` section (environment prefix `ARKHAI_MEDIATION__`), read through
`tests/e2e/roles/helpers/mediation.py`, names the run's dispute authority for the
buyer: SERVICE_URL its origin, ACCOUNT and RECORD_KEY its identity, API_KEY_ENV
the variable the buyer's `[[DisputeCredential]]` names its token by, BUYER_API_KEY
that token, CA_BUNDLE_PATH the bundle it is trusted under, and, for a lane's own
target, LANE_OWNED and CONTROL_TOKEN. With SERVICE_URL set, the purchase drivers
write the buyer's credential and hand the token to each `market` process under
API_KEY_ENV; a missing required setting fails the scenario by name, an unready
lane-owned target fails setup by name, and an unready external one reports
`blocked`. With it blank, the scenarios that need an authority report `blocked`,
and a purchase writes no credential.

Each end-to-end lane configures its own target, the payments lane double
([`tools/payments-lane-double`](../tools/payments-lane-double/README.md)), which
the lane runs beside its storefronts at `https://payments-double:8443`, and
states its settings in committed runner profiles. A lane target runs the runner with
`RUNNER_PROFILES=docker,payments-lane,<lane>-lane`: `config/config-payments-lane.yml`
holds what every lane shares — the target and its identity, the fee, LANE_OWNED,
CA_BUNDLE_PATH, API_KEY_ENV and BUYER_API_KEY, both accounts and the buyer's
marketplace seed — and `config/config-<lane>-lane.yml` only what differs, the
seller's marketplace credential and, for bare metal, its whole-host fixture's
COMPUTE_HOURLY_GROSS and DISPUTE_WINDOW. Dynaconf merges the section key by key.
`test-buyer-machine` mounts the lane CA where CA_BUNDLE_PATH names it, and passes
the runner nothing else; rerunning markers against a lane's stack passes the
lane's RUNNER_PROFILES. The lane's settings mark the target LANE_OWNED, so an
unready one fails the scenario naming it rather than skipping; LANE_OWNED with no
SERVICE_URL fails too. `config-docker.yml` carries no `PAYMENTS` section, so a run
selecting the `docker` profile alone has no payments target.

DISPUTE_WINDOW_SECONDS is the dispute coverage, in whole seconds, of every compute
payments option the harness states — a VM listing's payments settlement, the
bare-metal lane's pool override — and the coverage its purchase checks expect of
those options. It defaults to 1296000 (15 days), which covers the 14-day minimum
filing window of the Arkhai mediation contract's default authority description
(`kit/arkhai-mediation`) plus the 300-second delivery deadline; no lane profile
sets it. A run against a dispute authority advertising a
shorter minimum may name a shorter coverage, no less than the delivery deadline plus
that minimum: 360 for a 60-second minimum. A value that is not an integer, or is less
than the delivery deadline, fails the scenario naming the setting; the storefront
refuses one below the authority's minimum. It is separate from DISPUTE_WINDOW, the
payment's own `window` input. A listing created under one coverage keeps it, so a
later run naming another fails the purchase's option check against that listing.

FEE_BPS defaults to 250. LIVEMODE, DEVELOPMENT_AUTH and LANE_OWNED default to
false and must be `true` or `false`; generated buyer tables explicitly pin the
receipt mode. Choose either DEVELOPMENT_AUTH=true (literal loopback service URL
only) or API_KEY_ENV naming the variable the buyer reads its bearer key from,
never both. The key is the setting BUYER_API_KEY, never a variable of the
runner's environment: the harness hands it to each buyer it runs under the name
API_KEY_ENV gives, to a `market` process in its environment and to an in-process
payments client as the environment it resolves the key from. An external run
states BUYER_API_KEY in a secret profile.

An unreachable or unready external `/health` also reports `blocked` and skips.
The readiness probe disables environment proxies and trusts the CA_BUNDLE_PATH
bundle alone when one is configured, as the payments client does; a bundle it
cannot load leaves the target unready. Invalid policy fails
rather than selecting another settlement mechanism. The shared serializer writes
only a named payments table — `Settlement.arkhai_payments`, or
`bare_metal.arkhai_payments`, which it supports for a bare-metal buyer — with the
configured CA bundle as its `ca_bundle_path`, and the scenario supplies domain
settings and payer.

Before any scenario runs, each lane target runs its payment storefront's
`check-payments --account <the seller's account>` in the storefront's own
container (`docker compose exec`), an authenticated read of the seller's balance
at the double through the storefront's configuration, its `ca_bundle_path` and
CA mount, and the key in its secret overlay, and
fails the lane on a nonzero exit; the command's one JSON line names the step that
failed.
See [Private Service Dependencies](../docs/development/TESTING.md#private-service-dependencies)
for the public testing boundary.

### Secret injection (Kubernetes / Vault)

In a Kubernetes environment, mount secrets as a file into `CONFIG_DIRECTORY`:

```yaml
# deployment.yaml (excerpt)
volumes:
  - name: e2e-secrets
    secret:
      secretName: arkhai-e2e-staging-secrets
volumeMounts:
  - name: e2e-secrets
    mountPath: /etc/arkhai-config/config-staging-secrets.yml
    subPath: config-staging-secrets.yml

env:
  - name: CONFIG_DIRECTORY
    value: /etc/arkhai-config
  - name: ACTIVE_PROFILES
    value: staging,staging-secrets
```

The mounted file only needs to contain the keys it overrides:

```yaml
# config-staging-secrets.yml (mounted by k8s secret)
buyer:
  private_key: "0x..."
seller:
  private_key: "0x..."
```

For Vault, use the Vault Agent sidecar to render the same file from a template.

### All configuration keys

```yaml
rpc:
  url: "http://localhost:8545"   # RPC HTTP or WebSocket endpoint
  chain_id: 31337                # must match the actual chain
  timeout_seconds: 30
  retry_attempts: 3
  retry_backoff_seconds: 2

registry:
  identity_address:   ""         # deployed IdentityRegistry contract
  reputation_address: ""         # deployed ReputationRegistry contract
  validation_address: ""         # deployed ValidationRegistry contract
  owner_address:      ""         # expected owner() of all three contracts

buyer:
  private_key:    ""             # hex private key (with or without 0x)
  wallet_address: ""             # checksummed Ethereum address

seller:
  private_key:    ""
  wallet_address: ""

tests:
  minimum_eth_balance: "0.01"   # wallets must hold more than this (ETH)
  gas_price_strategy: "medium"
  require_checksummed_addresses: true
```

Any key can be overridden via an env var using `ARKHAI_` prefix and `__` as
the nested separator:

```bash
ARKHAI_RPC__URL=https://mainnet.infura.io/v3/YOUR_KEY
ARKHAI_REGISTRY__IDENTITY_ADDRESS=0xabc…
ARKHAI_BUYER__PRIVATE_KEY=0xdeadbeef…
```

---

## Running tests

### Make targets

```bash
make test                          # all tests, ACTIVE_PROFILES=local
make test-ci                       # all tests + HTML report (for CI)
make test-module                   # limits tests tagged as that module (usually a single test file)

# Override profile and config dir
make test ACTIVE_PROFILES=staging CONFIG_DIRECTORY=/mnt/e2e-config

# Pass extra pytest args
make test PYTEST_ARGS="-k test_contract_owner -v --tb=long"
```

### End-to-end lanes

Each market domain's lane replaces its own compose stack with a fresh one,
builds its images, and runs its scenarios against it: `make test-e2e-vm`, `make
test-e2e-bare-metal`, and `make test-e2e-apicredits`. Each leaves its stack
running; `make e2e-<lane>-down` takes it down. `make test-e2e` runs all three in
turn, taking each stack down before the next. The compute lanes' provisioning
services run the mock profile unless `PROVISIONING_MODE=real`. Every lane runs
the payments and mediation lane doubles, and the VM lane's scenarios include the
six [VM dispute controls](#vm-dispute-controls) modules.

### Hosted VM servicing

`e2e_vm_payment_deal` runs in the VM lane. It publishes a hosted-only one-hour VM
option, approves the exact accepted mandate, commits through `LifecycleClient`,
replays commitment and steps servicing. An administrator then ends delivery
without payee stop rights; the seller files one mediation case while teardown is
gated. Finally, a seller refund reverses the held payment, separately from
callback-proven capacity return. The mock executor proves the service wiring, not
a real guest or SSH access.

Every stage runs against the VM lane's doubles. The lane's two registries
recommend the mediation lane double
([`tools/mediation-lane-double`](../tools/mediation-lane-double/README.md)) as
the dispute authority, and Bob's secret overlay
(`dev-env/identities/bob.storefront.secrets.toml`) holds an identity-bound
`[[DisputeCredential]]` for it, whose `api_key` is a public development value and
whose `ca_bundle_path` names the lane CA. No rule is installed, so the
operator-end stage's filing is accepted and each part is held by a real
extension at the payments double, nothing is ruled, and the storefront's
lifecycle read lists one open extension per part, bound to the case; the refund
stage then reverses the held money. The module's resource release frees the
capacity.

Against an external deployment, supply healthy payment and mediation
authorities, set MEDIATION.SERVICE_URL to the mediation authority's URL — the
stages reach the authority the registries recommend, and the setting states that
one accepting cases is there — configure exact signed-registry
recommendations, seller recommendation consent and an identity-bound
`[[DisputeCredential]]` for the accepted mediation authority. State it whole in
the storefront's secret overlay, its `api_key` the seller's bearer credential.
A running authority without a usable party credential is not enough.
Development-auth adapters belong to the disposable authority setup, not SCM.
Before pytest, check Compose health, payment health from host/seller/buyer,
mediation health and an authenticated publication using
`option["settlement"]["schema"]`, not the retired option-level mechanism key.
The [VM readiness gate](../docs/attachments/vm-end-classification/readiness.py)
and [hosted qualification packet](../docs/attachments/aeet-vm-hosted/index.md)
provide the direct entry point and observed stages; the gate reads the mediation
origin it checks as `PAYMENTS.MEDIATION_URL`, apart from the scenario's
MEDIATION.SERVICE_URL, so an external run sets both. Without a configured payment
target all four stages report blocked skips; no Alkahest fallback is used.

### VM dispute controls

Six scenarios in the VM lane prove the lane's dispute wiring — the lane CA, the
storefront's dispute adapter and servicing, and both doubles' controls together.
Each is a module of its own under `tests/e2e/roles/scenarios/vms/dispute/`, with
its own marker, on its own once-only deal over its own executor, pool and
resource; a deal a buyer filed on cannot take a second delivery-end filing, so no
scenario shares another's deal.

| Marker | Module | What it proves |
|---|---|---|
| `e2e_vm_dispute_ruled_end` | `test_ruled_delivery_end.py` | a rule's ruling, held at its gate on the buyer's filing, applies its reverse only on resume; the storefront's next servicing step records the end with cause `ruling` and tears delivery down |
| `e2e_vm_dispute_discount` | `test_operator_discount.py` | the storefront answers the buyer's case as respondent; an operator decision reverses part of the held money with no delivery end and closes the case, and delivery stays active |
| `e2e_vm_dispute_lost_filing` | `test_lost_filing_answer.py` | the answer to the storefront's operator-end filing is dropped after commit; the storefront's servicing retries the filing and its adapter adopts the one case |
| `e2e_vm_dispute_mediation_unavailable` | `test_mediation_unavailable.py` | with the mediation double unavailable, servicing reads the authority's outcome `unknown` while delivery stays active, and reads the case again once the outage is removed |
| `e2e_vm_dispute_payments_hold` | `test_payments_hold_a_ruling.py` | payments loses its answer to the first of two reverses and is then unavailable while the decision is repeated; the storefront shows the ruling unapplied, and the decision repeated once payments answers completes it with exactly one reverse per effect |
| `e2e_vm_dispute_hold_passed` | `test_hold_passed.py` | after the deal ends, both doubles' clocks advance past the part's terms end and then its release instant; the snapshot shows the payout, and the buyer's filing reports the part `not_held`, `paid_out`, and is dismissed with nothing held |

Every stage advances one side effect through the services' typed clients, the
doubles' `ControlClient`, or the mediation kit's dispute adapter, never a raw
HTTP call. SCM files a case only as it ends delivery — the storefront's operator
end, the buyer's `market end` after a surrender — and no SCM command files one
on a running deal, so where a scenario needs a case on a delivering deal the
harness files as the buyer: `file_as_buyer` (`tests/e2e/roles/helpers/mediation.py`)
submits a delivery-end claim through the mediation kit's `MediationAdapter` and
the deal-lifecycle kit's `submit_dispute`, with the buyer's token and the lane CA
from the runner's `mediation` section and a file evidence store of the module's
own. The storefront meets what a real buyer's filing gives it: no matching
surrender, so it answers with a contest. The lost-filing scenario's filer is the
storefront's operator end instead, since the buyer's retry is a same-key replay,
not the adapter's adoption.

The storefront's watch records an end from a delivery-end effect whatever its
applied state, so no stage steps the storefront's servicing while a ruling waits
at its gate. The payments-hold scenario's two reverses on one part are
indistinguishable to a payments rule and an outage cannot be scoped, so it stops
the ruling with a dropped answer on the first reverse, then an outage while the
decision is repeated. In the hold-passed scenario no storefront step follows the
clock advance, since the storefront reads wall time.

The modules run in any order: each removes its rules through `lane_double_rules`,
and the hold-passed module, the only one that advances the clocks, resets both
doubles' clocks through `lane_double_clock`, whatever its outcome. A deal still delivering when its scenario's stages end is ended by the
shared lease-expiry stages, for which the storefront files no case;
`DisputeStageZ_NoFurtherCase` then steps servicing once and holds the deal to the
scenario's own cases.

### VM buyer purchase

`e2e_vm_payment_purchase` runs in the VM lane. The lane's buyer, configured with
no wallet and Arkhai payments as its only settlement, buys one hour of a VM
through `market buy`, which selects the scenario's listing by discovery and
polls its settlement until delivery while the scenario steps it. The scenario
runs the shared buyer-purchase stages, checks the transaction against its
Agreement and the payer's balance drop against its debit, and ends the lease by
back-dating it and stepping one lease-watchdog cycle. The listing names its own
resource, host, pool and GPU model, and its payment stays held in the double
until the lane ends.

### Real bare-metal provisioning

`e2e_bare_metal_real_provisioning` runs the canonical complete deal against a
real bare-metal provisioning service and an operator-prepared relay-backed host.
It is in no default lane. Configure the existing `BARE_METAL_LANE` client settings
for that release and its pinned principals, and select the ignored
`real-provisioning-target` profile with a `domain: bare_metal` host. The target
must contain the operator-verified OpenSSH host public key and relay identifier;
it contains no private key, token or signing key.

```bash
make test-module MODULE=e2e_bare_metal_real_provisioning ACTIVE_PROFILES=local,real-provisioning-target
```

Before any hold or supply write, the target, real executor and enabled relay with
a configured token and active grant key are checked. The run reconciles its own
pool, executor and whole-machine declaration, adopts exactly one open listing
for its verified machine/shape, and refuses another declaration on that host.
Reconcile older declarations under paused admission before running it; the
scenario does not delete or reassign unrelated supply.

The buyer uses a generated key and the pinned machine key at the delivered relay
port; an unrelated key must be refused. Grant and reclaim jobs must succeed on
the target, management connectivity must survive, and lease expiry must release
capacity and close the delivered access while retaining relay quarantine.
Failure recovery truncates only the run's lease and names unconfirmed cleanup.
Without a bare-metal target the module skips before mutation. These checks are
source capabilities; a passing mock pipeline does not qualify real hardware.
Use the [operator runbook](../docs/development/VALIDATION_RUNBOOK.md#28-prepare-and-operate-buyer-relays)
to prove deployed grant admission before either real lane. Container admission
proof and native installer component tests have different scopes; neither
substitutes for a completed real purchase, SSH access and reclaim observation.

### Real-provisioning qualification

Three modules make the [runbook's owed observations](../docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes)
2, 4, 5 and 6: `e2e_vm_qualification` (observation 2) and
`e2e_bare_metal_qualification` (observations 4 and 5) as external-topology
extensions of the lanes' buyer purchases, and `e2e_real_provisioning_reapply`
(observation 6) as a follow-up that makes no deal, on the stack their purchases
populated.
Each is in no lane and needs both the `real-provisioning-target` profile and a
configured `PAYMENTS` target (with `LANE_OWNED` unset, so an unready target is a
blocked skip); without either it is a blocked skip before any hold or write.
The payer is funded by the deployment, never by a module, and is assumed
dedicated to the run. The VM host's listing, which the VM module creates unless
an earlier module did, states `PAYMENTS.DISPUTE_WINDOW_SECONDS` as its payments
option's dispute coverage, so a target whose dispute authority advertises a short
minimum filing window can be bought under a short hold; the bare-metal machine's
listing states the coverage its storefront's own configuration gives. Run each
through `test-module`, observation 6 after the other two on the same stack:

```bash
make test-module MODULE=e2e_vm_qualification ACTIVE_PROFILES=local,real-provisioning-target
make test-module MODULE=e2e_bare_metal_qualification ACTIVE_PROFILES=local,real-provisioning-target
make test-module MODULE=e2e_real_provisioning_reapply ACTIVE_PROFILES=local,real-provisioning-target
```

- `e2e_vm_qualification` (observation 2): two CPU-only guests bought through
  `market buy` on the target's VM host, the first guest's heartbeat across the
  second's create and teardown, host diagnostics before, during and after, and
  both leases ended by back-dating and a stepped watchdog cycle.
- `e2e_bare_metal_qualification` (observations 4 and 5): the normal cycle,
  then a successor whose reclaim refuses a planted foreign descendant until
  fixture-only repair, each ended by `market bare-metal teardown`. Without the
  bare-metal host's `cleanup_qualification` its working-data stages and the
  refusal cycle skip, and both observations are unproven.
- `e2e_real_provisioning_reapply` (observation 6): both hosts' registrations
  reapplied and a publication cycle stepped, nothing duplicated or changed. It
  needs the `BARE_METAL_LANE` settings beside the VM lane's.

Each module logs every observation's outcome at its end: made, failed, or
unproven naming what a skipped stage lacked, such as the target's
`management_unit` or relay `admission_log`. A failure after the buyer approved a
payment refunds it as the seller and ends the delivered guest or host through
its lease, and names by negotiation and transaction whatever it cannot.

The installed buyer scenario `e2e_bare_metal_deal` keeps its separate
`BARE_METAL` configuration and operator-supplied buyer key and known-hosts file.
It uses the same SSH helper in strict pinned mode, with one fresh attempt per
access observation. Only public-key authentication refusal proves revocation; a
transport or host-key failure fails the observation. It remains outside default
lanes and skips when its configuration is absent.

### Marketplace signing and controlled EVM settlement

Real provisioning modules use the existing controlled Anvil/Alkahest settlement.
Marketplace signing is independent of that wallet. In an external
`CONFIG_DIRECTORY` profile, VM settings accept `buyer.marketplace_scheme`
(default `eip191`) and the existing `buyer.marketplace_credential`;
`seller.marketplace_scheme` (default `eip191`) and
`seller.marketplace_credential` (fallback `seller.private_key`); and
`registry.authority_scheme` (default `eip191`). The second registry uses the same
`authority_scheme` field. Publisher pins use the seller marketplace principal,
while administrator and service credentials keep their separate roles.
`buyer.private_key`, `buyer.wallet_address` and `buyer.chain_rpc_url` remain EVM
wallet/chain inputs.

Bare-metal lane marketplace signing retains `buyer_scheme` and
`buyer_credential`. Set `bare_metal_lane.buyer_wallet_private_key` for its separate
EVM key; existing local profiles fall back to `buyer_credential`. Its
`buyer_wallet_address` and `buyer_rpc_url` are unchanged. Ed25519 credentials use
the identity kit's canonical unpadded base64url encoding. Keep secret values in
private external configuration, never in `REAL_PROVISIONING_TARGET` or committed
profiles. Existing local/mock profiles retain their current defaults. These are
test fixture inputs, not changes to the public buyer CLI or service trust.

<a id="real-vm-provisioning"></a>

### Real provisioning target and VM lane

`e2e_vm_real_provisioning` runs the canonical compute deal against a real KVM
host: the create and teardown jobs run the real playbooks, the scenario
connects to the delivered VM over SSH with a key it generates for the run, and
it confirms the VM is gone from the host once the lease ends. It is in no lane,
because the pipeline has no host to provision on; it runs from an operator's
machine against a deployed stack whose provisioning service is outside its
mock profile and holds the key it reaches the host with. The host is prepared
beforehand with the host-kit's `vm-setup.yaml`, and needs hardware
virtualization; it needs no GPU.

1. Copy the example target to its real name beside it and fill it in for the
   host, or render that file from your environment's own records:

   ```bash
   cp config/config-real-provisioning-target.yml.example config/config-real-provisioning-target.yml
   ```

   `config-real-provisioning-target.yml` is ignored and never committed. Its
   `REAL_PROVISIONING_TARGET` version 2 section holds at most one host per
   domain. A VM host names its identifier, `connection` (service address, user,
   port and key path), `access`, sellable `capacity`, and a `listing_shape` that
   fits twice within capacity. Direct access states `public_host`; relay access
   states only `relay_id`. Bare-metal hosts additionally state `physical_host_id`
   and their verified `ssh_host_public_key`, and have no VM listing shape.
   A VM target may state `resource_id` to select its scenario declaration;
   otherwise it uses `compute-e2e-real-001`. Listing adoption, registration,
   purchase checks, capacity reuse and reapply use that same identifier.
   Each real VM purchase explicitly refreshes its site projections before
   discovery, including when the scenario holds background lifecycle loops.
   Its CLI discovers by region, so the real purchase refuses before payment
   unless that query selects its listing alone. Keep unrelated listings paused.
   A bare-metal target may also state `pool_id` and `resource_id` to reconcile
   its existing pool and declaration. Omitted, the scenarios use
   `bare-metal-e2e-real-pool` and `bare-metal-e2e-real-001`. These identifiers
   apply to the real deal, purchase, cleanup qualification and reapply alike;
   a different declaration for that host or physical machine is still refused.
   The lane reads a relay before any mutation and requires it enabled, with
   a configured token and active grant key; it never creates the relay. The
   target carries no private key or relay credential. Version 1 is refused
   with conversion instructions; a missing or misspelled field fails by name.
2. Configure marketplace identities and the separate controlled Anvil wallet as
   described above. External deployments must trust the configured scheme-tagged
   principals; do not copy local development secrets onto an exposed service.
   Forward the stack's services to the ports the `local` profile names
   (`config/config-local.yml`): the storefront, the registry, the provisioning
   service, and the chain. The stack must trust the `local` profile's
   principals.
3. Run the module with both profiles:

   ```bash
   make test-module MODULE=e2e_vm_real_provisioning ACTIVE_PROFILES=local,real-provisioning-target
   ```

Without the `real-provisioning-target` profile, or with its file missing, every stage
skips naming the profile and file, and nothing is written to the stack. A run
that fails after settlement tries cleanup for both guests through their leases,
and reports each unconfirmed removal. The first SSH session stays open across the
second guest's create and teardown, with a maximum five-second observed gap;
management connectivity is checked around each operation. The two smaller guests
prove tunnel coexistence and require no GPU.

---

### Bare-metal payment deal

The bare-metal lane includes marker `e2e_bare_metal_payment_deal`, which runs
against the lane's payments double: `make test-e2e-bare-metal` runs it with the
rest of the lane. To rerun it against the lane's running stack, select the
lane's runner profiles:

```sh
make test-buyer-machine \
  NETWORK=simple-market-bare-metal_default \
  BUYER_MODULE=e2e_bare_metal_payment_deal \
  RUNNER_PROFILES=docker,payments-lane,bare-metal-lane
```

The lane's profiles supply the shared PAYMENTS settings, SELLER_ACCOUNT among
them, plus COMPUTE_HOURLY_GROSS=1000000 and DISPUTE_WINDOW=P7D; another target
supplies them in the runner's config directory. The seller — the lane's
`domains/bare_metal/storefront/storefront.dev.toml` — enables the same payments
policy and trusts the double's service identity. SELLER_MARKETPLACE_CREDENTIAL
must resolve to the lane's pinned seller scheme; the purchase buyer is a separate
wallet-free Ed25519 profile. A run with no payments target configured reports a
named blocked payments prerequisite, not success.

The scenario runs the shared buyer-purchase stages
(`tests/e2e/roles/helpers/buyer_purchase_stages.py`) and the canonical compute
deal's stages from fulfillment onwards, inserting its own. Its supply stage
declares a distinct backed whole host and its publication stage publishes only a
USD 1.00/hour option for a one-hour term. The registry recommends the lane's
mediation double, which the option names as its dispute authority; the buyer's
teardown files a delivery-end case with it, and, where the run names a mediation
target, the scenario asserts the case accepted with every part held — with no
rule installed, nothing is ruled — and does not read the filing as refund
evidence. The option includes a
300-second delivery deadline, a 15-day dispute window (PAYMENTS.DISPUTE_WINDOW_SECONDS's
default) and an unbounded case hold. The dispute window covers the delivery deadline
plus the authority's minimum filing window; the payment `window=P7D` is a separate input.

The installed `market bare-metal buy` emits
`run_started → negotiation_completed(status=agreed) → payment_approved →
run_ended(status=agreed)`. It commits through `BuyerLifecycle` after approval.
The scenario checks the transaction against its Agreement and receipt and the
payer's balance drop against its debit, then reads readiness through the
storefront's settle wait on the negotiation. Delivery reads use that purchase's
signer and fulfillment transport. Re-drive recovers the original run's retained
profile and repeats canonical lifecycle `commit`, keeping both transaction and
fulfillment unchanged; there is no bare-metal settle command. The buyer's
`market bare-metal teardown` then ends delivery and starts mock reclaim, after
which the seller's refund reverses the still-held once payment, and the site's
capacity release is proven separately. Unless the last stage recorded the deal
ended, the module's cleanup first opens any mock gate still closed, then finds
the purchase in the buyer's run log; when
the log records the payment approved, it refunds the payment (a repeat refund
returns the same result), then reads the purchase's fulfillment and releases a
host it finds. A host it cannot read or tear down — a delivery that stopped, or
is still starting, before its fulfillment was recorded, say — is reported as a
failed step for the provisioning service to recover. A refund the seller
refuses because it has not yet verified the payment, or because the payments
service or the storefront is unavailable, is retried for 60 seconds, as is a
refusal that turns out final; a refund that still fails, retried or not, fails
the run naming the negotiation and transaction, for an operator to reverse any
hold that remains and release any host the seller delivers for it afterwards.
Cleanup then removes its mock rules, drains, and removes its pool override, and
resumes the loops it paused last. Each step is attempted even after an earlier
one fails, and the failures are reported together; removing a mock rule that is
already gone is not a failure.
This is mock grant/reclaim evidence, not SSH qualification. The canonical
Alkahest mock-deal scenario remains selected unchanged.

## CI/CD

The repository's [`E2E` workflow](../.github/workflows/e2e.yml) runs the three
lanes, each as its own job, nightly and on demand. See "System Integration Tests"
in [`TESTING.md`](../docs/development/TESTING.md#4-system-integration-tests-end-to-end)
for dispatching it on a branch and fetching its logs.

---

## Adding tests

1. Create `tests/test_<feature>.py`
2. Import fixtures from `conftest.py` (`w3`, `registry_settings`, etc.)
3. Mark tests with `@pytest.mark.contracts`, `@pytest.mark.wallets`, or add a
   new marker in `pyproject.toml` under `[tool.pytest.ini_options] markers`
4. Add helper utilities to `tests/helpers/` if they are reusable

```python
# tests/test_example.py
import pytest

@pytest.mark.contracts
def test_my_new_check(w3, registry_settings):
    address = registry_settings["identity_address"]
    # ... your assertions
```
