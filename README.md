# Music Search MCP

An MCP server that searches your music library using vague recollections. Describe a song you barely remember — a lyric fragment, a mood, a fuzzy memory — and it finds it in your listening history.

## Project Roadmap

| Step | Feature | Status |
|------|---------|--------|
| 1 | Spotify integration — fetch liked songs | **Done** |
| 2 | Last.fm integration — fetch scrobble history | Planned |
| 3 | Lyrics fetching (Genius/Musixmatch/lrclib) | Planned |
| 4 | Embedding pipeline + vector database (ChromaDB) | Planned |
| 5 | Semantic search — query with vague descriptions | Planned |
| 6 | MCP server — expose search as MCP tool | Planned |
| 7 | Spotify playback integration (stretch goal) | Planned |

## Setup

### Prerequisites

- Python 3.11+
- A Spotify Developer account

### 1. Clone and install

```bash
git clone https://github.com/Earththing/Music_Search_MCP.git
cd Music_Search_MCP
pip install -e .
```

### 2. Create a Spotify App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Set the Redirect URI to `http://localhost:8888/callback`
4. Note your Client ID and Client Secret

### 3. Configure credentials

```bash
copy .env.example .env
```

Edit `.env` and fill in your Spotify credentials:

```
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
```

### 4. Fetch your liked songs

```bash
music-search liked-songs          # Fetch all liked songs
music-search liked-songs -n 20    # Fetch first 20
```

On first run, a browser window will open for Spotify login. The token is cached locally for subsequent runs.

## Architecture

```
music_search_mcp/
  __init__.py         # Package root
  config.py           # Environment/config management
  spotify_client.py   # Spotify API client (auth + data fetching)
  cli.py              # CLI entry point for testing
```

**Key design decisions:**
- **spotipy** library for Spotify OAuth2 + API calls
- Token cached locally (`.spotify_token_cache`) so you only log in once
- Songs normalized to a consistent dict format for downstream processing
