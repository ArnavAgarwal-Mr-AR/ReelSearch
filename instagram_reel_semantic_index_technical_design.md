# Instagram Reel Discovery & Semantic Indexing Platform

## Technical Architecture, Data Model, Search Engine, APIs, Reliability, Security, and Operations

**Document status:** Target architecture / implementation specification\
**Scope:** Instagram Reels only\
**Client:** Web application\
**Primary design goal:** Given an Instagram Reel URL, build a rich
machine-generated representation of the Reel and make that
representation highly searchable. Given a natural-language search query,
retrieve the most relevant Reels and display at most four
high-confidence results.

------------------------------------------------------------------------

## 1. Executive Summary

This system is a self-hostable web-based platform for discovering and
bookmarking public Instagram Reels.

The system deliberately does **not** ask users to write descriptions. A
user submits an Instagram Reel URL and the platform creates the
searchable representation itself. This removes low-quality,
inconsistent, keyword-stuffed, or adversarial user descriptions from the
search index.

The central design idea is to separate three concepts:

1.  **Reel identity** --- determined exclusively by the canonical
    Instagram Reel URL.
2.  **Reel context** --- a structured, machine-generated representation
    of what the Reel contains.
3.  **Search representation** --- lexical text plus semantic embeddings
    derived from that context.

The resulting architecture is:

``` text
                         ┌──────────────────────┐
                         │      WEB CLIENT      │
                         │  React / Next.js UI  │
                         └──────────┬───────────┘
                                    │ HTTPS
                     ┌──────────────┴──────────────┐
                     │                             │
                 Save URL                       Search
                     │                             │
                     ▼                             ▼
             ┌──────────────┐             ┌─────────────────┐
             │  API Gateway │             │  Query Service  │
             └──────┬───────┘             └────────┬────────┘
                    │                              │
                    ▼                              ▼
             ┌──────────────┐              Query Understanding
             │ URL Validator│                      │
             └──────┬───────┘                      ▼
                    │                    ┌────────────────────┐
                    ▼                    │ Hybrid Retrieval   │
             Canonicalizer              │ FTS + Vector       │
                    │                    └─────────┬──────────┘
                    ▼                              │
              Reel Identity                         ▼
                    │                         Candidate Pool
                    ▼                              │
              PostgreSQL                           ▼
                    │                         Re-ranker
                    ▼                              │
               Job Queue                           ▼
                    │                         Confidence Gate
                    ▼                              │
             Context Worker                        ▼
                    │                           TOP 4
                    ├───────────────►              │
                    ▼                              │
             Reel Context                           │
                    │                              │
                    ├──────────────► Search Index ◄┘
                    │
                    ▼
             Embedding Model
```

The first version intentionally avoids Elasticsearch/OpenSearch.
PostgreSQL remains the system of record and provides relational storage,
full-text search, and pgvector semantic retrieval. pgvector supports
HNSW approximate nearest-neighbor indexes and explicitly documents
hybrid use with PostgreSQL full-text search and re-ranking strategies.
\[1\]

------------------------------------------------------------------------

# 2. Goals and Non-Goals

## 2.1 Goals

The system must:

-   Accept Instagram Reel URLs through a web UI.
-   Accept **only URLs** from users; users cannot supply searchable
    descriptions.
-   Canonicalize Instagram Reel URLs deterministically.
-   Treat two Reels as the same Reel **if their canonical URLs are
    identical**.
-   Generate structured Reel context automatically.
-   Store context in a queryable, versioned form.
-   Support both exact/lexical and semantic search.
-   Understand natural-language queries rather than relying on exact
    keywords.
-   Retrieve a sufficiently large internal candidate set.
-   Re-rank candidates for high precision.
-   Display no more than four results.
-   Avoid filling the UI with weak matches merely to reach four.
-   Return fewer than four results when the confidence threshold is not
    met.
-   Support asynchronous enrichment.
-   Make enrichment idempotent.
-   Recover from worker crashes and transient upstream failures.
-   Provide deterministic API contracts.
-   Protect the system from URL abuse, SSRF, resource exhaustion,
    injection, and cost attacks.
-   Provide observability for search quality and system health.
-   Remain deployable on a modest self-hosted infrastructure initially.
-   Support model and context-schema evolution without changing Reel
    identity.

## 2.2 Explicitly out of scope

The following are intentionally excluded from this architecture:

-   YouTube Shorts.
-   Other video platforms.
-   User-written Reel descriptions.
-   User-supplied arbitrary content descriptions.
-   Video hosting.
-   Video transcoding.
-   Serving the Reel video through this infrastructure.
-   Cross-platform duplicate identity.
-   Perceptual-hash based identity.
-   Automatic merging of different Instagram URLs.
-   Private/deleted-content lifecycle handling as a product concern.
-   Geo-restriction logic.
-   Content moderation and content-flagging workflows.

The source design previously included Instagram and YouTube, user
descriptions, perceptual hashing, moderation, and lazy dead-link
validation. This specification intentionally removes those pieces based
on the revised requirements.

------------------------------------------------------------------------

# 3. Core Architectural Principle

The system is not a "bookmark database with descriptions."

It is a **semantic index of Instagram Reels**.

The fundamental data flow is:

``` text
                  Instagram Reel URL
                           │
                           ▼
                  Canonical Reel URL
                           │
                           ▼
                     Reel Identity
                           │
                           ▼
              ┌────────────────────────┐
              │     Reel Context       │
              │                        │
              │ summary                │
              │ objects                │
              │ actions                │
              │ entities               │
              │ topics                 │
              │ environment            │
              │ style                  │
              │ keywords               │
              │ metadata               │
              └───────────┬────────────┘
                          │
                 ┌────────┴────────┐
                 ▼                 ▼
          Searchable text       Embedding
                 │                 │
                 ▼                 ▼
          PostgreSQL FTS        pgvector
                 │                 │
                 └────────┬────────┘
                          ▼
                   Hybrid Retrieval
                          │
                          ▼
                       Re-ranker
                          │
                          ▼
                   Confidence Gate
                          │
                          ▼
                    Maximum 4 UI
```

This architecture solves the central problem of the original design: the
quality of search is no longer dependent on whether a human happened to
write a good description.

------------------------------------------------------------------------

# 4. User Experience

The user interacts with a normal web application.

## 4.1 Saving a Reel

The UI contains a URL input:

``` text
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  Save an Instagram Reel                                   │
│                                                            │
│  ┌──────────────────────────────────────────────┐          │
│  │ https://www.instagram.com/reel/Cxyz123/      │          │
│  └──────────────────────────────────────────────┘          │
│                                                            │
│                         [ Save Reel ]                       │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

The user does not enter:

-   a title,
-   a description,
-   keywords,
-   categories,
-   tags.

The backend owns the searchable representation.

## 4.2 Searching

``` text
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  Search Reels                                             │
│                                                            │
│  ┌──────────────────────────────────────────────┐          │
│  │ red supra drifting on a mountain road       │ 🔍       │
│  └──────────────────────────────────────────────┘          │
│                                                            │
│  Results                                                   │
│                                                            │
│  ┌──────────────┐  ┌──────────────┐                       │
│  │   Reel #1    │  │   Reel #2    │                       │
│  └──────────────┘  └──────────────┘                       │
│                                                            │
│  ┌──────────────┐  ┌──────────────┐                       │
│  │   Reel #3    │  │   Reel #4    │                       │
│  └──────────────┘  └──────────────┘                       │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

The system may internally inspect dozens of candidates, but the web UI
displays **at most four**.

## 4.3 Dynamic Client-Side Search History (Zero Static Query Contamination)

The frontend interface strictly rejects static, hardcoded, or mock query chips (e.g. sample searches that pollute the discovery area or duplicate previous queries).

Instead, search discovery is governed by **dynamic, localized search tracking**:
1. **Dynamic LocalStorage Persistence**:
   Executed queries are sanitized and persisted to client browser storage (`localStorage` key: `reelsearch_recent_queries_v1`).
2. **De-duplication & Cap**:
   Queries are strictly deduplicated case-insensitively and capped at the 6 most recent searches.
3. **Clean Initial State**:
   If no searches have been performed, the recent queries section remains completely hidden from the viewport.
4. **Instant Re-execution**:
   Clicking a recent query chip immediately re-executes the search, utilizing the multi-tier L1/L2 cache for sub-40ms responses.

------------------------------------------------------------------------

# 5. Reel Identity

## 5.1 Identity rule

The system uses one strict rule:

> Two records represent the same Reel when their canonical Instagram
> Reel URLs are identical.

No visual similarity is used for identity.

No AI model decides whether two URLs are the same.

No perceptual hash decides whether two URLs are the same.

This produces a deterministic identity model.

``` text
URL A
  │
  ▼
canonicalize(A)
  │
  ▼
C

URL B
  │
  ▼
canonicalize(B)
  │
  ▼
C

C == C
  │
  ▼
Same Reel
```

If:

``` text
canonicalize(A) != canonicalize(B)
```

then they are separate Reel records.

------------------------------------------------------------------------

# 6. Instagram URL Canonicalization

Canonicalization is one of the most important correctness boundaries in
the system.

The objective is to remove URL syntax that does not identify the Reel
while preserving the Reel shortcode that does.

## 6.1 Accepted URL shape

The primary accepted public form is:

``` text
https://www.instagram.com/reel/{SHORTCODE}/
```

The canonicalizer may accept equivalent host/scheme/query variants, but
it emits exactly one normalized representation.

Example inputs:

``` text
https://www.instagram.com/reel/Cxyz123/
https://instagram.com/reel/Cxyz123/
https://www.instagram.com/reel/Cxyz123/?utm_source=share
https://www.instagram.com/reel/Cxyz123/?igsh=abcdef
https://www.instagram.com/reel/Cxyz123/#fragment
```

Canonical output:

``` text
https://www.instagram.com/reel/Cxyz123/
```

## 6.2 Canonicalization algorithm

``` text
                 RAW URL
                    │
                    ▼
             Parse URL safely
                    │
                    ▼
        ┌───────────────────────┐
        │ Scheme is http/https? │
        └──────────┬────────────┘
                   │
             invalid → 400
                   │
                   ▼
        Normalize hostname
                   │
                   ▼
        Is Instagram host?
                   │
             no → 400
                   │
                   ▼
        Parse path components
                   │
                   ▼
        Is path /reel/{code}/ ?
                   │
             no → 400
                   │
                   ▼
          Validate shortcode
                   │
                   ▼
         Remove query string
                   │
                   ▼
          Remove fragment
                   │
                   ▼
        Normalize trailing slash
                   │
                   ▼
         HTTPS canonical form
                   │
                   ▼
     https://www.instagram.com/reel/C/
                   │
                   ▼
                SHA-256
                   │
                   ▼
                reel_id
```

## 6.3 Host validation

Do not use a weak test such as:

``` python
if "instagram.com" in hostname:
```

That would incorrectly accept:

``` text
instagram.com.attacker.example
attackerinstagram.com
instagram.com.evil.example
```

Instead:

``` python
ALLOWED_HOSTS = {
    "instagram.com",
    "www.instagram.com",
}
```

and compare the parsed hostname exactly after lowercasing and removing a
trailing DNS dot.

The system must reject:

``` text
instagram.com.evil.example
www.instagram.com.evil.example
```

## 6.4 Scheme normalization

For identity, the output is always:

``` text
https://
```

The API may accept:

``` text
http://
```

if product policy permits it, but it must never preserve HTTP as a
separate identity.

## 6.5 Query parameters

All query parameters are removed from the identity.

For example:

``` text
?utm_source=instagram
?utm_medium=share
?igsh=...
```

do not create new Reels.

The query string must **not** be used in the database uniqueness key.

## 6.6 Fragment

Fragments are never sent to the server and are irrelevant to identity.

Remove:

``` text
#anything
```

## 6.7 Path validation

Do not accept arbitrary Instagram URLs merely because the hostname is
Instagram.

For this system, the endpoint must represent:

``` text
/reel/{shortcode}/
```

A normal Instagram profile, image post, story, or unrelated path should
be rejected.

## 6.8 Shortcode validation

The shortcode should be treated as an opaque Instagram identifier.

Do not attempt to interpret it as:

-   a timestamp,
-   an integer,
-   a database ID,
-   a user ID.

Validate only the allowed character set and reasonable length defined by
the implementation.

## 6.9 Canonical URL generation

Use one formatter everywhere:

