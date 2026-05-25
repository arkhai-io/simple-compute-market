variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for resource deployment."
}

variable "agent_name" {
  type        = string
  description = "Name of the agent to be created."
}

variable "agent_app_sa_roles" {
  description = "List of roles to assign to the agent application service account"
  type        = list(string)
  default = [
    "roles/aiplatform.user",
    "roles/discoveryengine.editor",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/storage.admin",
    "roles/serviceusage.serviceUsageConsumer",
  ]
}

variable "vertex_sa_member" {
  type        = string
  description = "The member string for the Vertex AI service account."
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}