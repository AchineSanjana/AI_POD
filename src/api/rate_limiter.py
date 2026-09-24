"""In-memory sliding-window rate limiter for multi-tenant API protection.

Protects shared API resources by enforcing configurable requests-per-minute
limits per tenant and scope. Returns 429 Too Many Requests with a Retry-After header
when a limit is exceeded.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from threading import Lock
from typing import NamedTuple

from fastapi import Depends, HTTPException

from src.api.auth import get_current_tenant
from src.utils.config import get_tenant_rate_limit


class RateLimitResult(NamedTuple):
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._history: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    def check(
        self,
        tenant_id: str,
        scope: str = "recommendations",
        custom_limit: int | None = None,
        now: float | None = None,
    ) -> RateLimitResult:
        """Evaluate request against tenant's sliding-window rate limit."""
        current_time = time.time() if now is None else now
        limit = (
            custom_limit
            if custom_limit is not None
            else get_tenant_rate_limit(tenant_id, scope=scope)
        )

        key = (tenant_id, scope)
        cutoff = current_time - self.window_seconds

        with self._lock:
            if key not in self._history:
                self._history[key] = deque()

            history = self._history[key]

            # Purge timestamps outside the sliding window
            while history and history[0] <= cutoff:
                history.popleft()

            if len(history) >= limit:
                oldest = history[0]
                retry_after = max(1, math.ceil(oldest + self.window_seconds - current_time))
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    retry_after=retry_after,
                )

            history.append(current_time)
            remaining = max(0, limit - len(history))
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=remaining,
                retry_after=0,
            )

    def reset(self, tenant_id: str | None = None, scope: str | None = None) -> None:
        """Reset history, useful between unit tests."""
        with self._lock:
            if tenant_id is None and scope is None:
                self._history.clear()
            else:
                to_delete = [
                    k
                    for k in self._history
                    if (tenant_id is None or k[0] == tenant_id)
                    and (scope is None or k[1] == scope)
                ]
                for k in to_delete:
                    del self._history[k]


# Global shared in-memory rate limiter instance
RATE_LIMITER = InMemoryRateLimiter(window_seconds=60.0)


def check_rate_limit(
    scope: str = "recommendations",
    limiter: InMemoryRateLimiter | None = None,
) -> Callable[..., str]:
    """FastAPI dependency factory enforcing rate limits on authenticated tenants."""
    active_limiter = limiter or RATE_LIMITER

    def dependency(tenant_id: str = Depends(get_current_tenant)) -> str:
        result = active_limiter.check(tenant_id=tenant_id, scope=scope)
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded for tenant '{tenant_id}'. "
                    f"Max {result.limit} requests per minute allowed for {scope}."
                ),
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        return tenant_id

    return dependency
