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
| 1 | `ARKHAI_*` environment variables, including those the project's `.env` file supplies (a variable already set wins over the file's) | `ARKHAI_RPC__URL=https://…` |
| 2 | `config-<profile>.yml` files (secrets injected here) |
| 3 | `config.yml` (in `CONFIG_DIRECTORY`) | base env config |
| 4 | `.secrets.toml` | local secrets (gitignored) |
| 5 | `settings.toml` | project defaults / schema |

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
`e2e_vm_payment_deal`, `e2e_vm_payment_purchase`, `e2e_vm_recurring_purchase`,
`e2e_bare_metal_recurring_purchase`, `e2e_vm_rate_servicing`,
`e2e_bare_metal_rate_servicing`, `e2e_vm_rate_watchdog`,
`e2e_bare_metal_rate_watchdog`, `e2e_vm_rate_dispute` and the live verification
modules `e2e_vm_live_rate_servicing` and `e2e_vm_live_dispute`, and the qualification modules
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
that token, CA_BUNDLE_PATH the bundle it is trusted under, PROXY_URL, where its
origin resolves only inside its topology, the HTTP proxy the run reaches it
through (see "Live verification"), and, for a lane's own target, LANE_OWNED and
CONTROL_TOKEN. With SERVICE_URL set, the purchase drivers
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
marketplace seed — and `config/config-<lane>-lane.yml` the payments settings
that differ, the seller's marketplace credential and, for bare metal, its
whole-host fixture's COMPUTE_HOURLY_GROSS and DISPUTE_WINDOW, beside the lane's
`lane_time` section, which names the run's time mode and every party the lane
runs for the lane-time fixture (`tests/e2e/roles/helpers/lane_time.py`). Dynaconf
merges the `payments` section key by key.
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

