"""Lyrics fetching client using the LRCLIB API.

LRCLIB (https://lrclib.net) is a free, open lyrics database.
No API key required, no documented rate limits. The project encourages
setting a User-Agent with app name and project URL.

Uses httpx instead of requests because lrclib.net's TLS configuration
is incompatible with urllib3/requests on some Python installations.
"""

import httpx

LRCLIB_API_URL = "https://lrclib.net/api"
_HEADERS = {
    "User-Agent": "MusicSearchMCP/0.1.0 (https://github.com/Earththing/Music_Search_MCP)",
}


def search_lyrics(query: str, limit: int = 5) -> list[dict]:
    """Search for lyrics using a free-text query.

    Args:
        query: Search string (e.g. "never gonna give you up rick astley").
        limit: Maximum results to return.

    Returns:
        List of match dicts with keys:
            - id: LRCLIB track ID
            - name: Track name
            - artist: Artist name
            - album: Album name
            - duration: Duration in seconds
            - instrumental: Whether the track is instrumental
            - plain_lyrics: Full plain-text lyrics (or None)
            - synced_lyrics: Time-stamped lyrics (or None)
    """
    resp = httpx.get(
        f"{LRCLIB_API_URL}/search",
        params={"q": query},
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()

    results = []
    for item in resp.json()[:limit]:
        results.append(_parse_lrclib_result(item))

    return results


def get_lyrics(track_name: str, artist_name: str, album_name: str = "", duration: int | None = None) -> dict | None:
    """Get lyrics for a specific track by name and artist.

    This uses LRCLIB's "get" endpoint which tries to find an exact match.

    Args:
        track_name: The track title.
        artist_name: The artist name.
        album_name: Optional album name for better matching.
        duration: Optional track duration in seconds for better matching.

    Returns:
        A lyrics dict (same format as search_lyrics results), or None if not found.
    """
    params = {
        "track_name": track_name,
        "artist_name": artist_name,
    }
    if album_name:
        params["album_name"] = album_name
    if duration is not None:
        params["duration"] = duration

    resp = httpx.get(
        f"{LRCLIB_API_URL}/get",
        params=params,
        headers=_HEADERS,
        timeout=30,
    )

    if resp.status_code == 404:
        return None

    resp.raise_for_status()
    return _parse_lrclib_result(resp.json())


def fetch_lyrics_for_songs(songs: list[dict], source: str = "spotify") -> list[dict]:
    """Fetch lyrics for a list of songs from Spotify or Last.fm.

    Attempts to find lyrics for each song. Songs without lyrics are
    included in the output with plain_lyrics=None.

    Args:
        songs: List of song dicts (from spotify_client or lastfm_client).
        source: Either "spotify" or "lastfm" to determine field mapping.

    Returns:
        List of dicts with the original song data plus lyrics fields:
            - plain_lyrics: Full lyrics text (or None)
            - synced_lyrics: Synced lyrics (or None)
            - instrumental: Whether the track is instrumental
            - lyrics_found: Whether lyrics were successfully fetched
    """
    results = []

    for song in songs:
        if source == "spotify":
            track_name = song["name"]
            artist_name = song["artists"][0] if song["artists"] else ""
            album_name = song.get("album", "")
            duration = song.get("duration_ms", 0) // 1000 if song.get("duration_ms") else None
        elif source == "lastfm":
            track_name = song["name"]
            artist_name = song["artist"]
            album_name = song.get("album", "")
            duration = None
        else:
            raise ValueError(f"Unknown source: {source}")

        try:
            lyrics = get_lyrics(
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name,
                duration=duration,
            )
        except Exception:
            lyrics = None

        enriched = {
            **song,
            "plain_lyrics": lyrics["plain_lyrics"] if lyrics else None,
            "synced_lyrics": lyrics["synced_lyrics"] if lyrics else None,
            "instrumental": lyrics["instrumental"] if lyrics else False,
            "lyrics_found": lyrics is not None,
        }
        results.append(enriched)

    return results


def _parse_lrclib_result(item: dict) -> dict:
    """Parse a raw LRCLIB API response item into our standard format."""
    return {
        "id": item.get("id"),
        "name": item.get("trackName", item.get("name", "")),
        "artist": item.get("artistName", ""),
        "album": item.get("albumName", ""),
        "duration": item.get("duration"),
        "instrumental": item.get("instrumental", False),
        "plain_lyrics": item.get("plainLyrics"),
        "synced_lyrics": item.get("syncedLyrics"),
    }
