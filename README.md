# Music Search MCP

An MCP server that searches your music library using vague recollections. Describe a song you barely remember -- a lyric fragment, a mood, a fuzzy memory -- and it finds it in your listening history.

## Project Roadmap

| Step | Feature | Status |
|------|---------|--------|
| 1 | Spotify integration -- fetch liked songs | **Done** |
| 2 | Last.fm integration -- fetch scrobble history | **Done** |
| 3 | Lyrics fetching via LRCLIB + caching | **Done** |
| 4 | Embedding pipeline + vector database (ChromaDB) | **Done** |
| 5 | Semantic search -- query with vague descriptions | **Done** |
| 6 | MCP server -- expose search as MCP tool | Planned |
| 7 | Spotify playback integration (stretch goal) | Planned |

### Future Ideas

- Listening stats: first listened, play count, last heard, genre breakdown
- Visualizations: genre treemap, listening timeline, artist clusters
- These may live as a companion app alongside the MCP server

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

### 5. Load your music library

Fetch your song lists from Spotify/Last.fm and save them locally. This only needs to be done once (or when you want to refresh):

```bash
music-search load spotify    # Fetch all liked songs from Spotify
music-search load lastfm     # Fetch all scrobbles from Last.fm (auto-deduplicates)
music-search load all        # Fetch from both services

music-search status          # See what data you have stored locally
```

On first Spotify run, a browser window will open for login. The token is cached locally for subsequent runs. Song lists are saved to `data/` so all later commands work offline without hitting APIs again.

### 6. Enrich songs with lyrics

```bash
# Enrich from your locally stored song lists (no API calls to Spotify/Last.fm!)
music-search lyrics-enrich                           # Spotify liked songs (default)
music-search lyrics-enrich --source lastfm           # Last.fm scrobbles
music-search lyrics-enrich --source both             # Both sources combined
music-search lyrics-enrich --new 50                  # Enrich 50 NEW songs only (skip cached)
music-search lyrics-enrich -n 20                     # Process 20 songs total (including cached)
music-search lyrics-enrich --force -n 10             # Re-fetch from LRCLIB, ignoring cache

# Search LRCLIB directly (no API key needed)
music-search lyrics-search never gonna give you up rick astley
music-search lyrics-search bohemian rhapsody --show-lyrics
```

Lyrics are cached in `data/lyrics_cache.json` so subsequent runs skip already-fetched songs. Use `--new N` to only enrich songs that haven't been looked up yet.

### 7. Build the search index

Once you have lyrics cached, build the vector search index:

```bash
music-search index                              # Build index from cached lyrics
music-search index --model all-MiniLM-L6-v2     # Specify embedding model (this is the default)
```

The first run downloads the embedding model (~80MB). Subsequent runs use the cached model.

If you have an NVIDIA GPU with CUDA, embeddings will automatically run on GPU. Otherwise it falls back to CPU (still fast for typical library sizes).

### 8. Search your library

Search with natural language -- describe the song however you remember it:

```bash
music-search search that sad song about rain
music-search search upbeat dance track with synthesizers
music-search search "the one where they sing about letting go"
music-search search piano ballad about lost love -n 10        # More results
music-search search melancholy indie song -v                  # Show lyrics preview
```

The search uses cosine similarity against embedded lyrics + metadata, returning matches ranked by relevance score.

## Architecture

```
music_search_mcp/
  __init__.py         # Package root
  config.py           # Environment/config management
  spotify_client.py   # Spotify API client (auth + data fetching)
  lastfm_client.py    # Last.fm API client (scrobble history)
  lyrics_client.py    # LRCLIB lyrics fetcher (free, no API key)
  lyrics_cache.py     # Local JSON cache for fetched lyrics
  song_store.py       # Local JSON storage for song lists (avoid re-fetching)
  vector_store.py     # ChromaDB vector store for semantic search
  cli.py              # CLI entry point for testing

data/
  spotify_songs.json    # Liked songs from Spotify (auto-created, gitignored)
  lastfm_scrobbles.json # Unique scrobbles from Last.fm (auto-created, gitignored)
  lyrics_cache.json     # Cached lyrics (auto-created, gitignored)
  chroma_db/            # Vector database (auto-created, gitignored)
```

**Key design decisions:**
- **spotipy** library for Spotify OAuth2 + API calls
- **Last.fm API** accessed directly via `requests` (simple API key auth, no OAuth needed)
- **LRCLIB** for lyrics -- free, no API key, no rate limits, returns full plain-text lyrics
- **httpx** used for LRCLIB (better TLS compatibility than urllib3/requests on some systems)
- **Local song store** -- song lists saved as JSON after first API fetch; all subsequent commands (enrich, index, search) work offline
- **Lyrics cache** -- JSON file so songs don't need re-fetching between runs; shared across sources
- **ChromaDB** for local persistent vector storage with cosine similarity
- **sentence-transformers** (`all-MiniLM-L6-v2`) for embeddings -- ~80MB model, fast on CPU, auto-uses GPU/CUDA if available
- Each song is embedded as a combined document of lyrics + metadata (title, artist, album), enabling search by mood, theme, lyric fragments, or song identity
- Token cached locally (`.spotify_token_cache`) so you only log in once
- Songs normalized to a consistent dict format for downstream processing
- Last.fm scrobbles auto-deduplicated (same song played 50 times = 1 lyrics lookup)
