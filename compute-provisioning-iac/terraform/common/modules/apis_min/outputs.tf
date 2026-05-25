output "vertex_sa_member" {
  value       = google_project_service_identity.vertex_sa.member
  description = "The member string for the Vertex AI service account."
}