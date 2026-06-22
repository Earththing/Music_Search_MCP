# Music Search MCP

An MCP server that searches your music library using vague recollections. Describe a song you barely remember -- a lyric fragment, a mood, a fuzzy memory -- and it finds it in your listening history.

## Setup

### Prerequisites

- Python 3.11+
- A Spotify Developer account (Premium required as of Feb 2026)
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

Fetch your song lists from Spotify/Last.fm and save them locally:

```bash
music-search load spotify    # Fetch liked songs from Spotify
music-search load lastfm     # Fetch scrobbles from Last.fm (auto-deduplicates)
music-search load all        # Fetch from both services

music-search status          # See what data you have stored locally
```

**Incremental loading:** After the first load, subsequent `load` commands only fetch new songs. Spotify stops at already-known tracks; Last.fm uses the timestamp of the most recent scrobble. To re-fetch everything from scratch, use `--full`:

```bash
music-search load lastfm          # Only new scrobbles since last load
music-search load spotify         # Only new liked songs since last load
music-search load all --full      # Re-fetch everything from scratch
```

On first Spotify run, a browser window will open for login. The token is cached locally for subsequent runs. Song lists are saved to `data/` so all later commands work offline without hitting APIs again.

### 6. Enrich songs with lyrics

```bash
# Enrich from your locally stored song lists (no API calls to Spotify/Last.fm!)
music-search lyrics-enrich                           # Use whatever source is loaded (auto-detect)
music-search lyrics-enrich --source spotify          # Spotify liked songs only
music-search lyrics-enrich --source lastfm           # Last.fm scrobbles only
music-search lyrics-enrich --source both             # Both sources combined + deduplicated

# Control how many songs to process
music-search lyrics-enrich --new 500                 # Enrich 500 NEW (uncached) songs only
music-search lyrics-enrich -n 20                     # Process 20 songs total (including cached)
music-search lyrics-enrich --force -n 10             # Re-fetch from LRCLIB, ignoring cache

# Speed up enrichment with concurrent workers
music-search lyrics-enrich --new 500 --workers 8     # 8 parallel LRCLIB lookups

# Auto-rebuild the search index after enrichment
music-search lyrics-enrich --new 500 --index         # Enrich + re-index automatically

# Fill gaps: try alternative sources for songs LRCLIB missed
music-search lyrics-enrich --fill-gaps -n 100 --workers 3
music-search lyrics-enrich --fill-gaps -n 100 --workers 3   # Next run skips already-tried songs
music-search lyrics-enrich --reset-gaps                      # Clear flags to retry all gaps
music-search lyrics-enrich --reset-gaps --fill-gaps -n 100   # Reset + retry in one command

# Search LRCLIB directly (no API key needed)
music-search lyrics-search never gonna give you up rick astley
music-search lyrics-search bohemian rhapsody --show-lyrics
```

Lyrics are cached in `data/lyrics_cache.json` so subsequent runs skip already-fetched songs. Press Ctrl+C at any time to stop gracefully -- all completed lookups are saved immediately.

### 7. Enrich with metadata

Fetch additional metadata from Last.fm and Spotify:

```bash
music-search enrich-metadata lastfm     # Per-user play counts, tags, loved status
music-search enrich-metadata spotify     # Artist genres (paced to avoid rate limits)
music-search enrich-metadata all         # Both services
music-search enrich-metadata lastfm -n 100   # Limit to 100 songs
```

**Last.fm metadata** (~1h 53m for 27K songs at 4 req/sec): personal play counts, global listen counts, community tags, and loved status for each song.

**Spotify genres** (~58 min for 2K artists at 1 req/sec with pacing pauses): fetches genre tags from each artist. Since Spotify removed batch endpoints in February 2026, this uses individual API calls paced at 1/sec with 30-second pauses every 50 calls to avoid triggering rate-limit bans.

### 8. Build the search index

Once you have lyrics cached, build the vector search index:

```bash
music-search index                              # Build index from cached lyrics
music-search index --model all-MiniLM-L6-v2     # Specify embedding model (this is the default)
```

The first run downloads the embedding model (~80MB). Subsequent runs use the cached model.

