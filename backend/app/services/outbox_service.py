import logging
import json
import uuid
from typing import Optional, Dict, Any
from app.core.database import get_db_cursor

logger = logging.getLogger("reelsearch.outbox")


class OutboxService:
    @staticmethod
    def enqueue_context_generation_job(reel_id: str, payload: Optional[Dict[str, Any]] = None, cursor: Optional[Any] = None) -> str:
        """
        Inserts a job record into ingestion_jobs within the database transaction.
        Returns job_id UUID.
        """
        payload_data = payload or {}
        job_id = str(uuid.uuid4())
        sql = """
        INSERT INTO ingestion_jobs (job_id, reel_id, job_type, payload, status, attempt, max_attempts)
        VALUES (%s, %s, 'GENERATE_REEL_CONTEXT', %s::jsonb, 'pending', 0, 5)
        RETURNING job_id;
        """
        if cursor is not None:
            cursor.execute(sql, (job_id, reel_id, json.dumps(payload_data)))
            row = cursor.fetchone()
            return str(row["job_id"])

        with get_db_cursor(commit=True) as cur:
            cur.execute(sql, (job_id, reel_id, json.dumps(payload_data)))
            row = cur.fetchone()
            return str(row["job_id"])

    @staticmethod
    def claim_next_job(worker_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically claims a pending or retrying job for processing using FOR UPDATE SKIP LOCKED.
        """
        claim_sql = """
        UPDATE ingestion_jobs
        SET status = 'processing',
            locked_at = now(),
            locked_by = %s,
            attempt = attempt + 1,
            updated_at = now()
        WHERE job_id = (
            SELECT job_id
            FROM ingestion_jobs
            WHERE status IN ('pending', 'retrying')
              AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
              AND attempt < max_attempts
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING job_id, reel_id, job_type, payload, attempt;
        """
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(claim_sql, (worker_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    @staticmethod
    def mark_job_completed(job_id: str):
        sql = """
        UPDATE ingestion_jobs
        SET status = 'completed',
            locked_at = NULL,
            locked_by = NULL,
            updated_at = now()
        WHERE job_id = %s;
        """
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(sql, (job_id,))

    @staticmethod
    def mark_job_failed(job_id: str, error_message: str, final_failure: bool = False):
        new_status = 'failed' if final_failure else 'retrying'
        sql = """
        UPDATE ingestion_jobs
        SET status = %s,
            last_error = %s,
            locked_at = NULL,
            locked_by = NULL,
            updated_at = now()
        WHERE job_id = %s;
        """
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(sql, (new_status, error_message, job_id))
