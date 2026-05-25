# Service Account
resource "google_service_account" "installer_files_storage" {
  project      = var.gcp_project_name
  account_id   = var.storage_sa_id
  display_name = var.storage_sa_name
  description  = var.storage_sa_description
}

# Bind Storage Object Creator role to SA on the bucket
resource "google_storage_bucket_iam_member" "installer_files_storage_object_creator" {
  bucket = var.gcs_bucket_name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.installer_files_storage.email}"
}

# Bind Storage Object User role to SA on the bucket
resource "google_storage_bucket_iam_member" "installer_files_storage_object_user" {
  bucket = var.gcs_bucket_name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.installer_files_storage.email}"
}

# Service Account key (JSON)
resource "google_service_account_key" "installer_files_storage" {
  service_account_id = google_service_account.installer_files_storage.name
}
