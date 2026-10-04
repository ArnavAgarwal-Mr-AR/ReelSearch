import sys
import os
import time

print("STEP 0: Starting...", flush=True)
sys.path.insert(0, os.path.abspath('backend'))
sys.modules['torchvision'] = None
sys.modules['torchvision.transforms'] = None
# Prevent tensorflow from being loaded by transformers
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"

print("STEP 1: Importing database...", flush=True)
from app.core.database import init_db_pool
print("STEP 2: Initializing DB pool...", flush=True)
t = time.time()
init_db_pool()
print(f"   Done in {round((time.time() - t)*1000, 1)}ms", flush=True)

print("STEP 3: Importing EmbeddingService...", flush=True)
from app.services.embedding_service import EmbeddingService
print("STEP 4: Generating embedding...", flush=True)
t = time.time()
emb = EmbeddingService.generate_embedding("masculinity")
print(f"   Done in {round((time.time() - t)*1000, 1)}ms (dim={len(emb)})", flush=True)

print("STEP 5: Importing SearchService...", flush=True)
from app.services.search_service import SearchService

print("STEP 6: Lexical candidates...", flush=True)
t = time.time()
lex = SearchService._retrieve_lexical_candidates("masculinity", limit=10)
print(f"   Done in {round((time.time() - t)*1000, 1)}ms (found {len(lex)})", flush=True)

print("STEP 7: Vector candidates...", flush=True)
t = time.time()
vec = SearchService._retrieve_vector_candidates(emb, limit=10)
print(f"   Done in {round((time.time() - t)*1000, 1)}ms (found {len(vec)})", flush=True)

print("STEP 8: Full search...", flush=True)
t = time.time()
res = SearchService.search("masculinity")
print(f"   Done in {round((time.time() - t)*1000, 1)}ms (returned {res.count} results)", flush=True)
