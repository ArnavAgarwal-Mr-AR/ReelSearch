import logging
import json
from fastapi import APIRouter, HTTPException, status, Request
from fastapi.responses import JSONResponse
from app.models.schemas import SaveReelRequest, SaveReelResponse, ReelStatusResponse, ErrorResponse
from app.services.canonicalizer import canonicalize_instagram_reel, CanonicalizationError
from app.services.outbox_service import OutboxService
from app.core.database import get_db_cursor
from app.core.config import settings
from app.core.redis_client import check_rate_limit

logger = logging.getLogger("reelsearch.api.reels")
router = APIRouter(prefix="/reels", tags=["Reels"])


@router.post(
    "",
    summary="Save and index an Instagram Reel",
    responses={
        200: {"model": SaveReelResponse, "description": "Reel already exists and is ready"},
        202: {"model": SaveReelResponse, "description": "Reel accepted for asynchronous indexing"},
        400: {"model": ErrorResponse, "description": "Invalid Instagram URL or parameter"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"}
    }
)
async def save_reel(request: Request, body: SaveReelRequest):
    # 1. Rate limiting check (Section 49 & 56)
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not check_rate_limit(client_ip, max_requests=settings.RATE_LIMIT_PER_MINUTE, window_seconds=60):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests, please slow down."}}
        )

    # 2. Strict URL validation and canonicalization (Section 6)
    try:
        canonical_url, shortcode, reel_id = canonicalize_instagram_reel(body.url)
    except CanonicalizationError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": {"code": e.code, "message": e.message}}
        )

    # 3. Check for existing Reel in database (Section 33 Idempotency)
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT reel_id, canonical_url, enrichment_status FROM reels WHERE canonical_url = %s;",
            (canonical_url,)
        )
        existing = cursor.fetchone()

        if existing:
            status_val = existing["enrichment_status"]
            existing_id = str(existing["reel_id"])

            if status_val == "ready":
                # Existing and ready -> 200 OK (Section 33)
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "reel_id": existing_id,
                        "canonical_url": existing["canonical_url"],
                        "status": "ready",
                        "created": False,
                        "message": "Reel is already indexed and searchable."
                    }
                )
            elif status_val == "failed":
                # Retry failed job
                cursor.execute(
                    "UPDATE reels SET enrichment_status = 'pending', enrichment_attempts = 0, last_enrichment_error = NULL WHERE reel_id = %s;",
                    (existing_id,)
                )
                OutboxService.enqueue_context_generation_job(existing_id, cursor=cursor)
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content={
                        "reel_id": existing_id,
                        "canonical_url": existing["canonical_url"],
                        "status": "processing",
                        "created": False,
                        "message": "Retrying context enrichment for previously failed Reel."
                    }
                )
            else:
                # Still processing -> 202 Accepted
                return JSONResponse(
                    status_code=status.HTTP_202_ACCEPTED,
                    content={
                        "reel_id": existing_id,
                        "canonical_url": existing["canonical_url"],
                        "status": "processing",
                        "created": False,
                        "message": "Reel context generation is currently in progress."
                    }
                )

        # 4. Insert new Reel record (Section 9)
        insert_sql = """
        INSERT INTO reels (reel_id, canonical_url, instagram_shortcode, enrichment_status)
        VALUES (%s, %s, %s, 'pending')
        RETURNING reel_id;
        """
        cursor.execute(insert_sql, (reel_id, canonical_url, shortcode))

        # 5. Transactionally enqueue outbox background job (Section 91 & 92)
        OutboxService.enqueue_context_generation_job(reel_id, cursor=cursor)

    logger.info(f"Accepted new Reel {canonical_url} (ID: {reel_id}) for processing.")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "reel_id": reel_id,
            "canonical_url": canonical_url,
            "status": "processing",
            "created": True,
            "message": "Reel accepted for enrichment."
        }
    )


@router.get(
    "/{reel_id}",
    summary="Get status and metadata for a specific Reel",
    response_model=ReelStatusResponse
)
async def get_reel_status(reel_id: str):
    sql = """
    SELECT
        r.reel_id,
        r.canonical_url,
        r.instagram_shortcode,
        r.enrichment_status,
        r.enrichment_attempts,
        r.last_enrichment_error,
        r.first_seen_at,
        r.updated_at,
        c.summary,
        c.objects,
        c.actions,
        c.entities,
        c.topics,
        c.environments,
        c.visual_style,
        c.keywords,
        c.context_version
    FROM reels r
    LEFT JOIN reel_context c ON c.reel_id = r.reel_id
    WHERE r.reel_id = %s;
    """
    with get_db_cursor() as cursor:
        cursor.execute(sql, (reel_id,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REEL_NOT_FOUND", "message": f"Reel with id {reel_id} does not exist."}
        )

    context_data = None
    if row.get("summary"):
        context_data = {
            "summary": row["summary"],
            "objects": row.get("objects") or [],
            "actions": row.get("actions") or [],
            "entities": row.get("entities") or [],
            "topics": row.get("topics") or [],
            "environments": row.get("environments") or [],
            "visual_style": row.get("visual_style") or [],
            "keywords": row.get("keywords") or [],
        }

    return ReelStatusResponse(
        reel_id=str(row["reel_id"]),
        canonical_url=row["canonical_url"],
        instagram_shortcode=row["instagram_shortcode"],
        status=row["enrichment_status"],
        enrichment_attempts=row["enrichment_attempts"],
        last_enrichment_error=row["last_enrichment_error"],
        context_version=row.get("context_version"),
        first_seen_at=str(row["first_seen_at"]) if row.get("first_seen_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        context=context_data
    )


@router.get(
    "",
    summary="List recent indexed Reels for exploration"
)
async def list_recent_reels(limit: int = 20):
    sql = """
    SELECT
        r.reel_id,
        r.canonical_url,
        r.instagram_shortcode,
        r.enrichment_status,
        r.updated_at,
        c.summary,
        c.topics,
        c.entities
    FROM reels r
    LEFT JOIN reel_context c ON c.reel_id = r.reel_id
    ORDER BY r.updated_at DESC
    LIMIT %s;
    """
    results = []
    with get_db_cursor() as cursor:
        cursor.execute(sql, (limit,))
        for row in cursor.fetchall():
            results.append({
                "reel_id": str(row["reel_id"]),
                "canonical_url": row["canonical_url"],
                "shortcode": row["instagram_shortcode"],
                "status": row["enrichment_status"],
                "summary": row.get("summary") or "Pending enrichment...",
                "topics": row.get("topics") or [],
                "entities": row.get("entities") or [],
                "updated_at": str(row["updated_at"])
            })
    return {"reels": results, "count": len(results)}
