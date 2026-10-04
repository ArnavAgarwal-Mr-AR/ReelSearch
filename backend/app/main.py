import logging
import time
import uuid
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db_pool, close_db_pool, run_migrations
from app.api.routes_reels import router as reels_router
from app.api.routes_search import router as search_router
from app.api.routes_system import router as system_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("reelsearch.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing ReelSearch platform backend...")
    # Initialize DB connection pool and run migrations
    try:
        init_db_pool()
        run_migrations()
    except Exception as e:
        logger.error(f"Error during startup database initialization: {e}")

    worker = None
    worker_thread = None
    if settings.EMBEDDED_WORKER:
        import threading
        from app.worker.context_worker import ContextWorker
        logger.info("Starting embedded context enrichment worker thread...")
        worker = ContextWorker(worker_id="embedded-worker")
        worker_thread = threading.Thread(target=worker.start_loop, kwargs={"poll_interval": 1.0}, daemon=True)
        worker_thread.start()

    # Pre-warm SentenceTransformer embedding model in background so first user query is instant (<300ms)
    import threading
    from app.services.embedding_service import EmbeddingService

    def _warmup_embedding_model():
        try:
            logger.info("Pre-warming embedding model in background thread...")
            EmbeddingService.generate_embedding("warmup query")
            logger.info("Embedding model pre-warmed successfully. Ready for instant search.")
        except Exception as e:
            logger.warning(f"Embedding warmup warning: {e}")

    threading.Thread(target=_warmup_embedding_model, daemon=True).start()

    yield

    logger.info("Shutting down ReelSearch backend...")
    if worker:
        worker.stop()
    close_db_pool()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Machine-generated semantic indexing and hybrid search platform for Instagram Reels.",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security and Request ID Middleware (Section 113)
@app.middleware("http")
async def security_and_tracing_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.time()

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-MS"] = f"{process_time:.2f}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:;"

    return response


from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException, status

# Global Exception Handlers (Section 14 & 113)
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.warning(f"[{request_id}] Validation error on {request.method} {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation failed for request parameters or payload.",
                "request_id": request_id,
                "details": exc.errors()
            }
        },
        headers={"X-Request-ID": request_id}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    error_code = "HTTP_ERROR"
    message = str(exc.detail)
    if isinstance(exc.detail, dict):
        error_code = exc.detail.get("code", "HTTP_ERROR")
        message = exc.detail.get("message", str(exc.detail))

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": error_code,
                "message": message,
                "request_id": request_id
            }
        },
        headers={"X-Request-ID": request_id}
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.exception(f"[{request_id}] Unhandled server exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred. Please try again later.",
                "request_id": request_id
            }
        },
        headers={"X-Request-ID": request_id}
    )


# Include API Routers
app.include_router(system_router)
app.include_router(reels_router, prefix=settings.API_V1_PREFIX)
app.include_router(search_router, prefix=settings.API_V1_PREFIX)

# Mount frontend static files if directory exists
frontend_dist_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.exists(frontend_dist_path):
    app.mount("/app", StaticFiles(directory=frontend_dist_path, html=True), name="frontend")


from fastapi.responses import RedirectResponse

@app.get("/", summary="Root Welcome / API Info")
async def root(request: Request):
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/app/")
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "api_docs": "/docs",
        "web_ui": "/app/",
        "endpoints": {
            "save_reel": f"POST {settings.API_V1_PREFIX}/reels",
            "search": f"GET {settings.API_V1_PREFIX}/search?q={{query}}",
            "stats": f"GET {settings.API_V1_PREFIX}/stats",
            "health": "GET /health",
            "ready": "GET /ready"
        }
    }

