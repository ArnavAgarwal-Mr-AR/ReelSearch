import os
import sys

# Disable slow TensorFlow dynamically linking and tokenizers parallelism warnings
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
# Force HuggingFace Hub offline mode so model loading never hangs on remote network timeouts
os.environ["HF_HUB_OFFLINE"] = "1"

# Bypass broken Windows torchvision nms operator registration before transformers/torchvision is touched
sys.modules['torchvision'] = None
sys.modules['torchvision.transforms'] = None

import functools
import logging
import math
from typing import List, Optional, Tuple
import numpy as np
from app.core.config import settings

logger = logging.getLogger("reelsearch.embedding")

_st_model = None
_st_model_failed = False


def get_sentence_transformer_model():
    global _st_model, _st_model_failed
    if _st_model_failed:
        return None
    if _st_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading SentenceTransformer model: {settings.EMBEDDING_MODEL} (offline)...")
            try:
                _st_model = SentenceTransformer(settings.EMBEDDING_MODEL, local_files_only=True)
            except Exception:
                # Fallback to standard loading if local files aren't found directly
                _st_model = SentenceTransformer(settings.EMBEDDING_MODEL)
            logger.info("SentenceTransformer model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load SentenceTransformer: {e}")
            _st_model_failed = True
            _st_model = None
    return _st_model


@functools.lru_cache(maxsize=1024)
def _cached_st_encode(clean_text: str) -> Optional[Tuple[float, ...]]:
    model = get_sentence_transformer_model()
    if model is not None:
        try:
            vec = model.encode(clean_text, normalize_embeddings=True)
            return tuple(float(x) for x in vec)
        except Exception as e:
            logger.warning(f"Error encoding with SentenceTransformer: {e}")
    return None


class EmbeddingService:
    @staticmethod
    def generate_embedding(text: str) -> List[float]:
        """
        Generates a dense vector embedding for the input text.
        Returns a Python list of floats.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return [0.0] * settings.EMBEDDING_DIM

        # 1. Try local sentence-transformers model (with in-memory LRU cache)
        if settings.EMBEDDING_PROVIDER == "sentence-transformers":
            cached_tuple = _cached_st_encode(clean_text)
            if cached_tuple is not None:
                return list(cached_tuple)

        # 2. Try OpenAI API if key is present
        if settings.OPENAI_API_KEY:
            try:
                import httpx
                headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
                payload = {"input": clean_text, "model": "text-embedding-3-small"}
                resp = httpx.post("https://api.openai.com/v1/embeddings", json=payload, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    vec = data["data"][0]["embedding"]
                    # Normalize vector
                    arr = np.array(vec, dtype=np.float32)
                    norm = np.linalg.norm(arr)
                    if norm > 0:
                        arr = arr / norm
                    return arr.tolist()
            except Exception as e:
                logger.warning(f"Error generating embedding via OpenAI: {e}")

        # 3. Fallback: dense deterministic vector for dev/offline resilience
        logger.warning("Using dense deterministic fallback vector embedding.")
        return EmbeddingService._deterministic_fallback_embedding(clean_text, settings.EMBEDDING_DIM)

    @staticmethod
    def _deterministic_fallback_embedding(text: str, dim: int = 384) -> List[float]:
        """Creates a dense unit-length pseudo-embedding with 100% non-zero dimension distribution."""
        import hashlib
        vec = np.zeros(dim, dtype=np.float32)
        words = text.lower().split()
        if not words:
            vec[0] = 1.0
            return vec.tolist()

        for w_idx, word in enumerate(words):
            weight = 1.0 / (1.0 + 0.05 * w_idx)
            seed_hash = hashlib.sha256(f"{word}:{w_idx}".encode("utf-8")).digest()
            for i in range(dim):
                byte_val = seed_hash[i % len(seed_hash)]
                val = ((byte_val / 127.5) - 1.0) * weight
                vec[i] += val

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0
        return vec.tolist()

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Calculates cosine similarity between two float vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        a = np.array(v1, dtype=np.float32)
        b = np.array(v2, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))
