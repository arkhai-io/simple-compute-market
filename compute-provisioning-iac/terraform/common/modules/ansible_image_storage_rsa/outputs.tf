output "custom_role_name" {
  description = "Fully-qualified custom role name (projects/<project>/roles/<role_id>)."
  value       = google_project_iam_custom_role.ansible_storage_uploader.name
}

output "service_account_email" {
  description = "Email of the created service account."
  value       = google_service_account.ansible_storage_uploader.email
}

output "service_account_key_json" {
  description = "Service account private key JSON (sensitive)."
  value       = base64decode(google_service_account_key.ansible_storage_uploader.private_key)
  sensitive   = true
}
