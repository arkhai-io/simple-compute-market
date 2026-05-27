# VM Infrastructure as Code - Ansible KVM Management

A comprehensive Terraform and Ansible-based Infrastructure as Code solution for managing KVM virtual machines with automated provisioning, lifecycle management, and infrastructure orchestration.

## Features

### Core Capabilities
- 🏢 **Multi-Tenant Architecture**: Complete tenant isolation with separate storage pools, network ranges, SSH keys, and resource quotas
- 🖥️ **Complete VM Lifecycle Management**: Create, start, stop, restart, destroy, and monitor VMs across tenants
- ⚙️ **Automated KVM Host Setup**: Comprehensive hypervisor configuration, security hardening, and GPU passthrough support
- 🐧 **Ubuntu Cloud Image Deployment**: Automated OS provisioning with cloud-init for networking and SSH
- 🔑 **Dual SSH Key Management**: Infrastructure root keys and tenant-specific keys with automated generation and FRP-based remote access
- 🌐 **FRP Integration**: Fast Reverse Proxy for secure remote SSH access to VMs through public VPS
- 🐳 **Docker Application Deployment**: Deploy containerized apps with Nginx reverse proxy, SSL certificates, and FRP subdomain routing
- 📊 **Advanced VM Monitoring**: Comprehensive performance metrics including CPU/RAM/storage usage, network statistics, and JSON output
- 📈 **Resource Quotas**: Enforced limits on VMs, RAM, vCPUs, and storage per tenant
- 🛡️ **Security Hardening**: SSH configuration, iptables, UFW, libvirt security, audit logging, and fail2ban
- 💾 **Golden Image Support**: Packer-based image building with GCS storage integration
- 🔧 **Automatic Inventory Management**: VMs auto-added/removed from Ansible inventory
- 📦 **Storage Management**: Dynamic disk allocation with tenant-specific storage pools
- 🧹 **Infrastructure Cleanup**: Complete resource cleanup with iptables rule removal
- 🎮 **GPU-Enabled VM Leasing**: Optional GPU passthrough VMs for Host Kit with resource leasing capabilities
- 🏗️ **Infrastructure Configuration Tracking**: Organized Cloud Resource Configurations for Compute Provisioning 

## Prerequisites

- **Ansible 2.9+** with collections support
- **Ubuntu/Debian KVM hosts** with sudo access and virtualization support
- **Python 3.6+** on Ansible control node
- **Hardware virtualization** support (Intel VT-x or AMD-V)
- **GPU-enabled host** with NVIDIA or AMD GPU and proper GPU setup (optional, for GPU passthrough features)
- **GCP credentials** (optional, for GCS image storage)
- **FRP server** (optional, for remote SSH access)
- **Terraform 1.14+** with updated GCP Provider version

## Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd compute-provisioning-iac/ansible
```

### 2. Install Required Ansible Collections
```bash
ansible-galaxy collection install -r requirements.yml
```

### 3. Setup Inventory
Configure your hosts in `inventory/hosts`:

```ini
[frp_servers]
proxy-dev ansible_host=<your-frp-server-ip> ansible_user=<user> ansible_ssh_private_key_file=<key-path>

[provisioning_servers]
provisioning-dev ansible_host=<your-provisioning-server-ip> ansible_user=<user> ansible_ssh_private_key_file=<key-path>

