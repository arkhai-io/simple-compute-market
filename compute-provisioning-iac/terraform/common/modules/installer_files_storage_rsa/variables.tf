variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "gcs_bucket_name" {
  description = "Destination bucket where the SA will be granted access."
  type        = string
}

variable "storage_sa_id" {
  description = "Service account ID (account_id), e.g. installer-files-storage-sa."
  type        = string
}

variable "storage_sa_name" {
  description = "Display name for the service account."
  type        = string
}

variable "storage_sa_description" {
  description = "Description for the service account."
  type        = string
}
