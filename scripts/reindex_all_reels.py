import sys
import os
import json
import logging

sys.path.insert(0, os.path.abspath('backend'))

# Bypass broken Windows torchvision nms operator registration
sys.modules['torchvision'] = None
sys.modules['torchvision.transforms'] = None

from app.core.database import init_db_pool, get_db_cursor, close_db_pool
from app.services.context_extractor import ContextExtractor
from app.services.embedding_service import EmbeddingService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reindex")

def reindex():
    init_db_pool()
    with get_db_cursor() as cur:
        cur.execute("SELECT reel_id, canonical_url, instagram_shortcode FROM reels;")
        reels = cur.fetchall()

    logger.info(f"Found {len(reels)} reel(s) to re-index.")

    for r in reels:
        reel_id = str(r["reel_id"])
        url = r["canonical_url"]
        shortcode = r["instagram_shortcode"]
        logger.info(f"Re-indexing {shortcode} ({url})...")

        meta = ContextExtractor.fetch_instagram_metadata(url)
        logger.info(f"  Title: {meta.get('title')[:60] if meta.get('title') else 'N/A'}")
        logger.info(f"  Author: {meta.get('author_name')}")
        logger.info(f"  Caption len: {len(meta.get('caption', ''))}")

        ctx = ContextExtractor.extract_structured_context(url, shortcode, metadata=meta)
        searchable_text = ContextExtractor.build_searchable_text(ctx)
        logger.info(f"  Summary: {ctx.summary[:80]}")
        logger.info(f"  Entities: {ctx.entities}")
        logger.info(f"  Topics: {ctx.topics}")
        logger.info(f"  Objects: {ctx.objects[:5]}")
        logger.info(f"  Searchable text sample: {searchable_text[:120]}...")

        embedding = EmbeddingService.generate_embedding(searchable_text)
        logger.info(f"  Embedding generated (dim={len(embedding)}, zero_count={embedding.count(0.0)})")

        upsert_sql = """
        INSERT INTO reel_context (
            reel_id, summary, objects, actions, entities, topics, environments,
            visual_style, keywords, searchable_text, embedding, context_version,
            model_version, embedding_model_version, search_vector, generated_at, updated_at
        ) VALUES (
            %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
            %s::jsonb, %s::jsonb, %s, %s::float8[], 1, 'reel-context-v2', 'all-MiniLM-L6-v2',
            to_tsvector('english', %s), now(), now()
        )
        ON CONFLICT (reel_id) DO UPDATE SET
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
            search_vector = EXCLUDED.search_vector,
            context_version = reel_context.context_version + 1,
            updated_at = now();
        """

        with get_db_cursor(commit=True) as cur:
            cur.execute(
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
                    searchable_text
                )
            )
            cur.execute(
                "UPDATE reels SET enrichment_status = 'ready', last_enrichment_error = NULL, updated_at = now() WHERE reel_id = %s;",
                (reel_id,)
            )

        logger.info(f"Re-indexed {shortcode} successfully!\n")

    close_db_pool()
    logger.info("All reels re-indexed successfully.")

if __name__ == "__main__":
    reindex()
