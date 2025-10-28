variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for resource deployment."
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

variable "gcp_project_env" {
  type        = string
  description = "The environment for the Google Cloud project (e.g., staging, production)."
}

variable "agent_name" {
  type        = string
  description = "Name of the agent to be created."
}

variable "app_sa_email" {
  type        = string
  description = "The email of the agent application service account."
}