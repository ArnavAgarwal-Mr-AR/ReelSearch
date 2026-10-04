import sys
import os
sys.path.insert(0, os.path.abspath('backend'))

# Bypass broken Windows torchvision nms operator registration
sys.modules['torchvision'] = None
sys.modules['torchvision.transforms'] = None

from app.services.context_extractor import ContextExtractor
from app.services.embedding_service import EmbeddingService

url = "https://www.instagram.com/reel/Dd-2CAHBHpj/"
meta = ContextExtractor.fetch_instagram_metadata(url)
print("Fetched metadata:")
print("  Title:", meta.get("title", "")[:60])
print("  Author:", meta.get("author_name"))
print("  Caption len:", len(meta.get("caption", "")))
print("  Caption sample:", meta.get("caption", "")[:120])
