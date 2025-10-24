output "bucket_load_test_results_name" {
  value       = google_storage_bucket.bucket_load_test_results.name
  description = "The name of the load test results storage bucket."
}

output "logs_data_bucket_url" {
  value       = google_storage_bucket.logs_data_bucket.url
  description = "The URL of the logs data storage bucket."
}

output "artifact_registry_repo_name" {
  value       = google_artifact_registry_repository.repo-artifacts-genai.repository_id
  description = "The name of the Artifact Registry repository."
}
