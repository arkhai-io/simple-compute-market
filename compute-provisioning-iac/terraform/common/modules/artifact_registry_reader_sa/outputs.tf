output "service_account_email" {
  value       = var.enabled ? google_service_account.artifact_registry_reader[0].email : ""
  description = "Email of the Artifact Registry reader service account. Empty string when disabled."
}

output "service_account_member" {
  value       = var.enabled ? "serviceAccount:${google_service_account.artifact_registry_reader[0].email}" : ""
  description = "IAM member string for the Artifact Registry reader service account. Empty string when disabled."
}

output "service_account_key_json" {
  value       = var.enabled ? base64decode(google_service_account_key.artifact_registry_reader[0].private_key) : ""
  description = "Service account private key JSON (sensitive). Empty string when disabled."
  sensitive   = true
}
