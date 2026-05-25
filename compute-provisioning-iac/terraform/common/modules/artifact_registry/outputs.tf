output "registry_uri" {
  value       = try(google_artifact_registry_repository.repo[0].registry_uri, null)
  description = "URI of the Artifact Registry repository."
}

output "registry_name" {
  value       = try(google_artifact_registry_repository.repo[0].repository_id, null)
  description = "Name of the Artifact Registry repository."
}