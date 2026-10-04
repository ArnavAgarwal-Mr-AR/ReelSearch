#!/usr/bin/env python
"""
Seed realistic demo Reels into ReelSearch database.
Generates structured context, searchable text, and embeddings.
"""
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.core.database import init_db_pool, get_db_cursor, close_db_pool
from app.services.canonicalizer import canonicalize_instagram_reel
from app.services.embedding_service import EmbeddingService
from app.services.context_extractor import ContextExtractor
from app.models.schemas import StructuredContext

DEMO_REELS = [
    {
        "url": "https://www.instagram.com/reel/CxyzSupra99/?utm_source=ig_web_copy_link",
        "context": {
            "summary": "A fiery red Toyota Supra MK4 executing high-speed power slides and drifting along a twisting mountain pass at golden hour sunset.",
            "objects": ["Toyota Supra", "sports car", "mountain pass", "asphalt road", "exhaust flames", "rear wing", "smoke"],
            "actions": ["drifting", "power sliding", "accelerating", "counter-steering", "racing"],
            "entities": ["Toyota Supra MK4", "2JZ-GTE"],
            "topics": ["cars", "drifting", "automotive", "JDM", "motorsport", "tuning"],
            "environments": ["mountain pass", "hairpin turn", "twilight", "sunset", "outdoor road"],
            "visual_style": ["cinematic", "dynamic drone shot", "golden hour lighting", "smoke trails"],
            "keywords": ["red sports car", "supra drift", "mountain drift", "car drifting", "jdm supra", "turbo flutter"]
        }
    },
    {
        "url": "https://www.instagram.com/reel/CdefTokyo88/",
        "context": {
            "summary": "First-person POV walking through rainy neon-lit alleyways of Shibuya Tokyo at night with glowing reflections on puddles.",
            "objects": ["neon signs", "rain umbrella", "vending machines", "lanterns", "narrow streets", "cyberpunk billboards"],
            "actions": ["walking", "strolling", "reflecting", "filming", "capturing"],
            "entities": ["Shibuya", "Tokyo", "Japan"],
            "topics": ["travel", "japan", "cyberpunk", "cityscape", "nightlife", "photography"],
            "environments": ["rainy street", "urban alley", "night", "city center", "shibuya crossing"],
            "visual_style": ["cyberpunk aesthetic", "lo-fi grain", "moody neon glow", "water reflections"],
            "keywords": ["tokyo rain", "shibuya night walk", "neon reflection", "cyberpunk vibe", "japanese street"]
        }
    },
    {
        "url": "https://www.instagram.com/reel/CghiPizza77/",
        "context": {
            "summary": "Artisan pizzaiolo stretching high-hydration sourdough pizza dough, topping with San Marzano tomatoes and baking in a wood-fired oven at 900F.",
            "objects": ["pizza dough", "wood fired oven", "San Marzano tomatoes", "fresh mozzarella", "basil", "pizza peel"],
            "actions": ["stretching dough", "shaping crust", "spreading tomato sauce", "baking pizza", "leoparding"],
            "entities": ["Neapolitan Pizza", "San Marzano", "Mozzarella di Bufala"],
            "topics": ["cooking", "baking", "italian food", "pizza making", "culinary arts", "gastronomy"],
            "environments": ["rustic kitchen", "pizzeria", "brick oven", "countertop"],
            "visual_style": ["warm lighting", "macro food photography", "slow motion cheese pull", "crust blister close up"],
            "keywords": ["neapolitan pizza", "sourdough crust", "woodfired oven", "pizza recipe", "cheesy pizza", "dough fermentation"]
        }
    },
    {
        "url": "https://www.instagram.com/reel/CjklMatcha66/?igsh=demo123",
        "context": {
            "summary": "Barista whisking ceremonial grade Uji matcha with bamboo chasen and pouring silky steamed oat milk to form a swan latte art.",
            "objects": ["matcha bowl", "bamboo whisk", "chasen", "ceramic mug", "steamed oat milk", "pitcher"],
            "actions": ["whisking matcha", "steaming milk", "pouring latte art", "swirling", "frothing"],
            "entities": ["Uji Matcha", "Oat Milk", "Kyoto Green Tea"],
            "topics": ["coffee shop", "matcha latte", "beverage", "tea ceremony", "barista skills", "morning routine"],
            "environments": ["minimalist cafe", "wooden coffee bar", "morning sun", "aesthetic kitchen"],
            "visual_style": ["clean minimalist", "calm aesthetic", "pastel green palette", "crisp pouring focus"],
            "keywords": ["matcha latte art", "swan latte art", "ceremonial matcha", "barista pour", "green tea latte"]
        }
    },
    {
        "url": "https://www.instagram.com/reel/CmnoBouldering55/",
        "context": {
            "summary": "Rock climber solving a difficult V8 roof problem in an indoor bouldering gym with dynamic heel hook and dyno finish.",
            "objects": ["climbing wall", "chalk bag", "climbing shoes", "holds", "crash pad", "slopers"],
            "actions": ["bouldering", "heel hooking", "dyno jump", "crimping", "chalking hands", "topping out"],
            "entities": ["V8 Boulder", "Indoor Climbing"],
            "topics": ["climbing", "bouldering", "fitness", "calisthenics", "extreme sports", "training"],
            "environments": ["indoor climbing gym", "bouldering cave", "padded floor"],
            "visual_style": ["action camera", "intense contrast", "chalk dust slow-mo", "athletic focus"],
            "keywords": ["rock climbing", "bouldering beta", "dyno move", "heel hook", "climbing gym", "boulder problem"]
        }
    }
]


