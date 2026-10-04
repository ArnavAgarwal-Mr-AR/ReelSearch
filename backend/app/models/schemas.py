from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, HttpUrl


class SaveReelRequest(BaseModel):
    url: str = Field(
        ...,
        description="Public Instagram Reel URL, e.g., https://www.instagram.com/reel/Cxyz123/",
        example="https://www.instagram.com/reel/Cxyz123/"
    )


class SaveReelResponse(BaseModel):
    reel_id: str
    canonical_url: str
    status: str  # 'processing', 'ready', 'pending'
    created: bool = True
    message: Optional[str] = None


class ReelStatusResponse(BaseModel):
    reel_id: str
    canonical_url: str
    instagram_shortcode: str
    status: str
    enrichment_attempts: int = 0
    last_enrichment_error: Optional[str] = None
    context_version: Optional[int] = None
    first_seen_at: Optional[str] = None
    updated_at: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class SearchResultItem(BaseModel):
    reel_id: str
    canonical_url: str
    title: str = "Instagram Reel"
    thumbnail_url: Optional[str] = None
    score: float
    summary: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    objects: List[str] = Field(default_factory=list)
    actions: List[str] = Field(default_factory=list)
    environments: List[str] = Field(default_factory=list)
    lexical_score: Optional[float] = None
    semantic_score: Optional[float] = None


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultItem]
    count: int
    confidence: str  # 'high', 'medium', 'low'
    max_results: int = 4
    latency_ms: Optional[float] = None


class SearchEventRequest(BaseModel):
    query: str
    result_count: int
    confidence: str
    latency_ms: float
    top_reel_id: Optional[str] = None
    clicked_reel_id: Optional[str] = None


class StructuredContext(BaseModel):
    summary: str = Field(..., max_length=1000)
    objects: List[str] = Field(default_factory=list, max_length=30)
    actions: List[str] = Field(default_factory=list, max_length=20)
    entities: List[str] = Field(default_factory=list, max_length=30)
    topics: List[str] = Field(default_factory=list, max_length=30)
    environments: List[str] = Field(default_factory=list, max_length=20)
    visual_style: List[str] = Field(default_factory=list, max_length=20)
    keywords: List[str] = Field(default_factory=list, max_length=50)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
