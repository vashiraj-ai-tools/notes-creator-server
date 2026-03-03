from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    APP_ENV: str = "development"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "*"]

    # Firebase
    FIREBASE_SERVICE_ACCOUNT_PATH: str = "vashiraj-notes-creator.json"
    FIREBASE_SERVICE_ACCOUNT_JSON: str = "" # Full JSON string for deployment
    FIREBASE_API_KEY: str = "" # Used for REST API (Sign in with password, etc)
    
    # Gemini – default key for free-tier / guest users
    DEFAULT_GEMINI_API_KEY: str = ""  # Reads from GEMINI_API_KEY env var fallback
    GEMINI_API_KEY: str = ""  # Legacy env var name
    
    # Rate limiting
    FREE_TIER_LIMIT: int = 5          # max requests for logged-in users without own key
    GUEST_TIER_LIMIT: int = 2         # max requests for anonymous guests
    FREE_TIER_WINDOW_HOURS: int = 24  # rolling window in hours
    
    # YouTube / Extraction
    YOUTUBE_COOKIES: str = "" # Optional: raw text of Netscape cookies file
    
    # Security
    ENCRYPTION_KEY: str = "" # Generated with Fernet.generate_key()
    JWT_SECRET: str = "" # Random string for our own tokens
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 days
    
    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