def seed():
    print("Starting database seeding...")
    init_db_pool()

    for item in DEMO_REELS:
        raw_url = item["url"]
        canonical_url, shortcode, reel_id = canonicalize_instagram_reel(raw_url)
        print(f"Seeding Reel: {canonical_url} (ID: {reel_id})")

        ctx_obj = StructuredContext(**item["context"])
        searchable_text = ContextExtractor.build_searchable_text(ctx_obj)
        print("  Generating embedding...")
        embedding = EmbeddingService.generate_embedding(searchable_text)

        with get_db_cursor(commit=True) as cursor:
            # Upsert into reels
            cursor.execute(
                """
                INSERT INTO reels (reel_id, canonical_url, instagram_shortcode, enrichment_status, first_seen_at, updated_at)
                VALUES (%s, %s, %s, 'ready', now(), now())
                ON CONFLICT (canonical_url) DO UPDATE SET enrichment_status = 'ready', updated_at = now();
                """,
                (reel_id, canonical_url, shortcode)
            )

            # Upsert into reel_context
            cursor.execute(
                """
                INSERT INTO reel_context (
                    reel_id, summary, objects, actions, entities, topics, environments,
                    visual_style, keywords, searchable_text, embedding, context_version,
                    model_version, embedding_model_version, search_vector, updated_at
                )
                VALUES (
                    %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s::jsonb, %s, %s::float8[], 1, 'reel-context-v1', 'all-MiniLM-L6-v2',
                    to_tsvector('english', %s), now()
                )
                ON CONFLICT (reel_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    objects = EXCLUDED.objects,
                    actions = EXCLUDED.actions,
                    entities = EXCLUDED.entities,
                    topics = EXCLUDED.topics,
                    environments = EXCLUDED.environments,
                    visual_style = EXCLUDED.visual_style,
                    keywords = EXCLUDED.keywords,
                    searchable_text = EXCLUDED.searchable_text,
                    embedding = EXCLUDED.embedding,
                    search_vector = EXCLUDED.search_vector,
                    updated_at = now();
                """,
                (
                    reel_id,
                    ctx_obj.summary,
                    json.dumps(ctx_obj.objects),
                    json.dumps(ctx_obj.actions),
                    json.dumps(ctx_obj.entities),
                    json.dumps(ctx_obj.topics),
                    json.dumps(ctx_obj.environments),
                    json.dumps(ctx_obj.visual_style),
                    json.dumps(ctx_obj.keywords),
                    searchable_text,
                    embedding,
                    searchable_text
                )
            )

    print("Demo data seeded successfully!")
    close_db_pool()


if __name__ == "__main__":
    seed()
