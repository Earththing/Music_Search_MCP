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


def _display_width(text: str) -> int:
    """Calculate the actual display width of a string in terminal columns.

    CJK and other fullwidth characters take 2 columns, while most Latin
    characters take 1. This prevents line wrapping when printing progress.
    """
    import unicodedata
    width = 0
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        width += 2 if eaw in ("W", "F") else 1
    return width


def _truncate_to_width(text: str, max_width: int) -> str:
    """Truncate a string to fit within a given display width.

    Accounts for wide (CJK) characters that occupy 2 terminal columns.
    Returns the string padded with spaces to exactly max_width columns.
    """
    import unicodedata
    current_width = 0
    chars = []
    for ch in text:
        eaw = unicodedata.east_asian_width(ch)
        ch_width = 2 if eaw in ("W", "F") else 1
        if current_width + ch_width > max_width:
            break
        chars.append(ch)
        current_width += ch_width
    # Pad with spaces to fill remaining terminal columns
    padding = max_width - current_width
    return "".join(chars) + " " * padding


def _progress(current: int, total: int, message: str) -> None:
    """Write a progress line that fully clears the previous one."""
    import shutil
    width = shutil.get_terminal_size().columns - 1
    line = f"  [{current}/{total}] {message}"
    # Truncate accounting for wide chars, pad to fill terminal width
    sys.stdout.write(f"\r{_truncate_to_width(line, width)}")
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


def _load_songs_from_store(source: str) -> tuple[list[dict], str]:
    """Load songs from local store. Returns (songs, effective_source).

    When source is "auto", uses whatever is available locally (both > spotify > lastfm).
    Falls back with a helpful error if the store hasn't been populated yet.
    """
    from .song_store import load_spotify_songs, load_lastfm_scrobbles

    # Auto-detect: use whatever's available
    if source == "auto":
        spotify_data = load_spotify_songs()
        lastfm_data = load_lastfm_scrobbles()

        if spotify_data and lastfm_data:
            source = "both"
        elif spotify_data:
            source = "spotify"
        elif lastfm_data:
            source = "lastfm"
        else:
            print("No songs stored locally yet.", file=sys.stderr)
            print("Run 'music-search load spotify' and/or 'music-search load lastfm' first.", file=sys.stderr)
            sys.exit(1)

    if source == "spotify":
        data = load_spotify_songs()
        if not data:
            print("No Spotify songs stored locally yet.", file=sys.stderr)
            print("Run 'music-search load spotify' first to fetch from the API.", file=sys.stderr)
            sys.exit(1)
        print(f"Loaded {data['count']} Spotify songs from local store (fetched {data['fetched_at'][:10]})")
        return data["songs"], "spotify"

    elif source == "lastfm":
        data = load_lastfm_scrobbles()
        if not data:
            print("No Last.fm scrobbles stored locally yet.", file=sys.stderr)
            print("Run 'music-search load lastfm' first to fetch from the API.", file=sys.stderr)
            sys.exit(1)
        print(f"Loaded {data['count']} Last.fm songs from local store (fetched {data['fetched_at'][:10]})")
        return data["songs"], "lastfm"

    elif source == "both":
        spotify_data = load_spotify_songs()
        lastfm_data = load_lastfm_scrobbles()

        if not spotify_data and not lastfm_data:
            print("No songs stored locally yet.", file=sys.stderr)
            print("Run 'music-search load spotify' and/or 'music-search load lastfm' first.", file=sys.stderr)
            sys.exit(1)

        songs = []
        if spotify_data:
            print(f"Loaded {spotify_data['count']} Spotify songs (fetched {spotify_data['fetched_at'][:10]})")
            songs.extend(spotify_data["songs"])

        if lastfm_data:
            print(f"Loaded {lastfm_data['count']} Last.fm songs (fetched {lastfm_data['fetched_at'][:10]})")
            # Normalize Last.fm songs to have same artist field format
            for s in lastfm_data["songs"]:
                songs.append({**s, "artists": [s["artist"]]})

        # Deduplicate across sources
        unique = _deduplicate_songs(songs, "spotify")
        print(f"  Combined: {len(unique)} unique songs")
        return unique, "spotify"  # use spotify field mapping since we normalized

    else:
        print(f"Unknown source: {source}", file=sys.stderr)
        sys.exit(1)


def cmd_load(args):
    """Fetch songs from Spotify/Last.fm APIs and save locally.

    By default, uses incremental mode — only fetches new songs since the
    last load. Use --full to re-fetch everything from scratch.
    """
    source = args.source
    full = args.full

    if source in ("spotify", "all"):
        _load_spotify(full=full)

    if source in ("lastfm", "all"):
        _load_lastfm(full=full)

    print("\nDone! You can now run 'music-search lyrics-enrich' without hitting the API again.")


def _load_spotify(full: bool = False):
    """Fetch liked songs from Spotify, with incremental support."""
    from .config import get_spotify_config
    from .spotify_client import fetch_liked_songs
    from .song_store import (save_spotify_songs, get_spotify_known_ids,
                             merge_spotify_songs)

    try:
        get_spotify_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    if full:
        print("Fetching ALL liked songs from Spotify (full reload)...")
        songs = fetch_liked_songs(limit=None)
        filepath = save_spotify_songs(songs)
        print(f"  Saved {len(songs)} liked songs to {filepath}")
    else:
        known_ids = get_spotify_known_ids()
        if known_ids:
            print(f"Fetching new liked songs from Spotify ({len(known_ids)} already stored)...")
            new_songs = fetch_liked_songs(limit=None, known_ids=known_ids)
            if new_songs:
                merged, new_count = merge_spotify_songs(new_songs)
                filepath = save_spotify_songs(merged)
                print(f"  Found {new_count} new songs (total: {len(merged)})")
            else:
                print("  No new liked songs since last load.")
        else:
            print("Fetching liked songs from Spotify (first load)...")
            songs = fetch_liked_songs(limit=None)
            filepath = save_spotify_songs(songs)
            print(f"  Saved {len(songs)} liked songs to {filepath}")


