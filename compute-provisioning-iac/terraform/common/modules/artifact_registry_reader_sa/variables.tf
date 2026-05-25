variable "enabled" {
  type        = bool
  description = "Whether to create the Artifact Registry reader service account. Set to false to skip resource creation for this environment."
  default     = true
}

variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "sa_id" {
  type        = string
  description = "Service account ID (account_id), e.g. artifact-registry-reader-sa."
}

variable "sa_name" {
  type        = string
  description = "Display name for the service account."
}

variable "sa_description" {
  type        = string
  description = "Description for the service account."
}

variable "ar_location" {
  type        = string
  description = "Region/location where the Artifact Registry repositories are hosted (e.g. asia-southeast1)."
}
