"""CLI entry point for testing and interacting with Music Search MCP."""

import argparse
import sys


def cmd_liked_songs(args):
    """Fetch and display liked songs from Spotify."""
    from .config import get_spotify_config
    from .spotify_client import fetch_liked_songs

    limit = args.limit

    try:
        get_spotify_config()  # Validate credentials before starting
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching liked songs from Spotify{f' (limit: {limit})' if limit else ''}...")
    print()
    songs = fetch_liked_songs(limit=limit)

    print(f"Found {len(songs)} liked songs:\n")
    print(f"{'#':<5} {'Title':<40} {'Artist(s)':<30} {'Album':<30}")
    print("-" * 105)

    for i, song in enumerate(songs, 1):
        title = song["name"][:38]
        artists = ", ".join(song["artists"])[:28]
        album = song["album"][:28]
        print(f"{i:<5} {title:<40} {artists:<30} {album:<30}")

    print(f"\nTotal: {len(songs)} songs")


def cmd_scrobbles(args):
    """Fetch and display scrobble history from Last.fm."""
    from .config import get_lastfm_config
    from .lastfm_client import fetch_scrobbles, get_scrobble_stats

    limit = args.limit

    try:
        get_lastfm_config()  # Validate credentials before starting
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Show total scrobbles first
    stats = get_scrobble_stats()
    print(f"Last.fm account has {stats['total_scrobbles']:,} total scrobbles.")
    print(f"Fetching scrobbles{f' (limit: {limit})' if limit else ' (all — this may take a while)'}...")
    print()

    scrobbles = fetch_scrobbles(limit=limit)

    print(f"{'#':<5} {'Title':<40} {'Artist':<30} {'Date':<20}")
    print("-" * 95)

    for i, scrobble in enumerate(scrobbles, 1):
        title = scrobble["name"][:38]
        artist = scrobble["artist"][:28]
        date = scrobble["date_text"] or ""
        prefix = "> " if scrobble["now_playing"] else ""
        print(f"{i:<5} {prefix}{title:<40} {artist:<30} {date:<20}")

    print(f"\nShowing: {len(scrobbles)} scrobbles")


def cmd_lyrics_search(args):
    """Search for lyrics using a free-text query."""
    from .lyrics_client import search_lyrics

    query = " ".join(args.query)
    print(f"Searching LRCLIB for: {query}\n")

    results = search_lyrics(query, limit=args.limit)

    if not results:
        print("No results found.")
        return

    for i, result in enumerate(results, 1):
        status = "[instrumental]" if result["instrumental"] else ""
        has_lyrics = "yes" if result["plain_lyrics"] else "no"
        print(f"{i}. {result['name']} — {result['artist']}")
        print(f"   Album: {result['album']}  |  Lyrics: {has_lyrics}  {status}")

        if args.show_lyrics and result["plain_lyrics"]:
            # Show first few lines as preview
            lines = result["plain_lyrics"].strip().split("\n")
            preview = lines[:6]
            print(f"   ---")
            for line in preview:
                print(f"   {line}")
            if len(lines) > 6:
                print(f"   ... ({len(lines) - 6} more lines)")
        print()


def _progress(current: int, total: int, message: str) -> None:
    """Write a progress line that fully clears the previous one."""
    import shutil
    width = shutil.get_terminal_size().columns - 1
    line = f"  [{current}/{total}] {message}"
    # Truncate if line is longer than terminal, then pad to fill the rest
    sys.stdout.write(f"\r{line[:width]:<{width}}")
    sys.stdout.flush()


def _get_artist_name(song: dict, source: str) -> str:
    """Extract artist name from a song dict based on source format."""
    if source == "spotify":
        return song["artists"][0] if song.get("artists") else ""
    else:  # lastfm
        return song.get("artist", "")


def _deduplicate_songs(songs: list[dict], source: str) -> list[dict]:
    """Remove duplicate songs (same track + artist), keeping first occurrence."""
    seen = set()
    unique = []
    for song in songs:
        artist = _get_artist_name(song, source)
        key = f"{song['name'].strip().lower()}||{artist.strip().lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(song)
    return unique