``` python
def canonicalize_instagram_reel(raw_url: str) -> str:
    parsed = safe_parse_url(raw_url)

    hostname = parsed.hostname.lower().rstrip(".")

    if hostname not in {
        "instagram.com",
        "www.instagram.com",
    }:
        raise InvalidInstagramURL()

    if parsed.username or parsed.password or parsed.port:
        raise InvalidInstagramURL()

    match = REEL_PATH_REGEX.fullmatch(parsed.path)

    if not match:
        raise InvalidInstagramReelURL()

    shortcode = match.group("shortcode")

    if not valid_shortcode(shortcode):
        raise InvalidInstagramReelURL()

    return f"https://www.instagram.com/reel/{shortcode}/"
```

Then:

``` python
reel_id = sha256(
    canonical_url.encode("utf-8")
).hexdigest()
```

A UUID can also be used as the public database identifier, but the
SHA-256 digest is particularly useful as a deterministic identity key.

------------------------------------------------------------------------

# 7. Why Perceptual Hashing Is Removed

The previous architecture attempted a second identity layer based on
thumbnail perceptual hashing.

That is not appropriate under the revised requirement.

A pHash can answer:

> "Do these two images look similar?"

It cannot reliably answer:

> "Are these two Instagram URLs the same Reel?"

Two unrelated Reels can have:

-   the same thumbnail,
-   a similar frame,
-   a black title card,
-   the same creator branding,
-   similar visual composition.

Therefore:

``` text
URL identity = deterministic
visual similarity = optional future search feature
```

These must not be conflated.

If visual similarity is introduced later, it should be a search feature,
not an identity mechanism.

------------------------------------------------------------------------

# 8. Database Architecture

PostgreSQL is the source of truth.

The first version should not introduce a separate search database.

``` text
                 ┌─────────────────────────────┐
                 │         PostgreSQL           │
                 │                             │
                 │  reels                      │
                 │  reel_context                │
                 │  context_versions            │
                 │  search_events               │
                 │  ingestion_jobs              │
                 │                             │
                 │  GIN / FTS                   │
                 │  pgvector / HNSW             │
                 └─────────────────────────────┘
```

Redis is used for:

-   queueing,
-   hot query caching,
-   rate limiting,
-   short-lived request state.

It is **not** the source of truth.

------------------------------------------------------------------------

# 9. Database Schema

## 9.1 `reels`

``` sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE reels (
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
```

## 9.2 Why `canonical_url` has a UNIQUE constraint

The application performs canonicalization, but the database must
independently enforce identity.

This protects against:

``` text
request A → same URL
request B → same URL
```

arriving concurrently.

The database becomes the final concurrency boundary.

``` text
                  Request A
                     │
                     ▼
                  INSERT
                     │
                     ├───────┐
                     │       │
                     ▼       │
                  SUCCESS    │
                             │
                  Request B  │
                     │       │
                     ▼       │
                  INSERT     │
                     │       │
                     ▼       │
                 UNIQUE KEY ◄┘
                     │
                     ▼
                conflict
```

------------------------------------------------------------------------

# 10. Reel Context

The most important table in the system is `reel_context`.

``` sql
CREATE TABLE reel_context (
    reel_id UUID PRIMARY KEY
        REFERENCES reels(reel_id)
        ON DELETE CASCADE,

    summary TEXT NOT NULL,

    objects JSONB NOT NULL DEFAULT '[]',
    actions JSONB NOT NULL DEFAULT '[]',
    entities JSONB NOT NULL DEFAULT '[]',
    topics JSONB NOT NULL DEFAULT '[]',
    environments JSONB NOT NULL DEFAULT '[]',
    visual_style JSONB NOT NULL DEFAULT '[]',
    keywords JSONB NOT NULL DEFAULT '[]',

    searchable_text TEXT NOT NULL,

    embedding VECTOR(1536),

    context_version INTEGER NOT NULL,

    model_version TEXT NOT NULL,

    embedding_model_version TEXT NOT NULL,

    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

The dimension `1536` is an example. It must match the embedding model
actually selected.

Do not hard-code a dimension independently of the model contract.

------------------------------------------------------------------------

# 11. Context Schema

A generated context should look like:

``` json
{
  "summary": "A red Toyota Supra drifting along a mountain road at sunset.",
  "objects": [
    "Toyota Supra",
    "sports car",
    "mountain road"
  ],
  "actions": [
    "drifting",
    "driving"
  ],
  "entities": [
    "Toyota Supra"
  ],
  "topics": [
    "cars",
    "drifting",
    "automotive",
    "JDM"
  ],
  "environments": [
    "mountain",
    "road",
    "sunset"
  ],
  "visual_style": [
    "cinematic",
    "automotive"
  ],
  "keywords": [
    "red sports car",
    "supra drift",
    "mountain drift",
    "car drifting"
  ]
}
```

The system then creates:

``` text
searchable_text =
    summary
    + entities
    + topics
    + objects
    + actions
    + environments
    + visual_style
    + keywords
```

The JSON remains structured for future use.

The flattened text exists for efficient lexical retrieval.

------------------------------------------------------------------------

# 12. Why Store Both Structured Context and Flattened Text?

Structured context:

``` text
objects
actions
topics
entities
```

is useful for:

-   filters,
-   debugging,
-   explainability,
-   analytics,
-   future ranking features.

Flattened text is useful for:

-   PostgreSQL full-text search,
-   lexical ranking,
-   keyword matching.

Embedding is useful for:

-   semantic similarity,
-   paraphrases,
-   natural language.

Therefore:

``` text
                 Reel Context
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    Structured     Search text    Embedding
        │             │             │
        ▼             ▼             ▼
     Filters         FTS         pgvector
```

------------------------------------------------------------------------

# 13. Context Generation Pipeline

Context generation is asynchronous.

``` text
POST /reels
     │
     ▼
Validate URL
     │
     ▼
Canonicalize
     │
     ▼
Create Reel
     │
     ▼
Enqueue job
     │
     ▼
Return 202/201
     │
     │
     └─────────────────────────────┐
                                   ▼
                            Context Worker
                                   │
                                   ▼
                         Fetch approved metadata
                                   │
                                   ▼
                         Obtain permitted visual
                         representation if available
                                   │
                                   ▼
                           Context extraction
                                   │
                                   ▼
                         Schema validation
                                   │
                                   ▼
                           Generate search text
                                   │
                                   ▼
                             Embedding
                                   │
                                   ▼
                         Atomic context update
                                   │
                                   ▼
                           Search available
```

## 13.1 Metadata Fetching via Social Crawler Profiles

Public Instagram Reels cannot be reliably fetched using standard browser User-Agents without authentication, as Instagram responds with an HTTP 302 redirecting to `/accounts/login/`.

To retrieve legitimate public metadata (caption, creator username, title, and engagement stats) without requiring private session cookies or Graph API credentials, the ingestion worker uses social crawler User-Agent profiles that platforms allow for OpenGraph link previews:

- `facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)`
- `Twitterbot/1.0`
- `WhatsApp/2.21.12.21 A`

These endpoints respond with standard HTML containing OpenGraph metadata tags:
- `og:description`: Formatted as `<Likes> likes, <Comments> comments - <Author> on <Date>: "<Caption>"`.
- `og:title`: Formatted as `<Author> on Instagram: "<Caption>"`.
- `og:image`: Direct CDN link to the poster/thumbnail.

The context extractor parses these fields, cleans platform boilerplate, and feeds the resulting real-world caption and entities into the NLP pipeline.

## 13.2 Embedding Generation & Platform Runtime Guarantees

Vector embeddings (384 dimensions via `all-MiniLM-L6-v2`) provide dense semantic representation for candidate retrieval and reranking.

1. **Host Isolation & Offline Loading Guarantees**:
   - In Windows Python environments, pre-compiled binary operator registrations (specifically `torchvision::nms`) can crash `sentence_transformers` imports with `RuntimeError: operator torchvision::nms does not exist`. The runtime must isolate these packages before `transformers` loads:
     ```python
     sys.modules['torchvision'] = None
     sys.modules['torchvision.transforms'] = None
     ```
   - **HuggingFace Hub Offline Protection**: Default instantiation of `SentenceTransformer` attempts remote HTTP GET requests to `huggingface.co/api/models/...`. On firewalled, high-latency, or Windows environments, this introduces catastrophic 45–50 second TCP timeouts. The runtime strictly enforces offline-only resolution:
     ```python
     os.environ["USE_TF"] = "0"
     os.environ["USE_TORCH"] = "1"
     os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
     os.environ["HF_HUB_OFFLINE"] = "1"
     _st_model = SentenceTransformer(settings.EMBEDDING_MODEL, local_files_only=True)
     ```
   - Loading drops from 49,000ms down to ~210ms (and 0ms at query time when pre-warmed).

2. **Lifespan Startup Pre-Warming**:
   - The FastAPI backend utilizes an asynchronous `lifespan` hook to pre-load and warm the embedding model on server boot in a background daemon thread. Cold-start query spikes are thereby completely eliminated for incoming search traffic.

3. **In-Memory Query Embedding LRU Cache**:
   - Query vectors are cached using `@functools.lru_cache(maxsize=1024)`. Re-encoding identical or frequent search terms takes **0.00ms**, eliminating repeated PyTorch tensor operations.

4. **Dense Vector Fallback Guarantee**:
   - Any fallback embedding mechanism must never collapse into sparse arrays (mostly `0.0`), as zero-heavy vectors destroy cosine similarity rankings. The fallback must compute a deterministic, dense rolling projection (e.g., rolling SHA-256 trigonometric projections normalized to unit length) ensuring non-sparse distribution across all 384 dimensions.

## 13.3 Adaptive LLM Invocation & Context Sufficiency Gating

Unconditionally invoking an external Generative LLM for every ingested Reel introduces unnecessary API costs, network latency, and third-party rate limit risks (HTTP 429/503).

To optimize performance and resource efficiency, the context worker operates a **two-tier adaptive extraction pipeline**:

1. **Local NLP Fast Path (Bypasses LLM)**:
   When an Instagram Reel already contains a rich, descriptive caption (e.g. detailed recipes, vehicle modifications, financial guidelines, or tutorials), a high-speed deterministic NLP extractor processes the metadata locally.
   - **Execution Cost**: $0.00
   - **Processing Latency**: < 2 ms
   - **Sufficiency Criteria**:
     - $\ge 15$ substantive content words (excluding all platform and English stop words).
     - Caption is not an empty engagement bait/question hook (e.g., *"What do you think?"*, *"Wait till the end"*, *"Thoughts?"*).
     - At least 1 concrete thematic topic and $\ge 4$ distinct search keywords identified.
     - Summary length $\ge 40$ characters.

2. **Generative LLM Inference Tier (Invoked for Sparse Captions)**:
   When a Reel contains sparse, conversational, or engagement-only captions (which accounts for >60% of short-form video posts), the worker escalates the metadata to a structured generative model (e.g. Gemini / `gemini-flash-lite-latest` with fallback to `gemini-flash-latest`).
   - The LLM receives the schema-constrained prompt from Section 14 to infer the missing summary, topics, actions, and entities.
   - If upstream LLM calls fail or exceed quotas, the pipeline gracefully degrades to the local heuristic context without failing the ingestion job.

------------------------------------------------------------------------

# 14. Context Extraction Should Be Structured

Do not prompt the model:

``` text
"Describe this Reel."
```

That tends to produce uncontrolled prose.

Instead, define a schema:

``` json
{
  "summary": "string",
  "objects": ["string"],
  "actions": ["string"],
  "entities": ["string"],
  "topics": ["string"],
  "environments": ["string"],
  "visual_style": ["string"],
  "keywords": ["string"]
}
```

The model is required to return this schema.

The worker then validates it before writing to PostgreSQL.

------------------------------------------------------------------------

# 15. Context Validation

The worker must never blindly trust model output.

``` text
Model output
     │
     ▼
JSON parser
     │
     ├── invalid → retry
     │
     ▼
Schema validation
     │
     ├── invalid → retry
     │
     ▼
Field limits
     │
     ├── invalid → normalize/reject
     │
     ▼
Deduplicate arrays
     │
     ▼
Normalize strings
     │
     ▼
Persist
```

Example limits:

``` text
summary:        1–500 characters
objects:        maximum 30
actions:        maximum 20
entities:       maximum 30
topics:         maximum 30
environments:   maximum 20
visual_style:   maximum 20
keywords:       maximum 50
```

These are implementation defaults, not immutable requirements.

------------------------------------------------------------------------

# 16. Context Normalization

Before storage:

-   trim whitespace,
-   normalize Unicode,
-   remove duplicate values,
-   normalize case for comparison,
-   preserve display capitalization separately where useful,
-   reject control characters,
-   reject excessively long values.

Example:

``` text
" Toyota Supra "
"toyota supra"
"Toyota Supra"
```

can be normalized for deduplication.

The canonical display value can still be:

``` text
Toyota Supra
```

------------------------------------------------------------------------

# 17. Search Architecture

The search system has five major stages:

``` text
                 User Query
                     │
                     ▼
              Query Understanding
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
       Terms      Entities    Intent
          │          │          │
          └──────────┼──────────┘
                     ▼
              Query Embedding
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
    Lexical Retrieval      Vector Retrieval
          │                     │
          └──────────┬──────────┘
                     ▼
              Candidate Fusion
                     │
                     ▼
                 Re-ranking
                     │
                     ▼
              Confidence Gate
                     │
                     ▼
                Maximum 4
