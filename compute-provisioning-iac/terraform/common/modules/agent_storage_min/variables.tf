variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for resource deployment."
}

variable "gcp_project_region" {
  type        = string
  description = "The Google Cloud region you will use to deploy the infrastructure."

}

variable "agent_name" {
  type        = string
  description = "Name of the agent."
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}