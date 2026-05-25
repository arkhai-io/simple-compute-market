# Try to get existing repo
data "github_repository" "existing_repo" {
  full_name = "${var.repository_owner}/${var.repository_name}"
}

# Setup env prefix
locals {
  env_prefix = upper(replace("${var.gcp_project_env}_${var.agent_name}_", "-", "_"))
}

resource "github_actions_variable" "bucket_name_load_test_results" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}BUCKET_NAME_LOAD_TEST_RESULTS"
  value         = var.bucket_load_test_results_name
  depends_on    = [data.github_repository.existing_repo]
}

resource "github_actions_variable" "logs_bucket_name" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}LOGS_BUCKET_NAME"
  value         = var.logs_data_bucket_url
  depends_on    = [data.github_repository.existing_repo]
}


resource "github_actions_variable" "container_name" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}CONTAINER_NAME"
  value         = var.gcp_project_name
  depends_on    = [data.github_repository.existing_repo]
}

resource "github_actions_variable" "artifact_registry_repo_name" {
  repository    = var.repository_name
  variable_name = "${local.env_prefix}ARTIFACT_REGISTRY_REPO_NAME"
  value         = var.artifact_registry_repo_name
  depends_on    = [data.github_repository.existing_repo]
}
