# Secret Manager Resources for Milton Secrets & API Credentials

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "${var.gemini_api_key_secret_name}-${var.environment}"
  labels    = local.common_labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "milton_config" {
  secret_id = "milton-config-${var.environment}"
  labels    = local.common_labels

  replication {
    auto {}
  }
}
