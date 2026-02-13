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


def cmd_lyrics_enrich(args):
    """Fetch lyrics for your Spotify liked songs."""
    from .config import get_spotify_config
    from .spotify_client import fetch_liked_songs
    from .lyrics_client import fetch_lyrics_for_songs

    try:
        get_spotify_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    limit = args.limit
    print(f"Fetching liked songs from Spotify{f' (limit: {limit})' if limit else ''}...")
    songs = fetch_liked_songs(limit=limit)
    print(f"Found {len(songs)} songs. Fetching lyrics from LRCLIB...\n")

    enriched = []
    found = 0
    instrumental = 0

    for i, song in enumerate(songs, 1):
        artist = song["artists"][0] if song["artists"] else ""
        sys.stdout.write(f"\r  [{i}/{len(songs)}] Looking up: {song['name'][:40]} - {artist[:20]}   ")
        sys.stdout.flush()

        result = fetch_lyrics_for_songs([song], source="spotify")[0]
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

    # Show summary table
    print(f"\n{'#':<5} {'Title':<35} {'Artist':<25} {'Lyrics':<10}")
    print("-" * 75)

    for i, song in enumerate(enriched, 1):
        title = song["name"][:33]
        artist = (song["artists"][0] if song["artists"] else "")[:23]
        if song["instrumental"]:
            status = "[instrumental]"
        elif song["lyrics_found"]:
            status = "[found]"
        else:
            status = "[missing]"
        print(f"{i:<5} {title:<35} {artist:<25} {status:<10}")


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
        help="Fetch lyrics for your Spotify liked songs",
    )
    lyrics_enrich_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of songs to enrich (default: all)",
    )
    lyrics_enrich_parser.set_defaults(func=cmd_lyrics_enrich)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
