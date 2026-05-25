# TO REFACTOR
locals {
  project_ids = {
    dev = var.gcp_project_name
  }
  name_suffix    = var.resource_suffix != "" ? "-${var.resource_suffix}" : ""
  display_suffix = var.resource_suffix != "" ? " ${upper(substr(var.resource_suffix, 0, 1))}${substr(var.resource_suffix, 1, -1)}" : ""
}

# Get the project number for the dev project
data "google_project" "dev_project" {
  project_id = var.gcp_project_name
}

# Grant Storage Object Creator role to default compute service account
resource "google_project_iam_member" "default_compute_sa_storage_object_creator" {
  project = var.gcp_project_name
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${data.google_project.dev_project.number}-compute@developer.gserviceaccount.com"
}

# Agent service account
resource "google_service_account" "app_sa" {
  account_id   = "${var.agent_name}-app${local.name_suffix}"
  display_name = "${var.agent_name} Agent Service Account${local.display_suffix}"
  project      = var.gcp_project_name
}

# Grant application SA the required permissions to run the application
resource "google_project_iam_member" "app_sa_roles" {
  for_each = {
    for pair in setproduct(keys(local.project_ids), var.agent_app_sa_roles) :
    join(",", pair) => {
      project = local.project_ids[pair[0]]
      role    = pair[1]
    }
  }

  project = each.value.project
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.app_sa.email}"
}


# Grant required permissions to Vertex AI service account for Agent Engine
resource "google_project_iam_member" "vertex_ai_sa_permissions" {
  for_each = {
    for pair in setproduct(keys(local.project_ids), var.agent_app_sa_roles) :
    join(",", pair) => pair[1]
  }

  project = var.gcp_project_name
  role    = each.value
  member  = var.vertex_sa_member
}
