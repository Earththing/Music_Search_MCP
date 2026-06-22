# Lessons Learned: Music Search MCP

A living document of patterns, pitfalls, and best practices discovered while building a semantic music search pipeline that integrates Spotify, Last.fm, LRCLIB, and ChromaDB.

---

## Architecture & Design

### Plan in chunks, implement incrementally
Breaking a large feature set into ordered, testable chunks (each 1-2 hours of work) keeps momentum high and lets you verify each layer before building on it. Our 7-chunk plan moves from infrastructure (rate limiting) through data fixes, richer data, alternative sources, metadata enrichment, SQL export, and finally a glue command. Each chunk is self-contained and testable.

### Separate fetching from processing
Decoupling API calls from enrichment/indexing was one of the best early decisions. Song stores (`data/spotify_songs.json`, `data/lastfm_scrobbles.json`) act as a local cache of raw API data. This means:
- You only hit APIs once, then iterate locally
- Rate limit bans don't block development
- You can experiment with indexing strategies without re-fetching
- Incremental loading becomes a natural extension

### The lyrics cache is the canonical enrichment layer
All enriched data flows through `lyrics_cache.json`. The vector index reads from it. This single-source-of-truth pattern is clean, but it means **every field you want in search results must be stored in the cache**. We discovered this the hard way when `album` and `spotify_url` were stored in song_store but never reached the cache or index.

**Lesson:** Trace data flow end-to-end when adding new fields. Ask: "Where does this field originate? Where does it need to end up? What's every layer in between?"

### Backfill patterns for evolving schemas
When you add new fields to a cache or store, existing entries won't have them. Rather than forcing a full re-fetch, write a backfill function that patches existing data from local sources (no API calls). Our `backfill_cache_metadata()` patched 20,000+ cache entries with album/URL data from song stores in seconds.

---

## API Integration

### Rate limits are real and consequential
Our Spotify app got banned multiple times — 17 hours, then 24 hours. This wasn't theoretical. Key lessons:

- **Spotify:** Rolling 30-second window, no published req/sec number. Development mode apps have lower limits. Returns HTTP 429 with `Retry-After` header. Penalties escalate (seconds to hours). No published threshold for permanent revocation, but Spotify reserves the right to terminate at any time.
- **Last.fm:** 5 req/sec averaged over 5 minutes. Returns error code 29 when exceeded. More forgiving but still requires throttling.
- **LRCLIB:** No documented limits, but being polite matters. We cap at 10/sec even with concurrent workers.

### Batch endpoints can disappear without warning
Spotify removed all batch endpoints (`GET /artists?ids=`, `GET /tracks?ids=`, etc.) for development-mode apps in February 2026. Code that worked one day returned 403 the next. The migration path was to use individual endpoints, but making 2,000+ individual calls at 1/sec triggered the rate limit we'd previously avoided with 44 batch calls.

**Lesson:** When switching from batch to individual calls, add pacing pauses (e.g., 30s pause every 50 calls) to break up sustained traffic patterns. Spotify's rolling window treats 2,000 sequential calls very differently from 44 batch calls, even at the same effective rate.

### Extended Quota Mode is now gated for individuals
As of May 2025, Spotify's Extended Quota Mode requires a legally registered business with 250K+ monthly active users. Individual developers are permanently in development mode with its lower rate limits. Design accordingly — assume you'll never get higher quotas.

### Build rate limiting as shared infrastructure
Don't sprinkle `time.sleep()` calls everywhere. A shared `RateLimiter` class with `acquire()`, `estimate_time()`, and `summary()` methods:
- Is thread-safe (critical for concurrent workers)
- Shows users what to expect before long operations
- Reports actual throttling behavior after operations
- Can be tuned per-API without touching call sites

### Retry strategies should be proportional
Not all 429s are equal:
- **Short waits (< 60s):** Auto-retry silently — users barely notice
- **Long bans (hours):** Return partial results and inform the user — don't hang
- **Server errors (5xx):** Exponential backoff with a cap on retries

