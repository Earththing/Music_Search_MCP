"""Last.fm API client for fetching scrobble history."""

import time
import requests

from .config import get_lastfm_config

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

# Retry config for transient server errors
_MAX_RETRIES = 5
_RETRY_DELAY = 3  # seconds, doubles each retry


def _lastfm_request(method: str, **params) -> dict:
    """Make a request to the Last.fm API with automatic retry on transient errors.

    Args:
        method: The Last.fm API method (e.g. 'user.getRecentTracks').
        **params: Additional query parameters.

    Returns:
        Parsed JSON response.

    Raises:
        requests.HTTPError: On persistent API errors after retries.
    """
    config = get_lastfm_config()

    query = {
        "method": method,
        "api_key": config["api_key"],
        "format": "json",
        **params,
    }

    delay = _RETRY_DELAY
    for attempt in range(_MAX_RETRIES):
        try:
            resp = requests.get(LASTFM_API_URL, params=query, timeout=30)
            resp.raise_for_status()

            data = resp.json()

            if "error" in data:
                raise ValueError(f"Last.fm API error {data['error']}: {data.get('message', '')}")

            return data

        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            # Retry on 5xx server errors and connection issues
            is_server_error = hasattr(e, "response") and e.response is not None and e.response.status_code >= 500
            is_connection_error = isinstance(e, (requests.ConnectionError, requests.Timeout))

            if (is_server_error or is_connection_error) and attempt < _MAX_RETRIES - 1:
                import sys
                print(f"\n  [retry {attempt + 1}/{_MAX_RETRIES}] Server error, waiting {delay}s...",
                      file=sys.stderr, end="", flush=True)
                time.sleep(delay)
                delay *= 2  # exponential backoff
                continue

            raise  # re-raise on final attempt or non-retryable error


def fetch_scrobbles(limit: int | None = None) -> list[dict]:
    """Fetch the user's scrobble (listening) history from Last.fm.

    Args:
        limit: Maximum number of scrobbles to fetch. None means fetch all.
              Note: fetching all can be slow for large histories (1000s of songs).

    Returns:
        List of scrobble dictionaries with keys:
            - name: Track name
            - artist: Artist name
            - album: Album name
            - timestamp: Unix timestamp of when the track was played (None if now playing)
            - date_text: Human-readable date string (None if now playing)
            - now_playing: Whether this track is currently playing
            - lastfm_url: Link to the track on Last.fm
    """
    config = get_lastfm_config()
    username = config["username"]

    scrobbles = []
    page = 1
    per_page = 200  # Last.fm API max per request

    try:
        while True:
            data = _lastfm_request(
                "user.getRecentTracks",
                user=username,
                limit=per_page,
                page=page,
                extended=0,
            )

            tracks_data = data.get("recenttracks", {})
            tracks = tracks_data.get("track", [])

            # If only one track, the API returns a dict instead of a list
            if isinstance(tracks, dict):
                tracks = [tracks]

            if not tracks:
                break

            for track in tracks:
                is_now_playing = track.get("@attr", {}).get("nowplaying") == "true"

                scrobbles.append({
                    "name": track.get("name", ""),
                    "artist": track.get("artist", {}).get("#text", ""),
                    "album": track.get("album", {}).get("#text", ""),
                    "timestamp": track.get("date", {}).get("uts") if not is_now_playing else None,
                    "date_text": track.get("date", {}).get("#text") if not is_now_playing else "Now playing",
                    "now_playing": is_now_playing,
                    "lastfm_url": track.get("url", ""),
                })

            if limit and len(scrobbles) >= limit:
                scrobbles = scrobbles[:limit]
                break

            # Check pagination
            attr = tracks_data.get("@attr", {})
            total_pages = int(attr.get("totalPages", 1))

            # Progress feedback for large fetches
            if total_pages > 5:
                import sys
                import shutil
                width = shutil.get_terminal_size().columns - 1
                line = f"  Page {page}/{total_pages} ({len(scrobbles):,} scrobbles so far)"
                sys.stdout.write(f"\r{line[:width]:<{width}}")
                sys.stdout.flush()

            if page >= total_pages:
                break

            page += 1

    except KeyboardInterrupt:
        import sys
        print(f"\n  Interrupted! Returning {len(scrobbles):,} scrobbles fetched so far.",
              file=sys.stderr)

    # Clear progress line if we printed one
    if page > 5:
        import sys
        import shutil
        width = shutil.get_terminal_size().columns - 1
        sys.stdout.write(f"\r{'':<{width}}\r")
        sys.stdout.flush()

    return scrobbles


def get_scrobble_stats(username: str | None = None) -> dict:
    """Get basic stats about the user's scrobble history.

    Returns:
        Dict with keys: total_scrobbles, total_pages
    """
    config = get_lastfm_config()
    user = username or config["username"]

    data = _lastfm_request(
        "user.getRecentTracks",
        user=user,
        limit=1,
        page=1,
    )

    attr = data.get("recenttracks", {}).get("@attr", {})

    return {
        "total_scrobbles": int(attr.get("total", 0)),
        "total_pages": int(attr.get("totalPages", 0)),
    }
