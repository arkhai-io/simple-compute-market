# ZeroTier and FRP

This document covers the network and proxy prerequisites for the deployed
stack.

## Inputs

- a ZeroTier controller or an existing managed network
- a public FRP gateway host
- DNS for the FRP domain
- SSH access to the FRP host and any hosts that will join ZeroTier

## ZeroTier

If the network does not already exist, use:

- `infra/zerotier/create_ztnetwork.sh`
- `infra/zerotier/authorize_zt_member.sh`
- `infra/zerotier/ZeroTierSetup.MD`

Every runtime host that participates in the canary path must join the same
network:

- registry host
- provisioning host
- seller agent host
- buyer agent host
- any colocated FRP or Redis/Postgres hosts that are expected to be reachable
  over ZeroTier

Record the resulting `ZEROTIER_NETWORK` and the ZeroTier IPs assigned to each
host.

## FRP

Use `compute-provisioning-iac` to configure the FRP gateway:

```bash
cd compute-provisioning-iac/ansible
ansible-playbook -i inventory/hosts playbooks/frp/frp-server-setup.yaml \
  -e "frp_domain=<frp-domain>" \
  -e "certbot_email=<email>" \
  --limit proxy-<environment>
```

Keep the generated credentials file outside Git. The IaC role writes
`credentials/frp-server-credentials-<host>-<timestamp>.json` on the Ansible
control machine. That file contains the FRP dashboard password needed by the
async provisioning service and the canary preflight.

## Verification

Verify all of the following before deploying services:

- ZeroTier node membership is authorized for every host
- FRP host DNS resolves correctly
- the FRP dashboard credentials file exists and is readable
- any `ufw` or host firewall rules allow the traffic described in
  `compute-provisioning-iac/README.md`

Outputs from this phase:

- `ZEROTIER_NETWORK`
- FRP gateway hostname or IP
- `FRP_DOMAIN`
- `FRP_DASHBOARD_PASSWORD`
