output "app_sa_email" {
  value       = google_service_account.app_sa.email
  description = "The email of the General Agent application service account."
}