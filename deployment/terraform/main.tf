# Terraform Main Configuration for Milton Agent Infrastructure

terraform {
  required_version = ">= 1.3.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Remote GCS Backend for Terraform State
  # backend "gcs" {
  #   bucket = "milton-terraform-state-bucket"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  service_name = "${var.app_name}-${var.environment}"
  common_labels = {
    app         = var.app_name
    environment = var.environment
    managed_by  = "terraform"
  }
}