def _load_lastfm(full: bool = False):
    """Fetch scrobbles from Last.fm, with incremental support."""
    from .config import get_lastfm_config
    from .lastfm_client import fetch_scrobbles, get_scrobble_stats
    from .song_store import (save_lastfm_scrobbles, get_lastfm_latest_timestamp,
                             merge_lastfm_scrobbles, save_scrobble_history)

    try:
        get_lastfm_config()
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    stats = get_scrobble_stats()
    print(f"Last.fm account has {stats['total_scrobbles']:,} total scrobbles.")

    if full:
        print("Fetching ALL scrobbles (full reload — this may take a while)...")
        print("Press Ctrl+C to stop early — what's been fetched so far will be saved.\n")
        scrobbles = fetch_scrobbles(limit=None)
        # Save raw scrobble history (every play event with timestamp)
        _, hist_new = save_scrobble_history(scrobbles)
        print(f"  Scrobble history: {hist_new} new play events recorded")
        unique = _deduplicate_songs(scrobbles, "lastfm")
        print(f"  {len(scrobbles)} scrobbles -> {len(unique)} unique songs")
        filepath = save_lastfm_scrobbles(unique)
        print(f"  Saved {len(unique)} unique songs to {filepath}")
    else:
        latest_ts = get_lastfm_latest_timestamp()
        if latest_ts is not None:
            from datetime import datetime, timezone
            last_date = datetime.fromtimestamp(latest_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"Fetching scrobbles since {last_date} (incremental)...")
            scrobbles = fetch_scrobbles(limit=None, since_timestamp=latest_ts)
            if scrobbles:
                # Save raw scrobble history
                _, hist_new = save_scrobble_history(scrobbles)
                print(f"  Scrobble history: {hist_new} new play events recorded")
                new_unique = _deduplicate_songs(scrobbles, "lastfm")
                merged, new_count = merge_lastfm_scrobbles(new_unique)
                filepath = save_lastfm_scrobbles(merged)
                print(f"  {len(scrobbles)} new scrobbles -> {new_count} new unique songs "
                      f"(total: {len(merged)})")
            else:
                print("  No new scrobbles since last load.")
        else:
            print("Fetching scrobbles (first load — this may take a while)...")
            print("Press Ctrl+C to stop early — what's been fetched so far will be saved.\n")
            scrobbles = fetch_scrobbles(limit=None)
            # Save raw scrobble history
            _, hist_new = save_scrobble_history(scrobbles)
            print(f"  Scrobble history: {hist_new} new play events recorded")
            unique = _deduplicate_songs(scrobbles, "lastfm")
            print(f"  {len(scrobbles)} scrobbles -> {len(unique)} unique songs")
            filepath = save_lastfm_scrobbles(unique)
            print(f"  Saved {len(unique)} unique songs to {filepath}")


def cmd_status(args):
    """Show what data is currently stored locally."""
    from .song_store import get_store_info
    from .lyrics_cache import get_cache_stats, _load_cache, _make_key
    from .vector_store import get_index_stats

    print("=== Music Search MCP - Local Data Status ===\n")

    # Song stores
    info = get_store_info()
    total_unique_songs = 0
    print("Song stores:")
    if info["spotify"]:
        print(f"  Spotify:  {info['spotify']['count']} liked songs (fetched {info['spotify']['fetched_at'][:10]})")
        total_unique_songs += info['spotify']['count']
    else:
        print(f"  Spotify:  not loaded yet  (run 'music-search load spotify')")

    if info["lastfm"]:
        print(f"  Last.fm:  {info['lastfm']['count']} unique songs (fetched {info['lastfm']['fetched_at'][:10]})")
        total_unique_songs += info['lastfm']['count']
    else:
        print(f"  Last.fm:  not loaded yet  (run 'music-search load lastfm')")

    # Lyrics cache
    print()
    cache_stats = get_cache_stats()
    if cache_stats["total"] > 0:
        print(f"Lyrics cache: {cache_stats['total']} songs")
        print(f"  With lyrics:    {cache_stats['with_lyrics']}")
        print(f"  Instrumental:   {cache_stats['instrumental']}")
        print(f"  Not found:      {cache_stats['not_found']}")

        # Count unenriched songs (in store but not in cache)
        if total_unique_songs > 0:
            cache_data = _load_cache()
            unenriched = _count_unenriched(info, cache_data, _make_key)
            if unenriched > 0:
                print(f"  Unenriched:     {unenriched} songs still need lyrics lookup")
    else:
        print(f"Lyrics cache: empty  (run 'music-search lyrics-enrich')")
        if total_unique_songs > 0:
            print(f"  {total_unique_songs} songs waiting for enrichment")

    # Vector index (lightweight check — no model loading)
    print()
    idx_size = 0
    try:
        idx_stats = get_index_stats(lightweight=True)
        idx_size = idx_stats["collection_size"]
        if idx_size > 0:
            print(f"Vector index: {idx_size} songs indexed")
            # Check if index is stale (fewer songs than cache has with lyrics)
            indexable = cache_stats["with_lyrics"] + cache_stats["instrumental"]
            if indexable > idx_size:
                print(f"  Stale:          {indexable - idx_size} songs not yet indexed "
                      f"(run 'music-search index')")
        else:
            print(f"Vector index: empty  (run 'music-search index')")
    except Exception:
        print(f"Vector index: empty  (run 'music-search index')")


