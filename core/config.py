from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    APP_ENV: str = "development"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "*"]

    # Firebase
    FIREBASE_SERVICE_ACCOUNT_PATH: str = "vashiraj-notes-creator.json"
    FIREBASE_API_KEY: str = "" # Used for REST API (Sign in with password, etc)
    
    # Security
    ENCRYPTION_KEY: str = "" # Generated with Fernet.generate_key()
    JWT_SECRET: str = "" # Random string for our own tokens
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 days
    
    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
