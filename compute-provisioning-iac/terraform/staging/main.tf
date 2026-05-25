resource "random_id" "resource_suffix" {
  byte_length = 4
}

locals {
  name_suffix = var.resource_suffix != "" ? "-${var.resource_suffix}" : ""
}

resource "google_storage_bucket" "remote_tfstate" {
  name                        = "${var.gcp_project_name}${local.name_suffix}-tfstate-${random_id.resource_suffix.hex}"
  location                    = var.gcp_project_region
  project                     = var.gcp_project_name
  uniform_bucket_level_access = true
}

# Compute Resource Storage
module "ansible_image_storage" {
  source             = "../common/modules/ansible_image_storage"
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
}

# Compute Resource Storage Service Account with Role
module "ansible_image_storage_rsa" {
  depends_on = [
    module.ansible_image_storage
  ]
  source                   = "../common/modules/ansible_image_storage_rsa"
  gcp_project_name         = var.gcp_project_name
  resource_suffix          = var.resource_suffix
  gcs_bucket_name          = module.ansible_image_storage.bucket_name
  storage_custom_role_id   = "gcs_ansible_bucket_uploader${replace(local.name_suffix, "-", "_")}"
  storage_custom_role_name = "GCS Ansible Bucket Uploader${local.name_suffix}"
  storage_sa_id            = "gcs-ansible-uploader${local.name_suffix}"
  storage_sa_name          = "GCS Ansible Bucket Uploader${local.name_suffix}"
  storage_sa_description   = "Uploads objects to a specific GCS bucket using a minimal custom role."
}

data "google_compute_network" "default" {
  name    = "default"
  project = var.gcp_project_name
}

# Async Provisioning Service
module "async_provisioning_service_registry" {
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  repository_id      = "async-provisioning-service"
  description        = "Async Provisioning Service"
}

# ERC 8004 Registry
module "erc_8004_registry" {
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  repository_id      = "erc-8004-registry"
  description        = "ERC-8004 Registry Indexer service"
}

# ZeroTier Network Controller
module "zerotier_networkcontroller_registry" {
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  repository_id      = "zerotier-networkcontroller-repo"
  description        = "Repo for ZeroTier Network Controller artifacts."
}

# Alkahest Registry (Python)
module "alkahest_registry" {
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  repository_id      = "alkahest-wheel-repo"
  description        = "Repo for Alkahest Python wheel artifacts."
  format             = "PYTHON"
}

# Puffer Registry (Python)
module "puffer_registry" {
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  repository_id      = "puffer-wheel-repo"
  description        = "Repo for Puffer Python wheel artifacts."
  format             = "PYTHON"
}

# Agent Registry (Docker)
module "agent_registry" {
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  repository_id      = "a2a-agent"
  description        = "Repo for Agent Docker artifacts."
}

# Artifact Registry Reader Service Account
# Grants pull / download access on a2a-agent, alkahest-wheel-repo, puffer-wheel-repo only.
# A single call here covers all three repos — no per-repo reader wiring needed.
module "artifact_registry_reader_sa" {
  depends_on = [
    module.alkahest_registry,
    module.puffer_registry,
    module.agent_registry,
  ]
  source           = "../common/modules/artifact_registry_reader_sa"
  enabled          = false
  gcp_project_name = var.gcp_project_name
  ar_location      = var.gcp_project_region
  sa_id            = "artifact-registry-reader-sa${local.name_suffix}"
  sa_name          = "Artifact Registry Reader SA${local.name_suffix}"
  sa_description   = "Service account with read-only access to a2a-agent, alkahest-wheel-repo, and puffer-wheel-repo."
}

# ERC FRP Server
module "erc_frp_ztnc_server" {
  source                      = "../common/modules/erc_frp_ztnc_server"
  gcp_project_name            = var.gcp_project_name
  gcp_project_region          = var.gcp_project_region
  gcp_project_zone            = "${var.gcp_project_region}-b"
  gcp_network_name            = data.google_compute_network.default.name
  erc_frp_firewall_name            = "arkhai${local.name_suffix}-guest-vm-open-ports-${random_id.resource_suffix.hex}"
  erc_frp_disk_name                = "arkhai${local.name_suffix}-erc-frp-ztnc-server-${random_id.resource_suffix.hex}"
  erc_frp_disk_size                = 10
  erc_frp_disk_image               = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20260128"
  erc_frp_ztnc_server_ip_name      = "arkhai${local.name_suffix}-erc-frp-ztnc-server-ip-${random_id.resource_suffix.hex}"
  erc_frp_ztnc_server_name         = "arkhai${local.name_suffix}-erc-frp-ztnc-server-${random_id.resource_suffix.hex}"
  erc_frp_ztnc_server_machine_type = "n2d-highcpu-2"
}

# Redis (Cloud Memorystore) — shared cache/queue for Docker images on the async provisioning server
module "agents_async_provisioning_redis" {
  source              = "../common/modules/redis"
  gcp_project_name    = var.gcp_project_name
  gcp_project_region  = var.gcp_project_region
  gcp_network_id      = data.google_compute_network.default.id
  redis_instance_name = "arkhai${local.name_suffix}-async-prov-redis-${random_id.resource_suffix.hex}"
  redis_display_name  = "Agents Async Provisioning Redis${local.name_suffix}"
  redis_tier          = "STANDARD_HA"
  redis_memory_size_gb = 2
  redis_version       = "REDIS_7_0"
  environment_label   = "staging"
}

# Agents Async Provisioning Server
module "agents_async_provisioning_server" {
  source                                 = "../common/modules/agents_async_provisioning_server"
  gcp_project_name                       = var.gcp_project_name
  gcp_project_region                     = var.gcp_project_region
  gcp_project_zone                       = "${var.gcp_project_region}-b"
  gcp_network_name                       = data.google_compute_network.default.name
  agents_async_prov_firewall_name        = "arkhai${local.name_suffix}-agents-async-prov-open-ports-${random_id.resource_suffix.hex}"
  agents_async_prov_disk_name            = "arkhai${local.name_suffix}-agents-async-prov-server-${random_id.resource_suffix.hex}"
  agents_async_prov_disk_size            = 25
  agents_async_prov_disk_image           = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20260128"
  agents_async_prov_server_ip_name       = "arkhai${local.name_suffix}-agents-async-prov-server-ip-${random_id.resource_suffix.hex}"
  agents_async_prov_server_name          = "arkhai${local.name_suffix}-agents-async-prov-server-${random_id.resource_suffix.hex}"
  agents_async_prov_server_machine_type  = "n2d-highcpu-4"
}