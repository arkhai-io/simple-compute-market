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

Registry, provisioning, seller, and buyer HTTP traffic stays on ZeroTier. FRP is only used for leased VM SSH access. Do not put the registry or agent HTTP APIs behind FRP.

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

Record the public FRP values from this phase as:

- `FRP_SERVER_ADDR`
- `FRP_DOMAIN`
- `FRP_DASHBOARD_PASSWORD`

The FRP dashboard public URL is `https://frp-admin.<domain>`. The default API
user is `admin`.

```bash
export FRP_USER=admin
export FRP_PASSWORD="<dashboard-password-from-credentials-file>"
export FRP_API_URL="https://frp-admin.<domain>/api"

curl -u "${FRP_USER}:${FRP_PASSWORD}" \
  "${FRP_API_URL}/serverinfo"
```

## Verification

Verify all of the following before deploying services:

- ZeroTier node membership is authorized for every host
- FRP host DNS resolves correctly
- the FRP dashboard credentials file exists and is readable
- any `ufw` or host firewall rules allow the traffic described in
  `compute-provisioning-iac/README.md`

Run concrete network checks from the participating hosts:

```bash
sudo zerotier-cli listnetworks
ping -c 1 <peer-zerotier-ip>
curl http://<registry-zerotier-ip>:8080/health
curl http://<seller-zerotier-ip>:8000/.well-known/agent-card.json
```

Outputs from this phase:

- `ZEROTIER_NETWORK`
- `FRP_SERVER_ADDR`
- FRP gateway hostname or IP
- `FRP_DOMAIN`
- `FRP_DASHBOARD_PASSWORD`
