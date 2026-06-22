"""Export music library data to SQLite for ad-hoc SQL exploration.

JSON files remain the primary data store. SQLite is a secondary export
that provides queryable views with FTS5 full-text search on lyrics.

Usage:
    music-search export-db          # Export to data/music_library.db
    music-search export-db --path ~/music.db  # Custom output path

Then explore with any SQLite tool:
    sqlite3 data/music_library.db
    .tables
    SELECT * FROM songs WHERE user_playcount > 10 ORDER BY user_playcount DESC;
    SELECT * FROM lyrics_fts WHERE lyrics_fts MATCH 'love rain';
"""

import json
import sqlite3
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_DEFAULT_DB = _DATA_DIR / "music_library.db"


def export_to_sqlite(db_path: Path | None = None) -> dict:
    """Export all music data to a SQLite database.

    Creates (or replaces) tables:
        - songs: All unique songs with metadata from both services
        - lyrics_fts: FTS5 virtual table for full-text lyrics search

    Args:
        db_path: Path to the SQLite database file. Defaults to data/music_library.db.

    Returns:
        Dict with export stats: songs_exported, lyrics_indexed, db_path.
    """
    from .song_store import load_spotify_songs, load_lastfm_scrobbles, load_scrobble_history
    from .lyrics_cache import _load_cache, _make_key

    db_path = db_path or _DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Load all data sources
    spotify_data = load_spotify_songs()
    lastfm_data = load_lastfm_scrobbles()
    lyrics_cache = _load_cache()
    scrobble_history = load_scrobble_history()

    # Build unified song list with provenance
    songs = _build_unified_songs(spotify_data, lastfm_data, lyrics_cache, _make_key)

    # Write to SQLite
    conn = sqlite3.connect(str(db_path))
    try:
        _create_tables(conn)
        songs_count = _insert_songs(conn, songs)
        lyrics_count = _insert_lyrics_fts(conn, songs)
        scrobble_count = _insert_scrobbles(conn, scrobble_history, _make_key)
        conn.commit()
    finally:
        conn.close()

    return {
        "songs_exported": songs_count,
        "lyrics_indexed": lyrics_count,
        "scrobbles_exported": scrobble_count,
        "db_path": str(db_path),
    }


