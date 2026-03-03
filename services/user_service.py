from fastapi import HTTPException, status
from firebase_admin import firestore
from core.firebase import get_firestore
from core.security import encrypt_api_key, decrypt_api_key
from services.rate_limiter import check_user_rate_limit

def get_or_create_user(uid: str, email: str, display_name: str = None) -> dict:
    db = get_firestore()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()
    
    if user_doc.exists:
        return user_doc.to_dict()
    
    # Create new profile
    user_data = {
        "email": email,
        "display_name": display_name,
        "created_at": firestore.SERVER_TIMESTAMP,
        "gemini_api_key": None,
        "use_own_key": True,
        "request_timestamps": [],
    }
    user_ref.set(user_data)
    return user_data

def save_gemini_api_key(uid: str, api_key: str) -> None:
    db = get_firestore()
    user_ref = db.collection("users").document(uid)
    
    # User document is guaranteed to exist by get_current_user
    encrypted = encrypt_api_key(api_key)
    user_ref.set({"gemini_api_key": encrypted, "use_own_key": True}, merge=True)

def get_user_profile(uid: str) -> dict:
    db = get_firestore()
    user_doc = db.collection("users").document(uid).get()
    if not user_doc.exists:
        raise HTTPException(status_code=404, detail="User not found")
        
    data = user_doc.to_dict()
    data["uid"] = uid
    data["has_api_key"] = bool(data.get("gemini_api_key"))
    data["use_own_key"] = data.get("use_own_key", True)
    
    # Include rate limit info
    rate_info = check_user_rate_limit(uid)
    data["rate_limit"] = {
        "remaining": rate_info["remaining"],
        "used": rate_info["used"],
        "limit": rate_info["limit"],
        "resets_at": rate_info["resets_at"],
    }
    
    # Don't return the encrypted key itself
    data.pop("gemini_api_key", None)
    data.pop("request_timestamps", None)
    data.pop("created_at", None)
    return data

def delete_gemini_api_key(uid: str) -> None:
    db = get_firestore()
    user_ref = db.collection("users").document(uid)
    user_ref.update({"gemini_api_key": None, "use_own_key": True})

def toggle_use_own_key(uid: str, use_own_key: bool) -> None:
    db = get_firestore()
    user_ref = db.collection("users").document(uid)
    user_ref.update({"use_own_key": use_own_key})
