# Music Search MCP

An MCP server that searches your music library using vague recollections. Describe a song you barely remember -- a lyric fragment, a mood, a fuzzy memory -- and it finds it in your listening history.

## Project Roadmap

| Step | Feature | Status |
|------|---------|--------|
| 1 | Spotify integration -- fetch liked songs | **Done** |
| 2 | Last.fm integration -- fetch scrobble history | **Done** |
| 3 | Lyrics fetching via LRCLIB | **Done** |
| 4 | Embedding pipeline + vector database (ChromaDB) | Planned |
| 5 | Semantic search -- query with vague descriptions | Planned |
| 6 | MCP server -- expose search as MCP tool | Planned |
| 7 | Spotify playback integration (stretch goal) | Planned |

## Setup

### Prerequisites

- Python 3.11+
- A Spotify Developer account
- A Last.fm account with API key

### 1. Clone and install

```bash
git clone https://github.com/Earththing/Music_Search_MCP.git
cd Music_Search_MCP
pip install -e .
```

### 2. Create a Spotify App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Set the Redirect URI to `http://127.0.0.1:8888/callback` (must use IP, not `localhost`)
4. Note your Client ID and Client Secret

### 3. Create a Last.fm API account

1. Go to [Last.fm API Account Creation](https://www.last.fm/api/account/create)
2. Note your API Key (shared secret is not needed)

### 4. Configure credentials

```bash
copy .env.example .env
```

Edit `.env` and fill in your credentials:

```
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback

LASTFM_API_KEY=your_api_key_here
LASTFM_USERNAME=your_lastfm_username
```

### 5. Fetch your music data

```bash
# Spotify liked songs
music-search liked-songs          # Fetch all liked songs
music-search liked-songs -n 20    # Fetch first 20

# Last.fm scrobble history
music-search scrobbles            # Fetch all scrobbles (can be slow for large histories)
music-search scrobbles -n 50      # Fetch most recent 50

# Search for lyrics (no API key needed)
music-search lyrics-search never gonna give you up rick astley
music-search lyrics-search bohemian rhapsody --show-lyrics

# Enrich your Spotify liked songs with lyrics
music-search lyrics-enrich -n 20  # Fetch lyrics for first 20 liked songs
```

On first Spotify run, a browser window will open for login. The token is cached locally for subsequent runs.

## Architecture

```
music_search_mcp/
  __init__.py         # Package root
  config.py           # Environment/config management
  spotify_client.py   # Spotify API client (auth + data fetching)
  lastfm_client.py    # Last.fm API client (scrobble history)
  lyrics_client.py    # LRCLIB lyrics fetcher (free, no API key)
  cli.py              # CLI entry point for testing
```

**Key design decisions:**
- **spotipy** library for Spotify OAuth2 + API calls
- **Last.fm API** accessed directly via `requests` (simple API key auth, no OAuth needed)
- **LRCLIB** for lyrics -- free, no API key, no rate limits, returns full plain-text lyrics
- **httpx** used for LRCLIB (better TLS compatibility than urllib3/requests on some systems)
- Token cached locally (`.spotify_token_cache`) so you only log in once
- Songs normalized to a consistent dict format for downstream processing
