"""
URL cache service — stores generated notes in Firestore with a 7-day TTL.

Cache key strategy (smart normalisation so URL variants for the same content
share one cache entry):
  - YouTube: extract the video ID from any YT URL format → "video:<id>"
  - Blog:    strip query params + fragment, keep scheme+host+path lowercased

The normalised string is then SHA-256 hashed to form the Firestore doc ID.
"""
import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse, parse_qs

import firebase_admin
from firebase_admin import firestore as fb_firestore

# ---------------------------------------------------------------------------
# Collection name & TTL
# ---------------------------------------------------------------------------
_COLLECTION = "url_cache"
_TTL_DAYS = 7

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

_YT_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/embed/|/shorts/|/v/)([A-Za-z0-9_-]{11})"
)


def _extract_youtube_id(url: str) -> Optional[str]:
    """Return the 11-char video ID from any recognised YouTube URL format."""
    m = _YT_ID_RE.search(url)
    if m:
        return m.group(1)
    # fallback: parse query string
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    v_list = qs.get("v", [])
    return v_list[0] if v_list else None


def normalise_url(url: str) -> str:
    """
    Return a stable, human-readable identifier that is the same for all URL
    variants pointing to the same content.
      - YouTube → "video:<11-char-id>"
      - Everything else → "blog:<scheme>://<host><path>" (lowercased, no trailing slash)
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().lstrip("www.")
    if host in {h.lstrip("www.") for h in _YT_HOSTS}:
        vid = _extract_youtube_id(url)
        if vid:
            return f"video:{vid}"
    # Blog / article
    canonical = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    return f"blog:{canonical}"


def get_cache_key(url: str) -> str:
    """SHA-256 hash of the normalised URL identifier."""
    return hashlib.sha256(normalise_url(url).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------
def _get_collection():
    client = fb_firestore.client()
    return client.collection(_COLLECTION)


def get_cached_notes(url: str) -> Optional[dict]:
    """
    Return cached {notes, source} if a fresh (≤ 7 days old) entry exists,
    otherwise None.
    """
    try:
        key = get_cache_key(url)
        doc = _get_collection().document(key).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        cached_at: datetime = data.get("cached_at")
        if cached_at is None:
            return None

        # Firestore returns timezone-aware datetimes; ensure comparison works
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)

        age = datetime.now(timezone.utc) - cached_at
        if age > timedelta(days=_TTL_DAYS):
            return None  # stale — treat as cache miss

        return {
            "notes": data.get("notes", ""),
            "source": data.get("source", {}),
        }
    except Exception as exc:
        # Never let a cache failure block the request
        print(f"[url_cache] get_cached_notes error: {exc}")
        return None


def cache_notes(url: str, notes_result: dict) -> None:
    """
    Persist notes_result (must contain 'notes' and 'source') for this URL.
    Silently swallows errors so callers are never disrupted.
    """
    try:
        key = get_cache_key(url)
        normalised = normalise_url(url)
        _get_collection().document(key).set({
            "cache_key": key,
            "normalised": normalised,
            "notes": notes_result.get("notes", ""),
            "source": notes_result.get("source", {}),
            "cached_at": datetime.now(timezone.utc),
        })
        print(f"[url_cache] Cached notes for: {normalised}")
    except Exception as exc:
        print(f"[url_cache] cache_notes error: {exc}")
