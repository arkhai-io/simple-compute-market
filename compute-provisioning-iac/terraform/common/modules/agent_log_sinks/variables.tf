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
  description = "Name of the agent to be created."
}

variable "feedback_logs_filter" {
  type        = string
  description = "Log Sink filter for capturing feedback data. Captures logs where the `log_type` field is `feedback`."
  default     = "jsonPayload.log_type=\"feedback\""
}

variable "telemetry_logs_filter" {
  type        = string
  description = "Log Sink filter for capturing telemetry data. Captures logs with the `traceloop.association.properties.log_type` attribute set to `tracing`."
  default     = "labels.service_name=\"my-awesome-agent\" labels.type=\"agent_telemetry\""
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}