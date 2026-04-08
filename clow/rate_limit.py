"""Rate limiting -- per IP, per user (plan-based), and per tenant."""

import time
from collections import defaultdict
from typing import NamedTuple


class RateLimit(NamedTuple):
    requests: int
    window_seconds: int


# Plan-based limits aligned with subscription tiers
PLAN_LIMITS = {
    "free": RateLimit(20, 3600),          # 20/hour
    "lite": RateLimit(60, 3600),          # 60/hour
    "starter": RateLimit(120, 3600),      # 120/hour
    "pro": RateLimit(200, 3600),          # 200/hour
    "business": RateLimit(400, 3600),     # 400/hour
    "unlimited": RateLimit(2000, 3600),   # 2000/hour
    "admin": RateLimit(9999, 3600),       # effectively unlimited
}

# Token limits per day (aligned with database.py pricing)
PLAN_TOKEN_LIMITS = {
    "free": 500_000,
    "lite": 1_800_000,
    "starter": 2_150_000,
    "pro": 3_000_000,
    "business": 4_800_000,
    "unlimited": 999_999_999,
    "admin": 999_999_999,
}

IP_LIMIT = RateLimit(60, 60)       # 60/minute per IP (DDoS protection)
WS_LIMIT = RateLimit(10, 60)       # 10/minute per IP (WebSocket)
BURST_LIMIT = RateLimit(10, 10)    # 10/10s burst protection per user


class RateLimiter:
    """Sliding window rate limiter with IP, user, and burst protection."""

    def __init__(self):
        self._ip_hits: dict[str, list[float]] = defaultdict(list)
        self._user_hits: dict[str, list[float]] = defaultdict(list)
        self._burst_hits: dict[str, list[float]] = defaultdict(list)
        self._ws_hits: dict[str, list[float]] = defaultdict(list)

    def _clean(self, hits: list[float], window: int) -> list[float]:
        cutoff = time.time() - window
        return [t for t in hits if t > cutoff]

    def check_ip(self, ip: str) -> tuple[bool, int]:
        """Check IP rate limit. Returns (allowed, remaining)."""
        now = time.time()
        self._ip_hits[ip] = self._clean(self._ip_hits[ip], IP_LIMIT.window_seconds)
        remaining = IP_LIMIT.requests - len(self._ip_hits[ip])
        if remaining <= 0:
            return False, 0
        self._ip_hits[ip].append(now)
        return True, remaining - 1

    def check_ws(self, ip: str) -> tuple[bool, int]:
        """Check WebSocket rate limit."""
        now = time.time()
        self._ws_hits[ip] = self._clean(self._ws_hits[ip], WS_LIMIT.window_seconds)
        remaining = WS_LIMIT.requests - len(self._ws_hits[ip])
        if remaining <= 0:
            return False, 0
        self._ws_hits[ip].append(now)
        return True, remaining - 1

    def check_user(self, user_id: str, plan: str = "free") -> tuple[bool, int]:
        """Check user rate limit based on plan. Returns (allowed, remaining)."""
        limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
        now = time.time()
        self._user_hits[user_id] = self._clean(self._user_hits[user_id], limit.window_seconds)
        remaining = limit.requests - len(self._user_hits[user_id])
        if remaining <= 0:
            return False, 0
        self._user_hits[user_id].append(now)
        return True, remaining - 1

    def check_burst(self, user_id: str) -> tuple[bool, int]:
        """Anti-burst: max 10 requests per 10 seconds per user."""
        now = time.time()
        self._burst_hits[user_id] = self._clean(self._burst_hits[user_id], BURST_LIMIT.window_seconds)
        remaining = BURST_LIMIT.requests - len(self._burst_hits[user_id])
        if remaining <= 0:
            return False, 0
        self._burst_hits[user_id].append(now)
        return True, remaining - 1

    def check(self, ip: str, user_id: str = "", plan: str = "free") -> tuple[bool, int]:
        """Check IP, user, and burst limits. Returns (allowed, min_remaining)."""
        ip_ok, ip_rem = self.check_ip(ip)
        if not ip_ok:
            return False, 0
        if user_id:
            burst_ok, _ = self.check_burst(user_id)
            if not burst_ok:
                return False, 0
            user_ok, user_rem = self.check_user(user_id, plan)
            if not user_ok:
                return False, 0
            return True, min(ip_rem, user_rem)
        return True, ip_rem

    def get_token_limit(self, plan: str) -> int:
        """Get daily token limit for a plan."""
        return PLAN_TOKEN_LIMITS.get(plan, PLAN_TOKEN_LIMITS["free"])


# ── Redis-backed rate limiter (optional) ─────────────────────

class RedisRateLimiter:
    """Rate limiter using Redis INCR + EXPIRE for persistence across restarts."""

    def __init__(self, redis_url: str):
        import redis as _redis
        self._r = _redis.from_url(redis_url, decode_responses=True)

    def _check(self, key: str, limit: RateLimit) -> tuple[bool, int]:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, limit.window_seconds)
        results = pipe.execute()
        count = results[0]
        remaining = max(0, limit.requests - count)
        return count <= limit.requests, remaining

    def check_ip(self, ip: str) -> tuple[bool, int]:
        return self._check(f"rl:ip:{ip}", IP_LIMIT)

    def check_ws(self, ip: str) -> tuple[bool, int]:
        return self._check(f"rl:ws:{ip}", WS_LIMIT)

    def check_user(self, user_id: str, plan: str = "free") -> tuple[bool, int]:
        limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
        return self._check(f"rl:user:{user_id}", limit)

    def check_burst(self, user_id: str) -> tuple[bool, int]:
        return self._check(f"rl:burst:{user_id}", BURST_LIMIT)

    def check(self, ip: str, user_id: str = "", plan: str = "free") -> tuple[bool, int]:
        ip_ok, ip_rem = self.check_ip(ip)
        if not ip_ok:
            return False, 0
        if user_id:
            burst_ok, _ = self.check_burst(user_id)
            if not burst_ok:
                return False, 0
            user_ok, user_rem = self.check_user(user_id, plan)
            if not user_ok:
                return False, 0
            return True, min(ip_rem, user_rem)
        return True, ip_rem

    def get_token_limit(self, plan: str) -> int:
        return PLAN_TOKEN_LIMITS.get(plan, PLAN_TOKEN_LIMITS["free"])


# Global instance — uses Redis if available, otherwise in-memory
def _create_limiter():
    import os
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            rl = RedisRateLimiter(redis_url)
            rl._r.ping()
            return rl
        except Exception:
            pass
    return RateLimiter()


limiter = _create_limiter()
