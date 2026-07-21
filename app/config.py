import os
from dataclasses import dataclass


from app.utils.secret_manager import fetch_secret_from_secret_manager


@dataclass
class Settings:
    app_name: str = "Milton Agent Backend"
    host: str = os.getenv("MILTON_HOST", "127.0.0.1")
    port: int = int(os.getenv("MILTON_PORT", "8000"))
    db_path: str = os.getenv("MILTON_DB_PATH", "milton_sessions.db")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    server_mode: str = os.getenv("MILTON_SERVER_MODE", "fastapi")
    async_background_processing: bool = os.getenv("MILTON_ASYNC_BACKGROUND_PROCESSING", "true").lower() == "true"
    gemini_api_key: str = (
        fetch_secret_from_secret_manager(os.getenv("GEMINI_API_KEY_SECRET_NAME", "gemini-api-key"))
        or os.getenv("GEMINI_API_KEY", "")
    )


settings = Settings()
