variable "gcp_project_env" {
  description = "The environment of the GCP project (e.g., dev, staging, prod)"
  type        = string
}

variable "gcp_project_name" {
  description = "Google Cloud Project ID for resource deployment."
  type        = string
}

variable "agent_name" {
  description = "Name of the agent."
  type        = string
}

variable "repository_owner" {
  description = "Owner of the Git repository - username or organization"
  type        = string
}

variable "repository_name" {
  description = "Name of the repository you'd like to connect to Cloud Build"
  type        = string
}

variable "bucket_load_test_results_name" {
  description = "The name of the load test results storage bucket."
  type        = string
}

variable "logs_data_bucket_url" {
  description = "The URL of the logs data storage bucket."
  type        = string
}

variable "artifact_registry_repo_name" {
  description = "The name of the Artifact Registry repository."
  type        = string
}
