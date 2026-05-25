variable "gcp_project_name" {
  type        = string
  description = "The Google Cloud project name where the infrastructure will be deployed."
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

variable "agents_async_prov_firewall_name" {
  type        = string
  description = "Name of the firewall rule for the agents async provisioning server."
}

variable "agents_async_prov_disk_name" {
  type        = string
  description = "Name of the persistent disk for the agents async provisioning server."
}

variable "agents_async_prov_disk_size" {
  type        = number
  description = "Size of the persistent disk for the agents async provisioning server in GB."
}

variable "agents_async_prov_disk_image" {
  type        = string
  description = "Image of the persistent disk for the agents async provisioning server."
}

variable "agents_async_prov_server_ip_name" {
  type        = string
  description = "Name of the static IP address for the agents async provisioning server."
}

variable "agents_async_prov_server_name" {
  type        = string
  description = "Name of the Compute Engine instance for the agents async provisioning server."
}

variable "agents_async_prov_server_machine_type" {
  type        = string
  description = "Machine type for the Compute Engine instance of the agents async provisioning server."
}
