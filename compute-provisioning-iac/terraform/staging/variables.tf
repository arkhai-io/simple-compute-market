variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for resource deployment."
}

variable "gcp_project_region" {
  type        = string
  description = "Google Cloud region for resource deployment."
  default     = "asia-southeast1"
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}