"""Spotify API client for fetching user library data.

Rate limits: Spotify uses a rolling 30-second window. Exact limits are
not disclosed, but development mode apps have lower limits. Returns
HTTP 429 with Retry-After header when exceeded. Spotipy handles basic
retries internally; we add a small delay between pages to be polite.
"""

import time
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

from .config import get_spotify_config

# Cache token in project root so re-auth isn't needed every run
_TOKEN_CACHE = Path(__file__).parent.parent / ".spotify_token_cache"

# Delay between API pages to stay well under rate limits
_PAGE_DELAY = 0.5  # seconds


def get_spotify_client() -> spotipy.Spotify:
    """Create an authenticated Spotify client using OAuth2 authorization code flow.

    On first run, this opens a browser for the user to log in.
    The token is cached locally for subsequent runs.
    """
    config = get_spotify_config()

    auth_manager = SpotifyOAuth(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        redirect_uri=config["redirect_uri"],
        scope="user-library-read",
        cache_path=str(_TOKEN_CACHE),
        open_browser=True,
    )

    # retries=3 tells spotipy to retry on 429/5xx up to 3 times
    return spotipy.Spotify(auth_manager=auth_manager, retries=3)


def fetch_liked_songs(limit: int | None = None) -> list[dict]:
    """Fetch the user's liked (saved) songs from Spotify.

    Args:
        limit: Maximum number of songs to fetch. None means fetch all.

    Returns:
        List of song dictionaries with keys:
            - id: Spotify track ID
            - name: Track name
            - artists: List of artist names
            - album: Album name
            - added_at: ISO timestamp when the song was liked
            - duration_ms: Track duration in milliseconds
            - spotify_url: Link to the track on Spotify
    """
    sp = get_spotify_client()
    songs = []
    batch_size = 50  # Spotify API max per request
    offset = 0

    try:
        while True:
            try:
                results = sp.current_user_saved_tracks(limit=batch_size, offset=offset)
            except SpotifyException as e:
                if e.http_status == 429:
                    retry_after = int(e.headers.get("Retry-After", 60)) if e.headers else 60
                    import sys
                    print(f"\n  Spotify rate limit hit! Retry after {retry_after}s "
                          f"({retry_after // 3600}h {(retry_after % 3600) // 60}m).",
                          file=sys.stderr)
                    print(f"  Fetched {len(songs)} songs so far — returning those.",
                          file=sys.stderr)
                    break
                raise

            items = results.get("items", [])

            if not items:
                break

            for item in items:
                track = item["track"]
                songs.append({
                    "id": track["id"],
                    "name": track["name"],
                    "artists": [artist["name"] for artist in track["artists"]],
                    "album": track["album"]["name"],
                    "added_at": item["added_at"],
                    "duration_ms": track["duration_ms"],
                    "spotify_url": track["external_urls"].get("spotify", ""),
                })

            offset += batch_size

            if limit and len(songs) >= limit:
                songs = songs[:limit]
                break

            # If we got fewer items than requested, we've reached the end
            if len(items) < batch_size:
                break

            # Polite delay between pages to avoid rate limits
            time.sleep(_PAGE_DELAY)

    except KeyboardInterrupt:
        import sys
        print(f"\n  Interrupted! Returning {len(songs)} songs fetched so far.",
              file=sys.stderr)

    return songs
