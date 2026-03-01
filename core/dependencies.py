from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

from core.firebase import get_firestore
from core.security import decrypt_api_key
from services.user_service import get_or_create_user

security = HTTPBearer()

def get_current_user_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verifies the Firebase ID token and returns the decoded token payload."""
    token = credentials.credentials
    try:
        # Verify the token against Firebase
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def get_current_user(token: dict = Depends(get_current_user_token)) -> dict:
    """Gets the current user from Firestore using the decoded token."""
    uid = token.get("uid")
    if not uid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
        
    user_data = get_or_create_user(uid, email=token.get("email"), display_name=token.get("name"))
    user_data["uid"] = uid
    return user_data

def get_current_user_api_key(user: dict = Depends(get_current_user)) -> str:
    """Gets the user's decrypted Gemini API key."""
    encrypted_key = user.get("gemini_api_key")
    if not encrypted_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gemini API key not found for user. Please save it in your settings.")
        
    try:
        return decrypt_api_key(encrypted_key)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to decrypt API key")
