"""
Rate limiting service for free-tier and guest usage.
- Logged-in users without own API key: 5 requests per 24h rolling window.
- Guest (anonymous) users: 2 requests per 24h, tracked by IP hash.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List

from core.config import get_settings
from core.firebase import get_firestore


def _filter_recent(timestamps: List[str], window_hours: int) -> List[str]:
    """Keep only timestamps within the rolling window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    recent = []
    for ts in timestamps:
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > cutoff:
                recent.append(ts)
        except (ValueError, TypeError):
            continue
    return recent


def _compute_reset(timestamps: List[str], window_hours: int) -> str | None:
    """Return ISO string of when the oldest tracked request expires."""
    if not timestamps:
        return None
    try:
        oldest = min(datetime.fromisoformat(ts) for ts in timestamps)
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        return (oldest + timedelta(hours=window_hours)).isoformat()
    except (ValueError, TypeError):
        return None


# ── Logged-in user rate limiting ─────────────────────────────────────────────

def check_user_rate_limit(uid: str) -> dict:
    """Check rate limit for a logged-in user without their own API key."""
    settings = get_settings()
    db = get_firestore()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()

    timestamps: List[str] = []
    if user_doc.exists:
        timestamps = user_doc.to_dict().get("request_timestamps", [])

    recent = _filter_recent(timestamps, settings.FREE_TIER_WINDOW_HOURS)
    remaining = max(0, settings.FREE_TIER_LIMIT - len(recent))

    return {
        "allowed": remaining > 0,
        "remaining": remaining,
        "used": len(recent),
        "limit": settings.FREE_TIER_LIMIT,
        "resets_at": _compute_reset(recent, settings.FREE_TIER_WINDOW_HOURS),
    }


def record_user_request(uid: str) -> None:
    """Record a free-tier request for a logged-in user."""
    settings = get_settings()
    db = get_firestore()
    user_ref = db.collection("users").document(uid)
    user_doc = user_ref.get()

    timestamps: List[str] = []
    if user_doc.exists:
        timestamps = user_doc.to_dict().get("request_timestamps", [])

    # Clean old entries and append new
    recent = _filter_recent(timestamps, settings.FREE_TIER_WINDOW_HOURS)
    recent.append(datetime.now(timezone.utc).isoformat())
    user_ref.set({"request_timestamps": recent}, merge=True)


# ── Guest (anonymous) rate limiting ──────────────────────────────────────────

def _hash_ip(ip: str) -> str:
    """Hash the IP address for privacy-safe storage."""
    return hashlib.sha256(ip.encode()).hexdigest()


def check_guest_rate_limit(ip: str) -> dict:
    """Check rate limit for an anonymous guest by IP."""
    settings = get_settings()
    db = get_firestore()
    ip_hash = _hash_ip(ip)
    doc_ref = db.collection("guest_requests").document(ip_hash)
    doc = doc_ref.get()

    timestamps: List[str] = []
    if doc.exists:
        timestamps = doc.to_dict().get("request_timestamps", [])

    recent = _filter_recent(timestamps, settings.FREE_TIER_WINDOW_HOURS)
    remaining = max(0, settings.GUEST_TIER_LIMIT - len(recent))

    return {
        "allowed": remaining > 0,
        "remaining": remaining,
        "used": len(recent),
        "limit": settings.GUEST_TIER_LIMIT,
        "resets_at": _compute_reset(recent, settings.FREE_TIER_WINDOW_HOURS),
    }


def record_guest_request(ip: str) -> None:
    """Record a guest request by IP hash."""
    settings = get_settings()
    db = get_firestore()
    ip_hash = _hash_ip(ip)
    doc_ref = db.collection("guest_requests").document(ip_hash)
    doc = doc_ref.get()

    timestamps: List[str] = []
    if doc.exists:
        timestamps = doc.to_dict().get("request_timestamps", [])

    recent = _filter_recent(timestamps, settings.FREE_TIER_WINDOW_HOURS)
    recent.append(datetime.now(timezone.utc).isoformat())
    doc_ref.set({"request_timestamps": recent})
