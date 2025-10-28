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

variable "cicd_gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the CICD runner."
}

variable "cicd_gcp_project_region" {
  type        = string
  description = "The Google Cloud region for the CICD GCP project."
}

variable "cicd_services" {
  type        = list(string)
  description = "List of services to be deployed in the CICD GCP project."
  default = [
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "discoveryengine.googleapis.com",
    "serviceusage.googleapis.com",
    "bigquery.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudtrace.googleapis.com"
  ]
}

variable "cicd_roles" {
  type        = list(string)
  description = "List of roles to be assigned to the CICD service account."
  default = [
    "roles/run.invoker",
    "roles/storage.admin",
    "roles/aiplatform.user",
    "roles/discoveryengine.editor",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.builder"
  ]
}

variable "cicd_sa_deployment_required_roles" {
  type        = list(string)
  description = "List of roles required for the CICD service account to deploy to other projects."
  default = [
    "roles/run.developer",
    "roles/iam.serviceAccountUser",
    "roles/aiplatform.user",
    "roles/storage.admin"
  ]
}

variable "repository_owner" {
  description = "Owner of the Git repository - username or organization"
  type        = string
}

variable "repository_name" {
  description = "Name of the repository you'd like to connect to Cloud Build"
  type        = string
}