def _build_unified_songs(spotify_data, lastfm_data, lyrics_cache, make_key):
    """Build a unified song list combining all sources with provenance."""
    songs = {}  # key -> unified song dict

    # Process Spotify songs
    if spotify_data:
        for s in spotify_data["songs"]:
            artist = s["artists"][0] if s.get("artists") else ""
            key = make_key(s["name"], artist)
            songs[key] = {
                "track_name": s["name"],
                "artist_name": artist,
                "all_artists": ", ".join(s.get("artists", [])),
                "album": s.get("album", ""),
                "spotify_id": s.get("id", ""),
                "spotify_url": s.get("spotify_url", ""),
                "lastfm_url": "",
                "in_spotify": True,
                "in_lastfm": False,
                "added_at": s.get("added_at", ""),
                "duration_ms": s.get("duration_ms", 0),
                "popularity": s.get("popularity", 0),
                "explicit": s.get("explicit", False),
                "release_date": s.get("release_date", ""),
                "track_number": s.get("track_number", 0),
                "disc_number": s.get("disc_number", 1),
                "genres": json.dumps(s.get("genres", [])),
                "artist_ids": json.dumps(s.get("artist_ids", [])),
                # Last.fm fields (may be filled from cache)
                "user_playcount": None,
                "global_listeners": None,
                "global_playcount": None,
                "tags": "[]",
                "loved": None,
                # Lyrics fields (filled from cache below)
                "lyrics_found": False,
                "instrumental": False,
                "lyrics_source": "",
                "plain_lyrics": None,
                "synced_lyrics": None,
            }

    # Process Last.fm songs
    if lastfm_data:
        for s in lastfm_data["songs"]:
            key = make_key(s["name"], s.get("artist", ""))
            if key in songs:
                # Song exists from Spotify — merge Last.fm data
                songs[key]["in_lastfm"] = True
                songs[key]["lastfm_url"] = s.get("lastfm_url", "")
                if s.get("user_playcount") is not None:
                    songs[key]["user_playcount"] = s["user_playcount"]
                if s.get("global_listeners") is not None:
                    songs[key]["global_listeners"] = s["global_listeners"]
                if s.get("global_playcount") is not None:
                    songs[key]["global_playcount"] = s["global_playcount"]
                if s.get("tags"):
                    songs[key]["tags"] = json.dumps(s["tags"])
                if s.get("loved") is not None:
                    songs[key]["loved"] = s["loved"]
            else:
                # Last.fm only song
                songs[key] = {
                    "track_name": s["name"],
                    "artist_name": s.get("artist", ""),
                    "all_artists": s.get("artist", ""),
                    "album": s.get("album", ""),
                    "spotify_id": "",
                    "spotify_url": "",
                    "lastfm_url": s.get("lastfm_url", ""),
                    "in_spotify": False,
                    "in_lastfm": True,
                    "added_at": "",
                    "duration_ms": 0,
                    "popularity": 0,
                    "explicit": False,
                    "release_date": "",
                    "track_number": 0,
                    "disc_number": 1,
                    "genres": "[]",
                    "artist_ids": "[]",
                    "user_playcount": s.get("user_playcount"),
                    "global_listeners": s.get("global_listeners"),
                    "global_playcount": s.get("global_playcount"),
                    "tags": json.dumps(s.get("tags", [])),
                    "loved": s.get("loved"),
                    "lyrics_found": False,
                    "instrumental": False,
                    "lyrics_source": "",
                    "plain_lyrics": None,
                    "synced_lyrics": None,
                }

    # Merge lyrics from cache
    for key, song in songs.items():
        cached = lyrics_cache.get(key)
        if cached:
            song["lyrics_found"] = cached.get("lyrics_found", False)
            song["instrumental"] = cached.get("instrumental", False)
            song["lyrics_source"] = cached.get("lyrics_source", "")
            song["plain_lyrics"] = cached.get("plain_lyrics")
            song["synced_lyrics"] = cached.get("synced_lyrics")
            # Backfill any missing metadata from cache
            if not song["album"] and cached.get("album"):
                song["album"] = cached["album"]
            if not song["spotify_url"] and cached.get("spotify_url"):
                song["spotify_url"] = cached["spotify_url"]
            if not song["lastfm_url"] and cached.get("lastfm_url"):
                song["lastfm_url"] = cached["lastfm_url"]

    return list(songs.values())


def _create_tables(conn: sqlite3.Connection):
    """Create the songs table and FTS5 virtual table."""
    conn.executescript("""
        DROP TABLE IF EXISTS lyrics_fts;
        DROP TABLE IF EXISTS songs;

        CREATE TABLE songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_name TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            all_artists TEXT DEFAULT '',
            album TEXT DEFAULT '',

            -- Provenance
            in_spotify BOOLEAN DEFAULT 0,
            in_lastfm BOOLEAN DEFAULT 0,
            spotify_id TEXT DEFAULT '',
            spotify_url TEXT DEFAULT '',
            lastfm_url TEXT DEFAULT '',

            -- Spotify metadata
            added_at TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            popularity INTEGER DEFAULT 0,
            explicit BOOLEAN DEFAULT 0,
            release_date TEXT DEFAULT '',
            track_number INTEGER DEFAULT 0,
            disc_number INTEGER DEFAULT 1,
            genres TEXT DEFAULT '[]',       -- JSON array
            artist_ids TEXT DEFAULT '[]',    -- JSON array

            -- Last.fm metadata
            user_playcount INTEGER,
            global_listeners INTEGER,
            global_playcount INTEGER,
            tags TEXT DEFAULT '[]',          -- JSON array
            loved BOOLEAN,
            first_scrobbled_at TEXT,         -- ISO 8601 UTC (earliest play)
            last_scrobbled_at TEXT,          -- ISO 8601 UTC (most recent play)

            -- Lyrics
            lyrics_found BOOLEAN DEFAULT 0,
            instrumental BOOLEAN DEFAULT 0,
            lyrics_source TEXT DEFAULT '',
            plain_lyrics TEXT,
            synced_lyrics TEXT
        );

        CREATE INDEX idx_songs_artist ON songs(artist_name);
        CREATE INDEX idx_songs_album ON songs(album);
        CREATE INDEX idx_songs_playcount ON songs(user_playcount);
        CREATE INDEX idx_songs_popularity ON songs(popularity);
        CREATE INDEX idx_songs_provenance ON songs(in_spotify, in_lastfm);

        -- Scrobble history (every individual play event)
        DROP TABLE IF EXISTS scrobbles;
        CREATE TABLE scrobbles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL REFERENCES songs(id),
            scrobbled_at TEXT NOT NULL,  -- ISO 8601 UTC
            timestamp INTEGER NOT NULL   -- Unix epoch
        );

        CREATE INDEX idx_scrobbles_song ON scrobbles(song_id);
        CREATE INDEX idx_scrobbles_time ON scrobbles(timestamp);

        -- FTS5 virtual table for full-text lyrics search
        CREATE VIRTUAL TABLE lyrics_fts USING fts5(
            track_name,
            artist_name,
            album,
            plain_lyrics,
            content=songs,
            content_rowid=id
        );
    """)


