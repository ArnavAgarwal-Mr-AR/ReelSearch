import logging
import json
import time
from typing import Optional, Any
from app.core.config import settings

logger = logging.getLogger("reelsearch.redis")

_redis_conn = None
_in_memory_cache = {}
_in_memory_rate_limit = {}


def get_redis_client():
    global _redis_conn
    if not settings.REDIS_ENABLED:
        return None
    if _redis_conn is None:
        try:
            import redis
            _redis_conn = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0
            )
            _redis_conn.ping()
            logger.info("Connected to Redis server.")
        except Exception as e:
            logger.warning(f"Redis unavailable, falling back to in-memory cache: {e}")
            _redis_conn = None
    return _redis_conn


def cache_get(key: str) -> Optional[Any]:
    global _redis_conn
    client = get_redis_client()
    if client:
        try:
            val = client.get(key)
            if val is not None:
                return json.loads(val)
        except Exception as e:
            logger.warning(f"Redis get failed, falling back to memory: {e}")
            _redis_conn = None

    # In-memory fallback with expiration check
    item = _in_memory_cache.get(key)
    if item:
        data, exp = item
        if exp is None or exp > time.time():
            return data
        else:
            del _in_memory_cache[key]
    return None


def cache_set(key: str, value: Any, ttl_seconds: Optional[int] = None):
    global _redis_conn
    if ttl_seconds is None:
        ttl_seconds = settings.REDIS_CACHE_TTL_SECONDS
    client = get_redis_client()
    if client:
        try:
            client.setex(key, ttl_seconds, json.dumps(value))
            return
        except Exception as e:
            logger.warning(f"Redis set failed (possible memory pressure or disconnect): {e}")
            _redis_conn = None

    # In-memory fallback (bounded to 500 entries to prevent memory leak)
    if len(_in_memory_cache) > 500:
        # Prune expired or oldest
        now = time.time()
        expired = [k for k, (_, exp) in _in_memory_cache.items() if exp and exp <= now]
        for k in expired[:100]:
            del _in_memory_cache[k]
        if len(_in_memory_cache) > 500:
            _in_memory_cache.clear()

    _in_memory_cache[key] = (value, time.time() + ttl_seconds)


def check_rate_limit(client_ip: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """Returns True if within rate limit, False if exceeded."""
    global _redis_conn
    key = f"rl:{client_ip}"
    client = get_redis_client()
    if client:
        try:
            current = client.incr(key)
            if current == 1:
                client.expire(key, window_seconds)
            return current <= max_requests
        except Exception as e:
            logger.warning(f"Redis rate limit check error: {e}")
            _redis_conn = None

    # In-memory rate limiting fallback (bounded to 500 IPs)
    now = time.time()
    if len(_in_memory_rate_limit) > 500:
        _in_memory_rate_limit.clear()

    req_history = _in_memory_rate_limit.setdefault(client_ip, [])
    # Filter requests within current window
    _in_memory_rate_limit[client_ip] = [ts for ts in req_history if ts > now - window_seconds]
    if len(_in_memory_rate_limit[client_ip]) >= max_requests:
        return False
    _in_memory_rate_limit[client_ip].append(now)
    return True
