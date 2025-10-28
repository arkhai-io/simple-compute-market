variable "repository_owner" {
  description = "Owner of the Git repository - username or organization"
  type        = string
}

variable "repository_name" {
  description = "Name of the repository you'd like to connect to Cloud Build"
  type        = string
}

variable "gcp_project_env" {
  description = "The environment for the GCP project (e.g., dev, staging, prod)"
  type        = string
}

variable "gcp_project_name" {
  description = "Google Cloud Project ID for the GCP resources."
  type        = string
}

variable "gcp_project_region" {
  description = "The Google Cloud region you will use to deploy the infrastructure."
  type        = string
}

variable "cicd_gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the CICD runner."
}

variable "cicd_project_number" {
  description = "The GCP project number for the CICD runner project."
  type        = string
}

variable "wif_pool_id" {
  description = "The Workload Identity Federation Pool ID for GitHub Actions."
  type        = string
}

variable "wif_provider_id" {
  description = "The Workload Identity Federation Provider ID for GitHub Actions."
  type        = string
}

variable "cicd_service_account_email" {
  description = "The email of the CICD runner service account."
  type        = string
}

variable "app_sa_email" {
  description = "The email of the General Agent application service account."
  type        = string
}