variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "gcp_project_env" {
  type        = string
  description = "The environment of the GCP project (e.g., dev, staging, prod)."
}

variable "gcp_project_prefix" {
  type        = string
  description = "The prefix to use for GCP project IDs."
  default     = "principia-"
}

variable "gcp_project_region" {
  type        = string
  description = "The Google Cloud region you will use to deploy the infrastructure."
}

variable "deploy_project_services" {
  type        = list(string)
  description = "List of services to be deployed in the GCP project."
}

variable "app_sa_roles" {
  type        = list(string)
  description = "List of roles to be assigned to the application service account."
  default = [
    "roles/aiplatform.user",
    "roles/discoveryengine.editor",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/storage.admin",
    "roles/serviceusage.serviceUsageConsumer",
  ]
}