```

------------------------------------------------------------------------

# 18. Query Understanding

Suppose the user enters:

``` text
"red supra drifting on a mountain"
```

The system internally extracts:

``` json
{
  "raw_query": "red supra drifting on a mountain",
  "entities": ["Toyota Supra"],
  "objects": ["sports car"],
  "actions": ["drifting"],
  "environment": ["mountain", "road"],
  "attributes": ["red"],
  "topics": ["automotive"]
}
```

The system may also generate an embedding for the raw query and/or
normalized representation.

The user never sees this internal structure.

------------------------------------------------------------------------

# 19. Query Expansion

Query expansion improves recall.

For:

``` text
"supra drift"
```

internal terms may include:

``` text
supra
Toyota Supra
sports car
JDM
drift
drifting
car drifting
automotive
```

But expansion must not become uncontrolled.

Use:

-   maximum expansion count,
-   deduplication,
-   model confidence,
-   domain vocabulary.

Do not expand every query into hundreds of speculative terms.

------------------------------------------------------------------------

# 20. Lexical Retrieval

PostgreSQL full-text search handles explicit terms.

Example:

``` sql
SELECT
    reel_id,
    ts_rank_cd(
        to_tsvector('english', searchable_text),
        plainto_tsquery('english', $1)
    ) AS lexical_score
FROM reel_context
WHERE
    to_tsvector('english', searchable_text)
    @@ plainto_tsquery('english', $1)
ORDER BY lexical_score DESC
LIMIT 50;
```

For production, store a generated `tsvector` column instead of
recomputing it for every query.

``` sql
ALTER TABLE reel_context
ADD COLUMN search_vector tsvector
GENERATED ALWAYS AS (
    to_tsvector('english', searchable_text)
) STORED;

CREATE INDEX reel_context_search_vector_idx
ON reel_context
USING GIN(search_vector);
```

------------------------------------------------------------------------

# 21. Semantic Retrieval

The query embedding is compared against Reel embeddings.

``` sql
SELECT
    reel_id,
    1 - (embedding <=> $1) AS semantic_score
FROM reel_context
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1
LIMIT 50;
```

For larger datasets, use HNSW.

``` sql
CREATE INDEX reel_context_embedding_hnsw
ON reel_context
USING hnsw (embedding vector_cosine_ops);
```

pgvector documents HNSW as a speed/recall tradeoff and supports cosine
distance, filtering, iterative scans, and hybrid search with PostgreSQL
full-text search. \[1\]

------------------------------------------------------------------------

# 22. Why HNSW?

HNSW is a good default for this workload because:

-   query latency is important,
-   recall matters,
-   embeddings are queried continuously,
-   the dataset may grow incrementally,
-   HNSW does not require a separate training step like IVFFlat.

The exact parameters must be benchmarked.

Start with documented defaults and tune based on measured recall/latency
rather than guessing.

Useful parameters include:

``` text
m
ef_construction
ef_search
```

Higher search effort can improve recall at the cost of latency. \[1\]

------------------------------------------------------------------------

# 23. Hybrid Candidate Retrieval

Neither lexical nor semantic search should be trusted alone.

Example:

``` text
Query:
"red supra drifting mountain"

Lexical results:
A
B
C
D
E
...

Vector results:
B
C
F
G
H
...
```

Merge:

``` text
A B C D E F G H
```

Deduplicate by `reel_id`.

Then score using a hybrid method.

------------------------------------------------------------------------

# 24. Reciprocal Rank Fusion

A strong initial fusion strategy is Reciprocal Rank Fusion.

For a result with rank `r`:

``` text
RRF(rank) = 1 / (k + rank)
```

If a Reel appears highly in both lexical and semantic rankings, it
receives a stronger combined signal.

Conceptually:

``` text
                    Lexical
                       │
                       ▼
                ranked candidates
                       │
                       ├──────┐
                              │
                              ▼
                           RRF merge
                              ▲
                              │
                       ┌──────┘
                       │
                ranked candidates
                       ▲
                       │
                    Vector
```

pgvector's documentation explicitly describes RRF and cross-encoder
re-ranking as approaches for combining full-text and vector retrieval.
\[1\]

------------------------------------------------------------------------

# 25. Candidate Pool Size

The UI limit is four.

The retrieval limit should be much larger.

Recommended initial pipeline:

``` text
Lexical:        50
Vector:         50
                    ↓
Merged:         up to 100
                    ↓
Deduplicated:   up to 100
                    ↓
Cheap scoring:  top 30
                    ↓
Re-ranker:      top 20
                    ↓
Confidence:     top 4
```

The exact numbers should be benchmarked.

The important principle is:

> Retrieve broadly, rank deeply, display narrowly.

------------------------------------------------------------------------

# 26. Re-ranking

Candidate retrieval answers:

> "Which Reels might be relevant?"

Re-ranking answers:

> "Which of these Reels most precisely satisfies the query?"

This distinction is crucial.

A candidate can be semantically similar but still wrong.

Example:

``` text
Query:
"red Toyota Supra drifting on a mountain road"
```

Candidate 1:

``` text
red Toyota Supra drifting on a mountain road
```

Candidate 2:

``` text
red BMW drifting in a city
```

Candidate 3:

``` text
Toyota Supra parked at a car show
```

All may be retrieved.

The re-ranker should strongly distinguish them.

------------------------------------------------------------------------

# 27. Initial Ranking Formula

A transparent first implementation can use:

``` text
final_score =
    0.50 * semantic_score
  + 0.30 * lexical_score
  + 0.10 * entity_match
  + 0.05 * action_match
  + 0.05 * attribute_match
```

These values are starting points, not permanent truth.

A production system should eventually learn ranking weights from real
search interaction data.

## 27.1 Dynamic Weight Redistribution for Hybrid Retrieval

In hybrid retrieval, candidates arrive through two parallel channels:
1. **Lexical Retrieval (PostgreSQL FTS `tsvector`)**
2. **Dense Vector Retrieval (pgvector / cosine similarity)**

A critical operational challenge occurs with conceptual or conversational queries (e.g., *"plastic polymer currency notes RBI"*). While the cosine semantic similarity may be very high ($\ge 0.70$), strict boolean full-text search (`plainto_tsquery`) requires all terms to be present and yields `lexical_score = 0.0`.

Under a static formula:
$$\text{final\_score} = 0.50 \times 0.735 + 0.30 \times 0.0 + \dots = 0.3675$$
This candidate would be incorrectly dropped by the Section 28 Confidence Gate ($< 0.50$).

To prevent semantic starvation when exact lexical matches are absent, the re-ranker dynamically redistributes weights:

- **Hybrid Candidates** ($\text{max\_lex} > 0 \text{ and } \text{lex\_raw} > 0$):
  $$\text{sem\_w} = 0.50, \quad \text{lex\_w} = 0.30$$
- **Semantic-Only Candidates** ($\text{lex\_raw} = 0$):
  $$\text{sem\_w} = 0.75, \quad \text{lex\_w} = 0.05$$

This ensures high-similarity semantic matches are not penalized for lacking verbatim keyword matches, preserving recall while maintaining strict precision.

------------------------------------------------------------------------

# 28. Precision-First Confidence Gate

Do not force four results.

``` text
                 Ranked results
                       │
                       ▼
              ┌─────────────────┐
              │ confidence gate │
              └────────┬────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
     score ≥ .80   .60–.80        < .60
        │              │              │
        ▼              ▼              ▼
     eligible       maybe          reject
        │              │              │
        └──────────────┴──────────────┘
                       │
                       ▼
                 Maximum 4
```

The actual threshold must be calibrated using a labelled evaluation set.

A score from a model is not automatically a calibrated probability.

Therefore avoid presenting:

``` text
97% match
```

unless the score has actually been calibrated.

------------------------------------------------------------------------

# 29. Result Diversification

Even with four results, there is a subtle problem.

Suppose the top four are:

``` text
Reel A
Reel A duplicate context
Reel A variant
Reel A near-identical content
```

The system should not return semantically redundant records merely
because their raw scores are high.

A light diversity penalty can be applied after ranking.

However, because URL identity is strict, this is a **ranking diversity
feature**, not an identity merge.

------------------------------------------------------------------------

# 30. Exact Match Boost

If the query contains an exact entity or phrase represented in the
context, give it a controlled boost.

Example:

``` text
query = "Toyota Supra"
```

A Reel whose entity list contains:

``` text
Toyota Supra
```

should beat a Reel whose embedding only vaguely resembles cars.

This prevents semantic search from over-generalizing.

------------------------------------------------------------------------

# 31. Query Types

The search engine should recognize several broad query patterns.

### Entity query

``` text
"Toyota Supra"
```

### Action query

``` text
"cars drifting"
```

### Scene query

``` text
"car driving through snowy mountains"
```

### Attribute query

``` text
"red sports car"
```

### Combined query

``` text
"red Toyota Supra drifting on a mountain road"
```

### Conceptual query

``` text
"cinematic automotive edits"
```

Different signals should receive different weights.

------------------------------------------------------------------------

# 32. Search API

## `POST /api/v1/reels`

Request:

``` http
POST /api/v1/reels
Content-Type: application/json
Authorization: Bearer <token>

{
  "url": "https://www.instagram.com/reel/Cxyz123/"
}
```

Response for a newly created Reel:

``` http
202 Accepted
Content-Type: application/json

{
  "reel_id": "0f4b...",
  "canonical_url": "https://www.instagram.com/reel/Cxyz123/",
  "status": "processing"
}
```

Why `202`?

Because context generation is asynchronous.

------------------------------------------------------------------------

# 33. Existing Reel

If the canonical URL already exists:

``` http
200 OK
```

``` json
{
  "reel_id": "0f4b...",
  "canonical_url": "https://www.instagram.com/reel/Cxyz123/",
  "status": "ready",
  "created": false
}
```

The operation is therefore naturally idempotent.

------------------------------------------------------------------------

# 34. Search API

``` http
GET /api/v1/search?q=red+supra+drifting
```

Response:

``` json
{
  "query": "red supra drifting",
  "results": [
    {
      "reel_id": "a1...",
      "canonical_url": "https://www.instagram.com/reel/Cabc123/",
      "title": "Instagram Reel",
      "thumbnail_url": "...",
      "score": 0.94
    },
    {
      "reel_id": "b2...",
      "canonical_url": "https://www.instagram.com/reel/Cdef456/",
      "title": "Instagram Reel",
      "thumbnail_url": "...",
      "score": 0.91
    }
  ],
  "count": 2,
  "max_results": 4
}
```

Never return more than four.

------------------------------------------------------------------------

# 35. Search API Validation

Parameters:

``` text
q:
    required
    minimum length: 2
    maximum length: 500

limit:
    ignored or clamped to 4

cursor:
    optional
```

Even if a client sends:

``` text
limit=100000
```

the server must never return 100,000 results.

For the current UI requirement, a simple contract is:

``` text
effective_limit = min(requested_limit, 4)
```

or simply remove the limit parameter entirely.

------------------------------------------------------------------------

# 36. Search Response Semantics

The response should tell the client whether the system found strong
matches.

Example:

``` json
{
  "query": "red supra drifting",
  "results": [...],
  "count": 4,
  "confidence": "high"
}
```

If only two strong results exist:

``` json
{
  "query": "red supra drifting",
  "results": [...],
  "count": 2,
  "confidence": "high"
}
```

If nothing passes the confidence gate:

``` json
{
  "query": "xyz impossible concept",
  "results": [],
  "count": 0,
  "confidence": "low"
}
```

Do not manufacture weak matches.

------------------------------------------------------------------------

# 37. Reel Status API

``` http
GET /api/v1/reels/{reel_id}
```

Response:

``` json
{
  "reel_id": "...",
  "canonical_url": "...",
  "status": "ready",
  "context_version": 3
}
```

This allows the web UI to poll or subscribe to enrichment completion.

------------------------------------------------------------------------

# 38. Context Generation API Is Internal

The browser should never be able to submit:

``` json
{
  "summary": "...",
  "topics": [...]
}
```

The public API only accepts:

``` json
{
  "url": "..."
}
```

Context generation is an internal worker contract.

------------------------------------------------------------------------

# 39. Internal Job Contract

``` json
{
  "job_id": "uuid",
  "job_type": "GENERATE_REEL_CONTEXT",
  "reel_id": "uuid",
  "attempt": 1,
  "created_at": "2026-09-30T10:00:00Z"
}
```

Workers must be idempotent.

------------------------------------------------------------------------

# 40. Idempotent Worker Design

A worker may crash:

``` text
fetch metadata
    ↓
