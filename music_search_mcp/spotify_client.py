"""Spotify API client for fetching user library data.

Rate limits: Spotify uses a rolling 30-second window. Exact limits are
not disclosed, but development mode apps have lower limits. Returns
HTTP 429 with Retry-After header when exceeded. Spotipy handles basic
retries internally; we also throttle via the shared RateLimiter.
"""

import time
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

from .config import get_spotify_config
from .rate_limiter import SPOTIFY_LIMITER

# Cache token in project root so re-auth isn't needed every run
_TOKEN_CACHE = Path(__file__).parent.parent / ".spotify_token_cache"


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


def fetch_liked_songs(limit: int | None = None,
                      known_ids: set[str] | None = None) -> list[dict]:
    """Fetch the user's liked (saved) songs from Spotify.

    Args:
        limit: Maximum number of songs to fetch. None means fetch all.
        known_ids: Set of Spotify track IDs already stored locally.
              When provided, fetching stops once a batch contains only
              songs we already have (incremental mode). This works because
              Spotify returns liked songs in reverse-chronological order.

    Returns:
        List of song dictionaries with keys:
            - id: Spotify track ID
            - name: Track name
            - artists: List of artist names
            - artist_ids: List of Spotify artist IDs (for genre lookup)
            - album: Album name
            - album_id: Spotify album ID
            - release_date: Album release date (YYYY, YYYY-MM, or YYYY-MM-DD)
            - added_at: ISO timestamp when the song was liked
            - duration_ms: Track duration in milliseconds
            - popularity: Spotify popularity score (0-100, global, not per-user)
            - explicit: Whether the track has explicit lyrics
            - track_number: Track position on the album
            - disc_number: Disc number for multi-disc albums
            - spotify_url: Link to the track on Spotify
    """
    sp = get_spotify_client()
    songs = []
    batch_size = 50  # Spotify API max per request
    offset = 0
    hit_known = False

    try:
        while True:
            SPOTIFY_LIMITER.acquire()
            try:
                results = sp.current_user_saved_tracks(limit=batch_size, offset=offset)
            except SpotifyException as e:
                if e.http_status == 429:
                    retry_after = int(e.headers.get("Retry-After", 60)) if e.headers else 60
                    import sys
                    if retry_after <= 60:
                        # Short wait — retry automatically
                        print(f"\n  Spotify rate limit hit, waiting {retry_after}s...",
                              file=sys.stderr)
                        time.sleep(retry_after)
                        continue
                    else:
                        # Long ban — return what we have
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

            new_in_batch = 0
            for item in items:
                track = item["track"]
                track_id = track["id"]

                # In incremental mode, check if we've seen this song before
                if known_ids and track_id in known_ids:
                    continue  # skip known songs

                new_in_batch += 1
                album_obj = track["album"]
                songs.append({
                    "id": track_id,
                    "name": track["name"],
                    "artists": [artist["name"] for artist in track["artists"]],
                    "artist_ids": [artist["id"] for artist in track["artists"]],
                    "album": album_obj["name"],
                    "album_id": album_obj.get("id", ""),
                    "release_date": album_obj.get("release_date", ""),
                    "added_at": item["added_at"],
                    "duration_ms": track["duration_ms"],
                    "popularity": track.get("popularity", 0),
                    "explicit": track.get("explicit", False),
                    "track_number": track.get("track_number", 0),
                    "disc_number": track.get("disc_number", 1),
                    "spotify_url": track["external_urls"].get("spotify", ""),
                })

            # In incremental mode, stop if entire batch was known songs
            if known_ids and new_in_batch == 0:
                hit_known = True
                break

            offset += batch_size

            if limit and len(songs) >= limit:
                songs = songs[:limit]
                break

            # If we got fewer items than requested, we've reached the end
            if len(items) < batch_size:
                break

    except KeyboardInterrupt:
        import sys
        print(f"\n  Interrupted! Returning {len(songs)} songs fetched so far.",
              file=sys.stderr)

    if hit_known and not songs:
        import sys
        print("  No new liked songs since last load.", file=sys.stderr)

    return songs


def fetch_artist_genres(artist_ids: list[str],
                        progress_callback=None,
                        batch_size: int = 50,
                        batch_pause: int = 30) -> dict[str, list[str]]:
    """Fetch genres for a list of Spotify artist IDs.

    Uses individual /artists/{id} calls since Spotify removed the batch
    /artists?ids= endpoint in February 2026 for development-mode apps.

    To avoid triggering Spotify's rolling-window rate limit (which can
    result in 24-hour bans), we pause between batches of calls. Making
    thousands of sequential 1/sec calls without pauses looks like
    sustained automated traffic; inserting periodic pauses keeps the
    request pattern under the radar.

    Args:
        artist_ids: List of Spotify artist IDs.
        progress_callback: Optional callable(done, total) for progress updates.
        batch_size: Number of API calls per batch before pausing (default: 50).
        batch_pause: Seconds to sleep between batches (default: 30). Set to 0
            to disable pausing (not recommended for large fetches).

    Returns:
        Dict mapping artist_id -> list of genre strings.
    """
    if not artist_ids:
        return {}

    sp = get_spotify_client()
    result = {}
    total = len(artist_ids)

    for i, artist_id in enumerate(artist_ids):
        # Batch pacing: after every batch_size calls, pause to avoid
        # tripping Spotify's rolling-window rate limit.
        if i > 0 and i % batch_size == 0 and batch_pause > 0:
            remaining = total - i
            if remaining > 0:
                import sys
                print(f"\n  Pausing {batch_pause}s to stay within rate limits... "
                      f"({i}/{total} artists done)",
                      file=sys.stderr, flush=True)
                time.sleep(batch_pause)

        SPOTIFY_LIMITER.acquire()
        try:
            artist_data = sp.artist(artist_id)
        except SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 60)) if e.headers else 60
                if retry_after <= 60:
                    import sys
                    print(f"\n  Spotify rate limit hit, waiting {retry_after}s...",
                          file=sys.stderr)
                    time.sleep(retry_after)
                    SPOTIFY_LIMITER.acquire()
                    try:
                        artist_data = sp.artist(artist_id)
                    except Exception:
                        continue
                else:
                    # Long ban — return what we have so far
                    import sys
                    print(f"\n  Spotify rate limit hit! Retry after {retry_after}s "
                          f"({retry_after // 3600}h {(retry_after % 3600) // 60}m).",
                          file=sys.stderr)
                    print(f"  Fetched genres for {len(result)}/{total} artists "
                          f"before rate limit.", file=sys.stderr)
                    break
            elif e.http_status == 403:
                continue  # Skip inaccessible artists
            else:
                continue
        except KeyboardInterrupt:
            import sys
            print(f"\n  Interrupted. Fetched genres for {len(result)}/{total} "
                  f"artists so far.", file=sys.stderr)
            break

        if artist_data and artist_data.get("id"):
            result[artist_data["id"]] = artist_data.get("genres", [])

        if progress_callback and (i + 1) % batch_size == 0:
            progress_callback(i + 1, total)

    return result
