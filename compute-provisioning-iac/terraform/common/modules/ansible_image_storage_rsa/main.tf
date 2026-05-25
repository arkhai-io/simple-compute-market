# Custom Role (project-level)
resource "google_project_iam_custom_role" "ansible_storage_uploader" {
  project     = var.gcp_project_name
  role_id     = var.storage_custom_role_id
  title       = var.storage_custom_role_name
  description = "Minimal permissions for uploading objects to a specific GCS bucket via tooling (e.g., Ansible)."
  permissions = [
    "storage.objects.create",
    "storage.objects.list",
    "storage.objects.delete",
    "storage.objects.get"
  ]
}

# Service Account
resource "google_service_account" "ansible_storage_uploader" {
  project      = var.gcp_project_name
  account_id   = var.storage_sa_id
  display_name = var.storage_sa_name
  description  = var.storage_sa_description
}

# Bind role to SA on the bucket only (least privilege)
resource "google_storage_bucket_iam_member" "ansible_storage_binding" {
  bucket = var.gcs_bucket_name
  role   = google_project_iam_custom_role.ansible_storage_uploader.name
  member = "serviceAccount:${google_service_account.ansible_storage_uploader.email}"
}

# Service Account key (JSON)
resource "google_service_account_key" "ansible_storage_uploader" {
  service_account_id = google_service_account.ansible_storage_uploader.name

  # optional: keep default key type/algorithm unless you have a policy requirement
  # public_key_type = "TYPE_X509_PEM_FILE"
}