[kvm_hosts]
kvm1 ansible_host=<kvm-host-ip> ansible_user=<user> ansible_ssh_private_key_file=<key-path>
# Add more KVM hosts as needed
```

**Inventory Group Descriptions**:
- `[frp_servers]`: Public-facing VPS/servers running the FRP server daemon. Acts as the secure tunnel entry point for VM SSH access and hosts the FRP admin dashboard. Targeted by `frp-server-setup.yaml` and `docker-app-setup.yaml` playbooks.
- `[provisioning_servers]`: Servers running the Async Provisioning Service. These handle inbound VM provisioning API requests, manage the job queue, and execute Ansible playbooks against KVM hosts. Targeted by `docker-app-setup.yaml`.
- `[kvm_hosts]`: Bare-metal or dedicated servers running KVM/QEMU hypervisors where guest VMs are created and managed. These are the actual compute nodes. Targeted by `vm-setup.yaml` and `vm-operations.yaml` playbooks.

### 4. Generate SSH Keypair
Generate an ed25519 SSH keypair to be used for provisioning operations. The **private key** will be injected into the Docker app (Async Provisioning Service) as a credential for connecting to VMs, and the **public key** will be added to `authorized_keys` on the KVM host during `vm-setup`.

```bash
ssh-keygen -t ed25519 -C "arkhai-ops@arkhai.io"
```

When prompted:
- **File path**: Save to a dedicated path, e.g. `~/.ssh/provisioner_ed25519` (avoid overwriting existing keys)
- **Passphrase**: Leave empty for automated/non-interactive use, or set one for additional security

After generation, two files will be created:
- `~/.ssh/provisioner_ed25519` — **Private key**: provide this to the Docker app via `app_container_env` (e.g. `SSH_PRIVATE_KEY`)
- `~/.ssh/provisioner_ed25519.pub` — **Public key**: this will be injected into `/root/.ssh/authorized_keys` (or the target user's) on the VM host during the `vm-setup.yaml` playbook run

> **Note**: Keep the private key secure and never commit it to version control. The public key is safe to store in configuration files or pass as an Ansible variable.

#### Encoding the Private Key for Container Injection

The Async Provisioning Service container reads `SSH_PRIVATE_KEY` as a **base64-encoded single-line string** and writes the decoded key to `~/.ssh/id_ed25519` at startup. Encode your key like this:

```bash
base64 < ~/.ssh/provisioner_ed25519 | tr -d '\n'
```

Capture it into a shell variable for use in the playbook command:

```bash
export SSH_PRIVATE_KEY=$(base64 < ~/.ssh/provisioner_ed25519 | tr -d '\n')
```

#### Encoding management-vars.yaml for Container Injection

The Async Provisioning Service container reads `MANAGEMENT_VARS_YAML` as a **base64-encoded single-line string** and writes the decoded file to `/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml` at startup. This file is required when running VM operations that use Packer-generated Golden Images.

management-vars.yaml is only required when runtime VM operations use golden images.

Encode your `management-vars.yaml` like this:

```bash
base64 < inventory/management-vars.yaml | tr -d '\n'
```

Capture it into a shell variable for use in the playbook command:

```bash
export MANAGEMENT_VARS_YAML=$(base64 < inventory/management-vars.yaml | tr -d '\n')
```

#### Deploying the Async Provisioning Service

Pass the encoded credentials via `SSH_PRIVATE_KEY` and `MANAGEMENT_VARS_YAML` inside `app_container_env`:

```bash
export SSH_PRIVATE_KEY=$(base64 < ~/.ssh/provisioner_ed25519 | tr -d '\n')
export MANAGEMENT_VARS_YAML=$(base64 < inventory/management-vars.yaml | tr -d '\n')

ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=<gcp-project-id>" \
  -e "gcp_registry_region=<registry-region>" \
  -e "gcp_repository=async-provisioning-service" \
  -e "gcp_service_account_key=<path-to-sa-key.json>" \
  -e "docker_image_name=async-provisioning-service" \
  -e "docker_image_tag=latest" \
  -e "app_container_name=provisioner" \
  -e "app_container_internal_port=8081" \
  -e "app_container_port=8001" \
  -e "app_nginx_port=8888" \
  -e "frp_subdomain_host=<frp-domain>" \
  -e "enable_ssl=true" \
  -e "certbot_email=<email>" \
  -e "app_nginx_site_name=provisioner" \
  -e "{\"app_container_env\":{\"HOST\":\"0.0.0.0\",\"PORT\":\"8081\",\"LOG_LEVEL\":\"info\",\"DATABASE_URL\":\"postgresql+psycopg2://postgres:postgres@<postgres-host>:5432/provisioning\",\"REDIS_URL\":\"redis://<redis-host>:6379/0\",\"REDIS_QUEUE_NAME\":\"provisioning_jobs\",\"ANSIBLE_TIMEOUT_SECONDS\":\"1800\",\"ANSIBLE_BECOME_PASS\":\"<become-pass>\",\"DEFAULT_VM_HOST\":\"<kvm-host-alias>\",\"FRP_SERVER_ADDR\":\"<frp-server-ip>\",\"FRP_DOMAIN\":\"<frp-domain>\",\"FRP_DASHBOARD_PASSWORD\":\"<frp-dashboard-pass>\",\"ENABLE_AUTH\":\"true\",\"AUTH_FAIL_OPEN\":\"false\",\"REGISTRY_URL\":\"https://<registry-url>\",\"REGISTRY_CACHE_TTL_SECONDS\":\"300\",\"REGISTRY_CACHE_MAX_SIZE\":\"256\",\"SSH_PRIVATE_KEY\":\"$SSH_PRIVATE_KEY\",\"MANAGEMENT_VARS_YAML\":\"$MANAGEMENT_VARS_YAML\"}}" \
  --limit provisioning-<environment>
```

**Parameter notes**:
- `SSH_PRIVATE_KEY`: base64-encoded private key (no newlines). The container decodes it to `~/.ssh/id_ed25519` on startup.
- `MANAGEMENT_VARS_YAML`: base64-encoded `management-vars.yaml` (no newlines). The container decodes it to `/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml` on startup. Required when using Golden Images (`vm_action=create` or `vm_action=undefine`).
- `DEFAULT_VM_HOST`: alias of the KVM host from the Ansible inventory (e.g. `kvm1`) that the service will SSH into for provisioning operations.
- `ANSIBLE_BECOME_PASS`: sudo password on the target KVM host.
- Store the generated FRP credentials JSON outside version control. The FRP setup role writes it to `credentials/frp-server-credentials-<host>-<timestamp>.json` at the repo root on the Ansible control machine.

### 5. Configure Build Variables (Optional)
Create `build-vars.yaml` for Golden Image builds:

build-vars.yaml is only required for golden image creation.

```yaml
## Utilize Terraform to retrieve Packer VM Image Registry
# Initialize Terraform Remote State
cd ../terraform/<environment>
terraform init

# Extract sensitive GCP configuration data from the terraform remote state:
cat > ../../ansible/build-vars.yaml <<EOF
gcs_bucket_url: $(terraform output -raw ansible_image_storage_bucket_url)
gcs_project_id: $(terraform output -raw ansible_image_storage_project_id)
gcs_service_account_content: |
$(terraform output -raw ansible_image_storage_sa_json | sed 's/^/  /')
EOF

# If an existing SSH key for the root user exists already within the Host environment and is intended to be reused, add its password and filename.
cat >> ../../ansible/build-vars.yaml <<EOF
root_password: ePPAxdHovplT75hYasOSS2KN2NmMWMAHu6v5BzRV
root_filename: root_ssh_8c05a2_ed25519
EOF

# Also, define if new cloud-init and packer variables file are to be generated from templates. Declare the Packer generated image's version. Follow the format:
# v<Major>.<Minor>.<Patch>-<Host Node Identifier>
cat >> ../../ansible/build-vars.yaml <<EOF
generate_new_templates: true
build_version: v0.0.1-hostnode1
EOF
# Then, to ensure continuity with the base ISO's latest version, run
cat >> ../../ansible/build-vars.yaml <<EOF
iso_url: https://cloud-images.ubuntu.com/noble/20260307/noble-server-cloudimg-amd64.img
EOF
curl -s https://cloud-images.ubuntu.com/noble/20260307/SHA256SUMS | awk '$2 ~ /noble-server-cloudimg-amd64\.img$/ { print "iso_checksum: sha256:" $1 }' >> build-vars.yaml

# Prepare cwd to the ansible folder
cd ../../ansible
```

## Quick Start

## Validation

Run the repo-local validation entrypoints from the submodule root before
changing playbooks, roles, or inventory:

```bash
make validate
make validate-inventory
make validate-playbooks
make validate-tests
```

These targets currently cover:

- inventory parsing via `ansible-inventory -i ansible/inventory/hosts --list`
- syntax checks for:
  - `playbooks/frp/frp-server-setup.yaml`
  - `playbooks/frp/docker-app-setup.yaml`
  - `playbooks/host-kit/vm-setup.yaml`
  - `playbooks/single-tenant/vm-operations.yaml`
- VM lifecycle contract tests in `tests/test_vm_management_contracts.py`, which
  verify the checked-in task contracts for `vm-create`, `vm-destroy`,
  `vm-undefine`, prerequisite fail-fast behavior, and JSON output formatting

`ansible-lint` is not part of the default validation path in this repo yet.

### Acceptance Validation

For real host-kit and libvirt validation on a live KVM host, use the optional
acceptance runner:

```bash
make validate-acceptance KVM_HOST=kvm1
./scripts/run_acceptance_validation.sh --kvm-host kvm1 --vm-name iac-acceptance-kvm1
```

This path is intentionally not part of the default CI or `make validate`
because it requires a real inventory target with libvirt, FRP, and host-kit
access.

The acceptance runner performs:

- `ansible/playbooks/host-kit/vm-setup.yaml`
- `ansible/playbooks/single-tenant/vm-operations.yaml` with `vm_action=create`
- `ansible/playbooks/single-tenant/vm-operations.yaml` with `vm_action=check`
- `ansible/playbooks/single-tenant/vm-operations.yaml` with `vm_action=destroy`
- `ansible/playbooks/single-tenant/vm-operations.yaml` with `vm_action=undefine`

Useful flags:

- `--skip-host-kit` when the host-kit baseline is already converged
- `--keep-vm` if you want to retain the acceptance VM after `vm_action=create`
  and `vm_action=check`
- `--extra-vars-file <path>` when the acceptance run needs a checked-in vars
  bundle

### Deployment Sequence Overview

Follow this sequence in order. Each phase produces outputs (credentials, IPs, tokens) that are required as inputs for the next phase — particularly for generating the Async Provisioning Service variables.

```
Phase 1: Terraform (GCP Resources)
  Provisions: GCS bucket, Artifact Registry repos, service accounts
  Outputs → build-vars.yaml, docker-vars.yaml
         │
         ▼
Phase 2: FRP Server Setup  (playbooks/frp/frp-server-setup.yaml → [frp_servers])
  Provisions: FRP daemon, Nginx, SSL, credentials file
  Outputs → frp_server_addr, frp_auth_token, frp_dashboard_password
         │                                               │
         ▼                                               │
Phase 3: KVM Host Setup    (playbooks/host-kit/vm-setup.yaml → [kvm_hosts])   │
  Provisions: KVM/QEMU, GPU drivers, FRP client, golden image (optional)      │
  Outputs → DEFAULT_VM_HOST (inventory alias), ANSIBLE_BECOME_PASS            │
         │                                               │
         ▼                                               ▼
Phase 4a: ERC Registry     (playbooks/frp/docker-app-setup.yaml → [frp_servers / provisioning_servers])
  Provisions: Blockchain identity/reputation registry container
  Outputs → REGISTRY_URL (e.g. http://localhost:8080)
         │
         ▼
Phase 4b: Async Provisioning Service  (playbooks/frp/docker-app-setup.yaml → [provisioning_servers])
  Requires ALL prior outputs:
    FRP_SERVER_ADDR        ← Phase 2: frp_server_addr
    FRP_DOMAIN             ← Phase 2: frp_domain
    FRP_DASHBOARD_PASSWORD ← Phase 2: frp_dashboard_password (credentials file)
    DEFAULT_VM_HOST        ← Phase 3: KVM host inventory alias
    ANSIBLE_BECOME_PASS    ← Phase 3: KVM host sudo password
    REGISTRY_URL           ← Phase 4a: ERC Registry endpoint
         │
         ▼
Phase 5: VM Create / Lifecycle  (playbooks/single-tenant/vm-operations.yaml → [kvm_hosts])
  create → start → monitor → shutdown/reboot → lease_end → undefine
```

| Phase | Playbook | Target Group | Key Outputs Needed by Provisioning Service |
|---|---|---|---|
| 1 | `terraform apply` | GCP | `gcp_project_id`, registry/bucket details |
| 2 | `frp/frp-server-setup.yaml` | `[frp_servers]` | `FRP_SERVER_ADDR`, `FRP_DOMAIN`, `FRP_DASHBOARD_PASSWORD` |
| 3 | `host-kit/vm-setup.yaml` | `[kvm_hosts]` | `DEFAULT_VM_HOST`, `ANSIBLE_BECOME_PASS` |
| 4a | `frp/docker-app-setup.yaml` | `[frp_servers]` | `REGISTRY_URL` |
| 4b | `frp/docker-app-setup.yaml` | `[provisioning_servers]` | *(this is the service being configured)* |
| 5 | `single-tenant/vm-operations.yaml` | `[kvm_hosts]` | — |

> **Note**: The generated FRP credentials file is saved to `credentials/frp-server-credentials-<host>-<timestamp>.json` after Phase 2. Keep this file — it contains the `frp_auth_token` and `frp_dashboard_password` needed for Phases 3 and 4b.

---

### 1. Setup FRP Server (Optional, for secure remote access to leased VMs)
The FRP server acts as a secure bridge for buyers to access their leased VM resources without exposing additional ports on the Host Kit. You'll need a dedicated VM with at least 2 vCPUs and 4GB RAM that has network access to the Host Kit guest VMs.

**Note**: This is optional as direct port SSH access is still supported, but FRP is highly recommended for enhanced security as it eliminates the need to expose multiple ports on your infrastructure.

```bash
ansible-playbook -i inventory/hosts playbooks/frp/frp-server-setup.yaml \
  -e "frp_domain=vm.arkhai.io" \
  -e "certbot_email=admin@vm.arkhai.io" \
  --limit proxy-dev
```

**Parameter Explanations**:
- `frp_domain`: The domain or subdomain for FRP server access and SSL certificates
- `certbot_email`: Email address for Let's Encrypt SSL certificate registration

### 2. Setup KVM Host Infrastructure
This step configures the required drivers, BIOS setup adjustments on the kernel, installs necessary packages, and prepares the host for VM management, especially when using FRP for remote access.

```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "@build-vars.yaml" \
  -e "frp_server_addr=<frp-server-ip>" \
  -e "frp_server_port=7000" \
  -e "frp_auth_token=<frp-token>" \
  -e "image_setup_type=golden" \
  --limit kvm1
```

**Parameter Explanations**:
- `@build-vars.yaml`: Variables file containing build configuration (packer settings, GCP credentials, etc.)
- `frp_server_addr`: IP address of the FRP server for remote access integration
- `frp_server_port`: Port number for FRP server communication (default: 7000)
- `frp_auth_token`: Authentication token for FRP server client connections
- `image_setup_type`: Image setup method - "scratch" for base Ubuntu images, "golden" for custom built images

**Notes**:
- If libvirt security setup fails due to conflicts with BIOS, CPU, or machine configuration, you can skip it with `-e skip_libvirt_security=true`.
- You can change `image_setup_type=scratch` to `image_setup_type=golden` if you want to build a custom golden image. Otherwise, it will download and use the base Ubuntu cloud image.

### 3. Create Your First VM
Create a variables file with your VM configuration and run the playbook:

```bash
cat > /tmp/vm_vars.yml << 'EOF'
vm_host: kvm1
vm_target: vm-base-gpu  
vm_action: create
vm_ram: 4096
vm_vcpus: 4
vm_disk_size: 10G
vm_tenant_pubkey: "<tenant-ssh-key-from-local-machine>"
vm_gpu_provisioned: true
vm_gpu_count: 2
image_setup_type: scratch
frp_domain: "vm.arkhai.io"
frp_server_addr: "<frp-server-vm-ip-address>"
frp_dashboard_password: "<some-random-dashboard-api-password>"                        
EOF                                 
    
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    --extra-vars @inventory/management-vars.yaml \
    --extra-vars @/tmp/vm_vars.yml \
    --limit kvm1
```

**Parameter Explanations**:
- `@inventory/management-vars.yaml`: Variables file containing Golden Image Management configuration (Image Name, Bucket and Image Path, Root SSH details)
- `vm_host`: The KVM host where the VM will be created (from your inventory)
- `vm_target`: Name of the VM to create
- `vm_action`: Action to perform (create, start, stop, etc.)
- `vm_ram`: RAM allocation in MB (4096 = 4GB)
- `vm_vcpus`: Number of virtual CPUs to allocate
- `vm_disk_size`: Disk size for the VM (10G = 10GB)
- `vm_tenant_pubkey`: SSH public key for tenant access (from your local machine)
- `vm_gpu_provisioned`: Whether to enable GPU passthrough (false for non-GPU VMs)
- `vm_gpu_count`: Number of GPUs to passthrough (only used when vm_gpu_provisioned is true)
- `image_setup_type`: Image type to use (scratch = base Ubuntu image, golden = custom image)
- `frp_domain`: Domain/subdomain for FRP remote access
- `frp_server_addr`: IP address of your FRP server
- `frp_dashboard_password`: Password for FRP dashboard access

**`inventory/management-vars.yaml` Usage**
- `--extra-vars @inventory/management-vars.yaml` usage is only required when utilizing Packer-generated Golden Images for the VMs
- Mainly required when running `vm_action=creaate` and `vm_action=undefine`
- Requires at least a single run of `playbooks/host-kit/vm-setup.yaml` in order to be generated


**Troubleshooting SSH key parsing**
- If only part of your SSH key is being recognized (for example, just the key type such as `ssh-ed25519`), prefer the `--extra-vars @/tmp/vm_vars.yml` variables-file method.
- The variables-file method reliably preserves spaces, comments, and special characters in SSH keys.
- Verify the key was parsed correctly by checking the playbook debug output during VM creation.

### 4. Monitor VM Performance
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=monitor \
    --limit kvm1
```

**Parameter Explanations**:
- `vm_host`: The KVM host where the VM is running (from your inventory)
- `vm_target`: Name of the VM to monitor
- `vm_action`: Action to perform (monitor for performance metrics)

### 5. Additional VM Operations

**Shutdown VM Gracefully**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=shutdown \
    --limit kvm1
```

**Reboot VM**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=reboot \
    --limit kvm1
```

**Force Shutdown/Destroy VM**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=destroy \
    --limit kvm1
```

**Delete/Remove VM Completely**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e "@inventory/management-vars.yaml" \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=undefine \
    --limit kvm1
```

**Schedule VM Lease End** (set when the lease will expire and VM will be destroyed):
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=lease_end \
    -e '{"vm_lease_end":"2026-02-23 10:45"}' \
    --limit kvm1
```

**Parameter Explanations** (applies to all Additional VM operation commands above):
- `vm_host`: The KVM host where the VM operation will be performed (from your inventory)
- `vm_target`: Name of the VM to operate on
- `vm_action`: Action to perform (shutdown, reboot, destroy, undefine)

**Note**: This Quick Start guide provides the essential steps to get you up and running quickly. It covers setting up an FRP server for secure remote access, configuring your Host Kit infrastructure, creating and monitoring Guest VMs within the Host Kit. For complete documentation of all available features and advanced configurations, refer to the Usage Examples and Infrastructure Architecture sections below.

## Project Structure
```
image-and-ssh-provisioning-iac/
├── ansible/
│   ├── ansible.cfg                    # Ansible configuration
│   ├── group_vars/
│   │   └── all.yml                    # Global configuration and tenant defaults
│   ├── inventory/
│   │   ├── hosts                      # Main inventory file
│   │   └── management-vars.yaml       # Auto-generated management variables
│   ├── credentials/                   # FRP server credentials storage
│   ├── keys/                          # SSH keys storage when no customer public key provided
│   ├── playbooks/
│   │   ├── vm-setup.yaml              # KVM host infrastructure setup
│   │   ├── frp/
│   │   │   ├── frp-server-setup.yaml  # FRP server deployment
│   │   │   └── docker-app-setup.yaml  # Docker app deployment with FRP
│   │   ├── host-kit/
│   │   │   └── vm-setup.yaml          # Host-specific VM setup
│   │   └── single-tenant/
│   │       └── vm-operations.yaml     # VM lifecycle management
│   ├── roles/
│   │   ├── docker-app/                # Docker application deployment
│   │   │   ├── handlers/
│   │   │   ├── tasks/
│   │   │   └── templates/
│   │   ├── frp-setup/                 # FRP server configuration
│   │   │   ├── handlers/
│   │   │   ├── tasks/
│   │   │   └── templates/
│   │   ├── vm-management/             # VM lifecycle operations
│   │   │   ├── handlers/
│   │   │   ├── tasks/
│   │   │   └── templates/
│   │   └── vm-setup/                  # KVM host preparation
│   │       ├── backup/
│   │       ├── files/
│   │       ├── handlers/
│   │       ├── tasks/
│   │       └── templates/
│   └── requirements.yml               # Ansible collection requirements
├── terraform/
│   └── common/                        # Terraform Reusable Modules
│   │   ├── general_setup              # General GCP Project Configuration
│   │   ├── ansible_image_storage_*    # Packer Image Registry Resources
│   │   ├── agent_*                    # [TO ARCHIVE] Simple Compute Market Agent Resources
│   │   ├── cicd_setup                 # [TO ARCHIVE] Simple Compute Market CI/CD
│   │   └── general_github             # [TO ARCHIVE] Simple Compute Market GitHub Action
│   └── <environment>/                 # Separate main.tf for each environment
└── README.md                          # This file
```

## Configuration

### Global Settings
Default configurations are managed in `ansible/group_vars/all.yml`:

```yaml
# Global configuration for multi-tenant VM infrastructure
# This file defines default settings and tenant isolation parameters

---
# Default VM settings
default_vm_settings:
  ram: 2048                        # Default RAM in MB
  vcpus: 2                         # Default vCPU count
  disk_size: 20G                   # Default disk size
  os_variant: ubuntu24.04          # OS variant for virt-install
  
# Tenant isolation settings
tenant_isolation:
  enable_strict_isolation: true     # Enable strict tenant separation
  base_paths:
    vm_storage: /var/lib/libvirt/tenants  # Tenant VM storage location
    ssh_keys: /etc/ssh/tenant_keys        # Tenant SSH key storage
    logs: /var/log/tenants                # Tenant-specific logs
    configs: /etc/tenants                 # Tenant configurations
  network:
    base_network: 192.168.100.0/16  # Base network for tenant isolation
    subnet_size: 24                 # /24 subnets per tenant
    enable_network_isolation: true  # Network isolation between tenants
  security:
    enable_selinux_labels: true     # SELinux security labels
    enforce_resource_limits: true   # Resource quota enforcement
    enable_audit_logging: true      # Security audit logging

# Resource quotas per tenant
default_tenant_quotas:
  max_vms: 10                       # Maximum VMs per tenant
  max_total_ram_gb: 32              # Total RAM allocation limit
  max_total_vcpus: 20               # Total vCPU allocation limit
  max_storage_gb: 500               # Total storage allocation limit

# KVM/QEMU settings
kvm_settings:
  enable_cgroups: true              # Resource isolation via cgroups
  separate_pools: true              # Separate libvirt pools per tenant
  enable_numa: false                # NUMA awareness (disabled by default)

# GCP integration (for cloud deployments)
gcp_variables:
  gcs_bucket_url: gs://principia-infrastructure-dev-compute-images
  gcs_project_id: principia-infrastructure-dev
  
# Packer image building
packer_variables:
  iso_url: https://cloud-images.ubuntu.com/noble/20251126/noble-server-cloudimg-amd64.img
  iso_checksum: sha256:8bf11afd901fdec5aad647a8a284243a2a0b80a81ac732ae618ab36afa09f2b4
  accelerator: none
  build_format: qcow2               # VM image format
  build_name: ubuntu_noble          # Base image name, format <OS Name>_<Nickname>
  packer_work_dir: /tmp/packer      # Packer working directory
  output_dir: artifacts             # Packer artifacts directory
  generate_new_templates: true      # Enable generation of new Packer files
```

## Infrastructure Architecture

### KVM Host Setup (vm-setup role)
- **System Package Installation**: Essential tools including vim, nano, git, python3, pip, net-tools, at scheduler, SELinux utilities, and development packages
- **Firewall Configuration**: UFW setup with SSH access rules and default deny policy
- **KVM/QEMU Installation**: Complete virtualization stack with qemu-kvm, libvirt-daemon-system, libvirt-clients, bridge-utils, virtinst, virt-manager, virt-viewer, libguestfs-tools, and qemu-guest-agent
- **Hardware Virtualization**: CPU virtualization support detection, nested virtualization enablement for Intel VT-x and AMD-V, IOMMU configuration
- **User Permissions**: Automatic addition of users to libvirt and kvm groups for virtualization access
- **GPU Passthrough Support**: NVIDIA and AMD GPU detection, PCI device identification, IOMMU group analysis, VFIO driver configuration, and GPU isolation for VM assignment
- **Network Configuration**: KVM bridge networking setup, network isolation rules, and persistent iptables configurations
- **Security Hardening**: SSH access restrictions from VM networks, iptables rules blocking VM-to-host SSH, network isolation service, audit logging setup
- **Intrusion Prevention**: Fail2ban installation with custom jails for SSH protection, VM network attack detection, bridged network monitoring, and iptables-allports banning
- **FRP Client Setup**: Fast Reverse Proxy client installation, systemd service configuration, and secure tunneling for remote VM access
- **Golden Image Pipeline**: Packer installation, GCP SDK setup, HashiCorp repository configuration, and automated image building with GCS storage integration

> **Operational reboot guardrail**: Shut down running VMs before rebooting the host. If guests are still running, `libvirtd` can block systemd shutdown while it waits for those domains to stop, which in turn makes host reboots hang indefinitely.
- **GPU Detection Service**: Automated GPU monitoring service, hardware detection scripts, and resource availability tracking

#### VM Setup Command Examples

**Standard Host Setup (Base Ubuntu Image)**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "@build-vars.yaml" \
  -e "frp_server_addr=192.168.100.61" \
  -e "frp_server_port=7000" \
  -e "frp_auth_token=your-frp-token-here" \
  -e "image_setup_type=scratch" \
  --limit kvm1
```

**Host Setup with Libvirt Security Skip** (when BIOS/OS doesn't support SELinux):
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "@build-vars.yaml" \
  -e "frp_server_addr=192.168.100.61" \
  -e "frp_server_port=7000" \
  -e "frp_auth_token=your-frp-token-here" \
  -e "skip_libvirt_security=true" \
  -e "image_setup_type=scratch" \
  --limit kvm1
```

**Golden Image Build Setup**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "@build-vars.yaml" \
  -e "frp_server_addr=192.168.100.61" \
  -e "frp_server_port=7000" \
  -e "frp_auth_token=your-frp-token-here" \
  -e "image_setup_type=golden" \
  -e "packer_build_name=ubuntu_noble" \
  -e "packer_build_version=1.0.0" \
  -e "gcp_project_id=your-gcp-project" \
  -e "gcs_bucket_url=gs://your-bucket-name" \
  --limit kvm1
```

**Minimal Setup (No FRP, Base Image Only)**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "image_setup_type=scratch" \
  -e "skip_libvirt_security=true" \
  --limit kvm1
```

**Inject a Single SSH Public Key into authorized_keys**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "image_setup_type=scratch" \
  -e "vm_ssh_authorized_key='ssh-ed25519 AAAA... user@host'" \
  --limit kvm1
```

**Inject Multiple SSH Public Keys into authorized_keys**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "image_setup_type=scratch" \
  -e '{"vm_ssh_authorized_keys": ["ssh-ed25519 AAAA... user@host", "ssh-rsa BBBB... other@host"]}' \
  --limit kvm1
```

**Inject SSH Key for a Specific User**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "image_setup_type=scratch" \
  -e "vm_ssh_key_user=ubuntu" \
  -e "vm_ssh_authorized_key='ssh-ed25519 AAAA... user@host'" \
  --limit kvm1
```

**Only Inject SSH Keys (skip everything else)**:
```bash
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "vm_ssh_authorized_key='ssh-ed25519 AAAA... user@host'" \
  --tags "ssh_keys" \
  --limit kvm1
```

**Setup with Specific Tags** (selective installation):
```bash
# Only install system packages and KVM
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "image_setup_type=scratch" \
  --tags "system_setup,kvm_config" \
  --limit kvm1

# Only configure GPU passthrough
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  --tags "gpu_passthrough" \
  --limit kvm1

# Only setup FRP client
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "frp_server_addr=192.168.100.61" \
  -e "frp_server_port=7000" \
  -e "frp_auth_token=your-frp-token-here" \
  --tags "frp_client" \
  --limit kvm1

# Only build golden image (requires prior host setup)
ansible-playbook -i inventory/hosts playbooks/host-kit/vm-setup.yaml \
  -e "@build-vars.yaml" \
  -e "vm_image_type=golden" \
  -e "packer_build_name=ubuntu_noble" \
  -e "packer_build_version=1.0.0" \
  --tags "golden_image" \
  --limit kvm1
```

**Parameter Reference**:
- `@build-vars.yaml`: Variables file with GCP credentials and Packer configuration
- `frp_server_addr`: IP address of FRP server (e.g., `192.168.100.61`)
- `frp_server_port`: FRP server port (default: `7000`)
- `frp_auth_token`: Authentication token for FRP client-server connection
- `skip_libvirt_security`: Skip SELinux/libvirt security hardening when BIOS/OS doesn't support it (set to `true` or `false`)
- `image_setup_type`: Image type - `scratch` for base Ubuntu, `golden` for custom Packer build
- `vm_image_type`: Alternative parameter for image type (used internally, same values as `image_setup_type`)
- `packer_build_name`: Name for Packer build (e.g., `ubuntu_noble`, `ubuntu_jammy`)
- `packer_build_version`: Version string for built image (e.g., `1.0.0`, `2.1.3`)
- `gcp_project_id`: Google Cloud Project ID for GCS storage
- `gcs_bucket_url`: GCS bucket URL for storing golden images (e.g., `gs://my-images-bucket`)
- `gcs_service_account_content`: JSON content of GCP service account key (typically in `build-vars.yaml`)
- `vm_ssh_authorized_key`: Single SSH public key string to add to the target user's `authorized_keys` (e.g., `'ssh-ed25519 AAAA... user@host'`)
- `vm_ssh_authorized_keys`: List of SSH public key strings to add to `authorized_keys` (e.g., `["ssh-ed25519 AAAA...", "ssh-rsa BBBB..."]`)
- `vm_ssh_key_user`: User account whose `authorized_keys` is updated (default: `ansible_user`)

**Available Tags**:
- `system_setup`: Install system packages only
- `host_setup`: Complete host preparation (excludes VM operations)
- `gpu_passthrough`: GPU detection and passthrough configuration
- `kvm_config`: KVM/QEMU installation and setup
- `kvm_network`: Network bridge and isolation setup
- `security_hardening`: Security features (SSH, firewall, fail2ban)
- `ssh_keys`: Inject SSH public key(s) into authorized_keys only (also runs as part of `security_hardening` / `host_setup`)
- `frp_client`: FRP client installation and configuration
- `golden_image`: Golden image building with Packer
- `gpu_detection`: GPU detection service setup
- `vm_operations`: VM-related operations
- `build`: Build-related tasks
- `build_completion`: Post-build completion tasks

### FRP Server Setup (frp-setup role)
- **FRP Server Installation**: Automated download and installation of FRP server binary from GitHub releases
- **Authentication System**: Random 64-character authentication tokens and 32-character dashboard passwords generation
- **Configuration Management**: FRP server configuration templates with TLS encryption, dashboard access, and subdomain routing
- **Systemd Service**: FRP server systemd service creation, daemon management, and automatic startup configuration
- **Directory Structure**: Dedicated configuration directories (/etc/frp), log directories (/var/log/frp), and proper permissions
- **Nginx Integration**: Reverse proxy configuration for FRP admin dashboard with SSL termination
- **SSL Certificate Management**: Let's Encrypt integration for HTTPS access to FRP services
- **Security Configuration**: Token-based authentication, encrypted communications, and access control

#### FRP Server Setup Command Examples

**Standard FRP Server Setup with SSL**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/frp-server-setup.yaml \
  -e "frp_domain=vm.arkhai.io" \
  -e "certbot_email=admin@vm.arkhai.io" \
  --limit proxy-dev
```

**FRP Server Setup with Custom Credentials**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/frp-server-setup.yaml \
  -e "frp_domain=vm.arkhai.io" \
  -e "certbot_email=admin@vm.arkhai.io" \
  -e "frp_auth_token=your-custom-64-char-token-here-make-it-secure-and-random" \
  -e "frp_dashboard_password=your-custom-32-char-password" \
  --limit proxy-dev
```

**FRP Server Setup with Subdomain Host** (alternative parameter):
```bash
ansible-playbook -i inventory/hosts playbooks/frp/frp-server-setup.yaml \
  -e "frp_subdomain_host=vm.arkhai.io" \
  -e "certbot_email=admin@vm.arkhai.io" \
  --limit proxy-dev
```

**Parameter Reference**:
- `frp_domain`: Primary domain/subdomain for FRP services (e.g., `vm.arkhai.io`)
- `frp_subdomain_host`: Alternative parameter for domain (same as `frp_domain`, used internally)
- `certbot_email`: Email for Let's Encrypt SSL certificate notifications (e.g., `admin@vm.arkhai.io`)
- `frp_auth_token`: Custom 64-character authentication token (auto-generated if not provided)
- `frp_dashboard_password`: Custom 32-character dashboard password (auto-generated if not provided)

**Important Notes**:
- Auto-generated credentials are saved to `credentials/frp-server-credentials-<host>-<timestamp>.json`
- DNS must be configured before SSL: Create A record `frp-admin.<domain>` pointing to server IP
- FRP dashboard URL: `https://frp-admin.<domain>` (with SSL) or `http://localhost:7001` (SSH tunnel)
- Control port: `7000` (FRP client connections)
- Proxy port range: `7002-8000` (SSH tunnels for VMs)
- Default dashboard user: `admin`

**Firewall Ports Opened**:
- Port `22`: SSH access
- Port `80`: HTTP (for Let's Encrypt verification)
- Port `443`: HTTPS (for FRP admin dashboard)
- Port `7000`: FRP control port
- Ports `7002-8000`: FRP proxy port range

**Post-Installation Access**:
```bash
# SSH tunnel access (works without SSL)
ssh -L 7001:localhost:7001 user@<frp-server-ip>
# Then visit: http://localhost:7001

# Direct HTTPS access (after SSL setup)
# Visit: https://frp-admin.vm.arkhai.io
```

#### FRP Dashboard API Examples

The FRP server provides a REST API for monitoring and managing proxy connections. All API requests require Basic Authentication using the dashboard credentials.

**Authentication Setup**:
```bash
# Set credentials from your saved credentials file
FRP_USER="admin"
FRP_PASSWORD="<dashboard-password-from-credentials-file>"
FRP_API_URL="http://localhost:7001/api"  # Via SSH tunnel
# OR
FRP_API_URL="https://frp-admin.vm.arkhai.io/api"  # Direct HTTPS
```

**Get Server Information**:
```bash
curl -u "${FRP_USER}:${FRP_PASSWORD}" \
  "${FRP_API_URL}/serverinfo"
```

**Response Example**:
```json
{
    "version": "0.54.0",
    "bindPort": 7000,
    "vhostHTTPPort": 8080,
    "vhostHTTPSPort": 8443,
    "tcpmuxHTTPConnectPort": 0,
    "kcpBindPort": 0,
    "quicBindPort": 0,
    "subdomainHost": "vm.arkhai.io",
    "maxPoolCount": 50,
    "maxPortsPerClient": 0,
    "heartbeatTimeout": 90,
    "allowPortsStr": "7002-8000",
    "tlsForce": true,
    "totalTrafficIn": 55145,
    "totalTrafficOut": 56310,
    "curConns": 0,
    "clientCounts": 1,
    "proxyTypeCount": {
        "tcp": 1
    }
}
```

**List All Active Proxies (Fetch Ports)**:
```bash
curl -u "${FRP_USER}:${FRP_PASSWORD}" \
  "${FRP_API_URL}/proxy/tcp"
```

**Response Example**:
```json
{
    "proxies": [
        {
            "name": "vm-cyifje",
            "conf": null,
            "todayTrafficIn": 21678,
            "todayTrafficOut": 26851,
            "curConns": 0,
            "lastStartTime": "02-12 11:46:02",
            "lastCloseTime": "02-12 11:46:11",
            "status": "offline"
        },
        {
            "name": "vm-o0bw3z",
            "conf": null,
            "todayTrafficIn": 0,
            "todayTrafficOut": 0,
            "curConns": 0,
            "lastStartTime": "02-12 01:54:13",
            "lastCloseTime": "02-12 01:57:23",
            "status": "offline"
        },
        {
            "name": "vm-t6q98d",
            "conf": null,
            "todayTrafficIn": 33467,
            "todayTrafficOut": 29459,
            "curConns": 0,
            "lastStartTime": "02-12 02:18:50",
            "lastCloseTime": "02-12 04:47:57",
            "status": "offline"
        },
        {
            "name": "vm-uo0nwf",
            "conf": {
                "name": "vm-uo0nwf",
                "type": "tcp",
                "transport": {
                    "useEncryption": true,
                    "bandwidthLimit": "",
                    "bandwidthLimitMode": "client"
                },
                "loadBalancer": {
                    "group": ""
                },
                "healthCheck": {
                    "type": "",
                    "intervalSeconds": 0
                },
                "localIP": "127.0.0.1",
                "plugin": {
                    "type": "",
                    "ClientPluginOptions": null
                },
                "remotePort": 7002
            },
            "clientVersion": "0.54.0",
            "todayTrafficIn": 0,
            "todayTrafficOut": 0,
            "curConns": 0,
            "lastStartTime": "02-12 11:46:11",
            "lastCloseTime": "",
            "status": "online"
        }
    ]
}
```

**Get Specific Proxy Details**:
```bash
# Replace 'vm-base-gpu-ssh' with your proxy name
curl -u "${FRP_USER}:${FRP_PASSWORD}" \
  "${FRP_API_URL}/proxy/tcp/vm-uo0nwf"
```

**API Response Status Codes**:
- `200`: Success
- `401`: Authentication failed (invalid credentials)
- `404`: Resource not found (proxy/client doesn't exist)
- `500`: Server error

**Note**: The FRP Dashboard API runs on port 7001 (localhost only by default). For remote access, either use an SSH tunnel or access via the Nginx reverse proxy at `https://frp-admin.<domain>/api`.

### VM Management Operations (vm-management role)
- **VM Lifecycle Management**: Complete VM operations including create, start, stop, shutdown, reboot, destroy, undefine, and reset-password
- **Multi-GPU VM Support**: Advanced GPU allocation with IOMMU group detection, device passthrough configuration, and GPU combination selection scripts
- **Resource Validation**: VM creation prerequisites checking, hardware resource availability, network configuration validation
- **Lease Management**: VM lease scheduling with automatic termination at expiration time, comprehensive cleanup operations, and scheduled shutdown capabilities
- **Performance Monitoring**: Comprehensive VM metrics collection including CPU usage, memory consumption, storage utilization, and network statistics
- **Health Checks**: VM status verification, process monitoring, and operational state validation
- **JSON Output Formatting**: Structured data output for monitoring systems and API integration
- **Inventory Management**: VM listing and registration, automatic Ansible inventory updates, and resource tracking
- **Network Isolation**: Tenant-specific network configuration, bridge setup, and traffic segmentation
- **Storage Management**: Dynamic disk allocation, tenant-specific storage pools, and resource quota enforcement

#### Execution Flow

The modular architecture orchestrates VM operations in the following flow:

```yaml
1. Main Dispatcher (main.yml)
   └── Routes to appropriate task file based on vm_action

2. Prerequisites & Validation (prerequisites.yml)
   ├── Root access setup
   ├── Resource quota checks
   ├── VM existence validation
   └── Tenant resource allocation checks

3. VM Creation Flow (vm-create.yml)
   ├── SSH key generation (root and tenant)
   ├── Network Mode Selection
   │   ├── Direct Port Forwarding: Random port assignment (10000-20000)
   │   └── FRP Proxy Mode: Subdomain and port detection (7002-8000)
   ├── Image Source Selection
   │   ├── Scratch: Cloud-init configuration and Ubuntu download
   │   └── Golden: GCS image retrieval or local image copy
   ├── GPU Provisioning (when vm_gpu_provisioned=true)
   │   ├── Single GPU: gpu-virt-install-retry.yml with retry logic
   │   └── Multi-GPU: gpu-virt-install-multi.yml parallel setup
   ├── VM Installation (virt-install)
   ├── Boot Wait and IP Detection
   ├── FRP Configuration (when frp_server_addr defined)
   │   ├── Generate 6-character subdomain
   │   ├── Detect available remote port via SSH scan
   │   ├── Configure FRP client proxy
   │   └── Restart FRP client
   ├── Network Configuration
   │   ├── Direct Mode: iptables port forwarding + firewall rules
   │   └── FRP Mode: Skip port forwarding (handled by FRP)
   ├── Post-Boot Configuration
   │   ├── Hostname and instance-id setup
   │   ├── Tenant user creation
   │   ├── SSH key deployment
   │   └── Access verification
   ├── Inventory Management
   │   ├── Direct Mode: ansible_host=target_host, ansible_port=external_ssh_port
   │   └── FRP Mode: ansible_host=subdomain.frp_domain, ansible_port=frp_remote_port
   └── JSON Output Generation

4. VM Lifecycle Operations
   ├── vm-start.yml: Startup and readiness verification
   ├── vm-shutdown.yml: Graceful shutdown via qemu-guest-agent
   ├── vm-destroy.yml: Force stop operation
   ├── vm-reboot.yml: Restart with state verification
   └── vm-undefine.yml: Complete removal with cleanup
       ├── Stop VM if running
       ├── Remove disk storage
       ├── Clean firewall rules (direct mode only)
       ├── Remove FRP proxy configuration (FRP mode only)
       ├── Undefine from libvirt
       └── Update inventory

5. Advanced Operations
   ├── vm-monitor.yml: Comprehensive performance monitoring
   ├── vm-reset-password.yml: SSH-based credential management
   ├── vm-lease-end.yml: Schedule automatic lease expiration with VM destruction
   ├── vm-lease-remove.yml: Cancel scheduled lease end and remove cleanup jobs
   ├── vm-list.yml: Enumerate all VMs on host
   └── vm-check.yml: Host resources and system health verification

6. Error Handling & Cleanup
   ├── Resource cleanup on failures
   ├── Firewall rule removal (direct mode)
   ├── FRP proxy removal (FRP mode)
   ├── Storage cleanup
   └── Comprehensive error reporting
```

#### VM Management Command Examples

**Create VM with GPU Passthrough** (recommended method using variables file):
```bash
cat > /tmp/vm_vars.yml << 'EOF'
vm_host: kvm1
vm_target: vm-base-gpu
vm_action: create
vm_ram: 8192
vm_vcpus: 4
vm_disk_size: 20G
vm_tenant_pubkey: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINjmOBBEpr7KvLbsmjLOaqmPahELCroCiTYEjQ+p6yRM buyer@example.com"
vm_gpu_provisioned: true
vm_gpu_count: 2
image_setup_type: scratch
frp_domain: vm.arkhai.io
frp_server_addr: 192.168.100.61
frp_dashboard_password: "prFHMe8bsiOgTOM8I39udN0lD9h4Nt2W"
EOF

ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    --extra-vars @inventory/management-vars.yaml \
    --extra-vars @/tmp/vm_vars.yml \
    --limit kvm1
```

**Create VM without GPU**:
```bash
cat > /tmp/vm_vars.yml << 'EOF'
vm_host: kvm1
vm_target: vm-base-gpu
vm_action: create
vm_ram: 4096
vm_vcpus: 2
vm_disk_size: 10G
vm_tenant_pubkey: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINjmOBBEpr7KvLbsmjLOaqmPahELCroCiTYEjQ+p6yRM buyer@example.com"
vm_gpu_provisioned: false
image_setup_type: scratch
frp_domain: vm.arkhai.io
frp_server_addr: 192.168.100.61
frp_dashboard_password: "prFHMe8bsiOgTOM8I39udN0lD9h4Nt2W"
EOF

ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    --extra-vars @inventory/management-vars.yaml \
    --extra-vars @/tmp/vm_vars.yml \
    --limit kvm1
```

**Start VM**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=start \
    --limit kvm1
```

**Shutdown VM Gracefully**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=shutdown \
    --limit kvm1
```

**Reboot VM**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=reboot \
    --limit kvm1
```

**Force Destroy VM** (immediate shutdown):
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=destroy \
    --limit kvm1
```

**Undefine VM** (delete VM and all resources):
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e "@inventory/management-vars.yaml" \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=undefine \
    --limit kvm1
```

**Monitor VM Performance**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=monitor \
    --limit kvm1
```

**List All VMs on Host**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_action=list \
    --limit kvm1
```

**Check Host Resources and Status**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_action=check \
    --limit kvm1
```

**Reset VM Tenant Password**:
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=reset_password \
    --limit kvm1
```

**Schedule VM Lease End** (set when lease expires and VM will be automatically destroyed and cleaned up):
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=lease_end \
    -e '{"vm_lease_end":"2026-02-23 10:45"}' \
    --limit kvm1
```

**Note**: The lease end action schedules an automatic VM destruction and complete cleanup at the specified UTC time. All execution details (VM destroy, network cleanup, SSH key removal, storage deletion) are logged to a single file at `/var/log/vm-lease-end/<vm-name>/lease_end_*.log` on the target host. To check execution status after the lease expires:
```bash
ssh kvm1 'cat /var/log/vm-lease-end/vm-base-gpu/lease_end_*.log'
```

**Cancel Scheduled Lease End** (remove scheduled lease termination):
```bash
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=lease_remove \
    --limit kvm1
```

**Create VM with Specific Tags**:
```bash
# Only run VM creation tasks
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    --extra-vars @/tmp/vm_vars.yml \
    --tags vm_create \
    --limit kvm1

# Only run monitoring tasks
ansible-playbook -i inventory/hosts playbooks/single-tenant/vm-operations.yaml \
    -e vm_host=kvm1 \
    -e vm_target=vm-base-gpu \
    -e vm_action=monitor \
    --tags vm_monitor \
    --limit kvm1
```

**Parameter Reference for VM Creation**:
- `vm_host`: KVM host where VM will be created (from inventory, e.g., `kvm1`)
- `vm_target`: Name/identifier for the VM (e.g., `vm-base-gpu`, `customer-vm-001`)
- `vm_action`: Operation to perform (`create`, `start`, `shutdown`, `reboot`, `destroy`, `undefine`, `monitor`, `list`, `check`, `reset_password`, `lease_end`, `lease_remove`)
- `vm_ram`: RAM allocation in MB (e.g., `4096` = 4GB, `8192` = 8GB)
- `vm_vcpus`: Number of virtual CPUs (e.g., `2`, `4`, `8`)
- `vm_disk_size`: Disk size with unit (e.g., `10G`, `20G`, `50G`)
- `vm_tenant_pubkey`: SSH public key for tenant access (full key string)
- `vm_gpu_provisioned`: Enable GPU passthrough (`true` or `false`)
- `vm_gpu_count`: Number of GPUs to allocate (only when `vm_gpu_provisioned: true`)
- `image_setup_type`: Base image type (`scratch` for Ubuntu cloud image, `golden` for custom image)
- `frp_domain`: FRP domain for remote access (e.g., `vm.arkhai.io`)
- `frp_server_addr`: IP address of FRP server (e.g., `192.168.100.61`)
- `frp_dashboard_password`: FRP dashboard API password for proxy registration
- `vm_lease_end`: Lease expiration datetime in UTC format `YYYY-MM-DD HH:MM` (e.g., `2026-02-23 10:45`) - use JSON format in command: `-e '{"vm_lease_end":"2026-02-23 10:45"}'`

**Available Actions**:
- `create`: Create new VM with specified resources
- `start`: Start an existing stopped VM
- `shutdown`: Graceful ACPI shutdown (recommended)
- `reboot`: Graceful restart of VM
- `destroy`: Force immediate shutdown (not graceful)
- `undefine`: Delete VM and all associated resources permanently
- `monitor`: Get performance metrics (CPU, RAM, disk, network)
- `list`: List all VMs on the host with status
- `check`: Check host resources, available GPUs, and system health
- `reset_password`: Generate new tenant password and update VM
- `lease_end`: Schedule when the VM lease will expire (VM will be automatically destroyed and cleaned up at specified time)
- `lease_remove`: Cancel scheduled lease end and remove cleanup jobs

**Available Tags**:
- `vm_create`: VM creation tasks only
- `vm_start`: VM start tasks only
- `vm_shutdown`: VM shutdown tasks only
- `vm_reboot`: VM reboot tasks only
- `vm_destroy`: VM destroy tasks only
- `vm_undefine`: VM undefine/delete tasks only
- `vm_monitor`: VM monitoring tasks only
- `vm_list`: VM listing tasks only
- `vm_check`: Host check tasks only
- `vm_reset_password`: Password reset tasks only
- `vm_lease_end`: Lease end tasks only
- `vm_lease_remove`: Lease removal tasks only
- `always`: Prerequisites and JSON output (runs with all actions)

**Output Formats**:
All VM operations provide JSON-formatted output for API integration. Example create output:
```json
{
  "vm_name": "vm-base-gpu",
  "vm_host": "kvm1",
  "status": "running",
  "resources": {
    "ram_mb": 8192,
    "vcpus": 4,
    "disk_gb": 20
  },
  "network": {
    "ip": "192.168.122.10",
    "ssh_port": 7002
  },
  "access": {
    "ssh_command": "ssh -p 7002 tenant@192.168.100.61",
    "tenant_user": "tenant"
  },
  "gpu": {
    "enabled": true,
    "count": 2
  }
}
```

**Important Notes**:
- Use variables file method (`--extra-vars @/tmp/vm_vars.yml`) for VM creation to preserve SSH key formatting
- VM names are automatically generated if not specified: `vm-<random-6-chars>`
- FRP SSH ports are automatically allocated from available range (7002-8000)
- SSH keys are auto-generated if `vm_tenant_pubkey` is not provided
- Credentials are saved to `ansible/keys/<vm-name>/` directory
- Monitor action provides real-time metrics without requiring VM restart
- GPU passthrough requires host setup with `gpu_passthrough` tag enabled

### Docker Application Deployment (docker-app role) - Optional

Deploys Docker containers from any registry (GCP Artifact Registry, Docker Hub, or generic registries) and configures Nginx reverse proxy with configurable ports.

#### Features
- **Docker Engine Installation**: Complete Docker CE installation with containerd, docker-compose plugin, and systemd service management
- **Multi-Registry Support**: Docker Hub authentication, GCP Artifact Registry integration with service account keys, and generic registry support
- **Container Lifecycle Management**: Automated container deployment, environment variable configuration, volume mounting, and port mapping
- **Nginx Reverse Proxy**: HTTP reverse proxy configuration with WebSocket support, buffer size optimization, and custom location blocks
- **ACME Challenge Helper**: Nginx configuration creation of minimal web presence for ACME challenge validation to allow SSL certificates even though the actual service operates on different protocols.
- **SSL/TLS Termination**: Let's Encrypt certificate automation with Certbot, DNS validation, and HTTPS redirection
- **FRP Subdomain Integration**: Automatic subdomain routing for containerized applications through FRP tunnels
- **Health Monitoring**: Container status tracking, nginx access/error logging, and deployment statistics collection
- **Firewall Integration**: UFW rule management for HTTP/HTTPS access when SSL is enabled
- **Service Orchestration**: Nginx service management, container restart policies, and systemd integration

#### Architecture & Port Flow

The role sets up a layered proxy architecture:

```
External Request → Nginx (app_nginx_port) → localhost:app_container_port → Container (app_container_internal_port)
```

**Important**: `app_nginx_port` and `app_container_port` **must be different** to avoid conflicts.

Example with ports:
- `app_nginx_port=8888` - Nginx listens publicly on 8888
- `app_container_port=8002` - Docker publishes container to localhost:8002 (internal only)
- `app_container_internal_port=8080` - Container's actual internal port

Flow: **External:8888 → Nginx:8888 → localhost:8002 → Container:8080**

#### Quick Start Examples

**1. Public Docker Hub Image (e.g., nginx)**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_image_name=nginx" \
  -e "docker_image_tag=alpine" \
  -e "app_container_name=my-nginx" \
  -e "app_container_internal_port=80" \
  -e "app_container_port=8002" \
  -e "app_nginx_port=8888" \
  -e "app_nginx_site_name=my-nginx" \
  --limit myserver
```

**2. GCP Artifact Registry**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=my-project" \
  -e "gcp_registry_region=us-central1" \
  -e "gcp_repository=my-repo" \
  -e "gcp_service_account_key=/path/on/your/local/machine/sa-key.json" \
  -e "docker_image_name=my-app" \
  -e "docker_image_tag=v1.0.0" \
  -e "app_container_name=my-app" \
  -e "app_container_internal_port=8080" \
  -e "app_container_port=8002" \
  -e "app_nginx_port=8888" \
  -e "app_nginx_site_name=my-app" \
  --limit myserver
```

> The service account key JSON file is read from the **Ansible controller machine**, copied securely to the VM, used to authenticate, and then deleted from the VM. Docker is logged out from the GCP endpoint after the image is pulled.

**3. Private Docker Hub Image**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "dockerhub_username=myuser" \
  -e "dockerhub_password=mypass" \
  -e "docker_image_name=myuser/myapp" \
  -e "app_container_name=myapp" \
  -e "app_container_internal_port=3000" \
  -e "app_container_port=8002" \
  -e "app_nginx_port=8888" \
  -e "app_nginx_site_name=myapp" \
  --limit myserver
```

**4. Generic Registry**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=generic" \
  -e "docker_registry_url=registry.example.com" \
  -e "docker_registry_username=user" \
  -e "docker_registry_password=pass" \
  -e "docker_image_name=registry.example.com/namespace/myapp" \
  -e "app_container_internal_port=5000" \
  -e "app_container_port=8002" \
  -e "app_nginx_port=8888" \
  -e "app_nginx_site_name=myapp" \
  --limit myserver
```

**5. With FRP Subdomain and SSL Certificate**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=principia-infrastructure-dev" \
  -e "gcp_registry_region=asia-southeast1" \
  -e "gcp_repository=erc-8004-registry" \
  -e "gcp_service_account_key=/path/on/your/local/machine/sa-key.json" \
  -e "docker_image_name=erc-8004-registry" \
  -e "docker_image_tag=latest" \
  -e "app_container_name=erc-registry" \
  -e "app_container_internal_port=8080" \
  -e "app_container_port=8002" \
  -e "app_nginx_port=8888" \
  -e "app_nginx_site_name=erc-registry" \
  -e "frp_subdomain_host=vm.arkhai.io" \
  -e "enable_ssl=true" \
  -e "certbot_email=admin@example.com" \
  --limit proxy-dev
```

Access: `https://erc-registry.vm.arkhai.io/` (with SSL) or `http://erc-registry.vm.arkhai.io:8888/` (without SSL)

#### Required Variables

All deployments need these:

```yaml
docker_image_name: "image-name"              # Image name or full path
app_container_name: "unique-name"            # Unique container name
app_container_internal_port: 8080            # Container's internal port
app_container_port: 8002                     # Port published to host (must differ from nginx)
app_nginx_port: 8888                         # Port nginx listens on (default: 8080)
app_nginx_site_name: "unique-name"           # Unique nginx site name
```

#### Registry-Specific Variables

**GCP Artifact Registry**:
```yaml
docker_registry_type: "gcp"
gcp_project_id: "your-project-id"
gcp_registry_region: "us-central1"
gcp_repository: "your-repo"
docker_image_name: "app-name"                             # Just the image name
gcp_service_account_key: "/local/path/to/sa-key.json"    # Path on Ansible controller machine
```

> The key file is copied from the local machine to the VM at `/tmp/gcp-sa-key.json` (mode `0600`), used for `docker login`, then deleted. Docker is logged out from `https://<region>-docker.pkg.dev` after the pull completes.

**Docker Hub**:
```yaml
# Public images - no auth needed
docker_image_name: "nginx"           # Official image
docker_image_name: "user/image"      # User image

# Private images
dockerhub_username: "username"
dockerhub_password: "password"
docker_image_name: "user/private-image"
```

**Generic Registry**:
```yaml
docker_registry_type: "generic"
docker_registry_url: "registry.example.com"
docker_registry_username: "username"
docker_registry_password: "password"
docker_image_name: "registry.example.com/namespace/image"
```

#### Optional Variables

```yaml
# Image
docker_image_tag: "latest"           # Default: latest

# Container
app_container_env:
  NODE_ENV: "production"
  DATABASE_URL: "postgresql://..."
app_container_volumes:
  - "/host/path:/container/path"
  - "volume-name:/container/path"

# Nginx
app_nginx_server_name: "_"           # Default, or "yourdomain.com"
app_nginx_path: "/"                  # Default, or "/api" for subpath

# Network Mode
docker_network_mode: "bridge"        # Default: bridge (port-mapped). Set to "host" to use host networking (e.g. for ZeroTier access)

# FRP Subdomain Support (if frp-setup role configured)
frp_subdomain_host: "example.com"    # Wildcard DNS domain (e.g., vm.arkhai.io)
# Results in: app_nginx_site_name.frp_subdomain_host
# Example: my-app.example.com

# SSL/TLS Certificate (via Let's Encrypt)
enable_ssl: true                     # Default: false
certbot_email: "admin@example.com"   # Email for Let's Encrypt notifications
# Note: DNS must be properly configured and pointing to server before SSL setup
# Certbot automatically configures HTTPS redirect in nginx
```

#### Host Network Mode (ZeroTier Access)

By default the container runs with `bridge` networking and its port is mapped to the host via `-p app_container_port:app_container_internal_port`. When the deployment target is a bare-metal machine joined to a **ZeroTier** (or similar overlay) network, you may want the container to bind directly to the host's network stack so it is reachable on the ZeroTier IP without any extra port-forwarding rules.

Set `docker_network_mode=host` to enable this:
- The container shares the host's network namespace and binds its port directly on all interfaces (including ZeroTier).
- No `-p` port mapping is created — the container is accessible on `localhost:<app_container_internal_port>` and on every host IP, including the ZeroTier IP.
- Nginx still proxies to `127.0.0.1:<app_container_port>` as usual — no nginx changes are needed.
- `app_container_port` and `app_container_internal_port` should be set to the **same value** when using host mode, since there is no port translation.

**Example — Async Provisioning Service accessible over ZeroTier**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=arkhai-io" \
  -e "gcp_registry_region=us-east4" \
  -e "gcp_repository=async-provisioning-service" \
  -e "gcp_service_account_key=~/Downloads/key-reader.json" \
  -e "docker_image_name=async-provisioning-service" \
  -e "docker_image_tag=v0.1.3" \
  -e "app_container_name=provisioner" \
  -e "app_container_internal_port=8081" \
  -e "app_container_port=8081" \
  -e "app_nginx_port=8888" \
  -e "docker_network_mode=host" \
  -e "app_nginx_site_name=provisioner" \
  --limit provisioning-dev
```

The service will be reachable at:
- `http://<zerotier-ip>:8081` — direct ZeroTier access (bypasses Nginx)
- `http://localhost:8888` — via the Nginx reverse proxy

> **Note**: `network_mode: host` is Linux-only. It is not supported on Docker Desktop for macOS/Windows.

#### Multiple Applications

Deploy multiple apps on the same server using different ports and names:

```bash
# App 1
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_image_name=nginx" \
  -e "app_container_name=app1" \
  -e "app_container_internal_port=80" \
  -e "app_container_port=8002" \
  -e "app_nginx_port=8888" \
  -e "app_nginx_site_name=app1" \
  --limit myserver

# App 2
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_image_name=httpd" \
  -e "app_container_name=app2" \
  -e "app_container_internal_port=80" \
  -e "app_container_port=8004" \
  -e "app_nginx_port=8003" \
  -e "app_nginx_site_name=app2" \
  --limit myserver
```

Access:
- App 1: `http://server:8888/`
- App 2: `http://server:8003/`

#### Container Management

```bash
# View containers
docker ps
docker ps -a  # Include stopped

# View logs
docker logs my-app
docker logs -f my-app  # Follow

# Restart/Stop
docker restart my-app
docker stop my-app
docker start my-app

# Remove
docker stop my-app && docker rm my-app
```

#### Nginx Management

```bash
# View sites
ls -la /etc/nginx/sites-enabled/

# Test config
nginx -t

# View logs
tail -f /var/log/nginx/my-app-access.log
tail -f /var/log/nginx/my-app-error.log

# Disable site
rm /etc/nginx/sites-enabled/my-app
systemctl reload nginx
```

#### Troubleshooting

**Container won't start**:
```bash
docker logs my-app
docker inspect my-app
```

**Can't access via nginx**:
```bash
# Test direct container access (use app_container_port)
curl http://localhost:8002

# Test nginx proxy (use app_nginx_port)
curl http://localhost:8888/

# Check nginx logs
tail -f /var/log/nginx/my-app-error.log
```

**Port already in use**:
```bash
# Find what's using the port
sudo lsof -i :8002

# Use different ports - remember they must be different!
-e "app_container_port=8004" \
-e "app_nginx_port=8003"
```

**Port validation fails**: Error: "app_container_port and app_nginx_port must be different"
- `app_nginx_port`: Public-facing port (e.g., `8888`)
- `app_container_port`: Internal port Docker publishes (e.g., `8002`)
- `app_container_internal_port`: Container's actual port (e.g., `8080`)

**Authentication issues**:
```bash
# Test registry login
docker login registry.example.com

# For GCP - verify service account key file exists locally
ls -la /path/to/sa-key.json
```

**SSL Certificate Issues**:
- DNS not configured: ensure subdomain DNS record points to server IP. Test: `dig +short your-app.your-domain.com`
- Certificate renewal: `certbot renew --dry-run` (dry run) or `certbot renew --force-renewal`
- Certbot fails: ensure ports 80 and 443 are open, nginx is running (`systemctl status nginx`), check `/var/log/letsencrypt/letsencrypt.log`

#### Deployment Output

The role returns JSON deployment information via `ansible_stats`:

**With FRP Subdomain**:
```json
{
  "app_name": "erc-registry",
  "container_name": "erc-registry",
  "nginx_port": 8888,
  "container_port": 8002,
  "internal_port": 8080,
  "nginx_url": "http://erc-registry.vm.arkhai.io:8888/",
  "image": "asia-southeast1-docker.pkg.dev/principia-infrastructure-dev/erc-8004-registry/erc-8004-registry:latest"
}
```

**With SSL enabled**:
```json
{
  "app_name": "erc-registry",
  "nginx_url": "https://erc-registry.vm.arkhai.io/",
  "ssl_enabled": true
}
```

**Without FRP (direct access)**:
```json
{
  "app_name": "my-app",
  "nginx_url": "http://hostname:8888/",
  "image": "us-central1-docker.pkg.dev/project/repo/my-app:v1.0.0"
}
```

**Note**:
- Without SSL: URL includes port (e.g., `http://erc-registry.vm.arkhai.io:8888/`)
- With SSL: Certbot configures nginx for standard HTTPS port 443 with redirect (e.g., `https://erc-registry.vm.arkhai.io/`)
- FRP subdomain uses wildcard DNS from Cloudflare, nginx handles the actual port routing

#### Docker Application Deployment Command Examples

**Deploy from GCP Artifact Registry with SSL and Environment Variables**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=my-gcp-project-123" \
  -e "gcp_registry_region=asia-southeast1" \
  -e "gcp_repository=my-app-registry" \
  -e "gcp_service_account_key=/path/on/your/local/machine/sa-key.json" \
  -e "docker_image_name=my-app-api" \
  -e "docker_image_tag=v1.0.0" \
  -e "app_container_name=my-app-container" \
  -e "app_container_internal_port=8080" \
  -e "app_container_port=8001" \
  -e "app_nginx_port=8888" \
  -e "frp_subdomain_host=vm.arkhai.io" \
  -e "enable_ssl=true" \
  -e "certbot_email=admin@vm.arkhai.io" \
  -e "app_nginx_site_name=my-app" \
  -e '{"app_container_env":{"DATABASE_URL":"postgresql://user:pass@db.example.com/mydb?sslmode=require","API_KEY":"your-api-key-here","PORT":"8080","HOST":"0.0.0.0","LOG_LEVEL":"info"}}' \
  --limit proxy-dev
```

**Parameter Reference**:
- `docker_registry_type`: Registry type - `gcp`, `dockerhub`, or `generic` (omit for Docker Hub public images)
- `gcp_project_id`: GCP project ID (when using GCP Artifact Registry)
- `gcp_registry_region`: GCP registry region (e.g., `asia-southeast1`, `us-central1`)
- `gcp_repository`: GCP Artifact Registry repository name
- `gcp_service_account_key`: **Local file path** on the Ansible controller machine to the GCP service account JSON key. The file is copied to the VM, used to authenticate, then deleted. Docker is logged out from the GCP endpoint after the pull.
- `docker_image_name`: Docker image name (e.g., `my-app-api`, `nginx`)
- `docker_image_tag`: Image tag/version (default: `latest`)
- `app_container_name`: Container name for identification
- `app_container_port`: Host port to expose container on (e.g., `8001`, `8080`)
- `app_container_internal_port`: Container's internal port (e.g., `8080`, `3000`)
- `app_nginx_port`: Nginx listening port (e.g., `8888`, `8080`)
- `app_nginx_site_name`: Nginx site configuration name and subdomain prefix
- `frp_subdomain_host`: FRP domain for subdomain routing (e.g., `vm.arkhai.io`)
- `enable_ssl`: Enable Let's Encrypt SSL certificates (`true` or `false`)
- `certbot_email`: Email for Let's Encrypt notifications
- `app_container_env`: JSON dictionary of environment variables for the container
- `app_container_volumes`: List of volume mounts in `host:container` format (optional)

**Access URLs**:
- HTTP: `http://my-app.vm.arkhai.io:8888` (via FRP tunnel)
- HTTPS: `https://my-app.vm.arkhai.io` (with SSL enabled)

**Note**: This role is optional and typically deployed on the FRP server to run additional services alongside the proxy. The example shows GCP Artifact Registry deployment - for Docker Hub or other registries, adjust `docker_registry_type` and authentication parameters accordingly.

### ERC Registry Deployment
- **Blockchain Registry Service**: ERC-8004 compliant identity and reputation registry for blockchain networks
- **PostgreSQL Integration**: External Neon database connection with SSL/TLS security
- **Smart Contract Integration**: Connects to Ethereum-compatible chains (e.g., Base Sepolia) via RPC endpoints
- **Health Monitoring**: Configurable health checks and heartbeat mechanisms for service reliability

**Deploy Registry from GCP Artifact Registry**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=<gcp-project-id>" \
  -e "gcp_registry_region=asia-southeast1" \
  -e "gcp_repository=arkhai" \
  -e "gcp_service_account_key=/path/to/sa-key.json" \
  -e "docker_image_name=registry" \
  -e "docker_image_tag=latest" \
  -e "app_container_name=arkhai-registry" \
  -e "app_container_internal_port=8080" \
  -e "app_container_port=8001" \
  -e "app_nginx_port=8888" \
  -e "frp_subdomain_host=vm.arkhai.io" \
  -e "enable_ssl=true" \
  -e "certbot_email=admin@vm.arkhai.io" \
  -e "app_nginx_site_name=arkhai-registry" \
  -e '{"app_container_env":{"DATABASE_URL":"postgresql://neondb_owner:password@us-east-1.aws.neon.tech/arkhai-registry?sslmode=require&channel_binding=require","PORT":"8080","HOST":"0.0.0.0","ENABLE_HEALTH_CHECKS":"false","HEALTH_CHECK_INTERVAL":"60","ENDPOINT_CHECK_TIMEOUT":"10","HEARTBEAT_TTL_SECS":"60","LOG_LEVEL":"info"}}' \
  --limit proxy-dev
```

> The service account key JSON file is read from the **Ansible controller machine**, copied securely to the VM, used to activate the SA in gcloud and configure the Docker credential helper, then deleted from the VM. Docker is logged out from the GCP endpoint after the image is pulled.

**Registry Specific Parameters**:
- `docker_registry_type`: Set to `gcp` for GCP Artifact Registry
- `gcp_project_id`: GCP project ID containing the Artifact Registry
- `gcp_registry_region`: Registry region (e.g., `asia-southeast1`)
- `gcp_repository`: Artifact Registry repository name (`arkhai`)
- `gcp_service_account_key`: Local path on Ansible controller machine to the service account JSON key file
- `docker_image_name`: Image name in the repository (`registry`)
- `docker_image_tag`: Image version tag (`latest`)
- `app_container_name`: Container identifier (`erc-registry`)
- `app_container_internal_port`: Port the application listens on inside the container (`8080`)
- `app_container_port`: Host port mapped to container (`8001` - direct access port)
- `app_nginx_port`: Nginx reverse proxy port (`8888` - HTTP access port)
- `frp_subdomain_host`: Base domain for FRP subdomain routing (`vm.arkhai.io`)
- `enable_ssl`: Enable HTTPS with Let's Encrypt (`true`)
- `certbot_email`: Email for SSL certificate notifications
- `app_nginx_site_name`: Nginx site config name and subdomain prefix (`erc-registry`)

**ERC Registry Environment Variables** (in `app_container_env`):
- `DATABASE_URL`: PostgreSQL connection string with Neon database credentials
  - Format: `postgresql://user:password@host/database?sslmode=require&channel_binding=require`
  - Uses SSL/TLS encryption for secure database connections
- `CHAIN_ID`: Blockchain network identifier (`22313` for target network)
- `RPC_URL`: Ethereum RPC endpoint URL for blockchain interactions (e.g., Base Sepolia via Infura)
- `IDENTITY_REGISTRY_ADDRESS`: Smart contract address for ERC-8004 identity registry
- `REPUTATION_REGISTRY_ADDRESS`: Smart contract address for reputation scoring system
- `PORT`: Internal application port (`8080` - must match `app_container_internal_port`)
- `HOST`: Bind address (`0.0.0.0` - listen on all interfaces within container)
- `ENABLE_HEALTH_CHECKS`: Enable/disable endpoint health monitoring (`false` to disable)
- `HEALTH_CHECK_INTERVAL`: Seconds between health checks (`60`)
- `ENDPOINT_CHECK_TIMEOUT`: Timeout for individual health checks in seconds (`10`)
- `HEARTBEAT_TTL_SECS`: Service heartbeat time-to-live in seconds (`60`)
- `LOG_LEVEL`: Logging verbosity level (`info`, `debug`, `warn`, `error`)

**Access URLs**:
- HTTP: `http://erc-registry.vm-staging.arkhai.io:8888` (via FRP tunnel)
- HTTPS: `https://erc-registry.vm-staging.arkhai.io` (with SSL enabled)
- Direct Access: `http://<server-ip>:8001` (bypasses Nginx, FRP only)

**Security Considerations**:
- Database credentials use SSL mode with channel binding for enhanced security
- Smart contract addresses should be verified on blockchain explorer before deployment
- RPC endpoint should use authenticated/rate-limited access (replace `<ID>` with actual Infura project ID)
- Environment variables contain sensitive data - use Ansible Vault for production deployments

**Firewall Ports Opened**:
- Port `80`: HTTP (for Let's Encrypt ACME challenges)
- Port `443`: HTTPS (SSL-secured access to ERC Registry)
- Port `8888`: HTTP access via Nginx reverse proxy
- Port `8001`: Direct container access (optional, can be firewalled)
- Port `18080`: Host-network access for a colocated registry on the FRP/UFW gateway host when the production-style canary uses ZeroTier-reachable direct health/API access

If you colocate the registry on the FRP gateway host for a production-style canary,
keep `18080/tcp` open in UFW so the service stays reachable on the host ZeroTier
address. Otherwise the container can be healthy locally while remote ZeroTier peers
still time out.

### Async Provisioning Service Deployment
- **VM Provisioning Worker**: Asynchronous job queue service for handling VM creation, lifecycle, and teardown operations
- **Redis-Backed Queue**: Job scheduling and processing via Redis queue for reliable async workloads
- **Ansible Integration**: Executes Ansible playbooks for VM management with configurable timeouts
- **FRP Integration**: Communicates with FRP server for VM network proxy registration
- **ERC Registry Integration**: Integrates with local ERC Registry for resource and identity lookups
- **Auth Support**: Optional token-based authentication via `ENABLE_AUTH` flag

**Deploy Async Provisioning Service from GCP Artifact Registry**:
```bash
ansible-playbook -i inventory/hosts playbooks/frp/docker-app-setup.yaml \
  -e "docker_registry_type=gcp" \
  -e "gcp_project_id=<gcp-project-id>" \
  -e "gcp_registry_region=asia-southeast1" \
  -e "gcp_repository=async-provisioning-service" \
  -e "gcp_service_account_key=/path/to/sa-key.json" \
  -e "docker_image_name=async-provisioning-service" \
  -e "docker_image_tag=latest" \
  -e "app_container_name=provisioner" \
  -e "app_container_internal_port=8081" \
  -e "app_container_port=8001" \
  -e "app_nginx_port=8888" \
  -e "frp_subdomain_host=vm-market.arkhai.io" \
  -e "enable_ssl=true" \
  -e "certbot_email=admin@vm-market.arkhai.io" \
  -e "app_nginx_site_name=provisioner" \
  -e '{"app_container_env": {"HOST":"0.0.0.0","PORT":"8081","LOG_LEVEL":"info","DATABASE_URL":"postgresql+psycopg2://postgres:postgres@<postgres-host>:5432/provisioning","REDIS_URL":"redis://<redis-host>:6379/0","REDIS_QUEUE_NAME":"provisioning_jobs","ANSIBLE_TIMEOUT_SECONDS":"1800","ANSIBLE_BECOME_PASS":"vmhostuserpassword","DEFAULT_VM_HOST":"kvm1","FRP_SERVER_ADDR":"34.87.54.66","FRP_DOMAIN":"vm.arkhai.io","FRP_DASHBOARD_PASSWORD":"frpadashboardapipassword","ENABLE_AUTH":"true","AUTH_FAIL_OPEN":"false","REGISTRY_URL":"https://<registry-url>","REGISTRY_CACHE_TTL_SECONDS":"300","REGISTRY_CACHE_MAX_SIZE":"256","SSH_PRIVATE_KEY":"<base64-encoded-ssh-private-key>","MANAGEMENT_VARS_YAML":"<base64-encoded-management-vars-yaml>"}}' \
  --limit provisioning-dev
```

> The service account key JSON file is read from the **Ansible controller machine**, copied securely to the VM, used to activate the SA in gcloud and configure the Docker credential helper, then deleted from the VM. Docker is logged out from the GCP endpoint after the image is pulled.

**Async Provisioning Service Specific Parameters**:
- `docker_registry_type`: Set to `gcp` for GCP Artifact Registry
- `gcp_project_id`: GCP project ID containing the Artifact Registry
- `gcp_registry_region`: Registry region (e.g., `asia-southeast1`)
- `gcp_repository`: Artifact Registry repository name (`async-provisioning-service`)
- `gcp_service_account_key`: Local path on Ansible controller machine to the service account JSON key file
- `docker_image_name`: Image name in the repository (`async-provisioning-service`)
- `docker_image_tag`: Image version tag (`latest`)
- `app_container_name`: Container identifier (`provisioner`)
- `app_container_internal_port`: Port the application listens on inside the container (`8081`)
- `app_container_port`: Host port mapped to container (`8001` - direct access port)
- `app_nginx_port`: Nginx reverse proxy port (`8888` - HTTP access port)
- `frp_subdomain_host`: Base domain for FRP subdomain routing (e.g., `vm-market.arkhai.io`)
- `enable_ssl`: Enable HTTPS with Let's Encrypt (`true`)
- `certbot_email`: Email for SSL certificate notifications
- `app_nginx_site_name`: Nginx site config name and subdomain prefix (`provisioner`)

**Async Provisioning Service Environment Variables** (in `app_container_env`):
- `HOST`: Bind address (`0.0.0.0` - listen on all interfaces within container)
- `PORT`: Internal application port (`8081` - must match `app_container_internal_port`)
- `LOG_LEVEL`: Logging verbosity (`info`, `debug`, `warn`, `error`)
- `DATABASE_URL`: PostgreSQL connection string for deployed environments
- `REDIS_URL`: Redis connection URL for job queue (e.g., `redis://<redis-host>:6379/0`)
- `REDIS_QUEUE_NAME`: Name of the Redis queue for provisioning jobs (`provisioning_jobs`)
- `ANSIBLE_TIMEOUT_SECONDS`: Timeout in seconds for Ansible playbook executions (`1800`)
- `ANSIBLE_BECOME_PASS`: Sudo password for Ansible privilege escalation on VM hosts
- `ENABLE_AUTH`: Keep `true` in deployed environments so the service enforces `X-Agent-ID`
- `AUTH_FAIL_OPEN`: Keep `false` so registry lookup failures do not bypass auth
- `DEFAULT_VM_HOST`: Default KVM host used for VM provisioning (e.g., `kvm1`)
- `FRP_SERVER_ADDR`: IP address of the FRP server for VM network proxy registration
- `FRP_DOMAIN`: FRP base domain for VM subdomain routing (e.g., `vm.arkhai.io`)
- `FRP_DASHBOARD_PASSWORD`: FRP dashboard API password for proxy management
- `ENABLE_AUTH`: Enable token-based API authentication (`true` or `false`)
- `REGISTRY_URL`: URL of the local ERC Registry service (e.g., `http://localhost:8080`)
- `REGISTRY_CACHE_TTL_SECONDS`: Cache TTL for ERC Registry responses in seconds (`300`)
- `REGISTRY_CACHE_MAX_SIZE`: Maximum number of cached registry entries (`256`)
- `SSH_PRIVATE_KEY`: base64-encoded SSH private key (no newlines). The container decodes it to `~/.ssh/id_ed25519` on startup. Encode with: `base64 < ~/.ssh/provisioner_ed25519 | tr -d '\n'`
- `MANAGEMENT_VARS_YAML`: base64-encoded `management-vars.yaml` (no newlines). The container decodes it to `/app/compute-provisioning-iac/ansible/inventory/management-vars.yaml` on startup. Required when using Golden Images (`vm_action=create` or `vm_action=undefine`). Encode with: `base64 < inventory/management-vars.yaml | tr -d '\n'`

**Access URLs**:
- HTTP: `http://provisioner.vm-market.arkhai.io:8888` (via FRP tunnel)
- HTTPS: `https://provisioner.vm-market.arkhai.io` (with SSL enabled)
- Direct Access: `http://<server-ip>:8001` (bypasses Nginx)

**Firewall Ports Opened**:
- Port `80`: HTTP (for Let's Encrypt ACME challenges)
- Port `443`: HTTPS (SSL-secured access to Provisioning Service)
- Port `8888`: HTTP access via Nginx reverse proxy
- Port `8001`: Direct container access (optional, can be firewalled)

### ZeroTier Network Controller
- **Containerized Deployment**: ZeroTier Network Controller deployment uses the generic Docker application Ansible Playbook
- **Reverse Proxy**: Allows for non-9993 port entry via Nginx
- **SSL Certificate Enabled**: Valid SSL Certificate provides a trusted web presence

**Installation**:
```
## Utilize Terraform to retrieve ZeroTier Network Controller Registry information
# Initialize Terraform Remote State
cd ../terraform/<environment>
terraform init

# Retrieve Necessary Terraform Outputs
cat > ../../ansible/docker-vars.yaml <<EOF
docker_registry_type: gcp
gcp_project_id: $(terraform output -raw ansible_image_storage_project_id)
gcp_registry_region: $(terraform output -raw gcp_project_region)
gcp_repository: $(terraform output -raw zerotier_networkcontroller_registry_name)
docker_image_name: zero-tier
docker_image_tag: latest
app_container_name: zerotier-networkcontroller
app_container_internal_port: 9993
app_container_port: 9993
app_nginx_port: 80
frp_subdomain_host: <subdomain host>
enable_ssl: true
certbot_email: admin@<subdomain host>
app_nginx_site_name: ztnc
app_container_env:
  ZT_ENABLE_CONTROLLER: "true"
  ZT_ALLOW_TCP_FALLBACK: "1"
  ZT_ENABLE_API: "true"
EOF

# Prepare cwd to the ansible folder
cd ../../ansible
```

**Firewall Ports Opened****Firewall Ports Opened**:
- Port `9993`: TCP and UDP ZeroTier Network Controller access

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

[Add license information here]
