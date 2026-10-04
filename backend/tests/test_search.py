import pytest
from app.services.search_service import SearchService
from app.models.schemas import SearchResultItem


class TestSearchServiceLogic:
    def test_rrf_fusion_logic(self):
        lexical = [
            {"reel_id": "r1", "canonical_url": "url1", "lexical_score": 0.9},
            {"reel_id": "r2", "canonical_url": "url2", "lexical_score": 0.5},
        ]
        vector = [
            {"reel_id": "r2", "canonical_url": "url2", "semantic_score": 0.8},
            {"reel_id": "r3", "canonical_url": "url3", "semantic_score": 0.7},
        ]
        fused = SearchService._fuse_candidates(lexical, vector, k=60)
        assert "r1" in fused
        assert "r2" in fused
        assert "r3" in fused
        # r2 appears in both lists, so its RRF score should be highest
        assert fused["r2"]["rrf_score"] > fused["r1"]["rrf_score"]
        assert fused["r2"]["rrf_score"] > fused["r3"]["rrf_score"]

    def test_confidence_gate_max_4_enforcement(self):
        ranked_candidates = []
        for i in range(10):
            ranked_candidates.append({
                "reel_id": f"id_{i}",
                "canonical_url": f"https://www.instagram.com/reel/C{i}/",
                "summary": f"Unique reel content description {i}",
                "final_score": 0.95 - (i * 0.02),
                "entities": ["entity"],
                "topics": ["topic"],
                "objects": [],
                "actions": [],
                "environments": [],
                "lexical_score": 0.8,
                "semantic_score": 0.9
            })

        results, confidence = SearchService._apply_confidence_gate_and_diversify(ranked_candidates, max_results=4)
        # MUST NEVER EXCEED 4 (Section 2, 4.2, 34, 35)
        assert len(results) <= 4
        assert len(results) == 4
        assert confidence == "high"

    def test_confidence_gate_drops_weak_matches(self):
        weak_candidates = [
            {
                "reel_id": "weak_1",
                "canonical_url": "https://www.instagram.com/reel/Cweak1/",
                "summary": "Completely unrelated content",
                "final_score": 0.25,
                "entities": [],
                "topics": [],
                "objects": [],
                "actions": [],
                "environments": [],
                "lexical_score": 0.1,
                "semantic_score": 0.2
            }
        ]
        results, confidence = SearchService._apply_confidence_gate_and_diversify(weak_candidates, max_results=4)
        # Weak matches must be rejected, do not manufacture results
        assert len(results) == 0
        assert confidence == "low"
