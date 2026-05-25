locals {
  display_suffix = var.resource_suffix != "" ? " ${upper(substr(var.resource_suffix, 0, 1))}${substr(var.resource_suffix, 1, -1)}" : ""
}

resource "google_project_service" "deploy_project_services" {
  for_each = {
    for pair in setproduct([var.gcp_project_env], var.deploy_project_services) :
    "${pair[0]}_${replace(pair[1], ".", "_")}" => {
      project = var.gcp_project_name
      service = pair[1]
    }
  }
  project            = each.value.project
  service            = each.value.service
  disable_on_destroy = false
}

# General Agent service account
resource "google_service_account" "app_sa" {
  account_id   = "${var.gcp_project_prefix}${var.gcp_project_env}-app-sa${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  display_name = "${var.gcp_project_prefix}${var.gcp_project_env} General Agent Service Account${local.display_suffix}"
  project      = var.gcp_project_name
}

# Grant application SA the required permissions to run the application
resource "google_project_iam_member" "app_sa_roles" {
  depends_on = [google_service_account.app_sa]
  for_each = {
    for pair in setproduct([var.gcp_project_env], var.app_sa_roles) :
    join(",", pair) => {
      project = var.gcp_project_name
      role    = pair[1]
    }
  }

  project = each.value.project
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.app_sa.email}"
}

resource "google_storage_bucket" "logs_data_bucket" {
  name                        = "${var.gcp_project_name}-general-logs${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  location                    = var.gcp_project_region
  project                     = var.gcp_project_name
  uniform_bucket_level_access = true
  force_destroy               = true
}