To run the lanes in GitHub Actions, push the current branch and run `make run-e2e`
from the repository's root with an authenticated `gh` CLI on PATH, then run `make
fetch-e2e-logs` there to wait for
the run and download its diagnostics. When the commit already has a run, pass the
newest run ID seen before dispatching as `E2E_AFTER_RUN`, so the earlier run is not
taken while the new one is still unlisted. How the fetch selects its run, and where
the logs land, is
[`TESTING.md`'s "System Integration Tests"](../docs/development/TESTING.md#4-system-integration-tests-end-to-end).

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
| `e2e_vm_dispute_hold_passed` | `test_hold_passed.py` | after the deal ends, lane time is set past the part's terms end and then its release instant; the snapshot shows the payout, and the buyer's filing reports the part `not_held`, `paid_out`, and is dismissed with nothing held |

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
decision is repeated. The hold-passed scenario sets lane time only after its
deal has ended.

The modules run in any order: each removes its rules through `lane_double_rules`.
Lane time only moves forward and no module returns it, so a module after the
hold-passed one starts days later. A deal still delivering when its scenario's stages end is ended by the
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

### Recurring purchases

`e2e_vm_recurring_purchase` runs in the VM lane and
`e2e_bare_metal_recurring_purchase` in the bare-metal lane, each as lane-double
evidence. Each lane's storefront configuration
(`domains/vms/storefront/storefront.bob.lane.toml`,
`domains/bare_metal/storefront/storefront.dev.toml`) declares rate servicing for
`charged` and `returned`, a lane fixture no shipped configuration carries, so the
seller publishes a recurring on-demand option: VM's on a listing of the
scenario's own resource, bare metal's through a pool override. A default buyer
with no wallet buys it through the shipped `market buy` or `market bare-metal
buy`, which approves the mandate and commits, and the storefront delivers it.

The scenarios run the shared buyer-purchase stages, the canonical deal's
delivery and teardown stages with their mock gates, and the recurring stages
(`tests/e2e/roles/helpers/recurring_purchase_stages.py`), reaching every
instant by setting lane time, never by waiting: the mandate is one rate part
charging one period's price and the payer's balance fell by the receipt's
reserve; the fulfillment converges, lane time is brought to the Agreement's
start (both buyers ask for a deal starting at acceptance, so it already holds
it) and `delivery-recovery` steps once, and the settlement reads ready; once
the storefront's servicing has been stepped, the payments double records the
rate part started, and one start event, no earlier than the whole second of the
site's activation of the lease, and the storefront's lifecycle read shows the
deal active; the buy's stderr showed the per-period price, setup charge,
initial reserve and maximum end (that they precede the settlement stage that
approves is proved by each buyer's own tests, not here); with lane time a
minute into the first period, the buyer's own `end` stops the payment inside
the started period, which it charges, and the storefront records the payer's
end with no filing; once a servicing step has carried out that end at the site
(bare metal's hint already has, VM's servicing cycle does), the lease is
released through the shared teardown stages; the payer's balance is down by
exactly one period's price; and after one more servicing step the seller's
list, read through the typed seller lifecycle client, shows the deal `ended`
with no outstanding code. The seller's refund refuses a rate deal, so a failed
run's cleanup ends an approved deal by the buyer's own `end` too. Neither waits
for the delivery deadline.

### Rate servicing rows

`e2e_vm_rate_servicing` runs in the VM lane and `e2e_bare_metal_rate_servicing`
in the bare-metal lane, three modules each under
`tests/e2e/roles/scenarios/<domain>/rate_servicing/`, each its own deal and
lane-double evidence. Each shares the recurring purchase's stages through its
accepted money, under a shipped preset with a default buyer and the lane's
`[charged, returned]` declaration, then ends its deal one way
(`tests/e2e/roles/helpers/rate_servicing_stages.py`):

- funds running out: the deal is paid from the payments double's second payer
  (`PAYMENTS.RATE_PAYER_ACCOUNT`), funded through the double's funding control
  with three periods' price, one beyond the two its rate part holds reserved
  once started; the double's reservation control reserves the part through the
  Agreement's end, which that balance stops one period further, and lane time is
  set to that funded boundary, where the double records a `terms` stop; the
  storefront records that end there with no filing and tears the deal down, and
  the buyer's `delivery` read says a top-up cannot revive it;
- a spot seller's preemption: the storefront's administrator submits the
  seller's notice through the typed seller lifecycle client, the call `deals
  preempt` makes; the double holds it as a pending stop until lane time reaches
  the request's time plus the 120-second notice, when the storefront records the
  seller's stop at that instant with no filing and tears the deal down, and the
  payer is returned what the deal had not earned. That instant falls inside the
  part's first reservation, so the row reserves nothing further;
- the maximum term: the double's reservation control reserves the part through
  the Agreement's end, which the shared buyer's balance pays for, and lane time
  is set there; the part ends `returned`, the storefront records the term end
  with no filing and tears the deal down, and the buyer's read names no funding
  stop.

The payments service keeps a started rate part reserved ahead by its own
scheduler; the double reserves further only when its reservation control is
called, and a read never reserves, so a row setting lane time past the part's
first reservation first calls the control, in a stage of its own that only these
rows declare, failing on any refusal. No storefront route reads how it
classified an end, so the rows observe what follows from the classification —
the end's cause and instant, no filing, the teardown — and the buyer's read,
which classifies with the same compute-family classifier; the storefront's
classification itself is each storefront's application evidence. Off a Compose
lane's injected lane time and doubles the rows are blocked.

### The buyer's watchdog against a delivered deal

`e2e_vm_rate_watchdog` runs in the VM lane and `e2e_bare_metal_rate_watchdog` in
the bare-metal lane, one module each under
`tests/e2e/roles/scenarios/<domain>/rate_watchdog/`, on a deal of its own and
lane-double evidence. The buyer's `buy --watchdog --watchdog-interval 1
--watchdog-threshold 2` of a recurring on-demand option, its resume `buy --from`
and its `delivery` read run in the harness's process rather than as
subprocesses, through the `market` app's own entry under Typer's `CliRunner`
(`tests/e2e/roles/helpers/in_process_buyer.py`): mock provisioning's endpoint
reaches no machine and the watchdog paces its probes on a monotonic clock no
lane control moves, so the harness replaces the domain CLI's `watchdog_probe`
with a probe it programs, reachable or not, recording the endpoint it was built
for, and its `wait_clock` with a clock whose sleeps park at a gate the stage
releases one interval at a time, its `now` lane time. Every wait `buy` makes —
its commit, its wait for the deal, the watchdog's — therefore moves only when a
stage releases it. The buyer's configuration names no `[time]` table, so it
reads the harness's lane-time source; its environment is set for the module and
restored after; and a read runs only while `buy` is parked at the gate.

Each module shares the recurring purchase's stages through the rate part's
start, `buy` parked at the gate while delivery is stepped, then runs the cases
in the one order a deal allows (`tests/e2e/roles/helpers/rate_watchdog_stages.py`):
the wait released, the same `buy` enters its watchdog from available, its probe
built for the endpoint the storefront disclosed, and the read shows `monitored`,
again once lane time is a minute into the first period; an interrupt at the gate
ends the command, and once lane time passes its last probe by one interval, the
probe timeout and the reader's grace the read shows `unmonitored`, with no stop
sent; `buy --from` reads `monitored` again; then, the storefront's loops held for
the module, the probe answers unreachable for the two stepped intervals of the
threshold, the watchdog sends one payer stop and hint, the payments double's
events for the transaction are the storefront's `start` and the payer's `stop`,
`buy` ends `stopped`, the storefront records the payer's end with no filing, and
a `deal-servicing` step begins the teardown the shared teardown stages complete.
Off a Compose lane's injected lane time and doubles the modules are blocked.

### Rate-deal disputes

`e2e_vm_rate_dispute` runs in the VM lane: two modules under
`tests/e2e/roles/scenarios/vms/rate_dispute/`, each on a rate deal of its own and
lane-double evidence. Each shares the recurring purchase's stages through its
accepted money — a default buyer's `market buy` of a recurring on-demand option
under the lane's `[charged, returned]` declaration, delivered — then sets lane
time a minute into the second period, so the first period's earnings are held,
and files a case the authority rules with a stop
(`tests/e2e/roles/scenarios/vms/rate_dispute/stages.py`):

| Module | What it proves |
|---|---|
| `test_seller_filing.py` | the storefront's administrator ends delivery as a failure through the storefront client's interruption, and the storefront records the end and files `delivery_end` as the payee; a mediation-double rule, held at its gate, rules the filing as the dispute authority documents a mechanical ruling — basis `payee_filed`, a delivery end, a `stop` returning its period, a `reverse` of the earnings since the end and the Agreement's premature-stop `penalty` — and closes the case. Lane time passes the second period's end before the rule resumes, so the part earns after the end; the double then stops the part as the authority, a stop now since its time passed, reverses that period and takes the penalty from what the part still holds. The storefront records the ruling's end with no filing beyond its own |
| `test_buyer_contested_case.py` | the buyer files `delivery_end` through the mediation kit's dispute adapter in the harness (`file_as_buyer`), the storefront's respondent discovery contests the case with an append, and an operator decision through the typed control client rules a `stop` returning its period and a `reverse` of the held first period, closing the case. The storefront records the ruled end with no filing |

The seller's filing needs the part funded past its first reservation, so it
calls the payments double's reservation control first, as the rate rows do. Each
module reads the dispute authority's signed record as the buyer, through the
mediation kit's public client (`read_record`), and the payments snapshot, and
asserts on both through its row's assertion in
`tests/e2e/roles/helpers/producer_assertions.py`, which names the fields it
compares exactly, by relation, or not at all; the payment rows' and the
recurring purchase's endings assert through that module's payment assertions the
same way. Each then completes the teardown through the shared teardown stages,
checks the payer got back everything the part did not keep for the seller, and,
once the case is closed, reads the seller's list showing the deal `ended` with no
open case or extension. No stage steps the storefront's servicing while a ruling
waits at its gate, and each module removes its rules through
`lane_double_rules`. Off a Compose lane's injected lane time and doubles the
modules are blocked.

### Live verification

The live verification scenarios compare a hosted authority's outputs with what
the lanes' doubles emit. Each extends a lane row in the live verification form.
A payment ending runs its lane twin's shared stages against the run's external
payments target, on wall time, until the input its lane twin gives the payments
double; gives the live authority that input through the same client code; polls
the authority's signed transaction snapshot until the output appears, bounded;
and asserts on it through the lane twin's shared assertion in
`tests/e2e/roles/helpers/producer_assertions.py`, which names the fields it
compares exactly, by relation, or not at all. A different output fails the
observation. No stage runs after it: what the storefront does with the output is
the lane twin's evidence. Where the lane twin moves lane time or calls a
double's control, the live scenario waits for the instant the authority recorded
(a pending stop's, a funded boundary) or the Agreement fixes, bounded by the
term, and leaves reserving to the authority's own scheduler.

The modules are in no lane. A deployment prepares a topology meeting the
requirements below, runs them through `test-module`, and records its own
sanitized summary of the outcome; raw logs and records stay in its storage.
Each module checks its prerequisites at its first fixtures, before its holds and
anything it buys: against no external payments target, against a lane's own
double (LANE_OWNED), with no provenance to label its evidence, or with a
topology that misses a requirement below that the harness can read — test mode,
mock provisioning, a payer's balance — it is a blocked skip naming what is
missing, and with a setting the run owes missing it fails naming the setting.
A requirement only the deal itself shows is checked where the deal shows it,
still a blocked skip naming it: the dispute authority the bought Agreement pins,
and the storefront's dispute credential, which the seller's filing reveals and
the storefront's lifecycle read of the deal reports before the contested case's
contest.
Only the session's fixtures and the VM lane's idempotent host registration, an
autouse fixture, set up before them. Each module's first own stage logs the
live-evidence label with its provenance, every stage logs the identifiers it
reads, and the module logs its observation's outcome at its end: made, failed,
or unproven naming what a skipped stage lacked
(`tests/e2e/roles/helpers/qualification.py`).

```bash
make test-module MODULE=e2e_vm_live_rate_servicing ACTIVE_PROFILES=<the topology's profiles>
```

`e2e_vm_live_rate_servicing`, four modules under
`tests/e2e/roles/scenarios/vms/live/`, each on a deal of its own:

| Module | What it proves | Input to the payments authority | Output compared |
|---|---|---|---|
| `test_buyer_stop.py` | the buyer's stop, twin of `e2e_vm_recurring_purchase`'s buyer end | the buyer's own `market end`, a payer stop with no notice, sent no earlier than a minute after the Agreement's start, as its twin's is | the part stopped with cause `payer` and `charged`, the started periods settled, the rest refunded (`assert_payer_stop`) |
| `test_funds_exhausted.py` | funds running out, twin of the rate servicing row | none beyond the purchase: the rate payer's balance, three periods' price | a `terms` stop at the funded boundary the snapshot last reported, three periods settled (`assert_funds_exhausted`) |
| `test_preemption.py` | a spot seller's preemption, twin of the rate servicing row | the seller's notice through the typed seller lifecycle client, as `deals preempt` sends it | a pending `payee` stop due the notice after its receipt (`assert_payee_stop_pending`), then the final stop then, `returned`, the unstarted remainder refunded (`assert_payee_stop`) |
| `test_term_end.py` | the term end, twin of the maximum-term row | none beyond the purchase: the Agreement's end | a `terms` stop at the Agreement's end, `returned` (`assert_term_end`) |

What a topology provides for them, naming no deployment:

- **Provisioning: mock.** They prove the payments authority, not delivery, so
  this repository's VM storefront, provisioning service and registry run with
  provisioning in its mock mode, its test controls, fulfillment convergence and
  lease watchdog reachable as in a lane, and the storefront's loops pausable
  through its administrator. The storefront settles in `arkhai.payments.v1`
  against the payments target and declares rate servicing for `charged` and
  `returned` with no setup charge, as the VM chart's production example does;
  the buyer's registry recommends a dispute authority whose advertised minimum
  filing window PAYMENTS.DISPUTE_WINDOW_SECONDS covers beside the delivery
  deadline, as every compute payments option requires. The site holds no
  reservation but the run's: a module's cleanup releases every reservation the
  site holds. No rate servicing module files a case.
- **Payments: Arkhai payments in test mode, executing rate parts.** The target
  starts a rate part, keeps it reserved ahead by its own scheduler as far as the
  payer's balance pays, holds a payee's stop with notice as pending until it is
  due, and stops a part by its terms at its funded boundary and at its mandate's
  end. LIVEMODE is false.
- **Accounts and starting balances.** The run's buyer account
  (PAYMENTS.BUYER_ACCOUNT, with BUYER_API_KEY) holds at least one term's price
  at the run's period as each of the buyer's stop, the preemption and the term
  end starts, which each module reads before it buys — less is a blocked skip
  naming this requirement — and nothing else spends from it during a run. The
  seller account
  (PAYMENTS.SELLER_ACCOUNT) is the storefront's. Funds running out pays from a
  rate payer (PAYMENTS.RATE_PAYER_ACCOUNT, with RATE_PAYER_API_KEY) holding
  exactly three periods' price at the run's period — 49 998 USD/6 base units at
  a one-minute period, 750 000 at the lanes' fifteen minutes — and nothing else;
  any other balance makes that module a blocked skip naming this requirement,
  before it buys anything, and a run naming no rate payer or key fails that
  module naming the setting. No module funds an account.
- **Run settings.** The `PAYMENTS` section as every payment scenario reads it,
  with LANE_OWNED unset. The `LIVE` section (environment prefix `ARKHAI_LIVE__`,
  `tests/e2e/roles/helpers/live_verification.py`): PERIOD_SECONDS, the option's
  period (900); PAYEE_NOTICE_SECONDS, the spot seller's notice (120);
  MAXIMUM_TERM_SECONDS, the Agreement's duration the buyer asks for, at most the
  listing's hour (3600); POLL_BOUND_SECONDS, how long an output is polled for
  once due (120); and the provenance the evidence is labelled with,
  SOURCE_REVISION, TARGET_ALIAS and PAYMENTS_REVISION, without which each module
  is a blocked skip naming the setting. The period, notice and term set how long
  a run takes on wall time, the term end waiting out the whole term, so a
  deployment states short ones, within what a deal can hold: the harness refuses
  a period longer than the term and a notice no shorter than it, and the market
  refuses the rest — publication an option whose five-minute approval window,
  five-minute delivery deadline and period do not fit in the listing's hour, and
  negotiation a term shorter than the time to approval's expiry plus the
  delivery deadline and a period. Funds running out fails naming the term when
  it lasts at most its three periods, since the term end would come first,
  and the preemption fails naming the notice when it is no shorter than the term
  left once the deal is delivered.
- **What the caller owes between runs.** Resetting the rate payer to exactly
  three periods' price, which a run leaves empty, and topping up the buyer. A
  module stops only the deal its input stops; funds running out and the term end
  leave the authority to stop theirs, and a module's cleanup ends an approved
  deal no input stopped by the buyer's own `end`. Each module releases the
  site's reserved resources and removes its mock gates' rules; once its holds are
  released the storefront services the stopped deals and tears them down on its
  own.

```bash
make test-module MODULE=e2e_vm_live_dispute ACTIVE_PROFILES=<the topology's profiles>
```

`e2e_vm_live_dispute`, two modules under `tests/e2e/roles/scenarios/vms/live/`,
each on a deal of its own, extend `e2e_vm_rate_dispute`'s rows the same way.
Each runs the recurring purchase's shared stages, waits until the payments
authority holds the first period's earnings, and files as its lane twin does,
through the same client code. It then polls the hosted dispute authority's signed record,
read as the buyer through the mediation kit's public client, until the case is
closed, within POLL_BOUND_SECONDS, and asserts on the record and the payments
snapshot through its lane twin's dispute assertion. No module calls an operator
endpoint of the authority: a ruling is the authority's own. The wait for the
first period's earnings is a poll of the payments snapshot, bounded by the time
left in the first period and POLL_BOUND_SECONDS after it.

| Module | What it proves | Input to the dispute authority | Output compared |
|---|---|---|---|
| `test_seller_filing.py` | the seller's filing, twin of the rate-dispute row | the storefront's own `delivery_end` filing as the payee, made when its administrator ends the delivery as a failure through the storefront client's interruption | the authority's mechanical ruling: the part protected by an extension, basis `payee_filed`, the delivery end the one the storefront claimed, an authority stop returning its period, a reversal of the earnings since the end, the Agreement's premature-stop penalty capped at what the part held, the extension lifted and the case closed (`assert_payee_filing_ruled`) |
| `test_buyer_contested_case.py` | the buyer's contested case, twin of the rate-dispute row | the buyer's `delivery_end` filing through the mediation kit's dispute adapter in the harness (`file_as_buyer`), then the storefront's contest, an append its respondent discovery makes in one servicing step | the ruling the topology's policy makes: the part protected, the payee's answer before the ruling, basis `operator`, an authority stop returning its period and a reversal payments applied as ruled, the extension lifted and the case closed; the ruled delivery end and the reverse amount are the policy's and not compared (`assert_contested_case_ruled`) |

The contested case makes three observations: the buyer's filing, the
storefront's contest and the policy's ruling. With no ruling of the case once
POLL_BOUND_SECONDS has passed, its last stage is a blocked skip naming the
ruling-policy requirement below, so the ruling is unproven while the filing and
the contest stand; a ruling made with the case still open at the bound, or any
other ruling, fails it. The seller's filing makes one observation, which an
authority leaving the filing unruled at the bound fails, since it documents the
mechanical ruling.

What a topology provides for them, beside what the rate servicing modules need
above, naming no deployment:

- **Provisioning: mock**, as above. The storefront also holds a dispute
  credential for the dispute authority, which it files as the payee and answers
  the respondent listing with; a deployment proves it before a run with the
  storefront's own `check-mediation --origin <the authority's origin>` in the
  storefront's process. The seller's filing reads the storefront's refusal of a
  filing for want of one, and the contested case reads the storefront's
  lifecycle read of the deal before its contest, whose authority outcome names
  the missing credential; either is a blocked skip naming this requirement, the
  contested case's leaving the contest and the ruling unproven while the
  buyer's filing stands. The
  buyer's registry recommends that authority, so the Agreement pins it: an
  Agreement pinning another is a blocked skip naming both, once the deal is
  bought. Each module files one case.
