from typing import Optional
from pydantic import BaseModel, EmailStr

class UserProfile(BaseModel):
    uid: str
    email: EmailStr
    display_name: Optional[str] = None
    has_api_key: bool = False

class UpdateApiKeyRequest(BaseModel):
    api_key: str

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
