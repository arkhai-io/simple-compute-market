module "general_setup" {
  source             = "../common/modules/general_setup"
  gcp_project_name   = var.gcp_project_name
  gcp_project_env    = "dev"
  gcp_project_prefix = "principia-"
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  deploy_project_services = [
    "aiplatform.googleapis.com",
    "run.googleapis.com",
    "discoveryengine.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "bigquery.googleapis.com",
    "serviceusage.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "generativelanguage.googleapis.com",
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
  ]
  app_sa_roles = [
    "roles/aiplatform.user",
    "roles/discoveryengine.editor",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/storage.admin",
    "roles/serviceusage.serviceUsageConsumer",
  ]
}

module "cicd_setup" {
  source                  = "../common/modules/cicd_setup"
  gcp_project_name        = var.gcp_project_name
  gcp_project_env         = "dev"
  gcp_project_prefix      = "principia-"
  cicd_gcp_project_name   = var.gcp_project_name
  cicd_gcp_project_region = var.gcp_project_region
  resource_suffix         = var.resource_suffix
  cicd_services = [
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "discoveryengine.googleapis.com",
    "serviceusage.googleapis.com",
    "bigquery.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudtrace.googleapis.com"
  ]
  cicd_roles = [
    "roles/run.invoker",
    "roles/storage.admin",
    "roles/aiplatform.user",
    "roles/discoveryengine.editor",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.builder"
  ]
  cicd_sa_deployment_required_roles = [
    "roles/run.developer",
    "roles/iam.serviceAccountUser",
    "roles/aiplatform.user",
    "roles/storage.admin"
  ]
  repository_owner = "principia-systems"
  repository_name  = "market-temp"
}

# module "general_github" {
#   depends_on = [
#     module.general_setup,
#     module.cicd_setup
#   ]
#   source           = "../common/modules/general_github"
#   repository_owner = "principia-systems"
#   repository_name  = "market-temp"
#   gcp_project_env  = "dev"
#   gcp_project_name = var.gcp_project_name
#   gcp_project_region = var.gcp_project_region
#   cicd_gcp_project_name = var.gcp_project_name
#   cicd_project_number = module.cicd_setup.cicd_project_number
#   wif_pool_id = module.cicd_setup.wif_pool_id
#   wif_provider_id = module.cicd_setup.wif_provider_id
#   cicd_service_account_email = module.cicd_setup.cicd_service_account_email
#   app_sa_email = module.general_setup.app_sa_email
# }

locals {
  agents = [
    "a2a-agent-farmer",
    "a2a-agent-trader",
  ]
}

module "agent_storage" {
  depends_on = [
    module.general_setup,
    module.cicd_setup
  ]
  for_each              = toset(local.agents)
  source                = "../common/modules/agent_storage"
  gcp_project_name      = var.gcp_project_name
  cicd_gcp_project_name = var.gcp_project_name
  gcp_project_region    = var.gcp_project_region
  agent_name            = each.key
  resource_suffix       = var.resource_suffix
}

# module "agent_service" {
#   depends_on = [
#     module.general_setup,
#     module.cicd_setup
#   ]
#   for_each           = toset(local.agents)
#   source             = "../common/modules/agent_service"
#   gcp_project_name   = var.gcp_project_name
#   gcp_project_prefix = "principia-"
#   gcp_project_region = var.gcp_project_region
#   gcp_project_env    = "dev"
#   agent_name         = each.key
#   app_sa_email       = module.general_setup.app_sa_email
# }

# module "agent_log_sinks" {
#   depends_on = [
#     module.general_setup,
#     module.cicd_setup
#   ]
#   for_each              = toset(local.agents)
#   source                = "../common/modules/agent_log_sinks"
#   gcp_project_name      = var.gcp_project_name
#   gcp_project_region    = var.gcp_project_region
#   agent_name            = each.key
#   feedback_logs_filter  = "jsonPayload.log_type=\"feedback\" jsonPayload.service_name=\"${each.key}\""
#   telemetry_logs_filter = "labels.service_name=\"${each.key}\" labels.type=\"agent_telemetry\""
# }

# module "agent_github" {
#   depends_on = [
#     module.general_setup,
#     module.cicd_setup
#   ]
#   for_each           = toset(local.agents)
#   source             = "../common/modules/agent_github"
#   gcp_project_env    = "dev"
#   gcp_project_name   = var.gcp_project_name
#   agent_name         = each.key
#   repository_owner   = "principia-systems"
#   repository_name    = "market-temp"
#   bucket_load_test_results_name = module.agent_storage[each.key].bucket_load_test_results_name
#   logs_data_bucket_url = module.agent_storage[each.key].logs_data_bucket_url
#   artifact_registry_repo_name = module.agent_storage[each.key].artifact_registry_repo_name
# }

