"""Thread-safe rate limiter with estimation and tracking.

Provides shared rate limiters for all API clients (Spotify, Last.fm, LRCLIB)
with time estimation, call counting, and safe throttling for concurrent workers.

Usage:
    from .rate_limiter import LASTFM_LIMITER

    LASTFM_LIMITER.acquire()   # blocks until safe to proceed
    response = requests.get(...)

    # Before a long operation:
    print(LASTFM_LIMITER.estimate_time(27000))  # "~1h 53m at 4 req/sec"

    # After:
    print(f"API calls: {LASTFM_LIMITER.calls_made}")
"""

import threading
import time


class RateLimiter:
    """Thread-safe rate limiter with estimation and tracking.

    Enforces a maximum request rate across all threads sharing this instance.
    Tracks total calls made for reporting.

    Args:
        name: Human-readable name for this limiter (e.g. "Last.fm").
        max_per_second: Maximum requests per second to allow.
    """

    def __init__(self, name: str, max_per_second: float):
        self.name = name
        self.max_per_second = max_per_second
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self._calls_made = 0
        self._waits = 0  # times we had to sleep (throttled)
        self._start_time: float | None = None

    def acquire(self) -> None:
        """Block until it's safe to make a request, then record the call.

        Thread-safe — multiple workers can call this concurrently and
        requests will be spaced at least 1/max_per_second apart.
        """
        with self._lock:
            if self._start_time is None:
                self._start_time = time.monotonic()

            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                wait = self._min_interval - elapsed
                self._waits += 1
                # Release lock while sleeping so other threads aren't blocked
                # unnecessarily (they'll wait on next acquire)
                self._last_request_time = now + wait
                self._calls_made += 1
                # We need to sleep outside the lock for concurrent workers
                time.sleep(wait)
                return

            self._last_request_time = now
            self._calls_made += 1

    @property
    def calls_made(self) -> int:
        """Total API calls made through this limiter."""
        return self._calls_made

    @property
    def waits(self) -> int:
        """Number of times a request was throttled (had to wait)."""
        return self._waits

    def reset(self) -> None:
        """Reset all counters. Call before starting a new operation."""
        with self._lock:
            self._calls_made = 0
            self._waits = 0
            self._start_time = None
            self._last_request_time = 0.0

    def estimate_time(self, n_calls: int, workers: int = 1) -> str:
        """Estimate how long n_calls will take at the current rate.

        Args:
            n_calls: Number of API calls to estimate.
            workers: Number of concurrent workers (rate limit is shared).

        Returns:
            Human-readable estimate string, e.g. "~1h 53m at 4 req/sec"
        """
        if n_calls <= 0:
            return "no calls needed"

        # With rate limiting, workers don't help beyond the max rate
        effective_rate = min(self.max_per_second, self.max_per_second)
        seconds = n_calls / effective_rate

        time_str = _format_duration(seconds)
        rate_str = (f"{effective_rate:.0f}" if effective_rate == int(effective_rate)
                    else f"{effective_rate:.1f}")
        return f"~{time_str} at {rate_str} req/sec"

    def summary(self) -> str:
        """Return a summary of calls made, e.g. 'Last.fm: 2,847 calls, 12 throttled'."""
        parts = [f"{self.name}: {self._calls_made:,} calls"]
        if self._waits > 0:
            parts.append(f"{self._waits:,} throttled")
        if self._start_time is not None:
            elapsed = time.monotonic() - self._start_time
            parts.append(f"{_format_duration(elapsed)}")
        return ", ".join(parts)


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string.

    Examples: "45s", "12m 34s", "1h 53m", "2h 15m"
    """
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s" if s > 0 else f"{m}m"
    else:
        h, remainder = divmod(seconds, 3600)
        m = remainder // 60
        return f"{h}h {m}m" if m > 0 else f"{h}h"


# Pre-configured instances for each API
# These are module-level singletons shared across all code that imports them.

LASTFM_LIMITER = RateLimiter("Last.fm", max_per_second=4)
"""Last.fm API: 5 req/sec max, we use 4 to stay safe."""

SPOTIFY_LIMITER = RateLimiter("Spotify", max_per_second=1)
"""Spotify API: undisclosed limits. Set to 1/sec since the Feb 2026
removal of batch endpoints means more individual calls are needed.
Spotipy also has built-in retry on 429, so this is a safety net."""

LYRICS_LIMITER = RateLimiter("Lyrics", max_per_second=10)
"""LRCLIB + fallback providers: no published limits, capped at 10/sec
to be polite. Shared across concurrent workers."""