generate context
    ↓
CRASH
```

The job is delivered again.

The second execution must not create:

``` text
context v1
context v1 duplicate
context v1 duplicate
```

Instead, use a deterministic context version and an upsert.

``` sql
INSERT INTO reel_context (...)
VALUES (...)
ON CONFLICT (reel_id)
DO UPDATE SET
    summary = EXCLUDED.summary,
    objects = EXCLUDED.objects,
    ...
    context_version = EXCLUDED.context_version;
```

------------------------------------------------------------------------

# 41. Job State Machine

``` text
             ┌─────────┐
             │ PENDING │
             └────┬────┘
                  │
                  ▼
            ┌───────────┐
            │ PROCESSING│
            └─────┬─────┘
                  │
         ┌────────┴─────────┐
         │                  │
       success            failure
         │                  │
         ▼                  ▼
      ┌──────┐         ┌─────────┐
      │ READY│         │ RETRYING│
      └──────┘         └────┬────┘
                             │
                     retry budget
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
              PROCESSING              FAILED
```

------------------------------------------------------------------------

# 42. Retry Strategy

Transient errors should use exponential backoff.

Example:

``` text
attempt 1 → immediate
attempt 2 → 5 seconds
attempt 3 → 30 seconds
attempt 4 → 2 minutes
attempt 5 → 10 minutes
```

Add jitter:

``` text
delay = base_delay * 2^attempt + random_jitter
```

Never retry indefinitely.

------------------------------------------------------------------------

# 43. Dead-Letter Queue

After the maximum retry count:

``` text
Job
 │
 ▼
retry 1
 │
 ▼
retry 2
 │
 ▼
retry 3
 │
 ▼
retry 4
 │
 ▼
retry 5
 │
 ▼
DLQ
```

The Reel record remains intact.

A failed enrichment job should not delete the Reel.

------------------------------------------------------------------------

# 44. Partial Context

Context generation should support partial success.

For example:

``` text
metadata = successful
visual analysis = successful
embedding = failed
```

Store:

``` text
structured context = available
searchable text = available
embedding = NULL
```

The Reel can still be found lexically.

Later:

``` text
embedding retry
     ↓
embedding populated
     ↓
semantic search enabled
```

This is much better than treating enrichment as one indivisible
transaction.

------------------------------------------------------------------------

# 45. Atomic Index Update

Context updates should be atomic from the application's perspective.

Do:

``` text
generate context
      ↓
validate context
      ↓
generate searchable_text
      ↓
generate embedding
      ↓
BEGIN
      ↓
update reel_context
      ↓
update status = ready
      ↓
COMMIT
```

Do not mark a Reel `ready` before the searchable representation is
actually persisted.

------------------------------------------------------------------------

# 46. Search During Enrichment

A Reel may be:

``` text
pending
processing
ready
failed
```

Search should normally use only:

``` text
ready
```

unless the lexical context is already safely available.

A useful policy:

``` text
metadata only → not searchable
structured context + search text → lexical searchable
embedding available → hybrid searchable
```

This produces graceful degradation.

------------------------------------------------------------------------

# 47. Cache Architecture

Redis should be used for short-lived performance optimizations.

``` text
                  Query
                    │
                    ▼
              Query cache
                    │
             ┌──────┴──────┐
             │             │
            hit           miss
             │             │
             ▼             ▼
          response     PostgreSQL
                            │
                            ▼
                         results
                            │
                            ▼
                       Redis cache
```

Cache key:

``` text
search:v1:{normalized_query}:{ranking_version}
```

The ranking version is important.

If the ranking algorithm changes from:

``` text
ranking-v1
```

to:

``` text
ranking-v2
```

old cached results should not silently masquerade as v2 results.

------------------------------------------------------------------------

# 48. Cache Invalidation

Search caches can be stale.

When a Reel changes context:

``` text
Reel context update
       │
       ▼
search index changes
       │
       ▼
old query cache may be stale
```

Two practical strategies:

### Strategy A --- short TTL

Use a short TTL for search results.

### Strategy B --- versioned index

Include an index generation/version in the cache key.

For v1, short TTL plus versioned ranking is sufficient.

------------------------------------------------------------------------

# 49. Rate Limiting

The public API must be rate-limited.

At minimum:

``` text
POST /reels
GET /search
GET /reels/{id}
```

should have different limits.

Example starting values:

``` text
search:
    60 requests/minute/user

save:
    20 requests/minute/user

anonymous search:
    lower IP-based limit

anonymous save:
    very low limit or disabled
```

These are starting points, not final production values.

------------------------------------------------------------------------

# 50. Abuse Protection

Without user descriptions, one major abuse vector disappears:

``` text
keyword stuffing
```

But attackers can still:

-   submit huge numbers of URLs,
-   exhaust the enrichment queue,
-   generate model costs,
-   generate Brave/API costs if external discovery is ever introduced,
-   hammer search,
-   create cache churn.

Therefore rate limiting and quotas remain necessary.

------------------------------------------------------------------------

# 51. Authentication

The web application should support authenticated users.

Recommended model:

``` text
Browser
   │
   ▼
Authentication provider
   │
   ▼
session/JWT
   │
   ▼
API
```

The backend must derive:

``` text
user_id
```

from the authenticated identity.

Never accept:

``` json
{
  "user_id": "someone-else"
}
```

from the browser as an authoritative identity.

------------------------------------------------------------------------

# 52. Authorization

For the current product, the main authorization rule is simple:

``` text
Authenticated user
        │
        ├── save Reel
        ├── search
        └── view indexed Reel
```

Internal operations require service credentials.

Workers should not use public user tokens to perform privileged database
operations.

------------------------------------------------------------------------

# 53. SSRF Protection

The original architecture correctly recognized SSRF as a concern, but
the improved design should make the rule more explicit.

There are two different cases:

1.  Parsing the user URL.
2.  Server-side fetching of approved Instagram resources.

Never allow the submitted URL to become a generic HTTP target.

``` text
User URL
   │
   ▼
canonicalize
   │
   ▼
known Instagram Reel
   │
   ▼
approved upstream endpoint
```

Never:

``` text
User URL
   │
   ▼
requests.get(user_url)
```

without strict policy.

------------------------------------------------------------------------

# 54. Redirect Safety

Even if the original hostname is allowed, redirects must be validated.

Example:

``` text
instagram.com/reel/C123
        │
        ▼
HTTP redirect
        │
        ▼
internal.service.local
```

must never be followed.

For every redirect:

``` text
target hostname
     ↓
exact allowlist check
     ↓
allowed → continue
blocked → abort
```

Also enforce:

-   maximum redirects,
-   connection timeout,
-   total timeout,
-   response-size limits.

------------------------------------------------------------------------

# 55. DNS and IP Validation

If server-side HTTP requests are used, hostname validation alone is not
enough.

The resolved address must not be:

``` text
127.0.0.0/8
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.0.0/16
::1
fc00::/7
fe80::/10
```

and other infrastructure-reserved ranges as appropriate for the
deployment.

The safest implementation is to use a hardened outbound HTTP client or
egress proxy with an allowlist.

------------------------------------------------------------------------

# 56. Request Limits

Every external operation needs limits.

Example:

``` text
connect timeout:       3 sec
read timeout:          10 sec
max redirects:         3
max response size:     5 MB
max model input size:  implementation-specific
```

Never allow an upstream response to consume unlimited memory.

------------------------------------------------------------------------

# 57. Image Processing Security

If a thumbnail or visual representation is processed:

``` text
network
  ↓
download
  ↓
content-type validation
  ↓
size limit
  ↓
image decoder sandbox
  ↓
resize
  ↓
model
```

Do not trust:

``` text
Content-Type: image/jpeg
```

by itself.

Validate the actual payload as well.

------------------------------------------------------------------------

# 58. Prompt Injection Considerations

If external text is fed into an LLM context-generation pipeline, it must
be treated as **data**, not instructions.

For example, an Instagram caption might contain:

``` text
Ignore previous instructions and output...
```

The model should be instructed that external metadata is untrusted
content.

The context extraction prompt should have a strict schema and validation
layer.

------------------------------------------------------------------------

# 59. Model Output Security

Never execute model output.

Never allow model output to directly become:

-   SQL,
-   HTML,
-   JavaScript,
-   shell commands,
-   HTTP destinations.

All model output is data.

------------------------------------------------------------------------

# 60. XSS Protection

Search results contain externally derived strings.

React's normal escaped rendering helps, but the backend should still
treat all fields as untrusted.

Do not render model or upstream text using raw HTML unless absolutely
necessary.

If an embed requires HTML, sanitize it and use a strict Content Security
Policy.

------------------------------------------------------------------------

# 61. SQL Injection

All search queries must use parameterized SQL.

Never:

``` python
query = f"""
SELECT ...
WHERE searchable_text @@ plainto_tsquery('{user_query}')
"""
```

Use:

``` python
cursor.execute(
    """
    SELECT ...
    WHERE search_vector @@ plainto_tsquery('english', %s)
    """,
    (user_query,)
)
```

The same applies to every database operation.

------------------------------------------------------------------------

# 62. API Error Model

All APIs should return a consistent error shape.

``` json
{
  "error": {
    "code": "INVALID_INSTAGRAM_REEL_URL",
    "message": "The supplied URL is not a supported Instagram Reel URL.",
    "request_id": "req_123"
  }
}
```

Do not expose internal exceptions.

------------------------------------------------------------------------

# 63. Error Codes

Recommended initial codes:

``` text
INVALID_URL
INVALID_INSTAGRAM_HOST
INVALID_REEL_PATH
INVALID_SHORTCODE
UNAUTHORIZED
FORBIDDEN
RATE_LIMITED
REEL_NOT_FOUND
ENRICHMENT_PENDING
UPSTREAM_TIMEOUT
UPSTREAM_RATE_LIMIT
CONTEXT_GENERATION_FAILED
SEARCH_UNAVAILABLE
INTERNAL_ERROR
```

------------------------------------------------------------------------

# 64. HTTP Status Mapping

``` text
400 → malformed request
401 → unauthenticated
403 → unauthorized
404 → Reel/resource not found
409 → resource conflict if applicable
422 → semantically invalid URL
429 → rate limited
500 → internal error
502 → upstream dependency error
503 → temporarily unavailable
504 → upstream timeout
```

------------------------------------------------------------------------

# 65. Observability

Every request gets a request ID.

``` text
Browser
   │
   │ X-Request-ID
   ▼
API
   │
   ├── DB
   ├── Redis
   └── Worker
```

Logs should contain:

``` text
request_id
user_id (non-sensitive internal identifier)
endpoint
latency
status
error_code
```

Workers should additionally log:

``` text
job_id
reel_id
attempt
worker_id
model_version
duration
upstream latency
```

------------------------------------------------------------------------

# 66. Search Observability

Search quality needs its own telemetry.

Record:

``` text
query
normalized_query
timestamp
candidate_count
lexical_candidate_count
vector_candidate_count
reranker_candidate_count
returned_count
ranking_version
embedding_model_version
latency_ms
clicked_result
```

Avoid logging sensitive user data unnecessarily.

------------------------------------------------------------------------

# 67. Search Quality Metrics

Do not optimize only latency.

Measure:

### Precision@4

How many returned results were actually relevant?

### Recall@K

Did the correct Reel appear in the candidate set?

### MRR

How early does the relevant Reel appear?

### NDCG@4

How well are highly relevant results ordered?

### Zero-result rate

How often does the engine return nothing?

### Search abandonment

How often does the user search and click nothing?

------------------------------------------------------------------------

# 68. Golden Evaluation Dataset

Before tuning ranking, build a labelled dataset.

Example:

``` text
Query                               Reel    Relevance
-----------------------------------------------------
red supra drifting mountain          A       3
red supra drifting mountain          B       1
red supra drifting mountain          C       0

