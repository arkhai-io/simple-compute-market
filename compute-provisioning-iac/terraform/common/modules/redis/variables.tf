variable "gcp_project_name" {
  type        = string
  description = "The Google Cloud project name where the Redis instance will be deployed."
}

variable "gcp_project_region" {
  type        = string
  description = "The Google Cloud region where the Redis instance will be deployed."
}

variable "gcp_network_id" {
  type        = string
  description = "The self-link or full resource name of the VPC network authorized to access the Redis instance."
}

variable "redis_instance_name" {
  type        = string
  description = "Name of the Cloud Memorystore Redis instance."
}

variable "redis_display_name" {
  type        = string
  description = "Human-readable display name for the Redis instance."
  default     = "Agents Redis"
}

variable "redis_tier" {
  type        = string
  description = "Service tier for the Redis instance. BASIC (no replication) or STANDARD_HA (high availability with replication)."
  default     = "BASIC"

  validation {
    condition     = contains(["BASIC", "STANDARD_HA"], var.redis_tier)
    error_message = "redis_tier must be either BASIC or STANDARD_HA."
  }
}

variable "redis_memory_size_gb" {
  type        = number
  description = "Redis memory size in GiB."
  default     = 1
}

variable "redis_version" {
  type        = string
  description = "The version of Redis software. For example, REDIS_7_0."
  default     = "REDIS_7_0"
}

variable "environment_label" {
  type        = string
  description = "A label to identify the environment (e.g. production, staging)."
  default     = "production"
}
