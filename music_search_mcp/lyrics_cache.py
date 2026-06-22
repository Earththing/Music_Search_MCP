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
            May also contain: album, spotify_url, lastfm_url, lyrics_source (all optional).
    """
    cache = _load_cache()
    key = _make_key(track_name, artist_name)
    # Preserve existing fields not in lyrics_data (e.g. fallback_tried from
    # a previous save, enrichment metadata, etc.)
    existing = cache.get(key, {})
    cache[key] = {
        "track_name": track_name,
        "artist_name": artist_name,
        "plain_lyrics": lyrics_data.get("plain_lyrics"),
        "synced_lyrics": lyrics_data.get("synced_lyrics"),
        "instrumental": lyrics_data.get("instrumental", False),
        "lyrics_found": lyrics_data.get("lyrics_found", False),
        "album": lyrics_data.get("album", ""),
        "spotify_url": lyrics_data.get("spotify_url", ""),
        "lastfm_url": lyrics_data.get("lastfm_url", ""),
        "lyrics_source": lyrics_data.get("lyrics_source", ""),
        # Fill-gaps tracking: True if --fill-gaps already tried this song
        "fallback_tried": lyrics_data.get("fallback_tried",
                                          existing.get("fallback_tried", False)),
        # Richer Spotify fields (populated by backfill or enrichment)
        "popularity": lyrics_data.get("popularity", 0),
        "explicit": lyrics_data.get("explicit", False),
        "release_date": lyrics_data.get("release_date", ""),
        "duration_ms": lyrics_data.get("duration_ms", 0),
        "artist_ids": lyrics_data.get("artist_ids", []),
        "genres": lyrics_data.get("genres", []),
        # Last.fm metadata (populated by backfill or enrichment)
        "user_playcount": lyrics_data.get("user_playcount"),
        "tags": lyrics_data.get("tags"),
        "loved": lyrics_data.get("loved"),
    }
    _save_cache(cache)


def get_cache_stats() -> dict:
    """Get statistics about the lyrics cache.

    Returns:
        Dict with keys: total, with_lyrics, instrumental, not_found,
        fallback_tried, gaps_remaining.
    """
    cache = _load_cache()
    total = len(cache)
    with_lyrics = sum(1 for v in cache.values() if v.get("lyrics_found") and not v.get("instrumental"))
    instrumental = sum(1 for v in cache.values() if v.get("instrumental"))
    not_found = sum(1 for v in cache.values() if not v.get("lyrics_found"))
    fallback_tried = sum(1 for v in cache.values()
                         if not v.get("lyrics_found") and v.get("fallback_tried"))
    gaps_remaining = not_found - fallback_tried

    return {
        "total": total,
        "with_lyrics": with_lyrics,
        "instrumental": instrumental,
        "not_found": not_found,
        "fallback_tried": fallback_tried,
        "gaps_remaining": gaps_remaining,
    }


def reset_fallback_tried() -> int:
    """Clear the fallback_tried flag on all cache entries so --fill-gaps
    will re-check them.

    Returns:
        Number of entries reset.
    """
    cache = _load_cache()
    count = 0
    for entry in cache.values():
        if entry.get("fallback_tried"):
            entry["fallback_tried"] = False
            count += 1
    if count > 0:
        _save_cache(cache)
    return count


def backfill_cache_metadata() -> int:
    """Patch existing cache entries with metadata from song stores.

    Looks up each cached song in the Spotify and Last.fm song stores and
    fills in any missing fields (album, URLs, popularity, release_date, etc.).
    No API calls — purely local data.

    Returns:
        Number of cache entries updated.
    """
    from .song_store import load_spotify_songs, load_lastfm_scrobbles

    cache = _load_cache()
    if not cache:
        return 0

    # Build lookup dicts from song stores
    spotify_lookup = {}  # key -> song dict
    spotify_data = load_spotify_songs()
    if spotify_data:
        for s in spotify_data["songs"]:
            artist = s["artists"][0] if s.get("artists") else ""
            key = _make_key(s["name"], artist)
            spotify_lookup[key] = s

    lastfm_lookup = {}  # key -> song dict
    lastfm_data = load_lastfm_scrobbles()
    if lastfm_data:
        for s in lastfm_data["songs"]:
            key = _make_key(s["name"], s.get("artist", ""))
            lastfm_lookup[key] = s

    # Fields to backfill from Spotify (field_name, default_to_skip)
    # Only backfill if the cache entry is missing or has the default value.
    _SPOTIFY_FIELDS = [
        ("album", ""),
        ("spotify_url", ""),
        ("popularity", 0),
        ("explicit", False),
        ("release_date", ""),
        ("duration_ms", 0),
        ("artist_ids", []),
        ("genres", []),
    ]

    # Fields to backfill from Last.fm
    _LASTFM_FIELDS = [
        ("album", ""),
        ("lastfm_url", ""),
        ("user_playcount", None),  # None = never fetched; 0 = fetched but zero plays
        ("tags", None),
        ("loved", None),
    ]

    updated = 0
    for key, entry in cache.items():
        changed = False

        # Try Spotify store (has album, spotify_url, popularity, etc.)
        sp_song = spotify_lookup.get(key)
        if sp_song:
            for field, default in _SPOTIFY_FIELDS:
                if entry.get(field, default) == default and sp_song.get(field, default) != default:
                    entry[field] = sp_song[field]
                    changed = True

        # Try Last.fm store (has album, lastfm_url, play counts, tags)
        lfm_song = lastfm_lookup.get(key)
        if lfm_song:
            for field, default in _LASTFM_FIELDS:
                current = entry.get(field)
                source_val = lfm_song.get(field)
                # Backfill if entry is missing/default and source has a value
                if (current is None or current == default) and source_val is not None and source_val != default:
                    entry[field] = source_val
                    changed = True

        if changed:
            updated += 1

    if updated > 0:
        _save_cache(cache)

    return updated


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
