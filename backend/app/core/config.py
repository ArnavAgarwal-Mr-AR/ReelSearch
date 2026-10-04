import os
from typing import List, Union
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    PROJECT_NAME: str = "Instagram Reel Discovery & Semantic Indexing Platform"
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True
    ENVIRONMENT: str = "development"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # PostgreSQL Database Connection
    DATABASE_URL: str = Field(
        default="postgresql://postgres:password@localhost:5432/postgres",
        description="PostgreSQL connection string"
    )
    PG_HOST: str = "localhost"
    PG_PORT: int = 5432
    PG_USER: str = "postgres"
    PG_PASSWORD: str = "password"
    PG_DATABASE: str = "postgres"

    # Redis Connection & Memory Limits (tailored for cloud free tiers)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = True
    REDIS_CACHE_TTL_SECONDS: int = 300  # Automatically purges cache keys to prevent memory exhaustion
    RATE_LIMIT_PER_MINUTE: int = 30     # Max ingestion requests/min per IP
    SEARCH_RATE_LIMIT_PER_MINUTE: int = 60  # Max search queries/min per IP

    # Worker Mode: if True, runs worker thread inside API process (single deployment)
    EMBEDDED_WORKER: bool = True

    # Search Configuration
    CONFIDENCE_HIGH_THRESHOLD: float = 0.70
    CONFIDENCE_MIN_THRESHOLD: float = 0.50
    MAX_SEARCH_RESULTS: int = 4
    CANDIDATE_POOL_SIZE: int = 50
    RRF_K: int = 60

    # Embedding Configuration
    EMBEDDING_PROVIDER: str = "sentence-transformers"  # 'sentence-transformers', 'openai', 'dummy'
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    ALLOWED_HOSTS: Union[List[str], str] = ["instagram.com", "www.instagram.com"]

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [h.strip() for h in v.split(",") if h.strip()]
        return v

    model_config = {
        "env_file": (
            os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env.local"),
            os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
            os.path.join(os.path.dirname(__file__), "..", "..", ".env.local"),
            ".env",
            ".env.local",
        ),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
