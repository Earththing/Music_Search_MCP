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

    Args:
        scrobbles: List of unique (deduplicated) scrobble dicts.

    Returns:
        Path to the saved file.
    """
    data = {
        "source": "lastfm",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(scrobbles),
        "songs": scrobbles,
    }
    _save_store(_LASTFM_FILE, data)
    return _LASTFM_FILE


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