def _count_unenriched(store_info: dict, cache_data: dict, make_key) -> int:
    """Count songs in stores that are not yet in the lyrics cache."""
    from .song_store import load_spotify_songs, load_lastfm_scrobbles

    cached_keys = set(cache_data.keys())
    unenriched = 0

    if store_info["spotify"]:
        data = load_spotify_songs()
        if data:
            for song in data["songs"]:
                artist = song["artists"][0] if song.get("artists") else ""
                key = make_key(song["name"], artist)
                if key not in cached_keys:
                    unenriched += 1

    if store_info["lastfm"]:
        data = load_lastfm_scrobbles()
        if data:
            for song in data["songs"]:
                key = make_key(song["name"], song.get("artist", ""))
                if key not in cached_keys:
                    unenriched += 1

    return unenriched


def _enrich_one_song(song, source, force, get_cached_lyrics, save_lyrics_to_cache,
                     fetch_lyrics_for_songs, cache_lock, use_fallback=False):
    """Look up lyrics for a single song. Thread-safe via cache_lock."""
    artist = _get_artist_name(song, source)
    track_name = song["name"]

    # Check cache first (unless --force)
    with cache_lock:
        cached = None if force else get_cached_lyrics(track_name, artist)

    if cached is not None:
        result = {
            **song,
            "plain_lyrics": cached["plain_lyrics"],
            "synced_lyrics": cached["synced_lyrics"],
            "instrumental": cached["instrumental"],
            "lyrics_found": cached["lyrics_found"],
        }
        return result, True  # (result, was_cached)
    else:
        result = fetch_lyrics_for_songs([song], source=source,
                                        use_fallback=use_fallback)[0]
        # Mark fallback_tried so --fill-gaps won't re-check this song
        if use_fallback and not result.get("lyrics_found"):
            result["fallback_tried"] = True
        with cache_lock:
            save_lyrics_to_cache(track_name, artist, result)
        return result, False  # (result, was_cached)


