module "general_setup" {
  source             = "../common/modules/general_setup"
  gcp_project_name   = var.gcp_project_name
  gcp_project_env    = "dev"
  gcp_project_prefix = "principia-"
  gcp_project_region = var.gcp_project_region
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
    "a2a-agent",
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
}

module "agent_service" {
  depends_on = [
    module.general_setup,
    module.cicd_setup
  ]
  for_each           = toset(local.agents)
  source             = "../common/modules/agent_service"
  gcp_project_name   = var.gcp_project_name
  gcp_project_prefix = "principia-"
  gcp_project_region = var.gcp_project_region
  gcp_project_env    = "dev"
  agent_name         = each.key
  app_sa_email       = module.general_setup.app_sa_email
}

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
