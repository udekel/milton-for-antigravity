import os
from dataclasses import dataclass


@dataclass
class Settings:
    app_name: str = "Milton Agent Backend"
    host: str = os.getenv("MILTON_HOST", "127.0.0.1")
    port: int = int(os.getenv("MILTON_PORT", "8000"))
    db_path: str = os.getenv("MILTON_DB_PATH", "milton_sessions.db")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")


settings = Settings()
