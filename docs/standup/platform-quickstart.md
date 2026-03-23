# Platform Quickstart

This is the platform-operator path for standing up, verifying, and canarying
the isolated live environment with one entrypoint instead of a manual sequence
of rollout commands.

The operator uses:

- `scripts/run_platform_standup.py`

Who this is for:

- a human platform operator driving deploy, verify, and canary steps
- a coordinating agent/service that needs a stable platform orchestration
  surface and structured artifacts

The wrapper keeps the existing repo orchestration intact by delegating to:

- `scripts/materialize_host_envs.py`
- `scripts/check_chain_profile.py`
- `scripts/rollout_live_env.py`
- `scripts/refresh_canary_agent_ids.py`
- `scripts/run_repeatable_canary.py`

## This Path Assumes

- you are already operating a marketplace environment rather than joining one
- the marketplace bootstrap inputs are prepared, including local secret bundles
  and the live canary env
- if you are starting from zero, you have already read
  [Deploy Your Own Marketplace](deploy-your-own-marketplace.md)

## Required Inputs

- `--project` and `--zone` for live rollout actions
- shared secrets in `~/.config/web3-ops`
- local overlays in `~/.config/simple-market-service`
- a writable `render_output_dir`
- a live canary env that can receive refreshed `seller_agent_id` and
  `buyer_agent_id` values

## Repo Checkout Invocation

### Deploy

```bash
python scripts/run_platform_standup.py deploy \
  --project sms-canary-project \
  --zone us-east4-c \
  --render-output-dir /tmp/sms-rendered \
  --canary-env-path ~/.config/simple-market-service/prod-canary.env
```

This deploy stage renders host envs, validates the selected chain profile,
rolls out the live targets, and refreshes the canary `seller_agent_id` and
`buyer_agent_id`.

### Verify

```bash
python scripts/run_platform_standup.py verify \
  --environment isolated-eth-sepolia \
  --render-output-dir /tmp/sms-rendered
```

This runs the repo deployment-gate checks against the rendered env bundle and
the checked-in inventory contract.

### Canary

```bash
python scripts/run_platform_standup.py canary \
  --environment isolated-eth-sepolia \
  --render-output-dir /tmp/sms-rendered \
  --artifacts-dir ./artifacts/platform
```

This delegates to `scripts/run_repeatable_canary.py` so the platform operator
and automated agents use the same production-facing canary surface.

## Output

The platform wrapper writes a shared live-contract artifact that includes:

- the action (`deploy`, `verify`, or `canary`)
- `render_output_dir`
- chain metadata
- refreshed `seller_agent_id`
- refreshed `buyer_agent_id`
- artifact paths for canary output when applicable

## Notes

- This is operator-facing, not buyer-facing.
- It keeps the live rollout contract centralized instead of introducing another
  ad hoc deployment path.
- The current production entrypoint is the script wrapper above; this is a
  repo-checkout surface today, not an installed `market platform ...`
  subcommand.
