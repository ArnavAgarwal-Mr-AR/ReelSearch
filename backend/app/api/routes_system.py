import logging
import time
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from app.core.database import get_db_cursor
from app.core.redis_client import get_redis_client

logger = logging.getLogger("reelsearch.api.system")
router = APIRouter(tags=["System"])


@router.get("/health", summary="Basic liveness check")
async def health_check():
    return {"status": "ok", "timestamp": time.time()}


@router.get("/ready", summary="Readiness check for PostgreSQL and Redis")
async def readiness_check():
    pg_ready = False
    redis_ready = False

    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1;")
            pg_ready = True
    except Exception as e:
        logger.error(f"Readiness check failed for PostgreSQL: {e}")

    try:
        r = get_redis_client()
        if r:
            redis_ready = r.ping()
        else:
            redis_ready = True  # In-memory fallback available
    except Exception as e:
        logger.warning(f"Readiness check Redis issue: {e}")
        redis_ready = False

    is_ready = pg_ready
    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if is_ready else "not_ready",
            "postgres": pg_ready,
            "redis": redis_ready,
            "timestamp": time.time()
        }
    )


@router.get("/api/v1/stats", summary="Platform telemetry and index stats")
async def platform_stats():
    stats = {
        "total_reels": 0,
        "ready_reels": 0,
        "pending_reels": 0,
        "pending_jobs": 0,
        "total_searches": 0
    }
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT count(*) as cnt FROM reels;")
            stats["total_reels"] = cursor.fetchone()["cnt"]

            cursor.execute("SELECT count(*) as cnt FROM reels WHERE enrichment_status = 'ready';")
            stats["ready_reels"] = cursor.fetchone()["cnt"]

            cursor.execute("SELECT count(*) as cnt FROM reels WHERE enrichment_status IN ('pending', 'processing');")
            stats["pending_reels"] = cursor.fetchone()["cnt"]

            cursor.execute("SELECT count(*) as cnt FROM ingestion_jobs WHERE status IN ('pending', 'processing');")
            stats["pending_jobs"] = cursor.fetchone()["cnt"]

            cursor.execute("SELECT count(*) as cnt FROM search_events;")
            stats["total_searches"] = cursor.fetchone()["cnt"]
    except Exception as e:
        logger.error(f"Failed to fetch stats: {e}")

    return stats
