output "service_account_email" {
  description = "Email of the created service account."
  value       = google_service_account.installer_files_storage.email
}

output "service_account_key_json" {
  description = "Service account private key JSON (sensitive)."
  value       = base64decode(google_service_account_key.installer_files_storage.private_key)
  sensitive   = true
}