def cmd_lyrics_enrich(args):
    """Fetch lyrics for your music library, with local caching."""
    from .lyrics_client import fetch_lyrics_for_songs
    from .lyrics_cache import get_cached_lyrics, save_lyrics_to_cache, get_cache_stats

    source = args.source
    force = args.force
    limit = args.limit

    # Fetch songs from the chosen source
    if source == "spotify":
        from .config import get_spotify_config
        from .spotify_client import fetch_liked_songs
        try:
            get_spotify_config()
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Fetching liked songs from Spotify{f' (limit: {limit})' if limit else ''}...")
        songs = fetch_liked_songs(limit=limit)

    elif source == "lastfm":
        from .config import get_lastfm_config
        from .lastfm_client import fetch_scrobbles, get_scrobble_stats
        try:
            get_lastfm_config()
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            sys.exit(1)
        stats = get_scrobble_stats()
        print(f"Last.fm account has {stats['total_scrobbles']:,} total scrobbles.")
        print(f"Fetching scrobbles{f' (limit: {limit})' if limit else ''}...")
        scrobbles = fetch_scrobbles(limit=limit)
        # Deduplicate: scrobble history has many repeats of the same song
        songs = _deduplicate_songs(scrobbles, source)
        print(f"  {len(scrobbles)} scrobbles -> {len(songs)} unique songs")

    elif source == "both":
        from .config import get_spotify_config, get_lastfm_config
        from .spotify_client import fetch_liked_songs
        from .lastfm_client import fetch_scrobbles, get_scrobble_stats
        try:
            get_spotify_config()
            get_lastfm_config()
        except ValueError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            sys.exit(1)

        # Fetch from both sources
        print(f"Fetching liked songs from Spotify...")
        spotify_songs = fetch_liked_songs(limit=limit)
        print(f"  {len(spotify_songs)} liked songs")

        stats = get_scrobble_stats()
        print(f"Fetching scrobbles from Last.fm ({stats['total_scrobbles']:,} total)...")
        scrobbles = fetch_scrobbles(limit=limit)
        print(f"  {len(scrobbles)} scrobbles")

        # Normalize Last.fm songs to have same artist field format for dedup
        lastfm_normalized = []
        for s in scrobbles:
            lastfm_normalized.append({
                **s,
                "artists": [s["artist"]],  # match Spotify format
            })

        # Combine and deduplicate across both sources
        combined = spotify_songs + lastfm_normalized
        songs = _deduplicate_songs(combined, "spotify")  # use spotify format since we normalized
        source = "spotify"  # use spotify field mapping from here on
        print(f"  Combined: {len(songs)} unique songs")

    else:
        print(f"Unknown source: {source}", file=sys.stderr)
        sys.exit(1)

    # Check cache stats
    cache_stats = get_cache_stats()
    if cache_stats["total"] > 0 and not force:
        print(f"Lyrics cache: {cache_stats['total']} songs cached "
              f"({cache_stats['with_lyrics']} with lyrics, "
              f"{cache_stats['not_found']} not found)")

    print(f"Found {len(songs)} songs. Fetching lyrics from LRCLIB...\n")

    enriched = []
    found = 0
    instrumental = 0
    cached_hits = 0
    api_lookups = 0

    for i, song in enumerate(songs, 1):
        artist = _get_artist_name(song, source)
        track_name = song["name"]

        _progress(i, len(songs), f"Looking up: {track_name[:40]} - {artist[:20]}")

        # Check cache first (unless --force)
        cached = None if force else get_cached_lyrics(track_name, artist)

        if cached is not None:
            cached_hits += 1
            result = {
                **song,
                "plain_lyrics": cached["plain_lyrics"],
                "synced_lyrics": cached["synced_lyrics"],
                "instrumental": cached["instrumental"],
                "lyrics_found": cached["lyrics_found"],
            }
        else:
            api_lookups += 1
            result = fetch_lyrics_for_songs([song], source=source)[0]
            # Save to cache
            save_lyrics_to_cache(track_name, artist, result)

        enriched.append(result)

        if result["lyrics_found"]:
            if result["instrumental"]:
                instrumental += 1
            else:
                found += 1

    print(f"\n\nResults:")
    print(f"  Lyrics found:   {found}/{len(songs)}")
    print(f"  Instrumental:   {instrumental}/{len(songs)}")
    print(f"  Not found:      {len(songs) - found - instrumental}/{len(songs)}")
    print(f"  From cache:     {cached_hits}")
    print(f"  API lookups:    {api_lookups}")

    # Show summary table
    print(f"\n{'#':<5} {'Title':<35} {'Artist':<25} {'Lyrics':<15}")
    print("-" * 80)

    for i, song in enumerate(enriched, 1):
        title = song["name"][:33]
        artist = _get_artist_name(song, source)[:23]
        if song["instrumental"]:
            status = "[instrumental]"
        elif song["lyrics_found"]:
            status = "[found]"
        else:
            status = "[missing]"
        print(f"{i:<5} {title:<35} {artist:<25} {status:<15}")


