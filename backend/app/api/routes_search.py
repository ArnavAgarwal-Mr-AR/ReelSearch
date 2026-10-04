import logging
from fastapi import APIRouter, Query, HTTPException, status, Request
from fastapi.responses import JSONResponse
from app.models.schemas import SearchResponse, SearchEventRequest, ErrorResponse
from app.services.search_service import SearchService
from app.core.database import get_db_cursor
from app.core.config import settings
from app.core.redis_client import check_rate_limit

logger = logging.getLogger("reelsearch.api.search")
router = APIRouter(prefix="/search", tags=["Search"])


@router.get(
    "",
    summary="Natural language hybrid search for Instagram Reels (Max 4)",
    response_model=SearchResponse,
    responses={
        200: {"model": SearchResponse, "description": "High-confidence search results (maximum 4)"},
        400: {"model": ErrorResponse, "description": "Invalid query parameters"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"}
    }
)
def search_reels(
    request: Request,
    q: str = Query(..., min_length=2, max_length=500, description="Natural language search query"),
    limit: int = Query(4, ge=1, le=4, description="Maximum results to return (strictly capped at 4)")
):
    # 1. Rate limiting check (Section 49 & 116)
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not check_rate_limit(client_ip, max_requests=settings.SEARCH_RATE_LIMIT_PER_MINUTE, window_seconds=60):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Search rate limit exceeded. Please wait."}}
        )

    clean_query = q.strip()
    if len(clean_query) < 2:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": {"code": "QUERY_TOO_SHORT", "message": "Query must be at least 2 characters long."}}
        )

    try:
        response = SearchService.search(clean_query, limit=limit)
        return response
    except Exception as e:
        logger.exception(f"Search execution failed for query '{q}': {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": {"code": "SEARCH_FAILED", "message": "An error occurred during search processing."}}
        )


@router.post(
    "/events",
    summary="Record search interaction or click event (Section 67)",
    status_code=status.HTTP_201_CREATED
)
def record_search_event(request: Request, event: SearchEventRequest):
    client_ip = request.client.host if request.client else "127.0.0.1"
    try:
        sql = """
        INSERT INTO search_events (
            query, normalized_query, result_count, confidence, latency_ms, top_reel_id, clicked_reel_id, client_ip
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(
                sql,
                (
                    event.query,
                    event.query.lower().strip(),
                    event.result_count,
                    event.confidence,
                    event.latency_ms,
                    event.top_reel_id,
                    event.clicked_reel_id,
                    client_ip
                )
            )
        return {"status": "ok", "message": "Search event recorded."}
    except Exception as e:
        logger.debug(f"Failed to record search event: {e}")
        return {"status": "error", "message": str(e)}