- **Dispute: a hosted mediation authority serving `arkhai.mediation.v1`**
  against the payments target in test mode, so its effects move only test-mode
  money — filing with each part's protection by an extension at the payments
  target, appends, the respondent listing, and signed record reads by either
  party — applying a ruling's effects at that payments target before it records
  the case closed. The seller's filing compares the mechanical ruling the
  authority documents for a payee's `delivery_end` — a delivery end at the
  claimed instant, a `stop` returning its period, a `reverse` of the earnings
  since the end and the premature-stop penalty — and an authority that does not
  make it within POLL_BOUND_SECONDS of the filing fails the observation, as a
  different ruling does: that output is the authority's own, not the
  topology's.
- **Ruling policy, for the buyer's contested case.** A buyer's `delivery_end`
  filing that the storefront contests goes to the authority's operators. The
  topology applies a policy standing in for that person's decision: once the
  payee has answered, once, it rules the case as an operator, basis
  `operator`, with exactly these effects in this order — a delivery end, a
  `stop` of the part returning its period, and a `reverse` of the part of an
  amount it chooses — applies them and closes the case as ruled, within
  POLL_BOUND_SECONDS of the contest. Without it the ruling is unproven; a
  ruling with other effects, another order or another basis fails it.
- **Accounts and starting balances.** The buyer account holds at least one
  term's price at the run's period as each module starts, as above. MEDIATION's
  ACCOUNT and RECORD_KEY are the authority's identity, the one the buyer's
  registry recommends; BUYER_API_KEY is the buyer's token at it, which the
  buyer's filing and both modules' record reads use.
