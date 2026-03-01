from fastapi import APIRouter, Depends, HTTPException, status
from models.user import UserProfile, UpdateApiKeyRequest, ApiKeyResponse
from core.dependencies import get_current_user
from services.user_service import save_gemini_api_key, get_user_profile, delete_gemini_api_key

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me", response_model=UserProfile)
def get_me(user: dict = Depends(get_current_user)):
    """Get current user profile including API key status."""
    profile_data = get_user_profile(user["uid"])
    return UserProfile(**profile_data)

@router.put("/me/api-key", response_model=ApiKeyResponse)
def update_api_key(request: UpdateApiKeyRequest, user: dict = Depends(get_current_user)):
    """Save or update the user's encrypted Gemini API key."""
    save_gemini_api_key(user["uid"], request.api_key)
    return ApiKeyResponse(message="API key saved.")

@router.delete("/me/api-key", response_model=ApiKeyResponse)
def remove_api_key(user: dict = Depends(get_current_user)):
    """Delete the user's saved API key."""
    delete_gemini_api_key(user["uid"])
    return ApiKeyResponse(message="API key deleted.")