def _insert_songs(conn: sqlite3.Connection, songs: list[dict]) -> int:
    """Insert songs into the songs table."""
    cols = [
        "track_name", "artist_name", "all_artists", "album",
        "in_spotify", "in_lastfm", "spotify_id", "spotify_url", "lastfm_url",
        "added_at", "duration_ms", "popularity", "explicit", "release_date",
        "track_number", "disc_number", "genres", "artist_ids",
        "user_playcount", "global_listeners", "global_playcount", "tags", "loved",
        "lyrics_found", "instrumental", "lyrics_source",
        "plain_lyrics", "synced_lyrics",
    ]
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)

    rows = []
    for song in songs:
        row = tuple(song.get(col) for col in cols)
        rows.append(row)

    conn.executemany(
        f"INSERT INTO songs ({col_names}) VALUES ({placeholders})",
        rows,
    )

    return len(rows)


def _insert_lyrics_fts(conn: sqlite3.Connection, songs: list[dict]) -> int:
    """Populate the FTS5 index for lyrics search."""
    # Insert all rows (track/artist/album searchable for all songs,
    # lyrics searchable only for songs that have them)
    conn.execute("""
        INSERT INTO lyrics_fts(rowid, track_name, artist_name, album, plain_lyrics)
        SELECT id, track_name, artist_name, album, plain_lyrics
        FROM songs
    """)

    # Return count of songs with actual lyrics content
    cursor = conn.execute(
        "SELECT COUNT(*) FROM songs WHERE plain_lyrics IS NOT NULL"
    )
    return cursor.fetchone()[0]


def _insert_scrobbles(conn: sqlite3.Connection, scrobble_history: dict | None,
                      make_key) -> int:
    """Insert scrobble history and update songs with first/last scrobbled dates."""
    if not scrobble_history:
        return 0

    scrobbles = scrobble_history.get("scrobbles", [])
    if not scrobbles:
        return 0

    # Build song key -> id lookup from the songs table
    cursor = conn.execute("SELECT id, track_name, artist_name FROM songs")
    key_to_id = {}
    for row in cursor:
        key = make_key(row[1], row[2])
        key_to_id[key] = row[0]

    # Insert scrobble rows and track first/last per song
    from datetime import datetime, timezone

    rows = []
    song_dates: dict[int, list[int]] = {}  # song_id -> list of timestamps

    for s in scrobbles:
        key = make_key(s["name"], s.get("artist", ""))
        song_id = key_to_id.get(key)
        if song_id is None:
            continue

        ts = int(s["timestamp"])
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append((song_id, iso, ts))

        song_dates.setdefault(song_id, []).append(ts)

    conn.executemany(
        "INSERT INTO scrobbles (song_id, scrobbled_at, timestamp) VALUES (?, ?, ?)",
        rows,
    )

    # Update songs with first/last scrobbled dates
    for song_id, timestamps in song_dates.items():
        first_ts = min(timestamps)
        last_ts = max(timestamps)
        first_iso = datetime.fromtimestamp(first_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        last_iso = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE songs SET first_scrobbled_at = ?, last_scrobbled_at = ? WHERE id = ?",
            (first_iso, last_iso, song_id),
        )

    return len(rows)
