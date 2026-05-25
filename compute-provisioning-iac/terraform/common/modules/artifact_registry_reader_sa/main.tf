# Service Account for pulling images / downloading wheel files from Artifact Registry
resource "google_service_account" "artifact_registry_reader" {
  count        = var.enabled ? 1 : 0
  project      = var.gcp_project_name
  account_id   = var.sa_id
  display_name = var.sa_name
  description  = var.sa_description
}

# Service Account key (JSON)
resource "google_service_account_key" "artifact_registry_reader" {
  count              = var.enabled ? 1 : 0
  service_account_id = google_service_account.artifact_registry_reader[0].name
}

# Grant Artifact Registry Reader role scoped to specific repositories only
locals {
  ar_repositories = var.enabled ? [
    "a2a-agent",
    "puffer-wheel-repo",
    "alkahest-wheel-repo",
  ] : []
}

resource "google_artifact_registry_repository_iam_member" "artifact_registry_reader" {
  for_each = toset(local.ar_repositories)

  project    = var.gcp_project_name
  location   = var.ar_location
  repository = each.key
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.artifact_registry_reader[0].email}"
}
