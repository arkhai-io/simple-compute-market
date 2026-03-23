# Buyer Quickstart

This is the buyer-facing path for purchasing compute from a live production
environment with the smallest possible local surface.

The buyer uses one wrapper entrypoint:

- `scripts/run_human_buyer_purchase.py`

Who this is for:

- a human buyer purchasing compute from a live production environment
- an agent or service that needs one stable buyer-facing wrapper and a
  structured artifact

The wrapper discovers an open live offer, creates the buyer order, waits for
provisioning, and writes a structured artifact with at least:

- `order_id`
- `job_id`
- `vm_target`

## This Path Assumes

- a marketplace operator has already deployed a live registry, buyer agent, and
  provisioning service
- you control a buyer private key that the marketplace accepts for purchases
- you have been given the buyer-facing request URL, canonical auth URL, and
  provisioning URL for that marketplace

## How To Get These Values

- `BUYER_PRIVATE_KEY`:
  - use your own buyer wallet key
  - if you are joining an operator-managed marketplace, do not ask for a seller
    or platform key; this should stay buyer-owned
- `--registry-url`:
  - get the public registry URL from the marketplace operator or published
    marketplace onboarding docs
- `--buyer-agent-url`:
  - use the buyer-facing request URL that the marketplace exposes to buyers
- `--buyer-auth-url`:
  - use the buyer agent's canonical signing URL
  - if the operator gives you only one public URL and signatures are verified
    against that same URL, this may match `--buyer-agent-url`
- `--provisioning-url`:
  - get the public provisioning API URL from the marketplace operator

If you do not yet have those marketplace-specific values, stop here and ask the
marketplace operator for the buyer onboarding bundle before trying the purchase
wrapper.

## Required Inputs

- `BUYER_PRIVATE_KEY` set in the environment, or pass `--buyer-private-key-env`
- `--registry-url`
- `--buyer-agent-url`
- `--buyer-auth-url`
- `--provisioning-url`

Optional selectors:

- `--order-id`
- `--gpu-model`
- `--region`
- `--max-price`

## Repo Checkout Invocation

```bash
export BUYER_PRIVATE_KEY=0x...

python scripts/run_human_buyer_purchase.py \
  --registry-url http://127.0.0.1:28080 \
  --buyer-agent-url http://127.0.0.1:28001 \
  --buyer-auth-url http://10.243.0.117:8000 \
  --provisioning-url http://127.0.0.1:28081 \
  --buyer-private-key-env BUYER_PRIVATE_KEY
```

## Installed Invocation

If you installed the bundle with [CLI Installer](../../cli/INSTALLER.md), the
same wrapper is available from the default install root:

```bash
export BUYER_PRIVATE_KEY=0x...

python ~/.market/scripts/run_human_buyer_purchase.py \
  --registry-url http://127.0.0.1:28080 \
  --buyer-agent-url http://127.0.0.1:28001 \
  --buyer-auth-url http://10.243.0.117:8000 \
  --provisioning-url http://127.0.0.1:28081 \
  --buyer-private-key-env BUYER_PRIVATE_KEY
```

If you installed to a different `MARKET_INSTALL_DIR`, replace `~/.market` with
that path.

If you already know the exact seller offer to match, pass `--order-id`.
Otherwise the wrapper discovers open compute offers, applies any `--gpu-model`,
`--region`, and `--max-price` filters, and chooses the cheapest matching offer.

## Output

The wrapper writes a structured buyer artifact using the shared live contracts
from `scripts/role_contracts.py`. That artifact includes:

- the selected seller order
- the created buyer `order_id`
- the provisioning `job_id`
- the provisioned `vm_target`
- the buyer `request_url` and canonical `auth_url`
- optional SSH verification output if `--ssh-private-key-path` is provided

## Success Criteria

Treat the buyer path as successful only when all of the following are true:

- a live seller offer is discovered or explicitly selected
- the buyer order is created successfully
- provisioning reaches a terminal `succeeded` state
- the artifact records the selected seller order, `order_id`, `job_id`, and
  `vm_target`

## Notes

- This quickstart is buyer-facing, not operator-facing.
- It does not assume seller-owned secrets.
- It uses the live registry and live provisioning history rather than a locally
  seeded seller sandbox.
- The current production entrypoint is the script wrapper above, not an
  installed `market buyer ...` subcommand yet.
