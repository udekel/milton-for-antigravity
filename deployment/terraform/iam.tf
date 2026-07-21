# IAM Resources for Milton Agent Infrastructure

# Dedicated Runtime Service Account
resource "google_service_account" "milton_sa" {
  account_id   = "${var.app_name}-sa-${var.environment}"
  display_name = "Milton Agent Runtime Service Account (${var.environment})"
  description  = "Managed identity for Milton backend container execution"
}

# Grant Secret Manager Secret Accessor role to Runtime Service Account
resource "google_secret_manager_secret_iam_member" "secret_access" {
  secret_id = google_secret_manager_secret.gemini_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.milton_sa.email}"
}

# Grant Cloud Logging Writer role to Runtime Service Account
resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.milton_sa.email}"
}

# Grant Cloud Trace Agent role to Runtime Service Account for Telemetry
resource "google_project_iam_member" "trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.milton_sa.email}"
}
