# Agreed evidence and early termination — final deployed qualification

Nonvisual implementer qualification for the final production code of this
branch, not independent acceptance. Tested revision:
**`87e978790aa530f1f00403fd027fc0ff9635c89f`**, after the review 19–23 repairs;
later commits are documentation-only. Earlier deployed packets predate those
repairs, so every lane below was rerun on fresh images. No screenshots apply.

## Prepared target

- Images: one fresh build of this revision's wheelhouse and every lane image
  (`dev-env`, `registry`, `storefront`, `compute-provisioning`, `e2e-tests`,
  `bare-metal-storefront`, `apicredits-service`, `apicredits-storefront`,
  `apicredits-sample-app`) under a run-specific `IMAGE_SUFFIX`, through the
  shell-local Podman shim with the [#323](https://github.com/arkhai-io/simple-compute-market/issues/323)
  proxy environment. The build reproduced [#326](https://github.com/arkhai-io/simple-compute-market/issues/326);
  its one Anvil child was stopped through the build's own process group.
- Deployments: four separate invocation-owned Compose projects, one per lane,
  each rendered from this revision's committed lane files with fresh named
  volumes, isolated networks and remapped loopback ports. No inherited
  deployment selector, stock reset or fixed lane project was used. The test
  runner mounts the e2e sources of an exact clone of this revision.
- Authorities: each invocation started its own real development payments HTTP
  service backed by Formance and Postgres and a real development mediation
  service, funded disposable development accounts through
  `/operator/test-funds`, and pinned the same receipt signer and mediation
  description for both roles. Namespace-local loopback forwarders preserve the
  loopback-only development-auth guards; the hosted VM lane's mediation account
  bridge is the one described in [Hosted VM](../aeet-vm-hosted/index.md).
- Provisioning is the committed mock executor; the Anvil chain is real local
  Anvil. Buyer, seller, administrator and site are the lanes' deterministic
  public development personas, never public-network credentials.

Each registry recommends the exact served mediation authority; sellers and
buyers opt into registry recommendations. Compute hosted options carry a
300-second delivery deadline, a 1,296,000-second dispute window and an unbounded
case hold; the API-credit option carries a 1,209,600-second dispute window and
an unbounded case hold. Payment `window=P7D` is separate throughout.

## Readiness before pytest

Every lane gated on Compose `--wait` health, payment health from the host and
from the seller and buyer namespaces, mediation health and description pin,
and an authenticated registry read of the seeded publication using
`option["settlement"]["schema"]` per
[#327](https://github.com/arkhai-io/simple-compute-market/issues/327). The VM
lanes used the committed [VM readiness gate](../vm-end-classification/readiness.py);
bare metal used a disposable drive meeting the gate in
[Bare metal](../bare-metal-lifecycle/index.md#reproduction-boundary)
(both Alkahest and dispute-bearing hosted options); the API-credit gate checked
the hosted option's adjudication against the served mediation description.
All four gates printed their ready line before any scenario started.

## Results

Inside the branch-built runner, with `ACTIVE_PROFILES=docker,payments`,
`CONFIG_DIRECTORY=/app/config` and the lane's `PAYMENTS` profile:

| Lane | Scenario module | Result | pytest time | Skips |
|---|---|---|---|---|
| Bare metal | `bare_metal/test_bare_metal_mock_deal.py` | **39 passed** | 24.03 s | 0 |
| Bare metal | `bare_metal/test_bare_metal_payment_deal.py` | **3 passed**, all four payment checkpoints | 15.40 s | 0 |
| VM typed client | `vms/test_full_deal.py` | **38 passed** | 34.25 s | 0 |
| VM buyer CLI | `vms/test_full_deal_buyer_cli.py` | **30 passed** | 41.02 s | 0 |
| Hosted VM servicing | `vms/test_vm_payment_deal.py` | **4 passed** | 10.32 s | 0 |
| API credits, dispute terms | `apicredits/test_credits_payment_deal.py` | **3 passed**, all four payment checkpoints | 7.50 s | 0 |

Whole-invocation wall times, including payments/mediation start, lane start,
readiness, scenarios and cleanup: bare metal 2m58s, VM 3m28s, hosted VM 2m02s,
API credits 1m54s. No product defect was found and no code, test or fixture
was changed for this qualification.

Payment observations (USD/6 base units) read from the real ledger:

| Phase | Bare-metal payment deal | API-credit payment deal |
|---|---|---|
| Baseline | buyer 1,000,000,000; seller no hold | buyer 1,000,000,000; seller no hold |
| Held | buyer 999,000,000; one seller part held | buyer 997,000,000; one seller part held |
| Replayed | same transaction and hold; no second debit | same transaction and hold; no second debit |
| Refunded | buyer baseline restored; no hold | buyer baseline restored; no hold |

The hosted VM stages are those listed in [Hosted VM](../aeet-vm-hosted/index.md#stages-actually-run):
verified-receipt hosted commit and delivery, same-key replay with servicing,
administrator end filing one verified case at the real mediation service with no
local remedy, and seller refund with release waiting for the capacity-return
callback. This does not claim rate-stop/funding behaviour, respondent answers,
ruling execution, a real bare-metal host or real KVM.

## Cleanup

Each invocation removed namespace forwarders and runners before their owners,
then its Compose projects, named volumes and networks, and recorded an empty
owned inventory; a final label-scoped container, network and volume inventory
is empty. No server, tunnel, browser or deployment remains. Image tags and the
disposable launcher's state are local caches, not running services. No raw log,
private launcher or runtime artifact is published here.
