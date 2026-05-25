# Seller FRP setup (optional)

How to set up an FRP reverse-proxy server so buyer VMs are reachable via
wildcard subdomains instead of random TCP ports on your KVM host.

The default seller flow ([`seller-quickstart.md`](./seller-quickstart.md))
uses direct port-forward NAT: the KVM host's public IP exposes each VM
on a random port (`ssh -p <port> tenant@<kvm-host-ip>`). FRP replaces
that with a stable public host running `frps`, plus a `frpc` client on
each VM that opens a tunnel back. Buyers then SSH to a per-VM subdomain
(`ssh tenant@<vm>.vm.your-domain.com`).

Use FRP if:

- The KVM host isn't directly reachable (NAT'd, behind a corporate
  firewall, on a VPN-only network).
- You want subdomain-style routing instead of port-numbered routing.
- You're running multiple KVM hosts and want a single ingress address.

Skip FRP if your KVM host has a public IP and you don't mind random
ports — direct NAT is simpler and has one fewer moving part.

## Prerequisites

- A publicly-reachable VM with **at least 2 vCPU / 4 GB RAM** running
  Ubuntu 22.04+ (any provider: Hetzner, AWS EC2, GCP Compute Engine,
  DigitalOcean, Azure, Linode, bare metal). Around $5-10/mo is plenty.
- SSH access to that VM as a user with passwordless `sudo`.
- A domain you control DNS for. The wildcard record `*.vm.<your-domain>`
  must point at the FRP server's IP.

The FRP server VM doesn't need GPU/disk capacity — it only proxies TCP
traffic. Network throughput is the bottleneck; pick a region close to
your buyers.

## 1. Stand up the FRP server VM

Any provisioning path works — `terraform apply`, the cloud console, or
`hcloud`/`aws`/`gcloud` CLI. The Ansible playbook only needs SSH access
afterward.

Minimum requirements on the VM:

- Ubuntu 22.04 LTS or newer
- SSH port 22 open from your operator machine
- Ports `7000`, `7002-8000`, `80`, `443` open from the public internet
  (UFW rules are configured automatically by the playbook, but the
  cloud-provider firewall needs them open too)

## 2. Add the host to your Ansible inventory

Edit `compute-provisioning-iac/ansible/inventory/hosts` (copy from
`hosts.example` if you haven't):

```ini
[frp_servers]
proxy-prod ansible_host=<FRP_VM_PUBLIC_IP> ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_ed25519
```

`proxy-prod` is just a friendly alias — use whatever you want, the
playbook targets the group, not the name.

## 3. Run the setup playbook

From `compute-provisioning-iac/`:

```bash
ansible-playbook -i ansible/inventory/hosts \
  ansible/playbooks/frp/frp-server-setup.yaml \
  -e "frp_domain=vm.your-domain.com" \
  -e "certbot_email=admin@your-domain.com" \
  --limit proxy-prod
```

The playbook installs `frps`, configures Nginx + Let's Encrypt for the
dashboard, sets up UFW + fail2ban, and reboots the host. Run time:
~5 minutes.

When it finishes, **save the credentials file it writes locally** to
`compute-provisioning-iac/credentials/frp-server-credentials-<host>-<timestamp>.json`.
It contains the `auth_token` and `dashboard_password` you'll need next.

For full parameter details and re-run / SSL recovery flags, see
[`compute-provisioning-iac/README.md`](../compute-provisioning-iac/README.md#1-setup-frp-server-optional-for-secure-remote-access-to-leased-vms).

## 4. DNS records

Add two records pointing at the FRP server's public IP:

```
A  *.vm.your-domain.com   <FRP_VM_PUBLIC_IP>
A  frp-admin.vm.your-domain.com   <FRP_VM_PUBLIC_IP>
```

The wildcard is what lets each provisioned VM get its own subdomain.
The `frp-admin` record is for the dashboard (HTTPS via the Let's Encrypt
cert the playbook just provisioned).

DNS propagation can take a few minutes. Verify:

```bash
dig +short frp-admin.vm.your-domain.com
dig +short anything.vm.your-domain.com   # wildcard should answer the same IP
```

If `frp-admin` resolves but SSL hadn't yet been provisioned because DNS
wasn't ready during step 3, re-run the playbook with `--tags frp_ssl`.

## 5. Wire the seller config

Add three keys to your `config.seller.toml` under `[provisioning]`:

```toml
[provisioning]
mode                   = "http"
service_url            = "http://seller-provisioning:8081"
frp_server_addr        = "<FRP_VM_PUBLIC_IP>"
frp_domain             = "vm.your-domain.com"
frp_dashboard_password = "<from credentials JSON>"
```

The storefront forwards these to the provisioning service on each
`/vms` call. When all three are set, the provisioning playbook routes
the new VM through FRP instead of opening a port on the KVM host.

Bring the stack down and back up so the storefront re-reads the config:

```bash
docker compose -f compose/seller.yml -f compose/seller.live.yml \
  down seller-agent seller-provisioning
docker compose -f compose/seller.yml -f compose/seller.live.yml \
  up -d seller-agent seller-provisioning
```

## 6. Verify

Provision a test VM through the storefront admin API or buyer flow.
The settle response's `connection.ssh_commands.external` should look
like:

```
ssh -i <key> tenantXXXXXXXX@<subdomain>.vm.your-domain.com
```

not

```
ssh -i <key> -p <random_port> tenantXXXXXXXX@<kvm-host-ip>
```

If you see the second form, FRP isn't picking up — check that all three
`frp_*` config keys are non-empty and the provisioning service was
restarted after the config change.

The FRP dashboard at `https://frp-admin.vm.your-domain.com` (user
`admin`, password from credentials JSON) lists active proxies and lets
you confirm each VM has registered.

## Troubleshooting

**Playbook fails at `Obtain SSL certificate with Certbot`** — DNS isn't
pointing at the FRP server yet, or hasn't propagated. The playbook
continues without SSL; finish DNS, then re-run with `--tags frp_ssl`.

**VM provisioning succeeds but `frpc` doesn't connect from the VM** —
the FRP server's port `7000` isn't reachable from the KVM host. Check
the cloud-provider firewall (UFW on the FRP server is already set by
the playbook). `sudo ufw status verbose` on the FRP server should show
`7000/tcp ALLOW`.

**Wildcard subdomains 404** — Nginx on the FRP server only serves the
`frp-admin` site directly; the wildcard subdomains are proxied at the
TCP layer by `frps` itself. If `dig` resolves but connections fail,
check `journalctl -u frps -f` on the FRP server while a VM provisions.

**Dashboard password lost** — re-run the playbook; it generates a new
random password and writes a fresh credentials JSON. Existing `frpc`
clients use the auth token (separate), so they keep working as long as
the token didn't change.

**Want to switch back to direct port-forward** — set all three
`frp_*` keys back to `""` in `config.seller.toml` and restart the
stack. New VMs go back to direct NAT; existing leased VMs are
unaffected until they expire.
