output "service_url" {
  description = "Deployed Cloud Run Milton Backend URL"
  value       = google_cloud_run_v2_service.milton_service.uri
}

output "service_account_email" {
  description = "Runtime Service Account Email"
  value       = google_service_account.milton_sa.email
}

output "gemini_api_key_secret_id" {
  description = "GCP Secret Manager Secret ID for Gemini API Key"
  value       = google_secret_manager_secret.gemini_api_key.secret_id
}