If you have an NVIDIA GPU with CUDA, embeddings will automatically run on GPU. Otherwise it falls back to CPU (still fast for typical library sizes).

### 9. Search your library

Search with natural language -- describe the song however you remember it:

```bash
music-search search that sad song about rain
music-search search upbeat dance track with synthesizers
music-search search "the one where they sing about letting go"
music-search search piano ballad about lost love -n 10        # More results
music-search search melancholy indie song -v                  # Show lyrics preview
```

The search uses cosine similarity against embedded lyrics + metadata, returning matches ranked by relevance score. Results include Spotify links when available.

### 10. Export to SQLite

Export your full library to a SQLite database for ad-hoc SQL exploration:

```bash
music-search export-db                          # Export to data/music_library.db
music-search export-db --path ~/my_music.db     # Custom output path
```

The SQLite database includes:
- A `songs` table with full metadata and provenance (`in_spotify`, `in_lastfm`)
- A `lyrics_fts` FTS5 virtual table for full-text lyrics search

Example SQL queries:

```sql
-- Most-represented artists
SELECT artist_name, COUNT(*) as songs FROM songs GROUP BY artist_name ORDER BY songs DESC LIMIT 20;

-- Full-text lyrics search
SELECT track_name, artist_name FROM lyrics_fts WHERE lyrics_fts MATCH 'thunder' LIMIT 10;

-- Spotify vs Last.fm overlap
SELECT SUM(in_spotify AND in_lastfm) as both,
       SUM(in_spotify AND NOT in_lastfm) as spotify_only,
       SUM(in_lastfm AND NOT in_spotify) as lastfm_only
FROM songs;
```

### One-command refresh

Run the full pipeline in one shot:

```bash
music-search refresh                     # load > enrich > index > export (incremental)
music-search refresh --full              # Re-fetch everything from scratch
music-search refresh --fill-gaps         # Also try alternative lyrics sources
music-search refresh --workers 8         # Use 8 concurrent lyrics lookups
music-search refresh --reset-gaps --fill-gaps   # Retry all previously-failed gaps
```

## MCP Server (Claude Desktop Integration)

The project includes an MCP server that exposes the semantic search as a tool for Claude Desktop (or any MCP-compatible client). This lets you search your music library by chatting with Claude.

### Available Tools

| Tool | Description |
|------|-------------|
| `search_music` | Search your library with a natural language description |
| `library_status` | Check what data is indexed and whether the pipeline is set up |

### Setup

1. Make sure you have completed the steps above (load songs, enrich lyrics, build index).

2. Install the project (if not already):
   ```bash
   pip install -e .
   ```

3. Configure Claude Desktop. Open (or create) the config file:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

   Add the music search server (use the full path to avoid PATH issues):
   ```json
   {
     "mcpServers": {
       "music-search": {
         "command": "C:\\path\\to\\your\\Python311\\Scripts\\music-search-mcp.exe"
       }
     }
   }
   ```

   Find your full path with: `where music-search-mcp`

4. Restart Claude Desktop completely (quit from system tray, then relaunch). The music search tools should appear in the tools menu.

### Usage Examples

Once connected, ask Claude things like:

- "Search my music library for that sad song about rain"
- "Find upbeat dance tracks with synthesizers in my collection"
- "What's the status of my music search library?"
- "Can you find the song where they sing about letting go?"

### Note on First Search

The first search after starting the server takes ~7 seconds because the embedding model loads into memory. Subsequent searches are fast (under 1 second). The model stays cached for the lifetime of the server process.

### Running Manually (for testing)

```bash
music-search-mcp                          # Start the MCP server on stdio
mcp dev music_search_mcp/mcp_server.py    # Use the MCP CLI inspector (requires mcp[cli])
```

## Architecture

