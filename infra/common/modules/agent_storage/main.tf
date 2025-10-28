resource "google_storage_bucket" "bucket_load_test_results" {
  name                        = "${var.cicd_gcp_project_name}-${var.agent_name}-load-test"
  location                    = var.gcp_project_region
  project                     = var.cicd_gcp_project_name
  uniform_bucket_level_access = true
  force_destroy               = true
}

resource "google_storage_bucket" "logs_data_bucket" {
  name                        = "${var.gcp_project_name}-${var.agent_name}-logs"
  location                    = var.gcp_project_region
  project                     = var.gcp_project_name
  uniform_bucket_level_access = true
  force_destroy               = true
}

resource "google_artifact_registry_repository" "repo-artifacts-genai" {
  location      = var.gcp_project_region
  repository_id = "${var.agent_name}-repo"
  description   = "Repo for ${var.agent_name} applications"
  format        = "DOCKER"
  project       = var.cicd_gcp_project_name
}