def cmd_lyrics_enrich(args):
    """Fetch lyrics for your music library, with local caching."""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .lyrics_client import fetch_lyrics_for_songs
    from .lyrics_cache import get_cached_lyrics, save_lyrics_to_cache, get_cache_stats

    source = args.source
    force = args.force
    limit = args.limit
    new_only = args.new
    workers = args.workers
    fill_gaps = args.fill_gaps
    reset_gaps = getattr(args, "reset_gaps", False)

    # Handle --reset-gaps: clear fallback_tried flags before processing
    if reset_gaps:
        from .lyrics_cache import reset_fallback_tried
        count = reset_fallback_tried()
        if count > 0:
            print(f"Reset {count} songs for re-checking by --fill-gaps.")
        else:
            print("No songs had fallback_tried flag set.")
        # If --reset-gaps was used alone (without --fill-gaps), we're done
        if not fill_gaps and not force:
            return

    if limit is not None and new_only is not None:
        print("Cannot use both -n/--limit and --new at the same time.", file=sys.stderr)
        print("  -n N   = process N songs total (including cached)", file=sys.stderr)
        print("  --new N = enrich N new uncached songs only", file=sys.stderr)
        sys.exit(1)

    # Load songs from local store (no API calls!)
    songs, source = _load_songs_from_store(source)

    # Apply -n limit to the loaded songs (but not in --new mode, we filter later)
    if limit and not new_only and not fill_gaps:
        songs = songs[:limit]

    # Check cache stats
    cache_stats = get_cache_stats()
    if cache_stats["total"] > 0 and not force:
        print(f"Lyrics cache: {cache_stats['total']} songs cached "
              f"({cache_stats['with_lyrics']} with lyrics, "
              f"{cache_stats['not_found']} not found)")

    # If --fill-gaps mode, only retry songs where lyrics were NOT found
    # and fallback hasn't already been tried (use --reset-gaps to retry all)
    if fill_gaps:
        from .lyrics_cache import _load_cache, _make_key
        cache_data = _load_cache()
        gap_songs = []
        already_tried = 0
        for song in songs:
            artist = _get_artist_name(song, source)
            key = _make_key(song["name"], artist)
            cached = cache_data.get(key)
            if cached and not cached.get("lyrics_found"):
                if cached.get("fallback_tried"):
                    already_tried += 1
                else:
                    gap_songs.append(song)
        total_gaps = len(gap_songs) + already_tried
        print(f"Fill-gaps mode: {total_gaps} songs with missing lyrics")
        if already_tried > 0:
            print(f"  Skipping {already_tried} already tried by fallback "
                  f"(use --reset-gaps to retry them)")
        print(f"  {len(gap_songs)} songs to check "
              f"(using Musixmatch, Genius, NetEase, etc.)")
        songs = gap_songs
        if limit:
            songs = songs[:limit]
        if not songs:
            print("No new gaps to fill! Use --reset-gaps to retry previously checked songs.")
            return
        force = True  # force re-lookup for these songs

    # If --new mode, filter out already-cached songs before processing
    if new_only and not force:
        from .lyrics_cache import _load_cache, _make_key
        # Load cache once into memory instead of reading file per song
        cache_data = _load_cache()
        uncached_songs = []
        skipped = 0
        for song in songs:
            artist = _get_artist_name(song, source)
            key = _make_key(song["name"], artist)
            if key not in cache_data:
                uncached_songs.append(song)
            else:
                skipped += 1
        print(f"Skipping {skipped} already-cached songs, {len(uncached_songs)} new songs available.")
        songs = uncached_songs
        # Apply the --new limit to uncached songs only
        if new_only and len(songs) > new_only:
            songs = songs[:new_only]
        if not songs:
            print("No new songs to enrich. All songs are already cached!")
            return

    total_songs = len(songs)

    # Count how many will actually need API calls (not cached)
    if not force and not new_only:
        # In normal mode, some songs may be cached already
        from .lyrics_cache import _load_cache, _make_key
        _cache = _load_cache()
        uncached_count = 0
        for s in songs:
            a = _get_artist_name(s, source)
            if _make_key(s["name"], a) not in _cache:
                uncached_count += 1
        api_estimate = uncached_count
    else:
        api_estimate = total_songs

    # Show estimate with rate limit info
    from .rate_limiter import LYRICS_LIMITER
    LYRICS_LIMITER.reset()

    if workers > 1:
        print(f"Enriching {total_songs} songs with lyrics ({workers} workers)...")
    else:
        print(f"Enriching {total_songs} songs with lyrics...")
    if api_estimate > 0:
        est = LYRICS_LIMITER.estimate_time(api_estimate)
        print(f"  Estimated: {api_estimate:,} API lookups, {est}")
        print(f"  Rate limit: Lyrics ({LYRICS_LIMITER.max_per_second:.0f}/sec cap)")
    print()

    enriched = []
    found = 0
    instrumental = 0
    cached_hits = 0
    api_lookups = 0
    interrupted = False
    cache_lock = threading.Lock()
    completed_count = 0
    # Shared flag so workers can detect cancellation
    cancel_event = threading.Event()

    if workers <= 1:
        # Sequential mode (original behavior)
        try:
            for i, song in enumerate(songs, 1):
                artist = _get_artist_name(song, source)
                track_name = song["name"]

                _progress(i, total_songs, f"Looking up: {track_name[:40]} - {artist[:20]}")

                result, was_cached = _enrich_one_song(
                    song, source, force, get_cached_lyrics, save_lyrics_to_cache,
                    fetch_lyrics_for_songs, cache_lock,
                    use_fallback=fill_gaps,
                )

                if was_cached:
                    cached_hits += 1
                else:
                    api_lookups += 1

                enriched.append(result)

                if result["lyrics_found"]:
                    if result["instrumental"]:
                        instrumental += 1
                    else:
                        found += 1

        except KeyboardInterrupt:
            interrupted = True
    else:
        # Concurrent mode — submit in small batches so Ctrl+C can cancel
        # pending work instead of queuing everything upfront.
        def _cancellable_enrich(song):
            """Wrapper that checks cancel flag before doing work."""
            if cancel_event.is_set():
                return None, True  # cancelled, treat as cached (no-op)
            return _enrich_one_song(
                song, source, force, get_cached_lyrics, save_lyrics_to_cache,
                fetch_lyrics_for_songs, cache_lock,
                use_fallback=fill_gaps,
            )

        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_song = {}
            for song in songs:
                future = executor.submit(_cancellable_enrich, song)
                future_to_song[future] = song

            for future in as_completed(future_to_song):
                if cancel_event.is_set():
                    break
                completed_count += 1
                song = future_to_song[future]
                artist = _get_artist_name(song, source)
                track_name = song["name"]

                _progress(completed_count, total_songs,
                          f"Done: {track_name[:40]} - {artist[:20]}")

                try:
                    result, was_cached = future.result()
                    if result is None:
                        continue  # cancelled
                except Exception as e:
                    # If a single lookup fails, record it as not found
                    result = {
                        **song,
                        "plain_lyrics": None,
                        "synced_lyrics": None,
                        "instrumental": False,
                        "lyrics_found": False,
                    }
                    was_cached = False
                    api_lookups += 1

                if was_cached:
                    cached_hits += 1
                else:
                    api_lookups += 1

                enriched.append(result)

                if result["lyrics_found"]:
                    if result["instrumental"]:
                        instrumental += 1
                    else:
                        found += 1

        except KeyboardInterrupt:
            interrupted = True
            cancel_event.set()  # signal workers to stop
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    if interrupted:
        processed = len(enriched)
        print(f"\n\n  Interrupted! Processed {processed}/{total_songs} songs.")
        print(f"  All {api_lookups} API lookups have been saved to cache.")
        print(f"  Run again to continue where you left off.\n")

    processed = len(enriched)
    label = f" (interrupted)" if interrupted else ""
    print(f"\n\nResults{label}:")
    print(f"  Lyrics found:   {found}/{processed}")
    print(f"  Instrumental:   {instrumental}/{processed}")
    print(f"  Not found:      {processed - found - instrumental}/{processed}")
    print(f"  From cache:     {cached_hits}")
    print(f"  API lookups:    {api_lookups}")
    print(f"  Rate limit:     {LYRICS_LIMITER.summary()}")

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

    # Auto-index if requested and we did at least some API lookups
    if args.index and api_lookups > 0 and not interrupted:
        print("\n--- Auto-indexing ---")
        _run_index(getattr(args, "model", "all-MiniLM-L6-v2"))
    elif args.index and api_lookups == 0:
        print("\nNo new lyrics fetched, skipping re-index.")


def _run_index(model_name: str = "all-MiniLM-L6-v2"):
    """Run the indexing pipeline. Shared by cmd_index and auto-index."""
    from .lyrics_cache import _load_cache, backfill_cache_metadata
    from .vector_store import index_songs

    # Backfill album/URLs from song stores into cache (no API calls)
    backfilled = backfill_cache_metadata()
    if backfilled > 0:
        print(f"  Backfilled {backfilled} cache entries with album/URLs from song stores.")

    cache = _load_cache()
    if not cache:
        print("No lyrics cached yet.")
        return

    songs = list(cache.values())
    songs_with_content = [s for s in songs if s.get("lyrics_found")]

    if not songs_with_content:
        print("No songs with lyrics to index.")
        return

    print(f"Indexing {len(songs_with_content)} songs into vector database...")
    stats = index_songs(songs_with_content, model_name=model_name)

    print(f"  Indexed: {stats['indexed']} songs")
    print(f"  Collection size: {stats['collection_size']}")