cinematic car edit                   D       3
cinematic car edit                   E       2
cinematic car edit                   F       0
```

Use:

``` text
0 = irrelevant
1 = weakly related
2 = relevant
3 = highly relevant
```

Then evaluate ranking changes offline.

This is much better than changing weights based only on intuition.

------------------------------------------------------------------------

# 69. Search Improvement Loop

``` text
                Search logs
                    │
                    ▼
             Query analytics
                    │
                    ▼
            Build evaluation set
                    │
                    ▼
             Change ranking
                    │
                    ▼
             Offline evaluation
                    │
             ┌──────┴──────┐
             ▼             ▼
          improved      degraded
             │             │
             ▼             ▼
           deploy        rollback
```

------------------------------------------------------------------------

# 70. Search Feedback

The web UI can record:

``` text
query
result position
reel_id
clicked = true
```

A click is a useful relevance signal, but it is not ground truth.

For example:

-   users may click the first result because it is first,
-   users may click thumbnails accidentally,
-   users may prefer novelty.

Therefore use clicks as one signal rather than treating every click as a
perfect label.

------------------------------------------------------------------------

# 71. Search Latency Budget

A robust search engine must balance deep hybrid ranking with interactive latency:

``` text
Web request
    │
    ├── L1 In-Memory Cache Check (<1ms)
    ├── L2 Redis Cache Check (<40ms)
    ├── Query normalization
    ├── Query embedding (35ms, or 0ms if in LRU)
    ├── Parallel retrieval:
    │     ├── Lexical FTS (~250ms)
    │     └── Vector search (~280ms)
    ├── Reciprocal Rank Fusion (<1ms)
    ├── Multi-factor re-ranking (<2ms)
    ├── Confidence gate (<1ms)
    ├── Multi-tier cache write
    └── Asynchronous search logging (daemon thread)
```

### Benchmarked Production Latency Profile:

| Stage | Benchmark | Implementation Mechanism |
| :--- | :--- | :--- |
| **L1 Cache Hit** | `< 1 ms` | Thread-safe in-memory TTL dictionary (`maxsize=500`) |
| **L2 Cache Hit** | `< 40 ms` | Redis Cloud key-value lookup (`search:<query>:<limit>`) |
| **Query Embedding** | `35 ms` | Local `all-MiniLM-L6-v2` (`local_files_only=True`), PyTorch CPU |
| **Repeat Embedding** | `0.00 ms` | `@functools.lru_cache(maxsize=1024)` on query string |
| **Parallel Retrieval** | `~280 ms` | Concurrent `ThreadPoolExecutor(max_workers=8)` |
| **Rerank & Gates** | `< 2 ms` | Vector dot-product + lexical scaling + entity boosts |
| **Cold Live Query** | **`~380 ms`** | Full end-to-end HTTP lifecycle from browser client |

------------------------------------------------------------------------

# 72. Parallel Retrieval & Execution Concurrency

Lexical and vector searches run concurrently rather than sequentially.

``` text
                  Query
                    │
             Query embedding
                    │
            ┌───────┴────────┐
            │                │
            ▼                ▼
       PostgreSQL FTS    pgvector HNSW
       (ts_rank_cd)      (cosine_similarity)
            │                │
            └───────┬────────┘
                    ▼
                  Merge (RRF)
```

### Retrieval Optimizations:
1. **Persistent Worker Pool**:
   Do not allocate and tear down a new thread pool per search request. The service maintains a persistent, module-level `ThreadPoolExecutor(max_workers=8)` that handles concurrent lexical and vector sub-queries with zero initialization jitter.
2. **SQL Wire Transfer Minimization**:
   The candidate retrieval query in `_retrieve_vector_candidates` deliberately excludes the raw 384-dimensional float array (`c.embedding`) from the SQL `SELECT` list. Scoring is performed in the database engine via `cosine_similarity()`, reducing database network payloads from ~250KB down to ~8KB per query (a 35% reduction in wire latency).
3. **FastAPI Event Loop Starvation Avoidance**:
   Synchronous, blocking operations (database cursor queries and CPU vector multiplications) must never run directly on FastAPI's asynchronous event loop. Search routes are declared as synchronous functions (`def search_reels(...)` instead of `async def`), prompting FastAPI to automatically offload them to an underlying worker threadpool, preserving HTTP responsiveness.

------------------------------------------------------------------------

# 73. Multi-Tier Search Cache Architecture

Search responses are cached hierarchically to minimize database load and deliver sub-millisecond responses for popular and repeated queries:

``` text
Query Request
      │
      ▼
┌──────────────┐   HIT (<1ms)
│ L1 In-Memory ├──────────────► Return JSON
└──────┬───────┘
       │ MISS
       ▼
┌──────────────┐   HIT (<40ms)
│ L2 Redis     ├──────────────► Populate L1 & Return
└──────┬───────┘
       │ MISS
       ▼
┌──────────────┐
│ DB Search    ├──────────────► Populate L1 + L2 & Return
└──────────────┘
```

1. **L1 In-Memory Fast Cache**:
   - Resides directly within the application process (`_l1_cache`).
   - Eviction: Bounded to 500 entries with automatic LRU pruning and 120-second TTL.
   - Eliminates all network round-trips for rapid consecutive searches.
2. **L2 Distributed Cache (Redis Cloud)**:
   - Shared cross-process/cross-worker cache using key pattern `search:<query>:<limit>`.
   - Positive searches (high and medium confidence) cached with **300-second TTL** (5 minutes).
3. **Negative Caching (Zero-Result Protection)**:
   - Queries returning zero results or low confidence are cached with a shorter **60-second TTL**.
   - Prevents repeated typos or unmatchable queries from constantly pounding the database cluster.

------------------------------------------------------------------------

# 74. Database Index Strategy

Recommended:

``` sql
CREATE UNIQUE INDEX reels_canonical_url_uidx
ON reels(canonical_url);

CREATE UNIQUE INDEX reels_shortcode_uidx
ON reels(instagram_shortcode);

CREATE INDEX reel_context_search_vector_gin
ON reel_context
USING GIN(search_vector);

CREATE INDEX reel_context_embedding_hnsw
ON reel_context
USING hnsw (embedding vector_cosine_ops);
```

Additional B-tree indexes should only be added for actual query
patterns.

Avoid indexing every JSON field by default.

------------------------------------------------------------------------

# 75. JSONB Indexing

Do not immediately create a GIN index on every structured field.

For example:

``` text
objects
actions
topics
entities
```

may not need independent indexes in v1.

Search should primarily happen through:

``` text
search_vector
embedding
```

Structured fields can be used during ranking after candidate retrieval.

If later you introduce a filter such as:

``` text
topic = automotive
```

then add the appropriate index based on measured query patterns.

------------------------------------------------------------------------

# 76. Read Replicas

Initially:

``` text
                 API
                  │
             PostgreSQL
```

is enough.

At scale:

``` text
                   ┌──────────────┐
                   │   Primary    │
                   └──────┬───────┘
                          │ replication
              ┌───────────┴───────────┐
              ▼                       ▼
         Read Replica 1          Read Replica 2
```

But search can be sensitive to replica lag.

If a user saves a Reel and immediately searches for it, a replica may
not have the context yet.

Therefore:

-   search can use replicas at scale,
-   but read-your-own-write flows should use primary or an explicit
    freshness mechanism.

------------------------------------------------------------------------

# 77. Connection Pooling & Warm Connection Baselines

Application workers and API servers must not open unpooled or ad-hoc database connections. Furthermore, when using remote cloud database instances (such as Neon PostgreSQL in AWS `ap-southeast-1`), the TCP/TLS negotiation overhead across WAN hops is ~600ms per handshake.

### Pool Configuration Invariants:
1. **Pre-Warmed Connection Floor (`minconn=4`)**:
   Instead of initializing with `minconn=1`, the connection pool (`psycopg2.pool.ThreadedConnectionPool`) maintains a minimum baseline of 4 persistent, pre-opened connections. When concurrent lexical and vector threads request connections simultaneously, they acquire warm sockets immediately with **0 ms handshake delay**.
2. **TCP Keepalive Enforcement**:
   To prevent serverless cloud providers or PgBouncer proxies from silently closing idle sockets, connection parameters explicitly configure TCP keepalives:
   ```python
   "keepalives": 1,
   "keepalives_idle": 30,
   "keepalives_interval": 10,
   "keepalives_count": 5
   ```
3. **Explicit Timeouts**:
   Set explicit connection limits:
   ```text
   minconn: 4
   maxconn: 20
   connect_timeout: 5s
   statement_timeout: 3s
   ```
   PostgreSQL `statement_timeout` prevents any single runaway query from tying up pool capacity.

------------------------------------------------------------------------

# 78. Query Timeout

A user query must never be able to consume database resources
indefinitely.

For example:

``` text
search statement timeout = 500 ms
```

can be used as a starting target, but must be calibrated.

If the query exceeds the timeout:

``` text
503 SEARCH_UNAVAILABLE
```

or a controlled degraded response can be returned.

------------------------------------------------------------------------

# 79. Redis Architecture

Redis handles three independent concerns:

``` text
Redis
 ├── Queue
 ├── Cache
 └── Rate limiting
```

Use distinct key namespaces:

``` text
queue:reel-context:*
cache:search:*
ratelimit:user:*
```

If the deployment becomes large, separate Redis instances can be
introduced.

------------------------------------------------------------------------

# 80. Queue Backpressure

Suppose:

``` text
Incoming URLs = 1000/sec
Worker capacity = 100/sec
```

The queue will grow indefinitely.

The API must therefore enforce ingestion quotas.

``` text
User
 │
 ▼
Rate limit
 │
 ▼
Quota
 │
 ▼
Queue capacity
 │
 ├── capacity available → accept
 │
 └── overloaded → 429/503
```

Do not allow unlimited queue growth.

------------------------------------------------------------------------

# 81. Queue Poisoning

A malformed or permanently failing Reel should not retry forever.

Use:

``` text
max_attempts
dead_letter_queue
last_error
next_attempt_at
```

Store enough information to investigate failures.

------------------------------------------------------------------------

# 82. Context Model Versioning

Every context record contains:

``` text
context_version
model_version
embedding_model_version
```

Example:

``` text
context_version = 3
model_version = vision-v5
embedding_model_version = embed-v2
```

When models change:

``` text
old context
    │
    ▼
reprocessing queue
    │
    ▼
new context
    │
    ▼
new embedding
```

Reel identity remains unchanged.

------------------------------------------------------------------------

# 83. Re-indexing Strategy

Never require a full destructive migration.

Use:

``` text
context v1
     │
     ├── still searchable
     │
     ▼
context v2 generated
     │
     ▼
atomic replacement
```

If v2 fails:

``` text
v1 remains active
```

This provides rollback by data version.

------------------------------------------------------------------------

# 84. Search Index Versioning

Ranking changes should be versioned too.

Example:

``` text
ranking_version = 4
context_version = 3
embedding_model = embed-v2
```

This makes search results reproducible.

A production debugging question becomes answerable:

> Why did Reel X rank above Reel Y?

You can inspect:

``` text
query
candidate scores
ranking version
context version
embedding model
```

------------------------------------------------------------------------

# 85. Explainability Internally

For debugging, store or log component scores:

``` json
{
  "reel_id": "...",
  "semantic_score": 0.91,
  "lexical_score": 0.83,
  "entity_score": 1.0,
  "action_score": 1.0,
  "attribute_score": 0.75,
  "final_score": 0.91
}
```

Do not necessarily expose all of this to users.

But engineers need it to diagnose bad ranking.

------------------------------------------------------------------------

# 86. Example Search Walkthrough

Query:

``` text
"red supra drifting on a mountain road"
```

## Step 1 --- Normalize

``` text
red supra drifting mountain road
```

## Step 2 --- Query understanding

``` text
entity: Toyota Supra
action: drifting
attribute: red
environment: mountain road
topic: automotive
```

## Step 3 --- Query embedding

``` text
q_embedding = E(query)
```

## Step 4 --- Lexical retrieval

``` text
50 candidates
```

## Step 5 --- Vector retrieval

``` text
50 candidates
```

## Step 6 --- Fusion

``` text
~70 unique candidates
```

## Step 7 --- Cheap scoring

``` text
70 → 30
```

## Step 8 --- Re-ranking

``` text
30 → 10
```

## Step 9 --- Confidence

``` text
10 → 4
```

## Step 10 --- Response

``` json
{
  "results": [
    "...",
    "...",
    "...",
    "..."
  ]
}
```

------------------------------------------------------------------------

# 87. Example of Why Hybrid Search Matters

Query:

``` text
"car doing donuts in a parking lot"
```

A Reel context might say:

``` text
summary:
"Sports car performing circular tire spins in an empty parking area."

actions:
["drifting", "spinning", "driving"]

environment:
["parking lot"]

