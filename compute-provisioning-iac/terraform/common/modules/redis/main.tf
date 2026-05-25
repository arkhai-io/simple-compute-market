resource "google_project_service" "redis_api" {
  project            = var.gcp_project_name
  service            = "redis.googleapis.com"
  disable_on_destroy = false
}

resource "google_redis_instance" "redis" {
  depends_on = [google_project_service.redis_api]
  project        = var.gcp_project_name
  name           = var.redis_instance_name
  tier           = var.redis_tier
  memory_size_gb = var.redis_memory_size_gb

  region             = var.gcp_project_region
  authorized_network = var.gcp_network_id

  redis_version      = var.redis_version
  display_name       = var.redis_display_name

  labels = {
    environment = var.environment_label
  }
}
