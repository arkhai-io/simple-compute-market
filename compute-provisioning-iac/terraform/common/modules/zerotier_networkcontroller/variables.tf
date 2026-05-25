variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID for the GCP resources."
}

variable "resource_suffix" {
  type        = string
  description = "Suffix appended after the GCP project name in all resource names, enabling multiple environments in a single GCP project. E.g., 'prod', 'stg', 'dev'."
  default     = ""
}

variable "gcp_project_region" {
  type        = string
  description = "The Google Cloud region you will use to deploy the infrastructure."
}

variable "gcp_project_zone" {
  type        = string
  description = "The Google Cloud zone you will use to deploy the infrastructure."
}

variable "gcp_network_name" {
  type        = string
  description = "The Google Cloud network where the resource will be deployed."
}


variable "zerotier_networkcontroller_name" {
  type        = string
  description = "Name of the ZeroTier Network Controller service."
}

variable "zerotier_networkcontroller_machine_type" {
  type        = string
  description = "Machine type for the ZeroTier Network Controller VM instance."
}

variable "zerotier_networkcontroller_image_link" {
  type        = string
  description = "Container image for the ZeroTier Network Controller."
}