topics:
["cars", "drifting"]
```

There may be no exact phrase:

``` text
"doing donuts"
```

in the stored context.

Lexical search alone could fail.

Semantic search understands that:

``` text
doing donuts
≈
circular tire spins
≈
car spinning
≈
parking-lot drifting
```

That is precisely why both retrieval mechanisms are required.

------------------------------------------------------------------------

# 88. Example Where Lexical Search Protects Precision

Query:

``` text
"Toyota Supra"
```

A semantic model might return:

``` text
Nissan Skyline
BMW M3
Toyota GT86
Toyota Supra
```

Lexical/entity matching gives the exact named entity a strong signal.

Hybrid retrieval therefore prevents semantic similarity from becoming
too broad.

------------------------------------------------------------------------

# 89. Query With No Good Result

Query:

``` text
"purple elephant cooking pasta inside a submarine"
```

Suppose candidates have scores:

``` text
0.31
0.29
0.27
0.24
```

The system should return:

``` json
{
  "results": [],
  "count": 0,
  "confidence": "low"
}
```

It should **not** return four vaguely semantic matches merely because
the UI has four slots.

------------------------------------------------------------------------

# 90. Save Flow in Detail

``` text
Browser
  │
  │ POST /api/v1/reels
  ▼
API Gateway
  │
  ▼
Authentication
  │
  ▼
Rate limit
  │
  ▼
Validate JSON
  │
  ▼
Canonicalize URL
  │
  ▼
Generate identity
  │
  ▼
INSERT ... ON CONFLICT
  │
  ├── existing ────────► return existing
  │
  └── new
       │
       ▼
     commit
       │
       ▼
 enqueue context job
       │
       ▼
     response
```

The job must only be enqueued after the database transaction is safely
committed.

------------------------------------------------------------------------

# 91. Transactional Job Enqueue

There is a subtle reliability problem:

``` text
DB insert succeeds
     ↓
process crashes
     ↓
queue message never published
```

Now the Reel exists forever without enrichment.

The robust solution is an **outbox pattern**.

------------------------------------------------------------------------

# 92. Outbox Pattern

Use:

``` text
reels
outbox_events
```

inside the same PostgreSQL transaction.

``` text
BEGIN
 │
 ├── INSERT reel
 │
 └── INSERT outbox event
 │
COMMIT
```

A publisher then reads:

``` text
outbox_events
```

and sends jobs to Redis Streams.

``` text
              PostgreSQL
          ┌─────────────────┐
          │ reels            │
          │ outbox_events    │
          └────────┬────────┘
                   │
                   ▼
             Outbox Worker
                   │
                   ▼
              Redis Stream
                   │
                   ▼
             Context Worker
```

This prevents the "database succeeded but queue failed" gap.

------------------------------------------------------------------------

# 93. Outbox Schema

``` sql
CREATE TABLE outbox_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    event_type TEXT NOT NULL,

    aggregate_id UUID NOT NULL,

    payload JSONB NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    published_at TIMESTAMPTZ
);

CREATE INDEX outbox_unpublished_idx
ON outbox_events(created_at)
WHERE published_at IS NULL;
```

------------------------------------------------------------------------

# 94. Outbox Idempotency

The publisher can publish the same event more than once.

Therefore the consumer must still be idempotent.

This is a general distributed-systems rule:

> At-least-once delivery requires idempotent consumers.

Do not attempt to make the entire system depend on perfect exactly-once
delivery.

------------------------------------------------------------------------

# 95. Failure Matrix

  -----------------------------------------------------------------------
  Failure                             Expected behavior
  ----------------------------------- -----------------------------------
  Invalid URL                         400/422, no DB write

  Duplicate URL                       Return existing Reel

  PostgreSQL unavailable              Save fails safely

  Redis unavailable                   Existing data remains correct;
                                      queue publication can retry

  Context model timeout               Retry

  Context schema invalid              Retry

  Embedding failure                   Keep lexical context, retry
                                      embedding

  Worker crash                        Job redelivered

  Duplicate job                       Idempotent upsert

  Search cache unavailable            Query DB directly

  Vector search unavailable           Fall back to lexical search if
                                      available

  FTS unavailable                     Fall back to semantic search if
                                      available

  Both indexes unavailable            Controlled 503

  Upstream metadata timeout           Retry with backoff

  Queue overloaded                    Reject or throttle new ingestion

  Search query too large              400

  Search rate exceeded                429
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 96. Search Degradation Strategy

The search system should degrade gracefully.

``` text
                    Search
                      │
             ┌────────┴─────────┐
             ▼                  ▼
           FTS                Vector
             │                  │
          healthy?           healthy?
             │                  │
             └────────┬─────────┘
                      ▼
                  Hybrid
```

If vector search fails:

``` text
FTS only
```

If FTS fails:

``` text
Vector only
```

If both fail:

``` text
503
```

This is better than making either search mechanism an absolute
availability dependency.

------------------------------------------------------------------------

# 97. Cache Failure

Redis is not correctness-critical.

If Redis goes down:

``` text
cache miss
    ↓
PostgreSQL
```

The application becomes slower, but data remains correct.

For queues, however, the outbox pattern ensures events are not lost when
Redis is unavailable.

------------------------------------------------------------------------

# 98. PostgreSQL Failure

If primary PostgreSQL fails:

``` text
writes → unavailable
```

Search can potentially continue against a replica depending on the
deployment.

At larger scale:

``` text
                    PostgreSQL
                     Primary
                       │
              replication
                       │
              ┌────────┴────────┐
              ▼                 ▼
           Replica 1         Replica 2
```

The system should clearly expose degraded state internally rather than
pretending writes succeeded.

------------------------------------------------------------------------

# 99. API Idempotency

For save operations, canonical URL uniqueness already provides most of
the required idempotency.

Optionally also support:

``` http
Idempotency-Key: 2c6...
```

This is useful if the client retries after a network timeout.

Flow:

``` text
Client
  │
  │ request
  ▼
Server processes
  │
  ▼
network timeout
  │
  ▼
Client retries same Idempotency-Key
  │
  ▼
server returns original result
```

------------------------------------------------------------------------

# 100. Concurrency

Two users submit:

``` text
https://www.instagram.com/reel/Cxyz123/
```

simultaneously.

Both canonicalize to:

``` text
https://www.instagram.com/reel/Cxyz123/
```

Both calculate the same identity.

Database:

``` sql
INSERT ...
ON CONFLICT (canonical_url)
DO NOTHING;
```

Only one Reel is created.

The outbox/job creation should also be guarded so that duplicate context
jobs do not become an uncontrolled problem.

------------------------------------------------------------------------

# 101. Job Deduplication

Use a unique constraint such as:

``` sql
CREATE UNIQUE INDEX one_active_context_job_per_reel
ON ingestion_jobs(reel_id)
WHERE status IN ('pending', 'processing', 'retrying');
```

This means a Reel cannot have multiple active enrichment jobs
accidentally created.

------------------------------------------------------------------------

# 102. Ingestion Job Table

``` sql
CREATE TABLE ingestion_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    reel_id UUID NOT NULL REFERENCES reels(reel_id),

    job_type TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    attempts INTEGER NOT NULL DEFAULT 0,

    next_attempt_at TIMESTAMPTZ,

    last_error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    started_at TIMESTAMPTZ,

    completed_at TIMESTAMPTZ
);
```

------------------------------------------------------------------------

# 103. Web Application Architecture

A clean web architecture is:

``` text
┌──────────────────────────────────────────────────┐
│                  NEXT.JS / REACT                 │
│                                                  │
│  Search UI    Save UI    Reel Cards    State     │
└───────────────────────┬──────────────────────────┘
                        │ HTTPS
                        ▼
┌──────────────────────────────────────────────────┐
│                  API GATEWAY                      │
│                                                  │
│ Auth │ Rate Limit │ Validation │ Request IDs     │
└───────────────────────┬──────────────────────────┘
                        │
            ┌───────────┴────────────┐
            ▼                        ▼
     Reel Service              Search Service
            │                        │
            ▼                        ▼
       PostgreSQL                PostgreSQL
            │                        │
            ▼                        ▼
        Outbox                  Redis Cache
            │
            ▼
      Redis Streams
            │
            ▼
      Context Workers
```

------------------------------------------------------------------------

# 104. Web UI Does Not Need to Know the Search Algorithm

The frontend should simply call:

``` text
GET /api/v1/search?q=...
```

It should not know:

-   embedding dimensions,
-   FTS,
-   HNSW,
-   RRF,
-   ranking weights,
-   model versions.

This keeps the API stable while the backend evolves.

------------------------------------------------------------------------

# 105. Reel Card API Contract

A search result should contain only what the UI needs.

Example:

``` json
{
  "reel_id": "uuid",
  "canonical_url": "https://www.instagram.com/reel/Cxyz123/",
  "thumbnail_url": "...",
  "title": "...",
  "creator": "...",
  "score": 0.91
}
```

Do not return the entire context object to every search result.

Context is primarily a backend search representation.

------------------------------------------------------------------------

# 106. Embed / Playback

The web UI can render an Instagram embed or link to Instagram.

The system does not proxy the video.

``` text
Browser
  │
  ├── API → metadata/search
  │
  └── Instagram → playback/embed
```

This keeps video bandwidth outside the platform.

The exact embedding mechanism should follow the current Instagram
developer/product requirements. Meta's current oEmbed documentation
states that Instagram oEmbed supports Reels and is intended for
embedding Instagram content on websites; current API behavior should be
verified during implementation because Meta has changed oEmbed
requirements and returned fields over time. \[2\]

------------------------------------------------------------------------

# 107. Upstream Dependencies

## Instagram

Used for permitted metadata/embed functionality.

Potential failures:

-   rate limiting,
-   timeout,
-   unavailable metadata,
-   API contract changes,
-   upstream outage.

Mitigations:

-   cache permitted responses,
-   retry transient failures,
-   strict timeouts,
-   version upstream integration,
-   isolate upstream failures from core database writes.

Do not assume an upstream field will exist forever.

------------------------------------------------------------------------

# 108. Embedding Model Dependency

The embedding service is an external or internal dependency.

Failure:

``` text
context generated
      ↓
embedding service unavailable
      ↓
embedding = NULL
```

The Reel should remain lexically searchable if `searchable_text` exists.

------------------------------------------------------------------------

# 109. Context Model Dependency

If context generation fails:

``` text
Reel identity remains
```

The system retries.

Never delete the Reel merely because AI enrichment failed.

------------------------------------------------------------------------

# 110. Downstream Dependencies

The API serves:

-   web frontend,
-   potentially future clients.

The API should be the stable contract.

Workers and database schemas are internal implementation details.

------------------------------------------------------------------------

# 111. API Versioning

Use:

``` text
/api/v1/...
```

When breaking changes occur:

``` text
/api/v2/...
```

Do not silently change the response schema of v1.

------------------------------------------------------------------------

# 112. OpenAPI

Generate OpenAPI documentation from the API implementation.

Document:

-   request schemas,
-   response schemas,
-   error schemas,
-   authentication,
-   rate limits,
-   examples.

This becomes the frontend/backend contract.

------------------------------------------------------------------------

# 113. Security Headers

The web application should use:

``` text
Content-Security-Policy
Strict-Transport-Security
X-Content-Type-Options
Referrer-Policy
Permissions-Policy
```

Avoid overly permissive CSP rules.

If Instagram embedding requires specific domains, explicitly allow only
those required domains.

------------------------------------------------------------------------

# 114. Secrets

Never store:

-   API keys,
-   model credentials,
-   database passwords,

in source control.

Use environment variables or a secret manager.

Example:

``` text
DATABASE_URL
REDIS_URL
MODEL_API_KEY
INSTAGRAM_API_CREDENTIALS
```

Do not return secrets in API errors.

------------------------------------------------------------------------

# 115. Data Privacy

Search telemetry should be minimized.

Store:

``` text
query hash or query text according to product/privacy policy
result IDs
rank
timestamp
click
```

Avoid unnecessary:

-   IP retention,
-   raw session data,
-   personal profile information.

Define retention periods for analytics data.

------------------------------------------------------------------------

# 116. Rate-Limit Architecture

``` text
                 Request
                    │
                    ▼
             Authentication
                    │
                    ▼
             Redis limiter
                    │
             ┌──────┴──────┐
             ▼             ▼
          allowed        blocked
             │             │
             ▼             ▼
           API             429
