# Try to get existing repo
data "github_repository" "existing_repo" {
  full_name = "${var.repository_owner}/${var.repository_name}"
}

# Setup env prefix
locals {
  env_prefix = upper(replace("${var.gcp_project_env}_", "-", "_"))
}

resource "github_actions_variable" "gcp_project_number" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}GCP_PROJECT_NUMBER"
  value         = var.cicd_project_number
}

resource "github_actions_secret" "wif_pool_id" {
  repository      = var.repository_name
  secret_name     = "${local.env_prefix}WIF_POOL_ID"
  plaintext_value = var.wif_pool_id
  depends_on      = [data.github_repository.existing_repo]
}

resource "github_actions_secret" "wif_provider_id" {
  repository      = var.repository_name
  secret_name     = "${local.env_prefix}WIF_PROVIDER_ID"
  plaintext_value = var.wif_provider_id
  depends_on      = [data.github_repository.existing_repo]
}

resource "github_actions_secret" "gcp_service_account" {
  repository      = var.repository_name
  secret_name     = "${local.env_prefix}GCP_SERVICE_ACCOUNT"
  plaintext_value = var.cicd_service_account_email
  depends_on      = [data.github_repository.existing_repo]
}

resource "github_actions_variable" "staging_project_id" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}PROJECT_ID"
  value         = var.gcp_project_name
  depends_on    = [data.github_repository.existing_repo]
}

resource "github_actions_variable" "region" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}REGION"
  value         = var.gcp_project_region
  depends_on    = [data.github_repository.existing_repo]
}

resource "github_actions_variable" "cicd_project_id" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}CICD_PROJECT_ID"
  value         = var.cicd_gcp_project_name
  depends_on    = [data.github_repository.existing_repo]
}

resource "github_actions_variable" "app_sa_email" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}APP_SA_EMAIL"
  value         = var.app_sa_email
  depends_on    = [data.github_repository.existing_repo]
}

# resource "github_repository_environment" "production_environment" {
#   repository  = var.repository_name
#   environment = "production"
#   depends_on  = [github_repository.repo, data.github_repository.existing_repo]

#   deployment_branch_policy {
#     protected_branches     = false
#     custom_branch_policies = true
#   }
# }