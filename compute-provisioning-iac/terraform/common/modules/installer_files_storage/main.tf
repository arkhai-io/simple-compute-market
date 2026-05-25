locals {
  name_suffix = var.resource_suffix != "" ? "-${var.resource_suffix}" : ""
}

resource "google_storage_bucket" "installer_files_storage" {
  name                        = "${var.gcp_project_name}${local.name_suffix}-installer-files"
  location                    = var.gcp_project_region
  project                     = var.gcp_project_name
  uniform_bucket_level_access = true
}