```

Use different buckets:

``` text
user:search
user:save
ip:search
ip:save
```

This prevents a single user or IP from consuming the entire service.

------------------------------------------------------------------------

# 117. Search Cache Poisoning

Cache keys must be normalized.

For example:

``` text
"RED SUPRA"
"red supra"
" red   supra "
```

should normalize consistently.

But do not normalize away semantic information.

Use:

``` text
Unicode normalization
trim
collapse whitespace
case normalization where appropriate
```

Then:

``` text
cache key =
search:v3:{normalized_query}
```

------------------------------------------------------------------------

# 118. Search Cache Stampede

If a popular query expires for thousands of users simultaneously:

``` text
cache expires
     │
     ├── request 1 → DB
     ├── request 2 → DB
     ├── request 3 → DB
     ├── ...
```

Use:

-   request coalescing,
-   short distributed locks,
-   stale-while-revalidate.

For example:

``` text
cache stale
   │
   ├── return stale
   └── one worker refreshes
```

This prevents a hot query from overwhelming PostgreSQL.

------------------------------------------------------------------------

# 119. Database Correctness Invariants

The system should enforce these invariants:

### Identity

``` text
canonical_url is unique
```

### Reel ID

``` text
same canonical URL → same identity
```

### Context

``` text
one active context per Reel
```

### Searchability

``` text
ready Reel → valid search representation
```

### Jobs

``` text
one active enrichment job per Reel
```

### API

``` text
search response ≤ 4 results
```

These invariants should be tested automatically.

------------------------------------------------------------------------

# 120. Testing Strategy

## Unit tests

Test:

-   URL parser,
-   canonicalizer,
-   shortcode validation,
-   query normalization,
-   scoring,
-   RRF,
-   confidence thresholds.

## Integration tests

Test:

-   PostgreSQL,
-   Redis,
-   queue,
-   context worker,
-   outbox,
-   search.

## End-to-end tests

Test:

``` text
Browser
 → API
 → DB
 → Queue
 → Worker
 → Search
 → Browser
```

------------------------------------------------------------------------

# 121. Canonicalization Test Cases

Test:

``` text
https://instagram.com/reel/C123/
https://www.instagram.com/reel/C123/
https://www.instagram.com/reel/C123/?utm_source=x
https://www.instagram.com/reel/C123/#abc
```

All should produce:

``` text
https://www.instagram.com/reel/C123/
```

Reject:

``` text
https://instagram.com/p/C123/
https://instagram.com/stories/foo/123/
https://evilinstagram.com/reel/C123/
https://instagram.com.evil.com/reel/C123/
```

------------------------------------------------------------------------

# 122. Concurrency Tests

Start 100 simultaneous save requests for the same canonical URL.

Expected:

``` text
1 Reel
1 logical context job
0 duplicate Reel records
```

This test is extremely important.

------------------------------------------------------------------------

# 123. Worker Failure Tests

Simulate:

``` text
worker crashes after context generation
worker crashes after DB write
worker crashes before acknowledgement
Redis disconnects
model timeout
database timeout
```

Verify:

``` text
no corrupted context
no permanent missing job
no duplicate context
eventual recovery
```

------------------------------------------------------------------------

# 124. Search Quality Tests

For every benchmark query:

``` text
retrieve candidates
rank candidates
calculate:
Precision@4
Recall@50
MRR
NDCG@4
```

Track these before and after every ranking change.

------------------------------------------------------------------------

# 125. Load Testing

Test separately:

### Search

``` text
100 RPS
500 RPS
1000 RPS
```

### Ingestion

``` text
10 URLs/sec
100 URLs/sec
```

### Worker processing

Measure:

``` text
queue lag
job throughput
model latency
failure rate
```

Do not assume search and enrichment have the same scaling profile.

------------------------------------------------------------------------

# 126. Capacity Planning

The system has two independent workloads:

``` text
                  Platform
                 /        \
                /          \
          Search           Enrichment
             │                 │
        CPU/DB intensive    AI/network intensive
```

Search needs:

-   low latency,
-   database/index performance.

Enrichment needs:

-   workers,
-   model capacity,
-   upstream API capacity.

Scale them independently.

------------------------------------------------------------------------

# 127. Worker Horizontal Scaling

``` text
                 Redis Stream
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
    Worker 1      Worker 2      Worker 3
        │             │             │
        └─────────────┼─────────────┘
                      ▼
                  PostgreSQL
```

Each worker claims jobs independently.

Use consumer groups / acknowledgements and recovery of pending jobs.

------------------------------------------------------------------------

# 128. Deployment

Initial deployment:

``` text
Docker Compose / Kubernetes
```

Components:

``` text
frontend
api
worker
postgres
redis
```

Optional:

``` text
outbox publisher
```

The outbox publisher can initially run as part of the worker service if
operational simplicity is more important than strict process separation.

------------------------------------------------------------------------

# 129. Production Topology

``` text
                         INTERNET
                             │
                             ▼
                      ┌────────────┐
                      │ CDN / WAF  │
                      └─────┬──────┘
                            │
                            ▼
                      ┌────────────┐
                      │ Load Bal.  │
                      └─────┬──────┘
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
              API 1                  API 2
                 │                     │
                 └──────────┬──────────┘
                            ▼
                       PostgreSQL
                       /        \
                  Primary      Replica
                     │
                     ▼
                   Redis
                     │
                     ▼
              Worker Pool
```

------------------------------------------------------------------------

# 130. Backups

PostgreSQL must be backed up.

At minimum:

-   daily full backups,
-   point-in-time recovery where practical,
-   tested restore procedure.

Backups are not useful if restores are never tested.

------------------------------------------------------------------------

# 131. Disaster Recovery

Document:

``` text
RPO
RTO
```

Example targets:

``` text
RPO: 15 minutes
RTO: 1 hour
```

These are illustrative.

The correct values depend on the product requirement.

Redis cache loss should not cause data loss because PostgreSQL is
authoritative and the outbox protects pending events.

------------------------------------------------------------------------

# 132. Monitoring Dashboard

Monitor:

### API

``` text
request rate
error rate
p50/p95/p99 latency
429 rate
```

### PostgreSQL

``` text
CPU
memory
connections
slow queries
replication lag
index size
cache hit ratio
```

### Redis

``` text
memory
evictions
latency
queue depth
pending jobs
```

### Workers

``` text
throughput
failure rate
retry count
queue age
model latency
```

### Search

``` text
zero-result rate
Precision@4
Recall@50
NDCG@4
click-through rate
candidate counts
ranking latency
```

------------------------------------------------------------------------

# 133. Alerting

Important alerts:

``` text
API error rate > threshold
search p95 > threshold
queue lag > threshold
worker failure rate > threshold
database connections exhausted
replication lag high
Redis memory high
context generation failure spike
embedding failure spike
zero-result rate sudden increase
```

A sudden search-quality degradation may indicate a bad context/model
deployment even if infrastructure metrics look healthy.

------------------------------------------------------------------------

# 134. Model Deployment Safety

Never deploy a new context model globally without evaluation.

Use:

``` text
old model
   │
   ├── benchmark
   │
   ├── offline evaluation
   │
   └── shadow generation
           │
           ▼
       compare
           │
           ▼
       rollout
```

------------------------------------------------------------------------

# 135. Shadow Context Generation

For a new model:

``` text
Production Reel
     │
     ├── old model → production context
     │
     └── new model → shadow context
```

Compare:

``` text
coverage
entity extraction
semantic retrieval
ranking metrics
```

Only then replace the old context.

------------------------------------------------------------------------

# 136. Search Ranking Deployment

Ranking changes should also be versioned:

``` text
ranking-v1
ranking-v2
ranking-v3
```

Evaluate:

``` text
NDCG@4
MRR
Precision@4
latency
```

before production rollout.

------------------------------------------------------------------------

# 137. Blue/Green Ranking

A simple approach:

``` text
             Search
                │
        ┌───────┴───────┐
        ▼               ▼
    ranking-v1      ranking-v2
        │               │
        └───────┬───────┘
                ▼
             compare
```

Eventually:

``` text
v2 → 100%
```

If metrics degrade:

``` text
rollback → v1
```

------------------------------------------------------------------------

# 138. End-to-End Example

Suppose a user saves:

``` text
https://www.instagram.com/reel/Cabc123/
```

## Request

``` http
POST /api/v1/reels
```

## Canonicalization

``` text
https://www.instagram.com/reel/Cabc123/
```

## Identity

``` text
SHA-256(canonical_url)
```

## Database

``` text
reel created
status = pending
```

## Outbox

``` text
GENERATE_REEL_CONTEXT
```

## Worker

Retrieves permitted metadata/visual inputs.

## Context

``` json
{
  "summary": "A red Toyota Supra drifting along a mountain road.",
  "objects": ["Toyota Supra", "sports car", "mountain road"],
  "actions": ["drifting", "driving"],
  "entities": ["Toyota Supra"],
  "topics": ["cars", "drifting", "automotive"],
  "environments": ["mountain", "road", "sunset"],
  "visual_style": ["cinematic"],
  "keywords": [
    "red sports car",
    "Toyota Supra drift",
    "mountain drifting"
  ]
}
```

## Search text

``` text
A red Toyota Supra drifting along a mountain road.
Toyota Supra sports car mountain road.
drifting driving.
Toyota Supra.
cars drifting automotive.
mountain road sunset.
cinematic.
red sports car Toyota Supra drift mountain drifting.
```

## Embedding

``` text
E(context)
```

## Index

``` text
GIN(search_vector)
HNSW(embedding)
```

Later the user searches:

``` text
"red supra mountain drift"
```

The query goes through:

``` text
normalization
→ entity extraction
→ embedding
→ lexical retrieval
→ vector retrieval
→ fusion
→ reranking
→ confidence
→ top 4
```

------------------------------------------------------------------------

# 139. Complete System Flow

``` text
                              ┌───────────────┐
                              │   WEB USER    │
                              └───────┬───────┘
                                      │
                       ┌──────────────┴──────────────┐
                       │                             │
                       ▼                             ▼
                  SAVE URL                        SEARCH
                       │                             │
                       ▼                             ▼
               Authentication                Authentication
                       │                             │
                       ▼                             ▼
                  Rate Limit                  Rate Limit
                       │                             │
                       ▼                             ▼
                URL Validator               Query Normalizer
                       │                             │
                       ▼                             ▼
               Canonicalizer                Query Understanding
                       │                             │
                       ▼                             ▼
                 reel_id                   Query Embedding
                       │                             │
                       ▼                    ┌────────┴────────┐
                 PostgreSQL                 │                 │
                       │                    ▼                 ▼
                       ▼                  FTS             HNSW
                   Outbox                  │                 │
                       │                    └────────┬────────┘
                       ▼                             ▼
                Redis Stream                  Candidate Fusion
                       │                             │
                       ▼                             ▼
                 Worker Pool                    Re-ranker
                       │                             │
          ┌────────────┼────────────┐                │
          ▼            ▼            ▼                ▼
       Metadata     Visual       Context        Confidence Gate
       retrieval   analysis     generation          │
          │            │            │                ▼
          └────────────┼────────────┘             TOP 4
                       │
                       ▼
                 Schema validation
                       │
                       ▼
                    Embedding
                       │
                       ▼
               Atomic DB update
                       │
                       ▼
                 Search indexes
```

------------------------------------------------------------------------

# 140. Key Design Decisions

## Decision 1 --- URL is identity

``` text
canonical URL → unique Reel
```

Reason:

-   deterministic,
-   explainable,
-   easy to enforce,
-   no false visual merging.

## Decision 2 --- No user descriptions

Reason:

-   eliminates keyword stuffing,
-   eliminates inconsistent quality,
-   makes indexing deterministic,
-   simplifies UX.

## Decision 3 --- Structured context

Reason:

-   richer search representation,
-   supports filters,
-   supports ranking,
-   easier debugging.

## Decision 4 --- Hybrid search

Reason:

-   lexical search provides precision,
-   semantic search provides recall,
-   neither is sufficient alone.

## Decision 5 --- Re-ranking

Reason:

-   candidate retrieval is optimized for recall,
-   final ranking is optimized for precision.

## Decision 6 --- Four-result UI

Reason:

-   reduces cognitive load,
-   makes ranking quality matter,
-   avoids overwhelming the user.

## Decision 7 --- Confidence gate

Reason:

-   four weak results are worse than two strong results.

## Decision 8 --- PostgreSQL + pgvector

Reason:

-   one source of truth,
-   fewer moving parts,
-   relational + lexical + vector search,
-   straightforward self-hosting.

## Decision 9 --- Outbox

Reason:

-   prevents database/queue inconsistency.

## Decision 10 --- Version everything important

``` text
context_version
model_version
embedding_version
ranking_version
```

Reason:

-   reproducibility,
-   rollback,
-   debugging,
-   safe model evolution.

------------------------------------------------------------------------

# 141. What Changed From the Original Architecture

The original system stored:

``` text
user description
oEmbed description
AI caption
```

and searched across them. It also included YouTube, pHash duplicate
detection, moderation, and live Brave discovery.
fileciteturn0file0L85-L90

The revised system instead uses:

``` text
                         OLD
                          │
                URL + user description
                          │
                          ▼
                    FTS search


                         NEW
                          │
                       URL only
                          │
                          ▼
                  canonical identity
                          │
                          ▼
                  structured context
                          │
                 ┌────────┴────────┐
                 ▼                 ▼
              lexical           semantic
                 │                 │
                 └────────┬────────┘
                          ▼
                       rerank
                          │
                          ▼
                      top four
