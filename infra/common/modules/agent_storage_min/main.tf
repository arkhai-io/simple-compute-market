resource "google_storage_bucket" "logs_data_bucket" {
  name                        = "${var.gcp_project_name}-${var.agent_name}-logs"
  location                    = var.gcp_project_region
  project                     = var.gcp_project_name
  uniform_bucket_level_access = true
}