# Compute Resource Storage
module "ansible_image_storage" {
  depends_on = [
    module.general_setup,
    module.cicd_setup
  ]
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
  storage_custom_role_id   = "gcs_ansible_bucket_uploader${var.resource_suffix != "" ? "_${replace(var.resource_suffix, "-", "_")}" : ""}"
  storage_custom_role_name = "GCS Ansible Bucket Uploader${var.resource_suffix != "" ? " (${var.resource_suffix})" : ""}"
  storage_sa_id            = "gcs-ansible-uploader${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  storage_sa_name          = "GCS Ansible Bucket Uploader${var.resource_suffix != "" ? " (${var.resource_suffix})" : ""}"
  storage_sa_description   = "Uploads objects to a specific GCS bucket using a minimal custom role."
}

data "google_compute_network" "default" {
  name    = "default"
  project = var.gcp_project_name
}

# ERC 8004 Registry
module "erc_8004_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "erc-8004-registry"
  description        = "Repo for ERC 8004 artifacts." 
}

# Git Commit Trading Images
module "git_commit_trading_images_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "git-commit-trading-images"
  description        = "" 
}

# ZeroTier Network Controller
module "zerotier_networkcontroller_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "zerotier-networkcontroller-repo"
  description        = "Repo for ZeroTier Network Controller artifacts." 
}

# Async Provisioning Service
module "async_provisioning_service_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "async-provisioning-service"
  description        = "Async Provisioning Service"
}

# Alkahest Registry (Python)
module "alkahest_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "alkahest-wheel-repo"
  description        = "Repo for Alkahest Python wheel artifacts."
  format             = "PYTHON"
}

# Puffer Registry (Python)
module "puffer_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "puffer-wheel-repo"
  description        = "Repo for Puffer Python wheel artifacts."
  format             = "PYTHON"
}

# Agent Registry (Docker)
module "agent_registry" {
  depends_on = [
    module.general_setup,
  ]
  source             = "../common/modules/artifact_registry"
  enabled            = false
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  resource_suffix    = var.resource_suffix
  repository_id      = "a2a-agent"
  description        = "Repo for Agent Docker artifacts."
}

# Artifact Registry Reader Service Account
# Grants pull / download access on a2a-agent, alkahest-wheel-repo, puffer-wheel-repo only.
# A single call here covers all three repos — no per-repo reader wiring needed.
# Disabled in sandbox — set enabled = true to activate.
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
  sa_id            = "artifact-registry-reader-sa${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  sa_name          = "Artifact Registry Reader SA${var.resource_suffix != "" ? " (${var.resource_suffix})" : ""}"
  sa_description   = "Service account with read-only access to a2a-agent, alkahest-wheel-repo, and puffer-wheel-repo."
}

# ERC FRP Server
module "erc_frp_ztnc_server" {
  source                           = "../common/modules/erc_frp_ztnc_server"
  gcp_project_name                 = var.gcp_project_name
  gcp_project_region               = var.gcp_project_region
  gcp_project_zone                 = "${var.gcp_project_region}-b"
  gcp_network_name                 = data.google_compute_network.default.name
  erc_frp_firewall_name            = "arkhai-guest-vm-open-ports${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  erc_frp_disk_name                = "arkhai-frp-server${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  erc_frp_disk_size                = 10
  erc_frp_disk_image               = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20260128"
  erc_frp_ztnc_server_ip_name      = "arkhai-frp-server-ip${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  erc_frp_ztnc_server_name         = "arkhai-erc-registry-and-frp-server${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  erc_frp_ztnc_server_machine_type = "n2d-highcpu-2"
}

# Agents Async Provisioning Server
module "agents_async_provisioning_server" {
  source                                 = "../common/modules/agents_async_provisioning_server"
  gcp_project_name                       = var.gcp_project_name
  gcp_project_region                     = var.gcp_project_region
  gcp_project_zone                       = "${var.gcp_project_region}-b"
  gcp_network_name                       = data.google_compute_network.default.name
  agents_async_prov_firewall_name        = "arkhai-agents-async-prov-open-ports${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  agents_async_prov_disk_name            = "arkhai-agents-async-prov-server${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  agents_async_prov_disk_size            = 25
  agents_async_prov_disk_image           = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20260128"
  agents_async_prov_server_ip_name       = "arkhai-agents-async-prov-server-ip${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  agents_async_prov_server_name          = "arkhai-agents-async-prov-server${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  agents_async_prov_server_machine_type  = "n2d-highcpu-4"
}