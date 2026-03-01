from datetime import datetime, timedelta
from typing import Any, Union
from jose import jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
from core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Union[timedelta, None] = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def encrypt_api_key(api_key: str) -> str:
    settings = get_settings()
    if not settings.ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY is missing from environment.")
    f = Fernet(settings.ENCRYPTION_KEY.encode('utf-8'))
    return f.encrypt(api_key.encode('utf-8')).decode('utf-8')

def decrypt_api_key(encrypted_api_key: str) -> str:
    settings = get_settings()
    if not settings.ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY is missing from environment.")
    f = Fernet(settings.ENCRYPTION_KEY.encode('utf-8'))
    return f.decrypt(encrypted_api_key.encode('utf-8')).decode('utf-8')
