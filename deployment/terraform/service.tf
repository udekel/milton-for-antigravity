# Cloud Run Service Configuration for Milton Agent Backend API

resource "google_cloud_run_v2_service" "milton_service" {
  name     = local.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.milton_sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "2000m"
          memory = "4Gi"
        }
      }

      ports {
        container_port = 8000
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "MILTON_MODE"
        value = "SUMMARIZE_EVERYTHING"
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  labels = local.common_labels
}

# Allow public or internal IAM access to Cloud Run service
resource "google_cloud_run_v2_service_iam_binding" "invoker" {
  location = google_cloud_run_v2_service.milton_service.location
  name     = google_cloud_run_v2_service.milton_service.name
  role     = "roles/run.invoker"
  members  = ["allAuthenticatedUsers"]
}
