"""Local JSON storage for song lists fetched from Spotify and Last.fm.

Decouples API fetching from enrichment/indexing so you only hit the APIs
once, then work from local data. Avoids rate-limit issues during development.

Files:
  data/spotify_songs.json    - Liked songs from Spotify
  data/lastfm_scrobbles.json - Unique scrobbles from Last.fm
"""

import json
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_SPOTIFY_FILE = _DATA_DIR / "spotify_songs.json"
_LASTFM_FILE = _DATA_DIR / "lastfm_scrobbles.json"


def _load_store(filepath: Path) -> dict | None:
    """Load a song store file. Returns None if it doesn't exist."""
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_store(filepath: Path, data: dict) -> None:
    """Save a song store file."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_spotify_songs(songs: list[dict]) -> Path:
    """Save Spotify liked songs to local store.

    Args:
        songs: List of song dicts from fetch_liked_songs().

    Returns:
        Path to the saved file.
    """
    data = {
        "source": "spotify",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(songs),
        "songs": songs,
    }
    _save_store(_SPOTIFY_FILE, data)
    return _SPOTIFY_FILE


def save_lastfm_scrobbles(scrobbles: list[dict]) -> Path:
    """Save Last.fm scrobbles to local store.

    Merges new scrobbles with any existing ones (deduplication by name+artist
    is handled by the caller). Preserves the latest_timestamp for incremental
    loading.

    Args:
        scrobbles: List of unique (deduplicated) scrobble dicts.

    Returns:
        Path to the saved file.
    """
    # Find the latest timestamp from the new scrobbles
    latest_ts = _find_latest_timestamp(scrobbles)

    data = {
        "source": "lastfm",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(scrobbles),
        "songs": scrobbles,
        "latest_timestamp": latest_ts,
    }
    _save_store(_LASTFM_FILE, data)
    return _LASTFM_FILE


def _find_latest_timestamp(scrobbles: list[dict]) -> int | None:
    """Find the most recent Unix timestamp among scrobbles."""
    latest = None
    for s in scrobbles:
        ts = s.get("timestamp")
        if ts is not None:
            ts_int = int(ts)
            if latest is None or ts_int > latest:
                latest = ts_int
    return latest


def get_lastfm_latest_timestamp() -> int | None:
    """Get the latest scrobble timestamp from the stored Last.fm data.

    Used for incremental loading — pass this to fetch_scrobbles(since_timestamp=...)
    to only fetch new scrobbles.

    Returns:
        Unix timestamp of the most recent scrobble, or None if no data stored.
    """
    data = _load_store(_LASTFM_FILE)
    if not data:
        return None
    # Try the stored field first (set by save_lastfm_scrobbles)
    ts = data.get("latest_timestamp")
    if ts is not None:
        return ts
    # Fall back to scanning songs (for stores saved before this field existed)
    return _find_latest_timestamp(data.get("songs", []))


def merge_lastfm_scrobbles(new_scrobbles: list[dict]) -> tuple[list[dict], int]:
    """Merge new scrobbles into the existing Last.fm store.

    Deduplicates by normalized track+artist key. Returns the merged list
    and the count of genuinely new songs added.

    Args:
        new_scrobbles: Newly fetched scrobble dicts (already deduplicated).

    Returns:
        (merged_songs, new_count) — full merged list and how many were new.
    """
    existing_data = _load_store(_LASTFM_FILE)
    if not existing_data:
        return new_scrobbles, len(new_scrobbles)

    existing_songs = existing_data.get("songs", [])

    # Build a set of existing keys for fast lookup
    existing_keys = set()
    for s in existing_songs:
        key = f"{s['name'].strip().lower()}||{s.get('artist', '').strip().lower()}"
        existing_keys.add(key)

    # Add only genuinely new songs
    new_count = 0
    merged = list(existing_songs)
    for s in new_scrobbles:
        key = f"{s['name'].strip().lower()}||{s.get('artist', '').strip().lower()}"
        if key not in existing_keys:
            merged.append(s)
            existing_keys.add(key)
            new_count += 1

    return merged, new_count


def get_spotify_known_ids() -> set[str]:
    """Get the set of Spotify track IDs already stored locally.

    Used for incremental loading — pass these to fetch_liked_songs(known_ids=...)
    so it can stop early when it hits songs we already have.

    Returns:
        Set of Spotify track ID strings. Empty set if no data stored.
    """
    data = _load_store(_SPOTIFY_FILE)
    if not data:
        return set()
    return {s["id"] for s in data.get("songs", []) if "id" in s}


def merge_spotify_songs(new_songs: list[dict]) -> tuple[list[dict], int]:
    """Merge new Spotify songs into the existing store.

    New songs are prepended (since Spotify returns most-recently-liked first).
    Deduplicates by track ID.

    Args:
        new_songs: Newly fetched song dicts.

    Returns:
        (merged_songs, new_count) — full merged list and how many were new.
    """
    existing_data = _load_store(_SPOTIFY_FILE)
    if not existing_data:
        return new_songs, len(new_songs)

    existing_songs = existing_data.get("songs", [])
    existing_ids = {s["id"] for s in existing_songs if "id" in s}

    # New songs go first (most recently liked), then existing ones
    genuinely_new = [s for s in new_songs if s["id"] not in existing_ids]
    merged = genuinely_new + existing_songs

    return merged, len(genuinely_new)


def load_spotify_songs() -> dict | None:
    """Load Spotify songs from local store.

    Returns:
        Dict with keys (source, fetched_at, count, songs), or None if not loaded yet.
    """
    return _load_store(_SPOTIFY_FILE)


def load_lastfm_scrobbles() -> dict | None:
    """Load Last.fm scrobbles from local store.

    Returns:
        Dict with keys (source, fetched_at, count, songs), or None if not loaded yet.
    """
    return _load_store(_LASTFM_FILE)


def get_store_info() -> dict:
    """Get info about what's currently stored locally.

    Returns:
        Dict with spotify and lastfm sub-dicts containing exists, count, fetched_at.
    """
    info = {"spotify": None, "lastfm": None}

    spotify_data = _load_store(_SPOTIFY_FILE)
    if spotify_data:
        info["spotify"] = {
            "count": spotify_data["count"],
            "fetched_at": spotify_data["fetched_at"],
            "file": str(_SPOTIFY_FILE),
        }

    lastfm_data = _load_store(_LASTFM_FILE)
    if lastfm_data:
        info["lastfm"] = {
            "count": lastfm_data["count"],
            "fetched_at": lastfm_data["fetched_at"],
            "file": str(_LASTFM_FILE),
        }

    return info
