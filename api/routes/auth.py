import requests
from fastapi import APIRouter, HTTPException, Depends, status
from models.user import RegisterRequest, LoginRequest, TokenResponse
from core.config import get_settings
from services.user_service import get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])

def _get_firebase_auth_url(endpoint: str) -> str:
    settings = get_settings()
    api_key = settings.FIREBASE_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="FIREBASE_API_KEY is not configured")
    return f"https://identitytoolkit.googleapis.com/v1/accounts:{endpoint}?key={api_key}"

@router.post("/register", response_model=TokenResponse)
def register(request: RegisterRequest):
    url = _get_firebase_auth_url("signUp")
    payload = {
        "email": request.email,
        "password": request.password,
        "returnSecureToken": True
    }
    
    response = requests.post(url, json=payload)
    data = response.json()
    
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"].get("message", "Registration failed"))
        
    uid = data["localId"]
    get_or_create_user(uid, request.email, request.display_name)
    
    return TokenResponse(
        uid=uid,
        email=data["email"],
        id_token=data["idToken"],
        refresh_token=data["refreshToken"],
        expires_in=data["expiresIn"]
    )

@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest):
    url = _get_firebase_auth_url("signInWithPassword")
    payload = {
        "email": request.email,
        "password": request.password,
        "returnSecureToken": True
    }
    
    response = requests.post(url, json=payload)
    data = response.json()
    
    if "error" in data:
        raise HTTPException(status_code=400, detail="Invalid email or password")
        
    return TokenResponse(
        uid=data["localId"],
        email=data["email"],
        id_token=data["idToken"],
        refresh_token=data["refreshToken"],
        expires_in=data["expiresIn"]
    )