def cmd_index(args):
    """Build the vector search index from cached lyrics."""
    from .lyrics_cache import _load_cache
    from .vector_store import get_index_stats

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

    print("(First run will download the embedding model ~80MB)\n")

    _run_index(args.model)

    # Show full stats
    stats = get_index_stats(lightweight=True)
    print(f"\nIndexing complete:")
    print(f"  Collection size: {stats['collection_size']}")


def cmd_enrich_metadata(args):
    """Fetch play counts, tags, and genres from Last.fm and Spotify APIs.

    This enriches the song stores with additional metadata that isn't
    available from the basic load commands. Each API call is rate-limited
    and progress is resumable (already-enriched songs are skipped).
    """
    from .song_store import (load_spotify_songs, save_spotify_songs,
                             load_lastfm_scrobbles, save_lastfm_scrobbles)
    from .rate_limiter import LASTFM_LIMITER, SPOTIFY_LIMITER

    target = args.target  # "lastfm", "spotify", or "all"
    limit = args.limit

    # --- Last.fm: per-user play counts and tags ---
    if target in ("lastfm", "all"):
        _enrich_lastfm_metadata(limit)

    # --- Spotify: artist genres ---
    if target in ("spotify", "all"):
        _enrich_spotify_genres(limit)


def _enrich_lastfm_metadata(limit: int | None = None):
    """Fetch per-user play counts and tags from Last.fm for stored songs."""
    from .song_store import load_lastfm_scrobbles, save_lastfm_scrobbles
    from .lastfm_client import get_track_info
    from .rate_limiter import LASTFM_LIMITER

    data = load_lastfm_scrobbles()
    if not data:
        print("No Last.fm songs stored. Run 'music-search load lastfm' first.")
        return

    songs = data["songs"]

    # Filter to songs not yet enriched
    unenriched = [s for s in songs if "user_playcount" not in s]
    if not unenriched:
        print(f"Last.fm: All {len(songs)} songs already have play counts.")
        return

    to_process = unenriched[:limit] if limit else unenriched
    print(f"Last.fm: Enriching {len(to_process)}/{len(unenriched)} songs with play counts & tags...")

    LASTFM_LIMITER.reset()
    est = LASTFM_LIMITER.estimate_time(len(to_process))
    print(f"  Estimated: {est}")
    print(f"  Rate limit: Last.fm ({LASTFM_LIMITER.max_per_second:.0f}/sec cap)")
    print()

    enriched_count = 0
    try:
        for i, song in enumerate(to_process, 1):
            _progress(i, len(to_process),
                      f"Fetching: {song['name'][:40]} - {song.get('artist', '')[:20]}")

            info = get_track_info(song["name"], song.get("artist", ""))
            if info:
                song["user_playcount"] = info["user_playcount"]
                song["global_listeners"] = info["listeners"]
                song["global_playcount"] = info["playcount"]
                song["tags"] = info["tags"]
                song["loved"] = info["loved"]
            else:
                # Mark as attempted so we don't retry
                song["user_playcount"] = 0
                song["tags"] = []
                song["loved"] = False

            enriched_count += 1

    except KeyboardInterrupt:
        print(f"\n\n  Interrupted! Enriched {enriched_count}/{len(to_process)} songs.")
        print(f"  Progress saved. Run again to continue.")

    # Save progress (even if interrupted)
    if enriched_count > 0:
        save_lastfm_scrobbles(songs)
        print(f"\n\nLast.fm enrichment: {enriched_count} songs updated.")
        print(f"  Rate limit: {LASTFM_LIMITER.summary()}")
    else:
        print("\n\nNo songs enriched.")


