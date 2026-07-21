"""GCP Secret Manager integration module for Milton Agent."""

import logging
import os
from typing import Optional

logger = logging.getLogger("milton.secret_manager")


def fetch_secret_from_secret_manager(secret_id: str, project_id: Optional[str] = None, version: str = "latest") -> Optional[str]:
    """Fetches a secret payload directly from GCP Secret Manager API.

    Falls back gracefully to environment variables if Secret Manager client is unavailable or unconfigured.
    """
    if not secret_id:
        return None

    project = project_id or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")

    # Method 1: Try google-cloud-secretmanager SDK if installed
    if project:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project}/secrets/{secret_id}/versions/{version}"
            response = client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode("UTF-8").strip()
            logger.info(f"Successfully loaded secret '{secret_id}' from GCP Secret Manager")
            return secret_value
        except Exception as e:
            logger.debug(f"GCP Secret Manager SDK fetch skipped for secret '{secret_id}': {e}")

    # Method 2: Check standard env var mappings
    env_var_name = secret_id.upper().replace("-", "_")
    val = os.getenv(env_var_name) or os.getenv(secret_id)
    if val:
        return val

    return None
