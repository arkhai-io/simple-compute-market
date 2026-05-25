variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}

variable "gcs_bucket_name" {
  description = "Destination bucket where the SA will be granted access."
  type        = string
}

variable "storage_custom_role_id" {
  description = "Role ID for the custom role (must be unique in the project), e.g. gcs_ansible_bucket_uploader."
  type        = string
}

variable "storage_custom_role_name" {
  description = "Role name for the custom role (must be unique in the project), e.g. GCS Ansible Bucket Uploader."
  type        = string
}

variable "storage_sa_id" {
  description = "Service account ID (account_id), e.g. gcs-ansible-uploader."
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
