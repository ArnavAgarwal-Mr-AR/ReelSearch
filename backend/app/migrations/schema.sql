-- Instagram Reel Discovery & Semantic Indexing Platform
-- Database Schema as specified in Sections 8, 9, 10, 93, 102

-- Enable pgcrypto for UUIDs if available
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Reels Table (Section 9.1)
CREATE TABLE IF NOT EXISTS reels (
    reel_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_url TEXT NOT NULL UNIQUE,
    instagram_shortcode TEXT NOT NULL UNIQUE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    enrichment_status TEXT NOT NULL DEFAULT 'pending',
    enrichment_attempts INTEGER NOT NULL DEFAULT 0,
    last_enrichment_error TEXT,
    CHECK (
        enrichment_status IN (
            'pending',
            'processing',
            'ready',
            'retrying',
            'failed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_reels_status ON reels(enrichment_status);
CREATE INDEX IF NOT EXISTS idx_reels_shortcode ON reels(instagram_shortcode);

-- 2. Reel Context Table (Section 10)
CREATE TABLE IF NOT EXISTS reel_context (
    reel_id UUID PRIMARY KEY REFERENCES reels(reel_id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    objects JSONB NOT NULL DEFAULT '[]'::jsonb,
    actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    entities JSONB NOT NULL DEFAULT '[]'::jsonb,
    topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    environments JSONB NOT NULL DEFAULT '[]'::jsonb,
    visual_style JSONB NOT NULL DEFAULT '[]'::jsonb,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    searchable_text TEXT NOT NULL,
    embedding FLOAT8[] DEFAULT NULL,
    context_version INTEGER NOT NULL DEFAULT 1,
    model_version TEXT NOT NULL DEFAULT 'reel-context-v1',
    embedding_model_version TEXT NOT NULL DEFAULT 'all-MiniLM-L6-v2',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_vector tsvector
);

-- Full text search index on search_vector (Section 20)
CREATE INDEX IF NOT EXISTS idx_reel_context_search_vector ON reel_context USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_reel_context_entities ON reel_context USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_reel_context_topics ON reel_context USING GIN(topics);

-- 3. Ingestion Jobs / Outbox Table (Section 93 & 102)
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reel_id UUID NOT NULL REFERENCES reels(reel_id) ON DELETE CASCADE,
    job_type TEXT NOT NULL DEFAULT 'GENERATE_REEL_CONTEXT',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    last_error TEXT,
    locked_at TIMESTAMPTZ,
    locked_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        status IN (
            'pending',
            'processing',
            'completed',
            'failed'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_status_attempt ON ingestion_jobs(status, attempt);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_reel_id ON ingestion_jobs(reel_id);

-- 4. Search Events Table (Section 67)
CREATE TABLE IF NOT EXISTS search_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL DEFAULT 'low',
    latency_ms FLOAT NOT NULL DEFAULT 0.0,
    top_reel_id UUID,
    clicked_reel_id UUID,
    client_ip TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_events_created_at ON search_events(created_at);

-- Cosine similarity helper function for float8 arrays
CREATE OR REPLACE FUNCTION cosine_similarity(a FLOAT8[], b FLOAT8[])
RETURNS FLOAT8 AS $$
DECLARE
    dot FLOAT8 := 0.0;
    norm_a FLOAT8 := 0.0;
    norm_b FLOAT8 := 0.0;
    dim INTEGER;
    i INTEGER;
BEGIN
    IF a IS NULL OR b IS NULL THEN
        RETURN 0.0;
    END IF;
    dim := array_length(a, 1);
    IF dim IS NULL OR dim != array_length(b, 1) THEN
        RETURN 0.0;
    END IF;
    FOR i IN 1..dim LOOP
        dot := dot + (a[i] * b[i]);
        norm_a := norm_a + (a[i] * a[i]);
        norm_b := norm_b + (b[i] * b[i]);
    END LOOP;
    IF norm_a = 0.0 OR norm_b = 0.0 THEN
        RETURN 0.0;
    END IF;
    RETURN dot / (sqrt(norm_a) * sqrt(norm_b));
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
