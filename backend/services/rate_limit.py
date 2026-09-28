"""Login brute-force protection.

In-process, in-memory - appropriate for this prototype's single-worker
deployment. No Redis or external store is introduced; if this were ever
run with multiple worker processes, each would keep its own counters,
which degrades the limit rather than breaking it (still some protection,
just not perfectly shared) - a documented trade-off, not a silent gap.

Keyed by the SAME normalised value used for the login lookup itself
(lower-cased email), never by whether the account actually exists - the
limiter must not become a second channel for account enumeration. A
request against an unregistered email is throttled exactly like one
against a real account.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    failures: int = 0
    window_start: float = field(default_factory=time.monotonic)
    locked_until: float | None = None


class LoginRateLimiter:
    def __init__(self, max_failures: int, window_seconds: int, lockout_seconds: int):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _get_bucket(self, key: str, now: float) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(window_start=now)
            self._buckets[key] = bucket
            return bucket
        if now - bucket.window_start > self.window_seconds and (
            bucket.locked_until is None or now >= bucket.locked_until
        ):
            # The failure window has elapsed with no active lockout -
            # start counting fresh rather than accumulating forever.
            bucket.failures = 0
            bucket.window_start = now
            bucket.locked_until = None
        return bucket

    def check(self, key: str) -> tuple[bool, int | None]:
        """Returns (allowed, seconds_remaining_if_locked). Called BEFORE
        attempting a password check, so a locked-out caller never even
        pays the bcrypt cost - that is itself timing-neutral with respect
        to account existence, since the key is the submitted email
        regardless of whether it is registered."""
        now = time.monotonic()
        with self._lock:
            bucket = self._get_bucket(key, now)
            if bucket.locked_until is not None and now < bucket.locked_until:
                return False, int(bucket.locked_until - now) + 1
            return True, None

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._get_bucket(key, now)
            bucket.failures += 1
            if bucket.failures >= self.max_failures:
                bucket.locked_until = now + self.lockout_seconds

    def record_success(self, key: str) -> None:
        """A genuinely successful login clears the counter for that key -
        a legitimate user who mistyped a password a few times is not
        punished after they get it right."""
        with self._lock:
            self._buckets.pop(key, None)

    def reset_all(self) -> None:
        """Test/demo utility only - never called from request-handling code."""
        with self._lock:
            self._buckets.clear()


_default_limiter: LoginRateLimiter | None = None


def get_login_rate_limiter(settings=None) -> LoginRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        if settings is None:
            from app.config import get_settings
            settings = get_settings()
        _default_limiter = LoginRateLimiter(
            max_failures=settings.login_max_failures,
            window_seconds=settings.login_failure_window_seconds,
            lockout_seconds=settings.login_lockout_seconds,
        )
    return _default_limiter
