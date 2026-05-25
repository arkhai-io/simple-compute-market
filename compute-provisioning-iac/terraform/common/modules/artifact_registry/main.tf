# Artifact Registry Repository
locals {
  name_suffix = var.resource_suffix != "" ? "-${var.resource_suffix}" : ""
}

resource "google_artifact_registry_repository" "repo" {
  count         = var.enabled ? 1 : 0
  location      = var.gcp_project_region
  repository_id = "${var.repository_id}${local.name_suffix}"
  description   = var.description
  format        = var.format
  project       = var.gcp_project_name

  cleanup_policies {
    id     = "keep-recent-versions"
    action = "KEEP"

    most_recent_versions {
      keep_count = 10
    }
  }
}

# Grant the dedicated reader SA pull/download access on this repository (opt-in per repo)
resource "google_artifact_registry_repository_iam_member" "reader" {
  count      = var.enabled && var.reader_service_account_member != "" ? 1 : 0
  location   = var.gcp_project_region
  repository = google_artifact_registry_repository.repo[0].repository_id
  project    = var.gcp_project_name
  role       = "roles/artifactregistry.reader"
  member     = var.reader_service_account_member
}