def _enrich_spotify_genres(limit: int | None = None):
    """Fetch artist genres from Spotify for stored songs."""
    from .song_store import load_spotify_songs, save_spotify_songs
    from .spotify_client import fetch_artist_genres
    from .rate_limiter import SPOTIFY_LIMITER

    data = load_spotify_songs()
    if not data:
        print("No Spotify songs stored. Run 'music-search load spotify' first.")
        return

    songs = data["songs"]

    # Collect unique artist IDs that haven't been genre-enriched yet
    # Treat empty genre lists as unenriched (batch endpoint 403s wrote empty [])
    unenriched_songs = [s for s in songs if not s.get("genres") and s.get("artist_ids")]
    songs_without_artist_ids = sum(1 for s in songs if not s.get("artist_ids"))
    if not unenriched_songs:
        if songs_without_artist_ids > 0:
            print(f"Spotify: {songs_without_artist_ids} songs don't have artist IDs yet.")
            print("  Run 'music-search load spotify --full' first to fetch the updated fields,")
            print("  then run this command again.")
        else:
            print(f"Spotify: All {len(songs)} songs already have genres.")
        return

    # Collect unique artist IDs
    artist_ids_needed = set()
    for s in unenriched_songs:
        for aid in s.get("artist_ids", []):
            artist_ids_needed.add(aid)

    if limit:
        # Limit by number of songs to process, not artist IDs
        unenriched_songs = unenriched_songs[:limit]
        artist_ids_needed = set()
        for s in unenriched_songs:
            for aid in s.get("artist_ids", []):
                artist_ids_needed.add(aid)

    artist_ids = list(artist_ids_needed)
    n_api_calls = len(artist_ids)  # 1 call per artist (batch endpoint removed Feb 2026)

    # Time estimate: each call ~1s + periodic batch pauses to avoid rate limits.
    # Spotify removed the batch /artists?ids= endpoint in Feb 2026, so we must
    # make individual calls. Making thousands in a row at 1/sec triggered a
    # 24-hour rate-limit ban, so we now pause 30s every 50 calls.
    batch_size = 50
    batch_pause = 30
    n_pauses = n_api_calls // batch_size  # pause after each full batch
    api_seconds = n_api_calls  # ~1 call/sec
    pause_seconds = n_pauses * batch_pause
    total_seconds = api_seconds + pause_seconds
    total_min = total_seconds / 60

    SPOTIFY_LIMITER.reset()
    print(f"Spotify: Fetching genres for {len(artist_ids)} unique artists "
          f"({len(unenriched_songs)} songs)...")
    print(f"  Strategy: {n_api_calls} individual /artists/{{id}} calls (batch endpoint")
    print(f"            removed Feb 2026), paced at ~1/sec with {batch_pause}s pauses")
    print(f"            every {batch_size} calls to avoid rate-limit bans.")
    print(f"  Estimated: ~{api_seconds}s API calls + ~{pause_seconds}s pacing pauses "
          f"= ~{total_min:.0f} min total")
    print()

    def _genre_progress(done, total):
        print(f"  [{done}/{total}] artists fetched...", flush=True)

    genre_map = fetch_artist_genres(artist_ids, progress_callback=_genre_progress,
                                    batch_size=batch_size, batch_pause=batch_pause)

    if not genre_map:
        print("\nNo genre data retrieved (rate limit or API issue).")
        print("  Try again later with: music-search enrich-metadata spotify")
        return

    # Only apply genres to songs whose artists were actually looked up
    # Don't write empty lists for artists we didn't fetch yet
    fetched_artist_ids = set(genre_map.keys())
    updated = 0
    for song in songs:
        if not song.get("genres") and song.get("artist_ids"):
            # Check if ALL of this song's artists have been looked up
            song_artist_ids = set(song["artist_ids"])
            if not song_artist_ids.issubset(fetched_artist_ids):
                continue  # Skip — we don't have data for all artists yet

            # Combine genres from all artists on the track
            all_genres = []
            for aid in song["artist_ids"]:
                all_genres.extend(genre_map.get(aid, []))
            # Deduplicate while preserving order
            seen = set()
            song["genres"] = [g for g in all_genres if not (g in seen or seen.add(g))]
            updated += 1

    if updated > 0:
        save_spotify_songs(songs)
        print(f"\nSpotify genre enrichment: {updated} songs updated "
              f"({len(genre_map)}/{len(artist_ids)} artists fetched).")
        print(f"  Rate limit: {SPOTIFY_LIMITER.summary()}")
        remaining = len(artist_ids) - len(genre_map)
        if remaining > 0:
            print(f"  {remaining} artists remaining. Run again later to continue.")
    else:
        print("\nNo songs needed genre enrichment.")


