resource "google_cloud_run_v2_service" "app_service" {
  name                = "${var.gcp_project_prefix}${var.agent_name}-service${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  location            = var.gcp_project_region
  project             = var.gcp_project_name
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels = {
    "created-by"  = "adk"
    "environment" = var.gcp_project_env
  }

  template {
    containers {
      # Placeholder, will be replaced by the CI/CD pipeline
      image = "us-docker.pkg.dev/cloudrun/container/hello"

      resources {
        limits = {
          cpu    = "4"
          memory = "8Gi"
        }
        cpu_idle = false
      }
    }

    service_account                  = var.app_sa_email
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    session_affinity = true
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # This lifecycle block prevents Terraform from overwriting the container image when it's
  # updated by Cloud Run deployments outside of Terraform (e.g., via CI/CD pipelines)
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}