def cmd_index(args):
    """Build the vector search index from cached lyrics."""
    from .lyrics_cache import _load_cache
    from .vector_store import index_songs, get_index_stats

    # Check for GPU
    try:
        import torch
        device = "GPU (CUDA)" if torch.cuda.is_available() else "CPU"
        if torch.cuda.is_available():
            device += f" - {torch.cuda.get_device_name(0)}"
    except ImportError:
        device = "CPU"

    print(f"Embedding device: {device}")
    print(f"Embedding model:  {args.model}\n")

    # Load all cached lyrics
    cache = _load_cache()
    if not cache:
        print("No lyrics cached yet. Run 'music-search lyrics-enrich' first.")
        sys.exit(1)

    songs = list(cache.values())
    songs_with_content = [s for s in songs if s.get("lyrics_found")]

    print(f"Lyrics cache: {len(songs)} total, {len(songs_with_content)} with lyrics/instrumental")

    if not songs_with_content:
        print("No songs with lyrics to index.")
        sys.exit(1)

    print(f"Indexing {len(songs_with_content)} songs into vector database...")
    print("(First run will download the embedding model ~80MB)\n")

    stats = index_songs(songs_with_content, model_name=args.model)

    print(f"\nIndexing complete:")
    print(f"  Processed:       {stats['total_processed']}")
    print(f"  Indexed:         {stats['indexed']}")
    print(f"  Skipped:         {stats['skipped']}")
    print(f"  Collection size: {stats['collection_size']}")


def cmd_search(args):
    """Search the vector index with a natural language query."""
    from .vector_store import search, get_index_stats

    # Check if index exists
    stats = get_index_stats(model_name=args.model)
    if stats["collection_size"] == 0:
        print("No songs indexed yet. Run 'music-search index' first.")
        sys.exit(1)

    query = " ".join(args.query)
    print(f"Searching {stats['collection_size']} songs for: \"{query}\"\n")

    results = search(query, n_results=args.limit, model_name=args.model)

    if not results:
        print("No results found.")
        return

    for i, result in enumerate(results, 1):
        score_pct = result["score"] * 100
        print(f"{i}. {result['track_name']} - {result['artist_name']}")
        print(f"   Album: {result['album']}  |  Match: {score_pct:.1f}%")
        if args.verbose:
            print(f"   Preview: {result['document_preview']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        prog="music-search",
        description="Music Search MCP - Search your music library using vague recollections",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # liked-songs command
    liked_parser = subparsers.add_parser("liked-songs", help="Fetch your Spotify liked songs")
    liked_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of songs to fetch (default: all)",
    )
    liked_parser.set_defaults(func=cmd_liked_songs)

    # scrobbles command
    scrobble_parser = subparsers.add_parser("scrobbles", help="Fetch your Last.fm scrobble history")
    scrobble_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of scrobbles to fetch (default: all)",
    )
    scrobble_parser.set_defaults(func=cmd_scrobbles)

    # lyrics-search command
    lyrics_search_parser = subparsers.add_parser("lyrics-search", help="Search LRCLIB for lyrics")
    lyrics_search_parser.add_argument(
        "query",
        nargs="+",
        help="Search query (e.g. 'never gonna give you up rick astley')",
    )
    lyrics_search_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=5,
        help="Maximum number of results (default: 5)",
    )
    lyrics_search_parser.add_argument(
        "--show-lyrics",
        action="store_true",
        help="Show a preview of the lyrics",
    )
    lyrics_search_parser.set_defaults(func=cmd_lyrics_search)

    # lyrics-enrich command
    lyrics_enrich_parser = subparsers.add_parser(
        "lyrics-enrich",
        help="Fetch lyrics for your music library",
    )
    lyrics_enrich_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of songs to enrich (default: all)",
    )
    lyrics_enrich_parser.add_argument(
        "--source",
        choices=["spotify", "lastfm", "both"],
        default="spotify",
        help="Music source: spotify (liked songs), lastfm (scrobbles), or both (default: spotify)",
    )
    lyrics_enrich_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch lyrics even if already cached",
    )
    lyrics_enrich_parser.set_defaults(func=cmd_lyrics_enrich)

    # index command
    index_parser = subparsers.add_parser(
        "index",
        help="Build the vector search index from cached lyrics",
    )
    index_parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="Sentence-transformer model for embeddings (default: all-MiniLM-L6-v2)",
    )
    index_parser.set_defaults(func=cmd_index)

    # search command
    search_parser = subparsers.add_parser(
        "search",
        help="Search your music library with a vague description",
    )
    search_parser.add_argument(
        "query",
        nargs="+",
        help="Natural language query (e.g. 'that sad piano song about letting go')",
    )
    search_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=5,
        help="Maximum number of results (default: 5)",
    )
    search_parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="Sentence-transformer model (must match index model)",
    )
    search_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show document preview for each result",
    )
    search_parser.set_defaults(func=cmd_search)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