def cmd_refresh(args):
    """One-command refresh: load > enrich > index > export.

    Runs the full pipeline in order, using incremental mode for loading
    and lyrics enrichment. Equivalent to running each step manually but
    in one shot.
    """
    import time
    from .rate_limiter import LYRICS_LIMITER

    t_start = time.perf_counter()
    full = args.full
    workers = args.workers
    fill_gaps = args.fill_gaps
    reset_gaps = getattr(args, "reset_gaps", False)

    # Handle --reset-gaps before the pipeline starts
    if reset_gaps and fill_gaps:
        from .lyrics_cache import reset_fallback_tried
        count = reset_fallback_tried()
        if count > 0:
            print(f"Reset {count} songs for re-checking by --fill-gaps.")
        print()

    # Step 1: Load from APIs (incremental by default)
    print("=" * 60)
    print("Step 1/4: Loading songs from APIs")
    print("=" * 60)

    spotify_ok = False
    lastfm_ok = False

    try:
        _load_spotify(full=full)
        spotify_ok = True
    except SystemExit:
        print("  Spotify: skipped (not configured)")
    except Exception as e:
        print(f"  Spotify: error ({e})")

    try:
        _load_lastfm(full=full)
        lastfm_ok = True
    except SystemExit:
        print("  Last.fm: skipped (not configured)")
    except Exception as e:
        print(f"  Last.fm: error ({e})")

    if not spotify_ok and not lastfm_ok:
        print("\nNo songs loaded. Configure at least one service first.")
        return

    # Step 2: Lyrics enrichment (new songs only)
    print()
    print("=" * 60)
    print("Step 2/4: Enriching new songs with lyrics")
    print("=" * 60)

    from .lyrics_client import fetch_lyrics_for_songs
    from .lyrics_cache import (get_cached_lyrics, save_lyrics_to_cache,
                               get_cache_stats, _load_cache, _make_key)
    import threading

    songs, source = _load_songs_from_store("auto")

    # Filter to uncached songs only
    cache_data = _load_cache()
    uncached = []
    for song in songs:
        artist = _get_artist_name(song, source)
        key = _make_key(song["name"], artist)
        if key not in cache_data:
            uncached.append(song)

    if uncached:
        LYRICS_LIMITER.reset()
        est = LYRICS_LIMITER.estimate_time(len(uncached))
        print(f"  {len(uncached)} new songs to enrich, {est}")

        cache_lock = threading.Lock()
        api_lookups = 0

        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            cancel_event = threading.Event()

            def _cancellable(song):
                if cancel_event.is_set():
                    return None, True
                return _enrich_one_song(
                    song, source, False, get_cached_lyrics,
                    save_lyrics_to_cache, fetch_lyrics_for_songs, cache_lock,
                    use_fallback=False,
                )

            executor = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = {executor.submit(_cancellable, s): s for s in uncached}
                done = 0
                for future in as_completed(futures):
                    if cancel_event.is_set():
                        break
                    done += 1
                    try:
                        result, was_cached = future.result()
                        if result is None:
                            continue
                        if not was_cached:
                            api_lookups += 1
                    except Exception:
                        api_lookups += 1
                    _progress(done, len(uncached), "Enriching...")
            except KeyboardInterrupt:
                cancel_event.set()
                print(f"\n  Interrupted at {done}/{len(uncached)}. Progress saved.")
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            try:
                for i, song in enumerate(uncached, 1):
                    artist = _get_artist_name(song, source)
                    _progress(i, len(uncached),
                              f"Looking up: {song['name'][:40]} - {artist[:20]}")
                    _, was_cached = _enrich_one_song(
                        song, source, False, get_cached_lyrics,
                        save_lyrics_to_cache, fetch_lyrics_for_songs, cache_lock,
                        use_fallback=False,
                    )
                    if not was_cached:
                        api_lookups += 1
            except KeyboardInterrupt:
                print(f"\n  Interrupted at {i}/{len(uncached)}. Progress saved.")

        print(f"\n  Enriched: {api_lookups} API lookups, {LYRICS_LIMITER.summary()}")
    else:
        print("  No new songs to enrich.")

    # Step 2b: Fill gaps with alternative sources (optional)
    if fill_gaps:
        cache_stats = get_cache_stats()
        if cache_stats["not_found"] > 0:
            print(f"\n  Filling gaps: {cache_stats['not_found']} songs with missing lyrics "
                  f"({cache_stats.get('gaps_remaining', '?')} not yet tried by fallback)...")
            # Re-load cache for gap detection
            cache_data = _load_cache()
            gap_songs = []
            already_tried = 0
            for song in songs:
                artist = _get_artist_name(song, source)
                key = _make_key(song["name"], artist)
                cached = cache_data.get(key)
                if cached and not cached.get("lyrics_found"):
                    if cached.get("fallback_tried"):
                        already_tried += 1
                    else:
                        gap_songs.append(song)
            if already_tried > 0:
                print(f"  Skipping {already_tried} already tried by fallback")

            if gap_songs:
                cache_lock = threading.Lock()
                filled = 0
                try:
                    for i, song in enumerate(gap_songs, 1):
                        artist = _get_artist_name(song, source)
                        _progress(i, len(gap_songs),
                                  f"Filling: {song['name'][:40]} - {artist[:20]}")
                        result, _ = _enrich_one_song(
                            song, source, True, get_cached_lyrics,
                            save_lyrics_to_cache, fetch_lyrics_for_songs, cache_lock,
                            use_fallback=True,  # fill-gaps uses alternative sources
                        )
                        if result.get("lyrics_found"):
                            filled += 1
                except KeyboardInterrupt:
                    print(f"\n  Interrupted. Filled {filled} gaps so far.")

                print(f"\n  Gaps filled: {filled}/{len(gap_songs)}")

    # Step 3: Build vector index
    print()
    print("=" * 60)
    print("Step 3/4: Building search index")
    print("=" * 60)

    _run_index(args.model)

    # Step 4: Export SQLite
    print()
    print("=" * 60)
    print("Step 4/4: Exporting SQLite database")
    print("=" * 60)

    from .sqlite_export import export_to_sqlite
    stats = export_to_sqlite()
    print(f"  Songs: {stats['songs_exported']:,}  |  Scrobbles: {stats.get('scrobbles_exported', 0):,}"
          f"  |  Lyrics indexed: {stats['lyrics_indexed']:,}")
    print(f"  Database: {stats['db_path']}")

    # Final summary
    t_elapsed = time.perf_counter() - t_start
    print()
    print("=" * 60)
    cache_stats = get_cache_stats()
    print(f"Refresh complete in {t_elapsed:.0f}s")
    print(f"  Songs: {stats['songs_exported']:,}")
    print(f"  Lyrics: {cache_stats['with_lyrics']:,} found, "
          f"{cache_stats['not_found']:,} missing")
    print(f"  Ready to search!")
    print("=" * 60)


def cmd_export_db(args):
    """Export all music data to a SQLite database for SQL exploration."""
    from pathlib import Path
    from .sqlite_export import export_to_sqlite

    db_path = Path(args.path) if args.path else None
    print("Exporting music library to SQLite...")

    stats = export_to_sqlite(db_path)

    print(f"\nExport complete:")
    print(f"  Songs:          {stats['songs_exported']:,}")
    print(f"  Scrobbles:      {stats.get('scrobbles_exported', 0):,} play events")
    print(f"  Lyrics indexed: {stats['lyrics_indexed']:,} (searchable via FTS5)")
    print(f"  Database:       {stats['db_path']}")
    print(f"\nExplore with:")
    print(f'  sqlite3 "{stats["db_path"]}"')
    print(f"  .mode column")
    print(f"  .headers on")
    print(f"  SELECT track_name, artist_name, user_playcount FROM songs")
    print(f"    WHERE user_playcount > 5 ORDER BY user_playcount DESC LIMIT 20;")
    print(f"  SELECT track_name, artist_name FROM lyrics_fts")
    print(f"    WHERE lyrics_fts MATCH 'love rain';")


