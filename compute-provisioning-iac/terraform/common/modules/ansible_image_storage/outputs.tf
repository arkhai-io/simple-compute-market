output "bucket_name" {
  value       = google_storage_bucket.ansible_image_storage.name
  description = "The name of the ansible image storage bucket."
}

output "bucket_url" {
  value       = google_storage_bucket.ansible_image_storage.url
  description = "The URL of the ansible image storage bucket."
}