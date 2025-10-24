variable "gcp_project_name" {
  type = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "cicd_gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the CICD runner."
}

variable "gcp_project_region" {
  type        = string
  description = "The Google Cloud region you will use to deploy the infrastructure."
}

variable "agent_name" {
  type        = string
  description = "Name of the agent."
}