def cmd_search(args):
    """Search the vector index with a natural language query."""
    import time
    import shutil
    from .vector_store import search, get_index_stats

    # Spinner characters for animated progress
    _SPINNER = ["|", "/", "-", "\\"]
    _spin_idx = 0

    def _search_progress(message: str) -> None:
        """Display a progress message with a spinner on the same line."""
        nonlocal _spin_idx
        width = shutil.get_terminal_size().columns - 1
        spinner = _SPINNER[_spin_idx % len(_SPINNER)]
        _spin_idx += 1
        line = f"  {spinner} {message}"
        sys.stdout.write(f"\r{_truncate_to_width(line, width)}")
        sys.stdout.flush()

    def _clear_progress() -> None:
        """Clear the progress line."""
        width = shutil.get_terminal_size().columns - 1
        sys.stdout.write(f"\r{' ' * width}\r")
        sys.stdout.flush()

    # Quick lightweight check first (no model loading)
    stats = get_index_stats(lightweight=True)
    if stats["collection_size"] == 0:
        print("No songs indexed yet. Run 'music-search index' first.")
        sys.exit(1)

    query = " ".join(args.query)
    print(f"Searching {stats['collection_size']} songs for: \"{query}\"\n")

    t_start = time.perf_counter()

    results = search(
        query,
        n_results=args.limit,
        model_name=args.model,
        progress_callback=_search_progress,
    )

    t_elapsed = time.perf_counter() - t_start
    _clear_progress()

    if not results:
        print("No results found.")
        return

    for i, result in enumerate(results, 1):
        score_pct = result["score"] * 100
        print(f"{i}. {result['track_name']} - {result['artist_name']}")
        print(f"   Album: {result['album']}  |  Match: {score_pct:.1f}%")

        # Show Spotify link (direct URL, or search fallback)
        spotify_url = result.get("spotify_url", "")
        if spotify_url:
            print(f"   Spotify: {spotify_url}")
        else:
            # Construct a search URL as fallback
            from urllib.parse import quote
            search_q = quote(f"{result['track_name']} {result['artist_name']}")
            print(f"   Spotify: https://open.spotify.com/search/{search_q}")

        if args.verbose:
            print(f"   Preview: {result['document_preview']}")
        print()

    print(f"  Search completed in {t_elapsed:.1f}s")


def main():
    parser = argparse.ArgumentParser(
        prog="music-search",
        description="Music Search MCP - Search your music library using vague recollections",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # load command
    load_parser = subparsers.add_parser(
        "load",
        help="Fetch songs from Spotify/Last.fm and save locally",
    )
    load_parser.add_argument(
        "source",
        choices=["spotify", "lastfm", "all"],
        help="Which service to fetch from: spotify, lastfm, or all",
    )
    load_parser.add_argument(
        "--full",
        action="store_true",
        help="Re-fetch everything from scratch (default: incremental, only fetching new songs)",
    )
    load_parser.set_defaults(func=cmd_load)

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show what data is currently stored locally",
    )
    status_parser.set_defaults(func=cmd_status)

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
        help="Maximum number of songs to process (default: all). Includes cached songs in the count.",
    )
    lyrics_enrich_parser.add_argument(
        "--new",
        type=int,
        default=None,
        metavar="N",
        help="Enrich N new (uncached) songs only. Skips already-cached songs and doesn't count them.",
    )
    lyrics_enrich_parser.add_argument(
        "--source",
        choices=["auto", "spotify", "lastfm", "both"],
        default="auto",
        help="Music source: auto (use whatever is loaded), spotify, lastfm, or both (default: auto)",
    )
    lyrics_enrich_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch lyrics even if already cached",
    )
    lyrics_enrich_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Number of concurrent LRCLIB lookups (default: 1). Try 4-8 for faster enrichment.",
    )
    lyrics_enrich_parser.add_argument(
        "--index",
        action="store_true",
        help="Automatically rebuild the search index after enrichment.",
    )
    lyrics_enrich_parser.add_argument(
        "--fill-gaps",
        action="store_true",
        help="Re-try songs where lyrics were NOT found, using alternative sources "
             "(Musixmatch, Genius, NetEase, etc.) via the syncedlyrics library. "
             "Songs already tried by fallback are skipped (use --reset-gaps to retry).",
    )
    lyrics_enrich_parser.add_argument(
        "--reset-gaps",
        action="store_true",
        help="Clear the 'already tried' flag on all songs so --fill-gaps will "
             "re-check them. Can be combined with --fill-gaps in one command.",
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

    # enrich-metadata command
    metadata_parser = subparsers.add_parser(
        "enrich-metadata",
        help="Fetch play counts, tags, and genres from Last.fm/Spotify",
    )
    metadata_parser.add_argument(
        "target",
        choices=["lastfm", "spotify", "all"],
        help="Which service to enrich from: lastfm (play counts + tags), "
             "spotify (artist genres), or all",
    )
    metadata_parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of songs to enrich (default: all unenriched)",
    )
    metadata_parser.set_defaults(func=cmd_enrich_metadata)

    # export-db command
    export_parser = subparsers.add_parser(
        "export-db",
        help="Export music library to SQLite for SQL exploration",
    )
    export_parser.add_argument(
        "--path",
        default=None,
        help="Output path for SQLite database (default: data/music_library.db)",
    )
    export_parser.set_defaults(func=cmd_export_db)

    # refresh command
    refresh_parser = subparsers.add_parser(
        "refresh",
        help="One-command pipeline: load > enrich > index > export",
    )
    refresh_parser.add_argument(
        "--full",
        action="store_true",
        help="Re-fetch everything from scratch (default: incremental)",
    )
    refresh_parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="Concurrent lyrics lookups (default: 4)",
    )
    refresh_parser.add_argument(
        "--fill-gaps",
        action="store_true",
        help="Also try alternative lyrics sources for songs with missing lyrics",
    )
    refresh_parser.add_argument(
        "--reset-gaps",
        action="store_true",
        help="Clear the 'already tried' flag before filling gaps (retry all)",
    )
    refresh_parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="Embedding model for indexing (default: all-MiniLM-L6-v2)",
    )
    refresh_parser.set_defaults(func=cmd_refresh)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
