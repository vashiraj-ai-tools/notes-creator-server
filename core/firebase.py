import firebase_admin
from firebase_admin import credentials, firestore
from core.config import get_settings

_db = None

def init_firebase() -> None:
    global _db
    settings = get_settings()
    
    if not firebase_admin._apps:
        if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
            import json
            service_account_info = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
            cred = credentials.Certificate(service_account_info)
        else:
            # Fallback to file path
            cred = credentials.Certificate(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
            
        firebase_admin.initialize_app(cred)
    
    _db = firestore.client()

def get_firestore():
    if _db is None:
        raise RuntimeError("Firebase not initialized. Call init_firebase() first.")
    return _db