- **Run settings.** The `PAYMENTS` and `LIVE` sections as above, with
  POLL_BOUND_SECONDS covering the authority's or the policy's time to rule; the
  `MEDIATION` section (`tests/e2e/roles/helpers/mediation.py`) naming the hosted
  authority, with LANE_OWNED unset — a lane-owned target is a blocked skip
  naming it — and no CONTROL_TOKEN. Where the authority's origin resolves only
  inside the topology, PROXY_URL names an HTTP proxy the run reaches, such as a
  forward to one in the topology: the harness reaches the origin through it, and
  the buyer processes it starts receive it as their HTTPS_PROXY with loopback
  excluded, so every HTTPS request they make outside loopback goes through it.
  SERVICE_URL stays the origin the Agreement pins, and its certificate is
  verified against it, under CA_BUNDLE_PATH when one is set. LIVE.MEDIATION_REVISION states
  the mediation authority's revision identifier, beside the other provenance,
  without which each module is a blocked skip naming the setting. A missing
  BUYER_API_KEY fails each module naming it.
- **What the caller owes between runs.** Topping up the buyer, and closing a
  case a module left open: the contested case's, awaiting an operator, when no
  policy rules it, and the seller's filing's when the authority did not rule it.
  The contested case's cleanup ends a deal no ruling stopped by the buyer's own
  `end`; the seller's filing leaves its deal to the authority's ruling. Each
  module releases the site's reserved resources and removes its mock gates'
  rules, as above.

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
listing states the coverage its storefront's own configuration gives. Set the VM
listing's delivery allowance, `PAYMENTS.VM_DELIVERY_DEADLINE_SECONDS`, before the
offer is published, with `PAYMENTS.DISPUTE_WINDOW_SECONDS` covering it plus the
authority's minimum filing window. Run each through `test-module`, observation 6
after the other two on the same stack:

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
  fixture-only repair, each ended by `market bare-metal end`. Without the
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
`market bare-metal end` then ends delivery and starts mock reclaim, after
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
lanes, each as its own job, nightly and on demand. [End-to-end lanes](#end-to-end-lanes)
gives dispatching it on a branch and fetching its logs.

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
