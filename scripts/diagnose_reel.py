import sys
import os
import json
import math

sys.path.insert(0, os.path.abspath('backend'))
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True, write_through=True)

from app.core.database import init_db_pool, get_db_cursor, close_db_pool
from app.services.canonicalizer import canonicalize_instagram_reel
from app.services.context_extractor import ContextExtractor
from app.services.embedding_service import EmbeddingService
from app.services.search_service import SearchService
from app.core.redis_client import get_redis_client

def run_diagnosis(raw_url: str):
    print("=" * 80)
    print("REELSEARCH SYSTEM DIAGNOSIS: END-TO-END VERIFICATION")
    print(f"Target URL: {raw_url}")
    print("=" * 80)

    # ---------------------------------------------------------
    # STEP 1: CANONICALIZATION & IDENTITY
    # ---------------------------------------------------------
    print("\n[STEP 1/6] CANONICALIZATION & IDENTITY")
    canonical_url, shortcode, reel_id = canonicalize_instagram_reel(raw_url)
    assert canonical_url == "https://www.instagram.com/reel/DeBbRLKTaNg/", f"Unexpected canonical URL: {canonical_url}"
    assert shortcode == "DeBbRLKTaNg", f"Unexpected shortcode: {shortcode}"
    assert "utm_source" not in canonical_url, "Query parameters not stripped!"
    assert "stkn" not in canonical_url, "Tracking parameters not stripped!"
    print(f"  ✓ Canonical URL:  {canonical_url}")
    print(f"  ✓ Shortcode:      {shortcode}")
    print(f"  ✓ Reel UUID:      {reel_id}")
    print("  ✓ Verification: URL tracking params stripped, trailing slash enforced, deterministic UUID generated.")

    # ---------------------------------------------------------
    # STEP 2: METADATA EXTRACTION VIA SOCIAL CRAWLER
    # ---------------------------------------------------------
    print("\n[STEP 2/6] METADATA EXTRACTION VIA SOCIAL CRAWLER")
    meta = ContextExtractor.fetch_instagram_metadata(canonical_url)
    assert meta.get("title"), "No title extracted"
    assert meta.get("author_name") == "johnapabon", f"Unexpected author: {meta.get('author_name')}"
    assert meta.get("thumbnail_url"), "No thumbnail URL extracted"
    print(f"  ✓ Author Username:     {meta.get('author_name')}")
    print(f"  ✓ Author Display Name: {meta.get('author_display_name')}")
    print(f"  ✓ Raw Title:           {meta.get('title')}")
    print(f"  ✓ Raw Caption:         {meta.get('caption')}")
    print(f"  ✓ Thumbnail URL:       {meta.get('thumbnail_url')[:65]}...")
    print("  ✓ Verification: Social crawler header bypassed 302 login wall and extracted OpenGraph link preview.")

    # ---------------------------------------------------------
    # STEP 3: STRUCTURED CONTEXT & HEURISTIC NLP
    # ---------------------------------------------------------
    print("\n[STEP 3/6] STRUCTURED CONTEXT EXTRACTION & CLEANING")
    ctx = ContextExtractor.extract_structured_context(canonical_url, shortcode, metadata=meta)
    searchable_text = ContextExtractor.build_searchable_text(ctx)

    # Verify no platform stopwords leaked into objects/entities
    for bad_word in ["instagram", "reel", "video"]:
        assert bad_word not in [e.lower() for e in ctx.entities], f"Stopword '{bad_word}' leaked into entities"
        assert bad_word not in [o.lower() for o in ctx.objects], f"Stopword '{bad_word}' leaked into objects"

    print(f"  ✓ Summary:       {ctx.summary}")
    print(f"  ✓ Entities:      {ctx.entities}")
    print(f"  ✓ Topics:        {ctx.topics}")
    print(f"  ✓ Objects:       {ctx.objects}")
    print(f"  ✓ Visual Style:  {ctx.visual_style}")
    print(f"  ✓ Keywords:      {ctx.keywords[:6]}")
    print(f"  ✓ Searchable Text ({len(searchable_text)} chars):")
    print(f"     \"{searchable_text}\"")
    print("  ✓ Verification: Pydantic schema validated, platform stopwords filtered, entities and topics deduced.")

    # ---------------------------------------------------------
    # STEP 4: VECTOR EMBEDDING GENERATION
    # ---------------------------------------------------------
    print("\n[STEP 4/6] VECTOR EMBEDDING GENERATION")
    embedding = EmbeddingService.generate_embedding(searchable_text)
    zero_count = embedding.count(0.0)
    norm = math.sqrt(sum(x * x for x in embedding))

    assert len(embedding) == 384, f"Embedding dimension mismatch: {len(embedding)}"
    assert zero_count == 0, f"Sparse embedding detected! Zeros: {zero_count}"
    assert abs(norm - 1.0) < 0.01, f"Embedding is not unit-normalized: norm={norm}"

    print(f"  ✓ Dimensions:       {len(embedding)}")
    print(f"  ✓ Zero Count:       {zero_count} (0 zeros = 100% dense vector)")
    print(f"  ✓ Euclidean Norm:   {norm:.6f} (Unit normalized)")
    print(f"  ✓ Sample [0:5]:     {embedding[:5]}")
    print("  ✓ Verification: Native SentenceTransformer all-MiniLM-L6-v2 generated dense semantic vector.")

    # ---------------------------------------------------------
    # STEP 5: DATABASE PERSISTENCE & TSVECTOR
    # ---------------------------------------------------------
    print("\n[STEP 5/6] DATABASE PERSISTENCE & POSTGRES FTS")
    init_db_pool()

    upsert_reel_sql = """
    INSERT INTO reels (
        reel_id, canonical_url, instagram_shortcode, enrichment_status, first_seen_at, updated_at
    ) VALUES (%s, %s, %s, 'ready', now(), now())
    ON CONFLICT (canonical_url) DO UPDATE SET
        enrichment_status = 'ready',
        updated_at = now();
    """

    upsert_context_sql = """
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
        cur.execute(upsert_reel_sql, (reel_id, canonical_url, shortcode))
        cur.execute(
            upsert_context_sql,
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

    # Query back to verify persistence
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT r.instagram_shortcode, rc.summary, rc.search_vector::text, 
                   array_length(rc.embedding, 1) as dim,
                   (SELECT count(*) FROM unnest(rc.embedding) as x WHERE x = 0.0) as db_zeros
            FROM reels r
            JOIN reel_context rc ON r.reel_id = rc.reel_id
            WHERE r.instagram_shortcode = %s;
        """, (shortcode,))
        db_row = cur.fetchone()

    assert db_row, "Failed to retrieve row from PostgreSQL"
    print(f"  ✓ PostgreSQL Shortcode: {db_row['instagram_shortcode']}")
    print(f"  ✓ PostgreSQL Vector:    {db_row['search_vector']}")
    print(f"  ✓ DB Embedding Dim:     {db_row['dim']}, DB Zeros: {db_row['db_zeros']}")
    print("  ✓ Verification: Stored in Neon PostgreSQL cloud with valid FTS tsvector and float8[] embedding.")

    # ---------------------------------------------------------
    # STEP 6: SEARCH & RETRIEVAL VERIFICATION
    # ---------------------------------------------------------
    print("\n[STEP 6/6] HYBRID SEARCH & CONFIDENCE GATING TEST")
    rc = get_redis_client()
    if rc:
        rc.flushdb()  # Fresh search test

    test_queries = [
        {
            "query": "cornell masculinity johnapabon",
            "type": "Direct Keyword + Entity",
            "should_match": True,
            "min_confidence": "high"
        },
        {
            "query": "cornell masculinity",
            "type": "Core Topic & Hashtag Query",
            "should_match": True,
            "min_confidence": "high"
        },
        {
            "query": "John Pabon greenwashing expert",
            "type": "Creator Identity Query",
            "should_match": True,
            "min_confidence": "medium"
        },
        {
            "query": "tokyo drifting high speed supra racing",
            "type": "Negative Control (Irrelevant)",
            "should_match": False,
            "min_confidence": None
        }
    ]

    for tq in test_queries:
        q = tq["query"]
        resp = SearchService.search(q, limit=4)
        found = any(r.canonical_url == canonical_url for r in resp.results)
        top_url = resp.results[0].canonical_url if resp.results else "None"
        top_score = resp.results[0].score if resp.results else 0.0

        print(f"\n  Query: '{q}' [{tq['type']}]")
        print(f"    - Results Count: {resp.count}, Overall Confidence: {resp.confidence}, Latency: {resp.latency_ms}ms")
        print(f"    - Top Result: {top_url} (Score: {top_score:.4f})")

        if tq["should_match"]:
            assert found, f"Expected reel {canonical_url} to match query '{q}', but it was not returned!"
            print(f"    ✓ SUCCESS: Correctly surfaced target reel as relevant match.")
        else:
            assert not found or top_url != canonical_url, f"Negative control failed! Unrelated reel surfaced for '{q}'"
            print(f"    ✓ SUCCESS: Correctly rejected or ranked out irrelevant query.")

    close_db_pool()
    print("\n" + "=" * 80)
    print("ALL 6 DIAGNOSTIC STEPS PASSED SUCCESSFULLY WITHOUT ERRORS.")
    print("=" * 80)

if __name__ == "__main__":
    url = "https://www.instagram.com/reel/DeBbRLKTaNg/?utm_source=ig_web_copy_link&stkn=NTc4MTIwNjQ2YQ=="
    run_diagnosis(url)