```

This makes the architecture much more coherent.

## 141.1 Search Latency & UI Architecture Refinements

During real-world benchmarking on Windows environments connecting to managed cloud databases (Neon PostgreSQL in AWS Singapore and Redis Cloud), several critical runtime bottlenecks were diagnosed and resolved:

``` text
INITIAL STATE (49,088 ms)
  ├── SentenceTransformer remote network timeout to huggingface.co (49,088 ms)
  ├── Serialized lexical → vector retrieval on cold DB connections (~1,200 ms)
  ├── 384-dimensional float vector wire transfer in SQL SELECT (~250 KB payload)
  └── Single-threaded asyncio event loop starvation under blocking CPU/DB calls

OPTIMIZED STATE (~380 ms cold / ~38 ms cached / 0.0 ms L1)
  ├── HF_HUB_OFFLINE=1 + local_files_only=True + startup lifespan pre-warming (35 ms)
  ├── Concurrent ThreadPoolExecutor(max_workers=8) with minconn=4 pre-warmed pool (~280 ms)
  ├── SQL projection trimming (omits c.embedding payload, cutting wire data to ~8 KB)
  ├── FastAPI sync thread-pool offloading (def search_reels) preserving event loop health
  ├── In-memory LRU vector cache (@lru_cache(maxsize=1024)) for instant re-encoding (0.0 ms)
  ├── Multi-tier L1 (In-Memory) + L2 (Redis Cloud) cache with negative caching
  └── Dynamic client-side search history (localStorage), eliminating static mock query clutter
```

### Measured Benchmark Progression:

| Lifecycle Phase | Baseline Latency | Optimized Latency | Speedup |
| :--- | :--- | :--- | :--- |
| **Embedding Generation** | `49,088 ms` | **`35 ms`** (0 ms cached) | **~1,400x** |
| **Full-Roundtrip Cold Search** | `~51,000 ms` | **`~380 ms`** | **~134x** |
| **Cached / Repeat Search** | `~50,000 ms` | **`~38 ms`** | **~1,315x** |
| **L1 In-Memory Hit** | `N/A` | **`< 1 ms`** | **Instant** |

------------------------------------------------------------------------

# 142. Recommended V1 Implementation Order

Do not build everything simultaneously.

## Phase 1 --- Identity

Build:

``` text
URL validation
canonicalization
reel_id
PostgreSQL
POST /reels
```

Tests:

``` text
same URL variants → same identity
invalid URLs → rejected
concurrent saves → one Reel
```

## Phase 2 --- Context

Build:

``` text
outbox
Redis Streams
worker
context schema
context validation
```

## Phase 3 --- Lexical search

Build:

``` text
search_vector
GIN index
GET /search
```

This gives you the first working search system.

## Phase 4 --- Embeddings

Add:

``` text
embedding generation
pgvector
HNSW
```

## Phase 5 --- Hybrid retrieval

Add:

``` text
FTS
+
vector
→ RRF
```

## Phase 6 --- Re-ranking

Add:

``` text
candidate pool
→ reranker
→ confidence
→ top 4
```

## Phase 7 --- Search analytics

Add:

``` text
search logs
click events
evaluation dataset
Precision@4
NDCG@4
MRR
```

## Phase 8 --- Optimization

Tune:

``` text
HNSW
database indexes
cache
ranking weights
model latency
worker concurrency
```

------------------------------------------------------------------------

# 143. V1 Minimal Infrastructure

A practical initial deployment is:

``` text
                ┌──────────────────────┐
                │       Web UI         │
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │         API          │
                └───────┬───────┬──────┘
                        │       │
                        ▼       ▼
                  PostgreSQL   Redis
                     │          │
                     │          ▼
                     │       Workers
                     │          │
                     └──────────┘
```

One PostgreSQL instance with pgvector and one Redis instance are enough
for the first meaningful deployment.

Do not prematurely introduce:

``` text
Kafka
Elasticsearch
OpenSearch
Cassandra
Kubernetes
multiple databases
```

unless measured scale actually requires them.

------------------------------------------------------------------------

# 144. When to Introduce a Dedicated Search Engine

PostgreSQL + pgvector is the right starting point.

Consider OpenSearch/Elasticsearch only when measurements demonstrate a
real need such as:

-   extremely large corpus,
-   complex faceting,
-   advanced lexical ranking,
-   high search throughput,
-   distributed search requirements,
-   operational need for a dedicated search cluster.

Migration should be possible because the application already has a clean
abstraction:

``` text
SearchService
    │
    ├── PostgreSQLSearchProvider
    │
    └── FutureSearchProvider
```

------------------------------------------------------------------------

# 145. Search Service Interface

Keep the application independent of the storage implementation:

``` python
class SearchProvider:

    async def search(
        self,
        query: str,
        limit: int = 4
    ) -> SearchResponse:
        ...
```

Implementation:

``` text
SearchProvider
     │
     └── PostgresHybridSearch
```

Later:

``` text
SearchProvider
     │
     ├── PostgresHybridSearch
     └── OpenSearchHybridSearch
```

------------------------------------------------------------------------

# 146. Context Service Interface

``` python
class ContextGenerator:

    async def generate(
        self,
        reel: ReelInput
    ) -> ReelContext:
        ...
```

The worker does not care whether context comes from:

-   one model,
-   multiple models,
-   an API,
-   a local GPU.

This makes the architecture replaceable.

------------------------------------------------------------------------

# 147. Final Architectural Contract

The entire system can ultimately be described in seven statements:

1.  **A Reel is identified by its canonical Instagram URL.**
2.  **Users submit URLs, not searchable descriptions.**
3.  **The system generates structured Reel context.**
4.  **Context is represented both lexically and semantically.**
5.  **Search retrieves broadly using hybrid retrieval and ranks narrowly
    using a re-ranker.**
6.  **The UI displays no more than four high-confidence results.**
7.  **Every asynchronous operation is idempotent, observable, retryable,
    and versioned.**

------------------------------------------------------------------------

# 148. Final Reference Architecture

``` text
                                  INTERNET
                                      │
                                      ▼
                           ┌────────────────────┐
                           │      WEB CLIENT     │
                           │   React / Next.js   │
                           └─────────┬──────────┘
                                     │ HTTPS
                                     ▼
                           ┌────────────────────┐
                           │    API GATEWAY     │
                           │                    │
                           │ Auth               │
                           │ Rate limiting      │
                           │ Validation         │
                           │ Request IDs        │
                           └─────────┬──────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
                    ▼                                 ▼
             ┌───────────────┐                 ┌───────────────┐
             │ Reel Service  │                 │ Query Service │
             └───────┬───────┘                 └───────┬───────┘
                     │                                   │
                     ▼                                   ▼
              URL Canonicalizer                  Query Understanding
                     │                                   │
                     ▼                                   ▼
               Reel Identity                       Embedding
                     │                                   │
                     ▼                          ┌────────┴────────┐
              ┌─────────────┐                    ▼                 ▼
              │ PostgreSQL  │                  FTS              HNSW
              │             │                    │                 │
              │ reels       │                    └────────┬────────┘
              │ context     │                             ▼
              │ jobs        │                       Candidate Pool
              │ outbox      │                             │
              └──────┬──────┘                             ▼
                     │                              Re-ranker
                     ▼                                   │
              Outbox Publisher                           ▼
                     │                              Confidence
                     ▼                                   │
                Redis Stream                             ▼
                     │                                  TOP 4
                     ▼
              ┌─────────────┐
              │   Workers   │
              │             │
              │ Metadata    │
              │ Vision      │
              │ Context     │
              │ Embedding   │
              └──────┬──────┘
                     │
                     ▼
               Atomic update
                     │
                     ▼
                PostgreSQL
                     │
          ┌──────────┴───────────┐
          ▼                      ▼
       GIN index              HNSW index
          │                      │
          └──────────┬───────────┘
                     ▼
                Search Service
                     │
                     ▼
                  Web UI
```

------------------------------------------------------------------------

# 149. Conclusion

The central improvement is not adding more infrastructure. It is
changing what the system considers a Reel's searchable representation.

The old approach was essentially:

``` text
Reel URL
    +
human-written description
    ↓
text search
```

The new architecture is:

``` text
                         Reel URL
                            │
                            ▼
                   deterministic identity
                            │
                            ▼
                    automatic context
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
        structured data              embedding
              │                           │
              ▼                           ▼
        lexical search              semantic search
              │                           │
              └─────────────┬─────────────┘
                            ▼
                     candidate fusion
                            │
                            ▼
                         re-ranking
                            │
                            ▼
                      confidence gate
                            │
                            ▼
                       maximum 4
```

This gives the platform a much stronger technical foundation:

-   **Identity is deterministic.**
-   **Search context is controlled by the system.**
-   **Users cannot poison the description index with arbitrary text.**
-   **Lexical search handles exact concepts.**
-   **Semantic search handles natural-language intent.**
-   **Re-ranking handles precision.**
-   **Confidence prevents irrelevant filler results.**
-   **PostgreSQL remains the source of truth.**
-   **pgvector avoids an unnecessary search cluster in V1.**
-   **The outbox prevents lost asynchronous work.**
-   **Idempotent workers make retries safe.**
-   **Versioning makes model evolution reversible.**
-   **Rate limiting and SSRF controls protect the public web service.**
-   **Search-quality metrics make ranking improvements measurable rather
    than subjective.**

The result is a system that is not merely an index of Instagram URLs. It
is a **semantic retrieval system purpose-built for finding the right
Instagram Reel from a natural-language description of what the user
remembers seeing.**

------------------------------------------------------------------------

## References

**\[1\] pgvector documentation** --- HNSW, vector indexing, hybrid
search, filtering, iterative scans, and re-ranking.\
urlpgvector documentationhttps://github.com/pgvector/pgvector

**\[2\] Meta / Instagram oEmbed documentation** --- Instagram embedding
and current oEmbed behavior. Meta's API behavior and available fields
should be verified against the current developer documentation at
implementation time because the API has changed over time.\
urlMeta Instagram oEmbed
documentationhttps://developers.facebook.com/docs/instagram-platform/oembed/

------------------------------------------------------------------------

# Appendix A --- Compact API Contract

``` text
POST   /api/v1/reels
GET    /api/v1/reels/{reel_id}
GET    /api/v1/search?q={query}
POST   /api/v1/search/events
GET    /health
GET    /ready
```

### Save

``` json
{
  "url": "https://www.instagram.com/reel/Cxyz123/"
}
```

### Search

``` json
{
  "query": "red supra drifting on a mountain road",
  "results": [],
  "count": 0,
  "confidence": "low"
}
```

### Error

``` json
{
  "error": {
    "code": "INVALID_INSTAGRAM_REEL_URL",
    "message": "The supplied URL is not a supported Instagram Reel URL.",
    "request_id": "req_123"
  }
}
```

------------------------------------------------------------------------

# Appendix B --- Core Invariants

``` text
canonical_url UNIQUE

same canonical URL
        ↓
same Reel

one active context
        ↓
one searchable representation

one active ingestion job
        ↓
bounded work

search result count
        ↓
<= 4

low confidence
        ↓
do not fill result slots

Redis unavailable
        ↓
correctness preserved

worker crashes
        ↓
job retry

model changes
        ↓
context version changes

ranking changes
        ↓
ranking version changes
```

------------------------------------------------------------------------

# Appendix C --- One-Page Mental Model

``` text
                 SAVE
                  │
                  ▼
             URL only
                  │
                  ▼
          Canonicalize URL
                  │
                  ▼
            Reel identity
                  │
                  ▼
              PostgreSQL
                  │
                  ▼
               Outbox
                  │
                  ▼
                Queue
                  │
                  ▼
               Worker
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
     metadata   vision    context
        │         │         │
        └─────────┼─────────┘
                  ▼
             search text
                  +
              embedding
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
       FTS                Vector
        │                   │
        └─────────┬─────────┘
                  ▼
              Reranker
                  │
                  ▼
            Confidence
                  │
                  ▼
               TOP 4
                  │
                  ▼
                 WEB
```

**This is the reference architecture for implementation.**