```
music_search_mcp/
  __init__.py         # Package root
  config.py           # Environment/config management
  spotify_client.py   # Spotify API client (auth + data fetching + artist genres)
  lastfm_client.py    # Last.fm API client (scrobble history + track info)
  lyrics_client.py    # LRCLIB lyrics fetcher + syncedlyrics fallback
  lyrics_cache.py     # Local JSON cache for fetched lyrics + metadata
  song_store.py       # Local JSON storage for song lists (avoid re-fetching)
  rate_limiter.py     # Thread-safe rate limiting for all API clients
  vector_store.py     # ChromaDB vector store for semantic search
  sqlite_export.py    # SQLite database export with FTS5 lyrics search
  cli.py              # CLI entry point (all commands)
  mcp_server.py       # MCP server for Claude Desktop integration

data/
  spotify_songs.json    # Liked songs from Spotify (auto-created, gitignored)
  lastfm_scrobbles.json # Unique scrobbles from Last.fm (auto-created, gitignored)
  lyrics_cache.json     # Cached lyrics + metadata (auto-created, gitignored)
  chroma_db/            # Vector database (auto-created, gitignored)
  music_library.db      # SQLite export (auto-created, gitignored)
```

## CLI Command Reference

| Command | Description |
|---------|-------------|
| `music-search load <source>` | Fetch songs from `spotify`, `lastfm`, or `all` and save locally |
| `music-search status` | Show local data status (stores, cache, index, unenriched count) |
| `music-search lyrics-enrich` | Fetch lyrics from LRCLIB (+ fallback sources with `--fill-gaps`) |
| `music-search lyrics-search <query>` | Search LRCLIB directly for lyrics |
| `music-search index` | Build the vector search index from cached lyrics |
| `music-search search <query>` | Search your music library with natural language |
| `music-search enrich-metadata <target>` | Fetch play counts/tags (Last.fm) or genres (Spotify) |
| `music-search export-db` | Export full library to SQLite with FTS5 lyrics search |
| `music-search refresh` | One-command pipeline: load > enrich > index > export |
| `music-search liked-songs` | Fetch and display Spotify liked songs (direct API call) |
| `music-search scrobbles` | Fetch and display Last.fm scrobbles (direct API call) |

### load options

```
--full                              Re-fetch everything from scratch (default: incremental)
```

### lyrics-enrich options

```
--source auto|spotify|lastfm|both   Song source (default: auto-detect)
--new N                             Enrich N new uncached songs only
-n N, --limit N                     Process N songs total (including cached)
--workers N                         Concurrent LRCLIB lookups (default: 1)
--force                             Re-fetch even if already cached
--index                             Rebuild search index after enrichment
--fill-gaps                         Try alternative sources (Musixmatch, Genius, NetEase)
                                    for songs LRCLIB missed. Skips already-tried songs.
--reset-gaps                        Clear 'already tried' flags so --fill-gaps retries all
```

### search options

```
-n N, --limit N                     Max results (default: 5)
--model MODEL                       Embedding model (default: all-MiniLM-L6-v2)
-v, --verbose                       Show lyrics preview in results
```

### enrich-metadata options

```
target                              lastfm, spotify, or all
-n N, --limit N                     Max songs to enrich (default: all unenriched)
```

### export-db options

```
--path PATH                         Output path (default: data/music_library.db)
```

### refresh options

```
--full                              Re-fetch everything from scratch
--workers N                         Concurrent lyrics lookups (default: 4)
--fill-gaps                         Try alternative lyrics sources for missing songs
--reset-gaps                        Clear 'already tried' flags before filling gaps
--model MODEL                       Embedding model for indexing
```

## Spotify API Notes (February 2026)

Spotify made significant changes to their Web API for development-mode apps in February 2026:

- **Batch endpoints removed:** `GET /artists?ids=`, `GET /tracks?ids=`, etc. are no longer available. Individual endpoints must be used instead, which means more API calls and careful rate limiting.
- **Fields removed:** `popularity` (tracks and artists), `followers` (artists), and others.
- **Artist `genres` field deprecated:** Still functional but may be removed in a future update.
- **Search limits reduced:** Max results per query dropped from 50 to 10.
- **Premium required:** App owners must maintain active Spotify Premium.
- **Extended Quota Mode** now requires a registered business with 250K+ monthly active users, making it unavailable to individual developers.

This project uses aggressive rate-limit mitigation (1 req/sec with 30s pauses every 50 calls for artist lookups) to avoid triggering Spotify's rolling-window rate limits, which can result in 24-hour bans.
