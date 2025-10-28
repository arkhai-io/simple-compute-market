output "cicd_project_number" {
  value       = data.google_project.cicd_project.number
  description = "The GCP project number for the CICD runner project."
}

output "wif_pool_id" {
  value       = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  description = "The Workload Identity Federation Pool ID for GitHub Actions."
}

output "wif_provider_id" {
  value       = google_iam_workload_identity_pool_provider.github_provider.workload_identity_pool_provider_id
  description = "The Workload Identity Federation Provider ID for GitHub Actions."
}

output "cicd_service_account_email" {
  value       = google_service_account.cicd_runner_sa.email
  description = "The email of the CICD runner service account."
}