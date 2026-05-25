output "bucket_name" {
  value       = google_storage_bucket.installer_files_storage.name
  description = "The name of the installer files storage bucket."
}

output "bucket_url" {
  value       = google_storage_bucket.installer_files_storage.url
  description = "The URL of the installer files storage bucket."
}
