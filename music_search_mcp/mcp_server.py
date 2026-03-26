"""MCP server for Music Search -- exposes semantic search as MCP tools.

Run via stdio transport for use with Claude Desktop or any MCP client.
Do NOT use print() in this module -- stdout is reserved for JSON-RPC.
Use logging (which defaults to stderr) for diagnostics.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (safe for MCP stdio transport).
# The MCP spec says the server MAY write UTF-8 strings to stderr for logging;
# clients MAY capture, forward, or ignore this logging.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("music-search-mcp")

# Create the MCP server instance
mcp = FastMCP("music-search")


@mcp.tool()
def search_music(query: str, n_results: int = 5) -> str:
    """Search your music library using a natural language description.

    Describe a song however you remember it -- a lyric fragment, a mood,
    a vague memory -- and this tool finds matching songs from your indexed
    listening history.

    Args:
        query: Natural language description of the song you're looking for.
               Examples: "that sad piano song about letting go",
               "upbeat dance track with synthesizers",
               "the one about walking in the rain"
        n_results: Maximum number of results to return (default 5, max 20).
    """
    from . import vector_store

    # Clamp n_results to a reasonable range
    n_results = max(1, min(n_results, 20))

    logger.info(f"Searching for: {query!r} (n_results={n_results})")

    try:
        results = vector_store.search(
            query, n_results=n_results, suppress_stderr=False,
        )
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return f"Search failed: {e}"

    if not results:
        return (
            "No results found. The vector index may be empty.\n"
            "Make sure you have run the indexing pipeline first:\n"
            "  music-search load spotify   (or lastfm)\n"
            "  music-search lyrics-enrich\n"
            "  music-search index"
        )

    # Format results as readable text for Claude to present conversationally
    from urllib.parse import quote

    lines = [f'Found {len(results)} results for "{query}":\n']
    for i, r in enumerate(results, 1):
        score_pct = r["score"] * 100
        lines.append(f"{i}. {r['track_name']} -- {r['artist_name']}")
        lines.append(f"   Album: {r['album']}")
        lines.append(f"   Match: {score_pct:.1f}%")

        # Spotify link (direct URL or search fallback)
        spotify_url = r.get("spotify_url", "")
        if not spotify_url:
            search_q = quote(f"{r['track_name']} {r['artist_name']}")
            spotify_url = f"https://open.spotify.com/search/{search_q}"
        lines.append(f"   Spotify: {spotify_url}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def library_status() -> str:
    """Show the current state of your music search library.

    Returns information about what data is indexed and available:
    song stores (Spotify/Last.fm), lyrics cache stats, and vector
    index size. Useful for checking if the pipeline has been set up.
    """
    from . import vector_store
    from .lyrics_cache import get_cache_stats
    from .song_store import get_store_info

    lines = ["Music Search Library Status", "=" * 30, ""]

    # Song stores
    info = get_store_info()
    lines.append("Song stores:")
    if info["spotify"]:
        lines.append(
            f"  Spotify:  {info['spotify']['count']} liked songs "
            f"(fetched {info['spotify']['fetched_at'][:10]})"
        )
    else:
        lines.append("  Spotify:  not loaded yet")

    if info["lastfm"]:
        lines.append(
            f"  Last.fm:  {info['lastfm']['count']} unique songs "
            f"(fetched {info['lastfm']['fetched_at'][:10]})"
        )
    else:
        lines.append("  Last.fm:  not loaded yet")

    # Lyrics cache
    lines.append("")
    cache_stats = get_cache_stats()
    if cache_stats["total"] > 0:
        lines.append(f"Lyrics cache: {cache_stats['total']} songs")
        lines.append(f"  With lyrics:    {cache_stats['with_lyrics']}")
        lines.append(f"  Instrumental:   {cache_stats['instrumental']}")
        lines.append(f"  Not found:      {cache_stats['not_found']}")
    else:
        lines.append("Lyrics cache: empty")

    # Vector index (lightweight -- no model loading)
    lines.append("")
    idx_size = 0
    try:
        idx_stats = vector_store.get_index_stats(lightweight=True)
        idx_size = idx_stats["collection_size"]
        if idx_size > 0:
            lines.append(f"Vector index: {idx_size} songs indexed")
            lines.append(f"  Model: {idx_stats['model_name']}")
        else:
            lines.append("Vector index: empty")
    except Exception:
        lines.append("Vector index: empty")

    # Readiness assessment
    lines.append("")
    if cache_stats["total"] > 0 and idx_size > 0:
        lines.append("Status: Ready for search!")
    else:
        lines.append("Status: Setup incomplete. Run the pipeline:")
        lines.append("  1. music-search load spotify  (or lastfm, or all)")
        lines.append("  2. music-search lyrics-enrich")
        lines.append("  3. music-search index")

    return "\n".join(lines)


@mcp.tool()
def query_library(sql: str) -> str:
    """Run a read-only SQL query against the music library database.

    The database contains these tables:

    **songs** — one row per unique song (merged from Spotify + Last.fm):
        id, track_name, artist_name, all_artists, album,
        in_spotify (bool), in_lastfm (bool), spotify_id, spotify_url, lastfm_url,
        added_at (ISO date, Spotify liked-date), duration_ms, popularity (0-100),
        explicit (bool), release_date, track_number, disc_number,
        genres (JSON array), artist_ids (JSON array),
        user_playcount (Last.fm total plays), global_listeners, global_playcount,
        tags (JSON array of Last.fm tags), loved (bool),
        first_scrobbled_at (ISO UTC, earliest Last.fm play),
        last_scrobbled_at (ISO UTC, most recent Last.fm play),
        lyrics_found (bool), instrumental (bool), lyrics_source,
        plain_lyrics (text), synced_lyrics (text)

    **scrobbles** — every individual Last.fm play event:
        id, song_id (FK to songs.id), scrobbled_at (ISO UTC), timestamp (Unix epoch)
        Use this for listening history, trends, play counts by time period, etc.

    **lyrics_fts** — FTS5 full-text search on lyrics:
        SELECT s.* FROM lyrics_fts f JOIN songs s ON s.id = f.rowid
        WHERE lyrics_fts MATCH 'love rain'

    Example queries:
        -- Oldest Last.fm songs not on Spotify:
        SELECT track_name, artist_name, first_scrobbled_at
        FROM songs WHERE in_lastfm = 1 AND in_spotify = 0
        ORDER BY first_scrobbled_at LIMIT 200

        -- What was I listening to in December 2019?
        SELECT s.track_name, s.artist_name, sc.scrobbled_at
        FROM scrobbles sc JOIN songs s ON s.id = sc.song_id
        WHERE sc.scrobbled_at LIKE '2019-12%'
        ORDER BY sc.timestamp

        -- Most played songs in a given month:
        SELECT s.track_name, s.artist_name, COUNT(*) as plays
        FROM scrobbles sc JOIN songs s ON s.id = sc.song_id
        WHERE sc.scrobbled_at LIKE '2024-01%'
        GROUP BY sc.song_id ORDER BY plays DESC LIMIT 20

    Args:
        sql: A SELECT query. Only read operations are allowed.
    """
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).parent.parent / "data" / "music_library.db"

    if not db_path.exists():
        return (
            "Database not found. Export it first by running:\n"
            "  music-search export-db"
        )

    # Only allow read operations
    stripped = sql.strip().rstrip(";").strip()
    first_word = stripped.split()[0].upper() if stripped else ""
    if first_word not in ("SELECT", "WITH", "EXPLAIN", "PRAGMA"):
        return "Only SELECT, WITH, EXPLAIN, and PRAGMA queries are allowed."

    logger.info(f"SQL query: {sql!r}")

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()
    except sqlite3.Error as e:
        return f"SQL error: {e}"

    if not rows:
        return "No results."

    # Format as readable text, capping output to avoid overwhelming context
    max_rows = 200
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]

    lines = [f"Results: {len(rows)}{' (truncated)' if truncated else ''} rows\n"]
    lines.append(" | ".join(columns))
    lines.append("-" * min(len(lines[-1]), 120))

    for row in rows:
        values = []
        for col in columns:
            val = row[col]
            if val is None:
                values.append("")
            elif col == "plain_lyrics" and isinstance(val, str) and len(val) > 80:
                values.append(val[:77] + "...")
            elif col == "synced_lyrics" and isinstance(val, str) and len(val) > 80:
                values.append(val[:77] + "...")
            else:
                values.append(str(val))
        lines.append(" | ".join(values))

    if truncated:
        lines.append(f"\n... truncated to {max_rows} rows. Use LIMIT or narrow your query.")

    return "\n".join(lines)


def main():
    """Entry point for the MCP server."""
    logger.info("Starting Music Search MCP server (stdio transport)...")

    # Eagerly load the embedding model so the first MCP tool call doesn't
    # timeout waiting for the ~8s model load.
    from . import vector_store
    logger.info("Warming up embedding model...")
    try:
        vector_store.warmup(suppress_stderr=False)
        logger.info("Embedding model ready.")
    except Exception as e:
        logger.warning(f"Model warmup failed (search will retry on first call): {e}")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
