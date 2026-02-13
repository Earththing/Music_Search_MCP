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
        prefix = "▶ " if scrobble["now_playing"] else ""
        print(f"{i:<5} {prefix}{title:<40} {artist:<30} {date:<20}")

    print(f"\nShowing: {len(scrobbles)} scrobbles")


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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
