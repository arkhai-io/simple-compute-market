# Isolated Canary Signoff: 2026-03-20

This record closes the isolated deployed-canary proof requirement from
`docs/clean-room-acceptance.md`.

## Captured Evidence

- isolated environment: `sms-canary-20260320-011902`
- canary runner host: `35.221.35.128`
- runner log path on the isolated host: `/home/levi/canary/last_run_3.log`
- provisioning job: `47a612d4-fc26-41a0-9aa2-e63cbb685845`
- seller order: `fc6f7eb4-7316-4826-94ef-304ac25c9b4f`
- buyer order: `6b792e1d-64b3-4ec9-8f49-1a3e64aebc0f`
- token path: `WETH`
- final canary result: `succeeded`

## Release-Gate Validation

On 2026-03-21, the preserved isolated canary log was copied to a local scratch
path and validated with:

```bash
python scripts/run_release_gate_checks.py \
  --deployed-canary-log /tmp/isolated_canary_success.log
```

That run completed successfully against the current repo state and exercised the
expanded release gates plus the full repo validation matrix.

## Operational Note

The isolated environment currently needs additional Base Sepolia ETH before the
same wallets can repeat the live canary from scratch. That does not invalidate
the preserved successful artifact above; it means reruns now require replenished
wallet balances.
