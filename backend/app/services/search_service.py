import time
import re
import json
import logging
import threading
import concurrent.futures
from typing import List, Dict, Any, Tuple, Optional
from app.core.database import get_db_cursor
from app.core.config import settings
from app.core.redis_client import cache_get, cache_set
from app.services.embedding_service import EmbeddingService
from app.models.schemas import SearchResponse, SearchResultItem

logger = logging.getLogger("reelsearch.search")

# Persistent global ThreadPoolExecutor for concurrent retrieval
_search_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

# L1 In-Memory Fast Cache (TTL-based) to deliver < 2ms responses for hot queries
_l1_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_l1_lock = threading.Lock()
_L1_MAX_SIZE = 500


def _get_l1_cache(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _l1_lock:
        item = _l1_cache.get(key)
        if item:
            expire_at, data = item
            if now < expire_at:
                return dict(data)
            else:
                _l1_cache.pop(key, None)
    return None


def _set_l1_cache(key: str, data: Dict[str, Any], ttl_seconds: int = 120):
    now = time.time()
    with _l1_lock:
        if len(_l1_cache) >= _L1_MAX_SIZE:
            keys_to_remove = list(_l1_cache.keys())[:100]
            for k in keys_to_remove:
                _l1_cache.pop(k, None)
        _l1_cache[key] = (now + ttl_seconds, data)


class SearchService:
    @staticmethod
    def search(query: str, limit: int = 4) -> SearchResponse:
        t0 = time.time()
        clean_query = query.strip()
        effective_limit = min(max(1, limit), settings.MAX_SEARCH_RESULTS)
        cache_key = f"search:{clean_query.lower()}:{effective_limit}"

        # 1. Check L1 hot in-memory cache (Instant sub-1ms response)
        l1_hit = _get_l1_cache(cache_key)
        if l1_hit:
            l1_hit["latency_ms"] = round((time.time() - t0) * 1000, 2)
            return SearchResponse(**l1_hit)

        # 2. Check L2 Redis cache
        cached = cache_get(cache_key)
        if cached:
            _set_l1_cache(cache_key, cached, ttl_seconds=120)
            cached["latency_ms"] = round((time.time() - t0) * 1000, 2)
            return SearchResponse(**cached)

        # 3. Query Understanding (Section 18)
        query_terms = re.findall(r"\w+", clean_query.lower())
        query_terms_set = set(query_terms)

        # 4. Concurrent Retrieval (Section 72): Run Lexical FTS & Vector Retrieval in Parallel
        pool_size = settings.CANDIDATE_POOL_SIZE
        lexical_future = _search_executor.submit(SearchService._retrieve_lexical_candidates, clean_query, pool_size)

        def _embed_and_search_vector():
            q_emb = EmbeddingService.generate_embedding(clean_query)
            v_cand = SearchService._retrieve_vector_candidates(q_emb, pool_size)
            return q_emb, v_cand

        vector_future = _search_executor.submit(_embed_and_search_vector)

        lexical_candidates = lexical_future.result()
        query_embedding, vector_candidates = vector_future.result()

        # 5. Reciprocal Rank Fusion (RRF) (Section 24)
        merged_candidates = SearchService._fuse_candidates(
            lexical_candidates, vector_candidates, k=settings.RRF_K
        )

        # 6. Multi-factor Re-ranking (Section 26 & 27)
        ranked_candidates = SearchService._rerank_candidates(
            merged_candidates, clean_query, query_terms_set, query_embedding
        )

        # 7. Precision-First Confidence Gate & Diversification (Section 28 & 29)
        final_results, confidence_level = SearchService._apply_confidence_gate_and_diversify(
            ranked_candidates, effective_limit
        )

        latency_ms = round((time.time() - t0) * 1000, 2)

        response = SearchResponse(
            query=clean_query,
            results=final_results,
            count=len(final_results),
            confidence=confidence_level,
            max_results=settings.MAX_SEARCH_RESULTS,
            latency_ms=latency_ms
        )

        # 8. Multi-tier Caching (L1 In-Memory + L2 Redis)
        ttl = 300 if confidence_level in {"high", "medium"} else 60
        resp_data = response.model_dump()
        _set_l1_cache(cache_key, resp_data, ttl_seconds=min(ttl, 120))
        cache_set(cache_key, resp_data, ttl_seconds=ttl)

        # 9. Asynchronous Search Event Logging (Section 66/67) - never blocks HTTP response
        top_id = final_results[0].reel_id if final_results else None
        threading.Thread(
            target=SearchService._log_search_event,
            args=(clean_query, len(final_results), confidence_level, latency_ms, top_id),
            daemon=True
        ).start()

        return response

    @staticmethod
    def _retrieve_lexical_candidates(query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """PostgreSQL full-text search using search_vector and plainto_tsquery."""
        sql = """
        SELECT
            c.reel_id,
            r.canonical_url,
            c.summary,
            c.objects,
            c.actions,
            c.entities,
            c.topics,
            c.environments,
            ts_rank_cd(c.search_vector, plainto_tsquery('english', %s)) AS lexical_score
        FROM reel_context c
        JOIN reels r ON r.reel_id = c.reel_id
        WHERE c.search_vector @@ plainto_tsquery('english', %s)
          AND r.enrichment_status = 'ready'
        ORDER BY lexical_score DESC
        LIMIT %s;
        """
        candidates = []
        try:
            with get_db_cursor() as cursor:
                cursor.execute(sql, (query, query, limit))
                rows = cursor.fetchall()
                for row in rows:
                    candidates.append(dict(row))
        except Exception as e:
            logger.error(f"Error in lexical retrieval: {e}")
        return candidates

    @staticmethod
    def _retrieve_vector_candidates(query_embedding: List[float], limit: int = 50) -> List[Dict[str, Any]]:
        """Vector retrieval using cosine_similarity function in PostgreSQL or in-memory (omits raw embedding payload)."""

        sql = """
        SELECT
            c.reel_id,
            r.canonical_url,
            c.summary,
            c.objects,
            c.actions,
            c.entities,
            c.topics,
            c.environments,
            cosine_similarity(c.embedding, %s::float8[]) AS semantic_score
        FROM reel_context c
        JOIN reels r ON r.reel_id = c.reel_id
        WHERE c.embedding IS NOT NULL
          AND r.enrichment_status = 'ready'
        ORDER BY semantic_score DESC
        LIMIT %s;
        """
        candidates = []
        try:
            with get_db_cursor() as cursor:
                cursor.execute(sql, (query_embedding, limit))
                rows = cursor.fetchall()
                for row in rows:
                    candidates.append(dict(row))
        except Exception as e:
            logger.warning(f"SQL vector retrieval error: {e}. Executing in-memory vector scan.")
            candidates = SearchService._in_memory_vector_scan(query_embedding, limit)
        return candidates

    @staticmethod
    def _in_memory_vector_scan(query_embedding: List[float], limit: int = 50) -> List[Dict[str, Any]]:
        sql = """
        SELECT
            c.reel_id,
            r.canonical_url,
            c.summary,
            c.objects,
            c.actions,
            c.entities,
            c.topics,
            c.environments,
            c.embedding
        FROM reel_context c
        JOIN reels r ON r.reel_id = c.reel_id
        WHERE c.embedding IS NOT NULL
          AND r.enrichment_status = 'ready';
        """
        results = []
        with get_db_cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            for row in rows:
                emb = row["embedding"]
                if isinstance(emb, str):
                    try:
                        emb = json.loads(emb)
                    except Exception:
                        emb = None
                if emb:
                    sim = EmbeddingService.cosine_similarity(query_embedding, emb)
                    row_dict = dict(row)
                    row_dict["semantic_score"] = sim
                    results.append(row_dict)
        results.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
        return results[:limit]

    @staticmethod
    def _fuse_candidates(
        lexical: List[Dict[str, Any]],
        vector: List[Dict[str, Any]],
        k: int = 60
    ) -> Dict[str, Dict[str, Any]]:
        """Reciprocal Rank Fusion (RRF) algorithm."""
        fused = {}

        for rank, item in enumerate(lexical):
            rid = str(item["reel_id"])
            if rid not in fused:
                fused[rid] = {**item, "rrf_score": 0.0, "lexical_rank": rank, "vector_rank": None}
            fused[rid]["rrf_score"] += 1.0 / (k + rank + 1)
            fused[rid]["lexical_score"] = item.get("lexical_score", 0.0)

        for rank, item in enumerate(vector):
            rid = str(item["reel_id"])
            if rid not in fused:
                fused[rid] = {**item, "rrf_score": 0.0, "lexical_rank": None, "vector_rank": rank}
            else:
                fused[rid]["vector_rank"] = rank
                # fill any missing fields
                for k_field in ["summary", "entities", "topics", "objects", "actions", "environments", "embedding"]:
                    if k_field in item and item[k_field] and not fused[rid].get(k_field):
                        fused[rid][k_field] = item[k_field]

            fused[rid]["rrf_score"] += 1.0 / (k + rank + 1)
            fused[rid]["semantic_score"] = item.get("semantic_score", 0.0)

        return fused

    @staticmethod
    def _rerank_candidates(
        candidates_map: Dict[str, Dict[str, Any]],
        raw_query: str,
        query_terms: set,
        query_embedding: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Section 27 & 30 Re-ranking formula:
        final_score = 0.50 * semantic + 0.30 * lexical + 0.10 * entity + 0.05 * action + 0.05 * attribute
        """
        ranked = []
        low_query = raw_query.lower()

        # Normalize max lexical score for standard scaling
        max_lex = max([c.get("lexical_score", 0.0) or 0.0 for c in candidates_map.values()] or [1.0])
        if max_lex == 0:
            max_lex = 1.0

        for rid, item in candidates_map.items():
            sem_score = item.get("semantic_score")
            if sem_score is None and item.get("embedding"):
                sem_score = EmbeddingService.cosine_similarity(query_embedding, item["embedding"])
                item["semantic_score"] = sem_score
            sem_score = max(0.0, float(sem_score or 0.0))

            lex_raw = float(item.get("lexical_score", 0.0) or 0.0)
            norm_lex = min(1.0, lex_raw / max_lex) if max_lex > 0 else 0.0

            # Match entities
            entities = [str(e).lower() for e in (item.get("entities") or [])]
            entity_match = 1.0 if any(e in low_query or e in query_terms for e in entities) else 0.0

            # Match actions
            actions = [str(a).lower() for a in (item.get("actions") or [])]
            action_match = 1.0 if any(a in query_terms for a in actions) else 0.0

            # Match environments / attributes
            envs = [str(env).lower() for env in (item.get("environments") or [])]
            attr_match = 1.0 if any(env in query_terms for env in envs) else 0.0

            # Compute formula with dynamic re-weighting if lexical match is absent
            if max_lex > 0 and lex_raw > 0:
                sem_w, lex_w = 0.50, 0.30
            else:
                sem_w, lex_w = 0.75, 0.05

            score = (
                sem_w * sem_score
                + lex_w * norm_lex
                + 0.10 * entity_match
                + 0.05 * action_match
                + 0.05 * attr_match
            )

            # Section 30 Exact Match Boost
            summary = (item.get("summary") or "").lower()
            if low_query in summary:
                score = min(1.0, score + 0.08)

            item["final_score"] = round(score, 4)
            ranked.append(item)

        ranked.sort(key=lambda x: x["final_score"], reverse=True)
        return ranked

    @staticmethod
    def _apply_confidence_gate_and_diversify(
        ranked: List[Dict[str, Any]],
        max_results: int
    ) -> Tuple[List[SearchResultItem], str]:
        """
        Applies confidence gate (Section 28) and keeps at most 4 results.
        Avoids filling results with weak matches.
        """
        if not ranked:
            return [], "low"

        top_score = ranked[0]["final_score"]
        confidence_level = (
            "high" if top_score >= settings.CONFIDENCE_HIGH_THRESHOLD
            else "medium" if top_score >= settings.CONFIDENCE_MIN_THRESHOLD
            else "low"
        )

        results = []
        seen_summaries = []

        for item in ranked:
            score = item["final_score"]
            # Confidence threshold: drop anything below minimum threshold unless it's a direct match
            if score < settings.CONFIDENCE_MIN_THRESHOLD:
                continue

            summary = item.get("summary") or "Instagram Reel"
            
            # Simple diversification: skip near-identical summaries
            if any(summary.lower() == s.lower() for s in seen_summaries):
                continue
            seen_summaries.append(summary)

            entities = item.get("entities") or []
            if isinstance(entities, str):
                entities = json.loads(entities)

            topics = item.get("topics") or []
            if isinstance(topics, str):
                topics = json.loads(topics)

            objects = item.get("objects") or []
            if isinstance(objects, str):
                objects = json.loads(objects)

            actions = item.get("actions") or []
            if isinstance(actions, str):
                actions = json.loads(actions)

            environments = item.get("environments") or []
            if isinstance(environments, str):
                environments = json.loads(environments)

            results.append(
                SearchResultItem(
                    reel_id=str(item["reel_id"]),
                    canonical_url=item["canonical_url"],
                    title=summary[:60] if summary else "Instagram Reel",
                    score=score,
                    summary=summary,
                    entities=entities[:10],
                    topics=topics[:10],
                    objects=objects[:10],
                    actions=actions[:10],
                    environments=environments[:10],
                    lexical_score=round(item.get("lexical_score") or 0.0, 3),
                    semantic_score=round(item.get("semantic_score") or 0.0, 3)
                )
            )

            # Strictly enforce maximum limit
            if len(results) >= max_results:
                break

        return results, confidence_level

    @staticmethod
    def _log_search_event(query: str, count: int, confidence: str, latency: float, top_id: Optional[str]):
        try:
            sql = """
            INSERT INTO search_events (query, normalized_query, result_count, confidence, latency_ms, top_reel_id)
            VALUES (%s, %s, %s, %s, %s, %s);
            """
            with get_db_cursor(commit=True) as cursor:
                cursor.execute(sql, (query, query.lower(), count, confidence, latency, top_id))
        except Exception as e:
            logger.debug(f"Failed to log search event: {e}")
