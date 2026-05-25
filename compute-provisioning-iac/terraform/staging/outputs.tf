output "gcp_project_region" {
  value       = var.gcp_project_region
  description = "The GCP project region used for provisioning resources."
}

output "ansible_image_storage_project_id" {
  value       = var.gcp_project_name
  description = "The GCP project ID for ansible image storage."
}

output "ansible_image_storage_bucket_name" {
  value       = module.ansible_image_storage.bucket_name
  description = "The name of the GCS bucket for ansible image storage."
}

output "ansible_image_storage_bucket_url" {
  value       = module.ansible_image_storage.bucket_url
  description = "The URL of the GCS bucket for ansible image storage."
}

output "ansible_image_storage_sa_json" {
  value       = module.ansible_image_storage_rsa.service_account_key_json
  description = "The JSON key of the service account for ansible image storage."
  sensitive   = true
}

output "zerotier_networkcontroller_registry_uri" {
  value = module.zerotier_networkcontroller_registry.registry_uri
  description = "URI of the Artifact Registry repository for the ZeroTier Network Controller image."
}

output "zerotier_networkcontroller_registry_name" {
  value = module.zerotier_networkcontroller_registry.registry_name
  description = "Name of the Artifact Registry repository for the ZeroTier Network Controller image."
}

output "artifact_registry_reader_sa_email" {
  value       = module.artifact_registry_reader_sa.service_account_email
  description = "Email of the dedicated Artifact Registry reader service account (a2a-agent, alkahest-wheel-repo, puffer-wheel-repo)."
}

output "artifact_registry_reader_sa_key_json" {
  value       = module.artifact_registry_reader_sa.service_account_key_json
  description = "Service account private key JSON for the Artifact Registry reader SA (sensitive)."
  sensitive   = true
}

output "agents_async_prov_redis_host" {
  value       = module.agents_async_provisioning_redis.redis_host
  description = "Internal IP of the Cloud Memorystore Redis instance used by Docker containers on the async provisioning server (REDIS_HOST)."
}

output "agents_async_prov_redis_port" {
  value       = module.agents_async_provisioning_redis.redis_port
  description = "Port of the Cloud Memorystore Redis instance (REDIS_PORT, typically 6379)."
}

output "agents_async_prov_redis_connection_string" {
  value       = module.agents_async_provisioning_redis.redis_connection_string
  description = "Full Redis connection string (redis://host:port) to pass as REDIS_URL to Docker containers on the async provisioning server."
}
