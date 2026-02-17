"""Lyrics fetching client with multi-source fallback.

Primary source: LRCLIB (https://lrclib.net) — free, open, no API key.
Fallback: syncedlyrics library — aggregates Musixmatch, Genius, NetEase,
Deezer, and others. No API keys needed.

Strategy: Try LRCLIB first (fast exact match), then fall back to syncedlyrics
for songs LRCLIB doesn't have. Each result tracks which source provided it
via the lyrics_source field.

Rate limiting: Even though LRCLIB has no published limits, we cap requests
via the shared LYRICS_LIMITER (10/sec) to be polite, especially important
when running concurrent workers.
"""

import httpx

from .rate_limiter import LYRICS_LIMITER

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
    LYRICS_LIMITER.acquire()
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

    LYRICS_LIMITER.acquire()
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


def _mute_syncedlyrics_loggers() -> None:
    """Permanently suppress syncedlyrics' noisy loggers.

    Called once before the first fallback search. With multiple concurrent
    workers, toggling logger levels per-call creates race conditions where
    one worker restores levels while another's daemon thread is still logging.
    Setting to CRITICAL once at module level avoids this entirely.
    """
    import logging
    for name in ["syncedlyrics", "Genius", "NetEase", "Deezer",
                 "Musixmatch", "Lrclib", "Megalobiz", "Lyricsify"]:
        logging.getLogger(name).setLevel(logging.CRITICAL)


_syncedlyrics_loggers_muted = False


def _syncedlyrics_fallback(track_name: str, artist_name: str) -> dict | None:
    """Try to find lyrics via the syncedlyrics library (multi-provider).

    Uses providers OTHER than LRCLIB (since we already tried that).
    Musixmatch is the best provider but has an infinite 401 retry loop
    when its token expires, so we run the whole search in a daemon thread
    with a 30-second timeout to kill hung retries.

    Returns a dict in our standard format, or None if not found.
    """
    try:
        import syncedlyrics
    except ImportError:
        return None

    import threading

    # Mute loggers once (not per-call — avoids race conditions with workers)
    global _syncedlyrics_loggers_muted
    if not _syncedlyrics_loggers_muted:
        _mute_syncedlyrics_loggers()
        _syncedlyrics_loggers_muted = True

    search_term = f"{track_name} {artist_name}"

    # Include musixmatch (only provider that reliably returns plain lyrics)
    # plus others as additional fallbacks. Exclude lrclib (already tried).
    _FALLBACK_PROVIDERS = ["musixmatch", "genius", "netease"]

    # Run in a daemon thread with timeout — protects against Musixmatch's
    # infinite 401 retry loop (sleeps 10s + recursive call, no max retries).
    # If it hangs, the daemon thread is abandoned after 30s.
    result_holder = [None]

    def _do_search():
        try:
            result_holder[0] = syncedlyrics.search(
                search_term,
                plain_only=True,
                providers=_FALLBACK_PROVIDERS,
            )
        except Exception:
            pass

    LYRICS_LIMITER.acquire()
    t = threading.Thread(target=_do_search, daemon=True)
    t.start()
    t.join(timeout=30)  # 30s max per song — kills hung Musixmatch retries

    result = result_holder[0]
    if not result or not result.strip():
        return None

    return {
        "name": track_name,
        "artist": artist_name,
        "album": "",
        "duration": None,
        "instrumental": False,
        "plain_lyrics": result.strip(),
        "synced_lyrics": None,
        "lyrics_source": "syncedlyrics",
    }


def fetch_lyrics_for_songs(songs: list[dict], source: str = "spotify",
                           use_fallback: bool = False) -> list[dict]:
    """Fetch lyrics for a list of songs from Spotify or Last.fm.

    Attempts to find lyrics for each song. Songs without lyrics are
    included in the output with plain_lyrics=None.

    Args:
        songs: List of song dicts (from spotify_client or lastfm_client).
        source: Either "spotify" or "lastfm" to determine field mapping.
        use_fallback: If True, try syncedlyrics (Musixmatch, Genius, etc.)
            when LRCLIB doesn't have the lyrics. Default False — only enabled
            explicitly via --fill-gaps to avoid slow lookups.

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

        # Try LRCLIB first (fast exact match)
        lyrics = None
        lyrics_source = ""
        try:
            lyrics = get_lyrics(
                track_name=track_name,
                artist_name=artist_name,
                album_name=album_name,
                duration=duration,
            )
            if lyrics:
                lyrics_source = "lrclib"
        except Exception:
            pass

        # Fallback: try syncedlyrics (Musixmatch, Genius, NetEase, etc.)
        # Only used when explicitly requested (--fill-gaps) to avoid slow lookups
        if lyrics is None and use_fallback:
            fallback = _syncedlyrics_fallback(track_name, artist_name)
            if fallback:
                lyrics = fallback
                lyrics_source = fallback.get("lyrics_source", "syncedlyrics")

        enriched = {
            **song,
            "plain_lyrics": lyrics["plain_lyrics"] if lyrics else None,
            "synced_lyrics": lyrics.get("synced_lyrics") if lyrics else None,
            "instrumental": lyrics.get("instrumental", False) if lyrics else False,
            "lyrics_found": lyrics is not None,
            "lyrics_source": lyrics_source,
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
