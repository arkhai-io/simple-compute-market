data "google_project" "project" {
  project_id = var.gcp_project_name
}

data "google_project" "cicd_project" {
  project_id = var.cicd_gcp_project_name
}

resource "google_project_service" "cicd_services" {
  count              = length(var.cicd_services)
  project            = var.cicd_gcp_project_name
  service            = var.cicd_services[count.index]
  disable_on_destroy = false
}

# Enable Cloud Resource Manager API for the CICD runner project
resource "google_project_service" "cicd_cloud_resource_manager_api" {
  project            = var.cicd_gcp_project_name
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "cicd_runner_sa" {
  account_id   = "${var.gcp_project_prefix}${var.gcp_project_env}-cicd-sa"
  display_name = "CICD Runner SA"
  project      = var.cicd_gcp_project_name
}

# Assign roles for the CICD project
resource "google_project_iam_member" "cicd_project_roles" {
  depends_on = [ google_service_account.cicd_runner_sa ]
  for_each = toset(var.cicd_roles)

  project    = var.cicd_gcp_project_name
  role       = each.value
  member     = "serviceAccount:${google_service_account.cicd_runner_sa.email}"
}

# Assign roles for the general project
resource "google_project_iam_member" "general_project_roles" {
  depends_on = [ google_service_account.cicd_runner_sa ]
  for_each = {
    for pair in setproduct([var.gcp_project_env], var.cicd_sa_deployment_required_roles) :
    "${pair[0]}-${pair[1]}" => {
      project = var.gcp_project_name
      role       = pair[1]
    }
  }

  project    = each.value.project
  role       = each.value.role
  member     = "serviceAccount:${google_service_account.cicd_runner_sa.email}"
}

# Allow Cloud Run service SA to pull containers stored in the CICD project
resource "google_project_iam_member" "cicd_run_invoker_artifact_registry_reader" {
  project  = var.cicd_gcp_project_name

  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.project.number}@serverless-robot-prod.iam.gserviceaccount.com"
}

# Special assignment: Allow the CICD SA to create tokens
resource "google_service_account_iam_member" "cicd_run_invoker_token_creator" {
  depends_on = [ google_service_account.cicd_runner_sa ]
  service_account_id = google_service_account.cicd_runner_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.cicd_runner_sa.email}"
}

# Special assignment: Allow the CICD SA to impersonate himself for trigger creation
resource "google_service_account_iam_member" "cicd_run_invoker_account_user" {
  depends_on = [ google_service_account.cicd_runner_sa ]
  service_account_id = google_service_account.cicd_runner_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cicd_runner_sa.email}"
}

resource "google_service_account_iam_member" "github_oidc_access" {
  service_account_id = google_service_account.cicd_runner_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.cicd_project.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github_pool.workload_identity_pool_id}/attribute.repository/${var.repository_owner}/${var.repository_name}"
}

# Allow the GitHub Actions principal to impersonate the CICD runner service account
resource "google_service_account_iam_member" "github_sa_impersonation" {
  service_account_id = google_service_account.cicd_runner_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.cicd_project.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github_pool.workload_identity_pool_id}/attribute.repository/${var.repository_owner}/${var.repository_name}"
}

resource "google_iam_workload_identity_pool" "github_pool" {
  workload_identity_pool_id = "${var.gcp_project_prefix}${var.gcp_project_env}-pool"
  project                   = var.cicd_gcp_project_name
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  workload_identity_pool_provider_id = "${var.gcp_project_prefix}${var.gcp_project_env}-oidc"
  project                            = var.cicd_gcp_project_name
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  display_name                       = "GitHub OIDC Provider"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_mapping = {
    "google.subject"         = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
  }
  attribute_condition = "attribute.repository == '${var.repository_owner}/${var.repository_name}'"
}

resource "google_storage_bucket" "logs_data_bucket" {
  name                        = "${var.cicd_gcp_project_name}-cicd-logs"
  location                    = var.cicd_gcp_project_region
  project                     = var.cicd_gcp_project_name
  uniform_bucket_level_access = true
  force_destroy               = true
}
