#!/usr/bin/env bash
# One-command deployment script for provisioning a Milton Agent instance with Terraform & GCP Secret Manager.

set -euo pipefail

PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-milton-agent-project}}"
REGION="${2:-us-central1}"
ENVIRONMENT="${3:-prod}"

echo "======================================================="
echo "        MILTON AGENT INFRASTRUCTURE DEPLOYMENT         "
echo "======================================================="
echo "Project ID:  ${PROJECT_ID}"
echo "Region:      ${REGION}"
echo "Environment: ${ENVIRONMENT}"
echo "-------------------------------------------------------"

if ! command -v terraform &> /dev/null; then
    echo "ERROR: Terraform CLI is required but not installed."
    echo "Install Terraform: https://developer.hashicorp.com/terraform/downloads"
    exit 1
fi

cd terraform

echo "Step 1: Initializing Terraform..."
terraform init

echo "Step 2: Planning infrastructure deployment..."
terraform plan -var="project_id=${PROJECT_ID}" -var="region=${REGION}" -var="environment=${ENVIRONMENT}"

echo "Step 3: Applying infrastructure configuration..."
terraform apply -auto-approve -var="project_id=${PROJECT_ID}" -var="region=${REGION}" -var="environment=${ENVIRONMENT}"

echo "-------------------------------------------------------"
echo "Deployment Complete!"
echo "Milton Service URL:"
terraform output service_url
