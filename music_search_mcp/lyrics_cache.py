"""Local JSON cache for lyrics data.

Stores fetched lyrics so they don't need to be re-fetched from LRCLIB
on subsequent runs. Cache is stored as a JSON file in the project data directory.
"""

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_CACHE_DIR = _PROJECT_ROOT / "data"
_CACHE_FILE = _CACHE_DIR / "lyrics_cache.json"


def _make_key(track_name: str, artist_name: str) -> str:
    """Create a normalized cache key from track and artist name."""
    return f"{track_name.strip().lower()}||{artist_name.strip().lower()}"


def _load_cache() -> dict:
    """Load the cache from disk."""
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    """Save the cache to disk."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_cached_lyrics(track_name: str, artist_name: str) -> dict | None:
    """Look up lyrics in the local cache.

    Args:
        track_name: The track title.
        artist_name: The artist name.

    Returns:
        Cached lyrics dict with keys (plain_lyrics, synced_lyrics, instrumental,
        lyrics_found), or None if not cached.
    """
    cache = _load_cache()
    key = _make_key(track_name, artist_name)
    return cache.get(key)


def save_lyrics_to_cache(track_name: str, artist_name: str, lyrics_data: dict) -> None:
    """Save lyrics data to the local cache.

    Args:
        track_name: The track title.
        artist_name: The artist name.
        lyrics_data: Dict with keys: plain_lyrics, synced_lyrics, instrumental, lyrics_found.
    """
    cache = _load_cache()
    key = _make_key(track_name, artist_name)
    cache[key] = {
        "track_name": track_name,
        "artist_name": artist_name,
        "plain_lyrics": lyrics_data.get("plain_lyrics"),
        "synced_lyrics": lyrics_data.get("synced_lyrics"),
        "instrumental": lyrics_data.get("instrumental", False),
        "lyrics_found": lyrics_data.get("lyrics_found", False),
    }
    _save_cache(cache)


def get_cache_stats() -> dict:
    """Get statistics about the lyrics cache.

    Returns:
        Dict with keys: total, with_lyrics, instrumental, not_found.
    """
    cache = _load_cache()
    total = len(cache)
    with_lyrics = sum(1 for v in cache.values() if v.get("lyrics_found") and not v.get("instrumental"))
    instrumental = sum(1 for v in cache.values() if v.get("instrumental"))
    not_found = sum(1 for v in cache.values() if not v.get("lyrics_found"))

    return {
        "total": total,
        "with_lyrics": with_lyrics,
        "instrumental": instrumental,
        "not_found": not_found,
    }


def clear_cache() -> int:
    """Clear the entire lyrics cache.

    Returns:
        Number of entries that were cleared.
    """
    cache = _load_cache()
    count = len(cache)
    if _CACHE_FILE.exists():
        _CACHE_FILE.unlink()
    return count
