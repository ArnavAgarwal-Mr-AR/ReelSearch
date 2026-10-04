import os
import time
import json
import logging
import uuid
from typing import Optional
from app.core.database import get_db_cursor
from app.services.outbox_service import OutboxService
from app.services.context_extractor import ContextExtractor
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger("reelsearch.worker")


class ContextWorker:
    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.running = False

    def process_one_job(self) -> bool:
        """
        Pulls and processes a single job from the outbox queue.
        Returns True if a job was found and processed, False if queue was empty.
        """
        job = OutboxService.claim_next_job(self.worker_id)
        if not job:
            return False

        job_id = str(job["job_id"])
        reel_id = str(job["reel_id"])
        attempt = job.get("attempt", 1)
        logger.info(f"[{self.worker_id}] Claimed job {job_id} for reel {reel_id} (attempt {attempt})")

        try:
            # 1. Fetch Reel details
            reel_record = None
            with get_db_cursor() as cursor:
                cursor.execute(
                    "SELECT reel_id, canonical_url, instagram_shortcode FROM reels WHERE reel_id = %s;",
                    (reel_id,)
                )
                reel_record = cursor.fetchone()

            if not reel_record:
                logger.error(f"Reel {reel_id} not found in database. Failing job.")
                OutboxService.mark_job_failed(job_id, "Reel not found", final_failure=True)
                return True

            canonical_url = reel_record["canonical_url"]
            shortcode = reel_record["instagram_shortcode"]

            # Update status to processing
            with get_db_cursor(commit=True) as cursor:
                cursor.execute(
                    "UPDATE reels SET enrichment_status = 'processing', enrichment_attempts = enrichment_attempts + 1, updated_at = now() WHERE reel_id = %s;",
                    (reel_id,)
                )

            # 2. Extract structured context
            ctx = ContextExtractor.extract_structured_context(canonical_url, shortcode)

            # 3. Generate flattened searchable text
            searchable_text = ContextExtractor.build_searchable_text(ctx)

            # 4. Generate dense vector embedding
            embedding = EmbeddingService.generate_embedding(searchable_text)

            # 5. Atomically persist context (Section 40 & 45)
            upsert_sql = """
            INSERT INTO reel_context (
                reel_id,
                summary,
                objects,
                actions,
                entities,
                topics,
                environments,
                visual_style,
                keywords,
                searchable_text,
                embedding,
                context_version,
                model_version,
                embedding_model_version,
                search_vector,
                generated_at,
                updated_at
            )
            VALUES (
                %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s::jsonb, %s, %s::float8[], 1, 'reel-context-v1', 'all-MiniLM-L6-v2',
                to_tsvector('english', %s), now(), now()
            )
            ON CONFLICT (reel_id)
            DO UPDATE SET
                summary = EXCLUDED.summary,
                objects = EXCLUDED.objects,
                actions = EXCLUDED.actions,
                entities = EXCLUDED.entities,
                topics = EXCLUDED.topics,
                environments = EXCLUDED.environments,
                visual_style = EXCLUDED.visual_style,
                keywords = EXCLUDED.keywords,
                searchable_text = EXCLUDED.searchable_text,
                embedding = EXCLUDED.embedding,
                context_version = reel_context.context_version + 1,
                search_vector = EXCLUDED.search_vector,
                updated_at = now();
            """

            with get_db_cursor(commit=True) as cursor:
                cursor.execute(
                    upsert_sql,
                    (
                        reel_id,
                        ctx.summary,
                        json.dumps(ctx.objects),
                        json.dumps(ctx.actions),
                        json.dumps(ctx.entities),
                        json.dumps(ctx.topics),
                        json.dumps(ctx.environments),
                        json.dumps(ctx.visual_style),
                        json.dumps(ctx.keywords),
                        searchable_text,
                        embedding,
                        searchable_text,
                    )
                )

                # Mark reel as ready
                cursor.execute(
                    "UPDATE reels SET enrichment_status = 'ready', last_enrichment_error = NULL, updated_at = now() WHERE reel_id = %s;",
                    (reel_id,)
                )

            # Mark job completed
            OutboxService.mark_job_completed(job_id)
            logger.info(f"[{self.worker_id}] Successfully enriched reel {reel_id} (shortcode: {shortcode})")
            return True

        except Exception as e:
            logger.exception(f"Error enriching reel {reel_id}: {e}")
            final_failure = attempt >= 5
            try:
                OutboxService.mark_job_failed(job_id, str(e), final_failure=final_failure)
                with get_db_cursor(commit=True) as cursor:
                    new_status = 'failed' if final_failure else 'retrying'
                    cursor.execute(
                        "UPDATE reels SET enrichment_status = %s, last_enrichment_error = %s, updated_at = now() WHERE reel_id = %s;",
                        (new_status, str(e), reel_id)
                    )
            except Exception as cleanup_err:
                logger.error(f"Failed to record job failure in database: {cleanup_err}")
            return True

    def start_loop(self, poll_interval: float = 1.0):
        """Continuously polls for and processes jobs."""
        logger.info(f"Starting ContextWorker loop [{self.worker_id}]...")
        self.running = True
        while self.running:
            try:
                processed = self.process_one_job()
                if not processed:
                    time.sleep(poll_interval)
            except KeyboardInterrupt:
                logger.info("Worker stopped by user.")
                break
            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                time.sleep(poll_interval * 2)

    def stop(self):
        self.running = False
