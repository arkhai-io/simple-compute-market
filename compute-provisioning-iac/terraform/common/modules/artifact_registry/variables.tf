variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "gcp_project_region" {
  type        = string
  description = "The Google Cloud region you will use to deploy the infrastructure."
}

variable "repository_id" {
  type        = string
  description = "The ID of the Artifact Registry repository."
}

variable "description" {
  type        = string
  description = "Description of the Artifact Registry repository."
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}

variable "enabled" {
  type        = bool
  description = "Whether to create the Artifact Registry repository. Set to false to skip resource creation for this environment."
  default     = true
}

variable "format" {
  type        = string
  description = "The format of the Artifact Registry repository (e.g., DOCKER, PYTHON)."
  default     = "DOCKER"
}

variable "reader_service_account_member" {
  type        = string
  description = "IAM member string (e.g. serviceAccount:foo@project.iam.gserviceaccount.com) to grant roles/artifactregistry.reader on this repository. Leave empty to skip."
  default     = ""
}