### Cache API responses locally as early as possible
Every API response should be cached before any processing. When a long enrichment run gets interrupted (Ctrl+C, rate limit, crash), all progress up to that point is preserved. Users can simply run the same command again to continue where they left off.

### Incremental loading saves time and API quota
Spotify returns liked songs in reverse-chronological order; Last.fm supports `from` timestamps. By tracking what we've already fetched (known IDs for Spotify, latest timestamp for Last.fm), subsequent loads only fetch new data. This is both faster and safer for rate limits.

---

## Data Quality

### API field availability changes
Spotify deprecated audio features (danceability, energy, valence, tempo) in November 2024. Then in February 2026, they removed `popularity` from tracks and artists, `followers` from artists, and deprecated the `genres` field on artists. **Always verify current API capabilities before committing to a feature.** Fields you rely on can be removed in any API update.

### TOS has a broad ML/AI prohibition
Spotify's developer terms prohibit "ingesting Spotify Content into a machine learning or AI model." Creating vector embeddings from track metadata (names, artists) for semantic search could technically fall under this. Mitigating factors: we're not training a model (using pre-trained embeddings for retrieval), lyrics come from LRCLIB (not Spotify), and it's personal use. But it's a risk worth knowing about.

### Not all services provide the same data
- Spotify has direct track URLs but no per-user play counts
- Last.fm has per-user play counts but no direct playable URLs
- LRCLIB has lyrics for many tracks but not all
- Some fields exist in one service but not the other

**Solution:** Track provenance (`in_spotify`, `in_lastfm`, `lyrics_source`) so you always know where data came from, and use fallback patterns (e.g., Spotify search URLs for Last.fm-only songs).

### Deduplication across services is messy
Songs appear in both Spotify and Last.fm with slightly different names, artists, and albums. Normalize to lowercase and strip whitespace for matching, but expect imperfect results. Using `track_name.lower() || artist_name.lower()` as a key works reasonably well.

### CJK and special characters need attention
Terminal display widths are wrong when you have CJK (Chinese, Japanese, Korean) characters because they occupy 2 terminal columns. Use `unicodedata.east_asian_width()` to calculate actual display width. This applies to progress bars, table formatting, and any fixed-width output.

---

## CLI & UX

### Show estimates before long operations
When an operation will take more than a few seconds, tell users:
- How many items will be processed
- The rate limit that applies
- Estimated wall-clock time
- How to interrupt safely (Ctrl+C)

```
Enriching 27,000 songs with lyrics...
  Estimated: 27,000 API lookups, ~45 min at 10 req/sec
  Rate limit: Lyrics (10/sec cap)
  Press Ctrl+C to stop early — progress is saved.
```

### Show summaries after operations
After the work is done, report what actually happened:
```
  Rate limit: Lyrics: 2,847 calls, 12 throttled, 24s total
```
This builds trust and helps users understand the system's behavior.

### Graceful Ctrl+C on everything
Every long-running loop should catch `KeyboardInterrupt`, save progress, and print a summary. Users shouldn't lose work because they interrupted a process. For `ThreadPoolExecutor`, the default `with` context manager calls `shutdown(wait=True)` which blocks until all threads finish — threads don't receive `KeyboardInterrupt`. Solution: use a shared `threading.Event()` cancel flag, check it in workers, and call `executor.shutdown(wait=False, cancel_futures=True)` in a `finally` block.

### Progress feedback matters
For operations processing thousands of items, use `\r`-based progress lines that overwrite in place. Include the current item count, total, and what's being processed. Clear the line when done so it doesn't leave artifacts.

### Track what you've already tried
When a fallback operation (like `--fill-gaps`) can be run incrementally in small batches, flag each item as "tried" so the next batch picks up where the last one left off instead of re-checking the same items. Provide a `--reset` flag to clear the flags and start over. Without this, users running in small batches will quickly hit a wall where every item has already been checked.

