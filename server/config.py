"""trmsg - Server Configuration"""
import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite+aiosqlite:///./trmsg.db"
    SECRET_KEY: str = "trmsg-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 200 * 1024 * 1024
    GEMINI_API_KEY: Optional[str] = None
    ALLOWED_EXTENSIONS: list = [
        "jpg","jpeg","png","gif","webp","svg",
        "pdf","txt","md","py","js","ts","go","rs","java","cpp","c","h",
        "mp4","mov","avi","mkv","mp3","wav","ogg",
        "zip","tar","gz","7z","doc","docx","xls","xlsx","csv","json","xml","yaml","toml",
    ]
    MAX_MESSAGE_LENGTH: int = 4000
    BURN_MESSAGE_MAX_SECONDS: int = 300
    class Config:
        env_file = ".env"

settings = Settings()
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
