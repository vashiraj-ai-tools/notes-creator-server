from typing import Optional
from pydantic import BaseModel, EmailStr


class RateLimit(BaseModel):
    remaining: int = 0
    used: int = 0
    limit: int = 5
    resets_at: Optional[str] = None


class UserProfile(BaseModel):
    uid: str
    email: EmailStr
    display_name: Optional[str] = None
    has_api_key: bool = False
    use_own_key: bool = True
    rate_limit: Optional[RateLimit] = None


class UpdateApiKeyRequest(BaseModel):
    api_key: str


class ToggleApiKeyRequest(BaseModel):
    use_own_key: bool


class ApiKeyResponse(BaseModel):
    message: str

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    uid: str
    email: str
    id_token: str
    refresh_token: str
    expires_in: str