### Logger suppression must be global with concurrent workers
When suppressing noisy third-party loggers (e.g., syncedlyrics' Musixmatch 401 spam), set logger levels once at module level rather than toggling per-call. With multiple workers, one worker's `finally` block can restore logger levels while another worker's daemon thread is still logging — a race condition that lets spam leak through.

---

## Embedding & Search

### First search is slow, subsequent searches are fast
Loading the sentence-transformer model takes ~6-8 seconds. After that, queries are sub-second. The MCP server keeps the model loaded between calls. For CLI, show a spinner during model loading so users know what's happening.

### ChromaDB upsert is idempotent but not subtractive
`collection.upsert()` updates existing documents and adds new ones, but never removes entries. If you delete a song from your cache, it stays in the index until you rebuild. This is fine for our use case (music library only grows), but worth knowing.

### Cosine distance vs. similarity score
ChromaDB returns cosine distance (0 = identical, 2 = opposite). Converting to similarity (`1 - distance`) gives a 0-1 score that's more intuitive. Display as a percentage for users.

### Document construction affects search quality
The text you embed matters. We combine song identity, album, instrumental flag, and full lyrics into a single document. This allows searching by any of these dimensions — mood, lyrics fragments, artist, genre references in lyrics, etc.

---

## Development Process

### Test imports after every change
A quick `python -c "from module import X; print('OK')"` catches syntax errors and circular imports immediately. Do this before running the full tool.

### Use the tool from the user's perspective
After implementing a feature, run the actual CLI command end-to-end. Don't just test the function — test the command. This catches argument parsing issues, output formatting problems, and integration bugs.

### Watch for the "null" file anti-pattern
In a previous session, a `Write` tool with a bad path created a file literally named `null`. Always use absolute paths and verify the target directory exists before writing files.

---

## Best Practices for Similar Projects

### For any multi-API aggregation project:
1. **Cache everything locally** — API access is the bottleneck, not disk space
2. **Build rate limiting first** — it's infrastructure that everything else depends on
3. **Track data provenance** — when combining data from multiple sources, always know where each piece came from
4. **Design for incremental updates** — full reloads are expensive; incremental is the default
5. **Make long operations interruptible and resumable** — save progress continuously, not just at the end
6. **Provide time estimates** — users need to know if something will take 5 seconds or 5 hours

### For embedding/search projects:
1. **Separate embedding from querying** — build the index as a batch job, query it interactively
2. **Choose your embedding model early** — changing it later means re-indexing everything
3. **Store metadata alongside embeddings** — you'll want to filter and display fields that aren't in the embedded text
4. **Use lightweight index checks** — don't load the embedding model just to check if the index exists

### For MCP servers:
1. **stdout is sacred** — it's the JSON-RPC transport; use stderr for logging
2. **First call is slow** — model loading happens on first search; subsequent calls are fast
3. **Full paths in config** — `PATH` resolution isn't reliable; use absolute paths to executables
4. **Suppress noisy library output** — redirect stderr during model loading to keep MCP transport clean

---

## Personal Preferences

### Planning style
- Wants to be consulted before major overhauls — no surprise rewrites
- Prefers seeing the full plan broken into ordered chunks before implementation starts
- Likes to understand how chunks fit together and what order they'll be implemented
- Approves plans before coding begins: "good plan, don't code yet" until ready

### Development style
- Prefers incremental, testable progress over big-bang changes
- Values seeing estimates and summaries (how long will this take? what happened?)
- Wants graceful handling of interrupts and errors — never lose work
- Appreciates when the tool tells you what to do next ("run 'music-search index' to rebuild")
- OK with web searches without asking, but wants approval for significant decisions

### Data philosophy
- Wants to know where data came from (provenance tracking is important)
- Wants to be able to combine data from different sources for exploration
- Prefers getting as much done in one shot as possible, within rate limit safety
- Values TOS compliance and rate limit awareness — "I would rather get as much done in one shot as I could as long as I don't get in trouble"

### Communication preferences
- Straightforward, technical communication
- Show the work — test results, actual output, error messages
- Don't over-explain obvious things, but do explain non-obvious design decisions
- Keep the user informed about what's happening and why

---

*Last updated: 2026-02-15 — After completing all 7 chunks + Spotify Feb 2026 migration fixes*
