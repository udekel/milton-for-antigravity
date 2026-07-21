variable "project_id" {
  description = "GCP Project ID for deploying Milton infrastructure"
  type        = string
  default     = "milton-agent-project"
}

variable "region" {
  description = "GCP Region for Cloud Run and Secret Manager deployment"
  type        = string
  default     = "us-central1"
}

variable "app_name" {
  description = "Application name prefix"
  type        = string
  default     = "milton-agent"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "container_image" {
  description = "Container image URI for Milton backend service"
  type        = string
  default     = "gcr.io/milton-agent-project/milton-backend:latest"
}

variable "min_instances" {
  description = "Minimum number of Cloud Run service instances"
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum number of Cloud Run service instances"
  type        = number
  default     = 10
}

variable "gemini_api_key_secret_name" {
  description = "Secret Manager secret ID for Gemini API key"
  type        = string
  default     = "gemini-api-key"
}
