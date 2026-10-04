import re
import unicodedata
import logging
from typing import Dict, Any, List, Optional
import httpx
from bs4 import BeautifulSoup
from app.models.schemas import StructuredContext
from app.core.config import settings

logger = logging.getLogger("reelsearch.context_extractor")


class ContextExtractor:
    PLATFORM_STOPWORDS = {
        "instagram", "reel", "reels", "video", "videos", "post", "posts", "creator",
        "like", "likes", "comment", "comments", "share", "follow", "profile", "view",
        "checkout", "everyone", "general", "showing", "presenting", "showcasing",
        "viral", "trending", "explore", "fyp", "foryou", "content", "clip", "clips"
    }

    ENGLISH_STOPWORDS = {
        "what", "whatever", "which", "who", "whom", "whose", "why", "how",
        "where", "when", "that", "this", "these", "those", "there", "their",
        "theirs", "they", "them", "you", "your", "yours", "yourself",
        "yourselves", "he", "him", "his", "she", "her", "hers", "herself",
        "we", "us", "our", "ours", "ourselves", "it", "its", "itself",
        "and", "but", "or", "nor", "for", "yet", "so", "with", "from",
        "into", "during", "including", "until", "against", "among", "throughout",
        "despite", "towards", "upon", "concerning", "about", "above", "below",
        "over", "under", "again", "further", "then", "once", "here", "all",
        "any", "both", "each", "few", "more", "most", "other", "some", "such",
        "no", "nor", "not", "only", "own", "same", "too", "very", "can", "will",
        "just", "don", "should", "now", "think", "thought", "know", "knew",
        "have", "has", "had", "having", "do", "does", "did", "doing", "would",
        "could", "should", "might", "must", "shall", "today", "yesterday",
        "tomorrow", "always", "never", "really", "actually", "maybe", "please",
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being"
    }

    ALL_STOPWORDS = PLATFORM_STOPWORDS | ENGLISH_STOPWORDS

    @staticmethod
    def fetch_instagram_metadata(canonical_url: str) -> Dict[str, Any]:
        """
        Fetches public metadata for the Instagram Reel using crawler user-agents that Instagram
        allows for OpenGraph link previews (Twitterbot, Facebookexternalhit, WhatsApp).
        Never throws fatal exception; falls back gracefully.
        """
        metadata = {
            "title": "",
            "author_name": "",
            "thumbnail_url": "",
            "caption": "",
        }

        crawler_headers = [
            {"User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)", "Accept-Language": "en-US,en;q=0.9"},
            {"User-Agent": "Twitterbot/1.0", "Accept-Language": "en-US,en;q=0.9"},
            {"User-Agent": "WhatsApp/2.21.12.21 A", "Accept-Language": "en-US,en;q=0.9"},
        ]

        raw_title = ""
        raw_desc = ""

        for headers in crawler_headers:
            try:
                resp = httpx.get(
                    canonical_url,
                    headers=headers,
                    follow_redirects=True,
                    timeout=8.0
                )
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    og_title = soup.find("meta", property="og:title")
                    og_desc = soup.find("meta", property="og:description")
                    meta_desc = soup.find("meta", attrs={"name": "description"})
                    og_image = soup.find("meta", property="og:image")

                    if og_title and og_title.get("content"):
                        raw_title = og_title["content"].strip()
                    if og_desc and og_desc.get("content"):
                        raw_desc = og_desc["content"].strip()
                    elif meta_desc and meta_desc.get("content"):
                        raw_desc = meta_desc["content"].strip()
                    if og_image and og_image.get("content"):
                        metadata["thumbnail_url"] = og_image["content"].strip()

                    if raw_title or raw_desc:
                        break
            except Exception as e:
                logger.debug(f"Crawler header fetch attempt error: {e}")

        # Parse real caption and author from OpenGraph contents
        # Example desc: '67K likes, 487 comments - thehimanichaudhary on October 1, 2026: "🚨BIG UPDATE..."'
        if raw_desc:
            m_author = re.search(r"-\s*([a-zA-Z0-9._]+)\s+on\s+[^:]+:\s*[\"\'\u201c]?(.*)", raw_desc, re.DOTALL)
            if m_author:
                metadata["author_name"] = m_author.group(1).strip()
                caption_candidate = m_author.group(2).strip()
                caption_candidate = re.sub(r'[\"\'\u201d]\.?\s*$', '', caption_candidate).strip()
                metadata["caption"] = caption_candidate
            elif not metadata["caption"] and not raw_desc.startswith("Page Not Found"):
                metadata["caption"] = raw_desc

        if raw_title:
            # Example title: 'Himani Chowdhary | Finance on Instagram: "🚨BIG UPDATE | New Rules..."'
            m_title = re.search(r"^(.*?)\s+on\s+Instagram:\s*[\"\'\u201c]?(.*)", raw_title, re.DOTALL)
            if m_title:
                display_name = m_title.group(1).strip()
                metadata["author_display_name"] = display_name
                if not metadata["author_name"] or metadata["author_name"] == "instagram_creator":
                    metadata["author_name"] = display_name
                title_candidate = m_title.group(2).strip()
                title_candidate = re.sub(r'[\"\'\u201d]\.?\s*$', '', title_candidate).strip()
                metadata["title"] = title_candidate
            else:
                metadata["title"] = raw_title

        # Harmonize caption and title
        if not metadata["caption"] and metadata["title"]:
            metadata["caption"] = metadata["title"]
        elif not metadata["title"] and metadata["caption"]:
            lines = [l.strip() for l in metadata["caption"].split("\n") if l.strip()]
            metadata["title"] = lines[0][:80] if lines else "Instagram Reel"

        if not metadata["title"] or metadata["title"] == "Instagram":
            metadata["title"] = f"Instagram Reel {canonical_url.split('/reel/')[-1].split('/')[0]}"

        return metadata

    @staticmethod
    def is_context_sufficient(meta: Dict[str, Any], ctx: StructuredContext) -> bool:
        """
        Determines whether the scraped caption/title has sufficient rich information
        to index directly without spending external LLM API quota and latency.
        """
        caption = (meta.get("caption") or "").strip()
        title = (meta.get("title") or "").strip()
        combined = f"{title}\n{caption}"

        # Extract substantive words (ignoring all platform and English stop words)
        words = [
            w.lower() for w in re.findall(r"\b[A-Za-z0-9_-]{3,}\b", combined)
            if w.lower() not in ContextExtractor.ALL_STOPWORDS
        ]

        # 1. Check for common social media engagement bait / question hooks
        combined_lower = combined.lower()
        is_engagement_bait = any(bait in combined_lower for bait in [
            "what do you think", "what think", "thoughts?", "wait till the end",
            "wait for it", "tag a friend", "drop a comment", "comment below",
            "watch till the end", "link in bio", "share this", "agree or disagree"
        ])

        # If caption is an engagement bait and doesn't contain a detailed breakdown
        if is_engagement_bait and len(words) < 20:
            return False

        # If the total substantive words are fewer than 15, context is too sparse
        if len(words) < 15:
            return False

        # If heuristic extraction found no specific topics
        if not ctx.topics or len(ctx.topics) == 0:
            return False

        # If heuristic extraction found very few keywords
        if len(ctx.keywords) < 4:
            return False

        # If the generated summary is too short (< 40 characters)
        if len(ctx.summary.strip()) < 40:
            return False

        # Sufficient context confirmed
        return True

    @staticmethod
    def extract_structured_context(
        canonical_url: str,
        shortcode: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StructuredContext:
        """
        Generates structured context following Section 11 & 14 schemas.
        If the Reel caption already contains sufficient rich context, uses high-speed local NLP.
        Invokes LLM (Gemini/OpenAI) ONLY when the Reel has sparse, minimal, or engagement-only context.
        """
        meta = metadata or ContextExtractor.fetch_instagram_metadata(canonical_url)

        # 1. Always compute initial local heuristic context first
        heuristic_ctx = ContextExtractor._heuristic_extraction(canonical_url, shortcode, meta)

        # 2. Check if the reel caption has sufficient substance to bypass LLM
        if ContextExtractor.is_context_sufficient(meta, heuristic_ctx):
            logger.info(
                f"Sufficient description detected for {shortcode} ({len(heuristic_ctx.topics)} topics, "
                f"{len(heuristic_ctx.keywords)} keywords). Using local NLP (bypassing LLM)."
            )
            return heuristic_ctx

        logger.info(
            f"Sparse/minimal context detected for {shortcode} (caption len: {len(meta.get('caption', ''))}). "
            f"Invoking LLM for semantic inference..."
        )

        # 3. Low context: Invoke LLM (Gemini / OpenAI) if configured
        if settings.GEMINI_API_KEY:
            try:
                context = ContextExtractor._extract_with_gemini(canonical_url, meta)
                if context:
                    return ContextExtractor.normalize_and_validate(context)
            except Exception as e:
                logger.warning(f"Gemini extraction failed: {e}, using heuristic NLP.")

        if settings.OPENAI_API_KEY:
            try:
                context = ContextExtractor._extract_with_openai(canonical_url, meta)
                if context:
                    return ContextExtractor.normalize_and_validate(context)
            except Exception as e:
                logger.warning(f"OpenAI extraction failed: {e}, using heuristic NLP.")

        # Fallback to local heuristic if LLM is unavailable or fails
        return heuristic_ctx

    @staticmethod
    def _heuristic_extraction(
        canonical_url: str,
        shortcode: str,
        meta: Dict[str, Any]
    ) -> StructuredContext:
        """Robust deterministic rule-based extractor with semantic filtering."""
        title = meta.get("title", "").strip()
        caption = meta.get("caption", "").strip()
        author = meta.get("author_name", "").strip()
        display_name = meta.get("author_display_name", "").strip()

        combined = f"{title}\n{caption}\n{display_name}".strip()
        if not combined or combined == f"Instagram Reel {shortcode}":
            combined = f"Reel {shortcode} by {author}" if author else f"Reel {shortcode}"

        # Clean words and hashtags
        hashtags = [h.lower() for h in re.findall(r"#(\w+)", combined)]
        words = re.findall(r"\b[A-Za-z0-9_-]{2,}\b", combined)

        # 1. Entity identification heuristics (Creator, proper nouns, abbreviations like UPI, FD, EMI)
        entities = []
        if author and author not in {"instagram_creator", "Instagram", "Instagram Reel"}:
            entities.append(author)

        # 1. Entity identification heuristics (Creator, proper nouns, abbreviations like UPI, FD, EMI)
        entities = []
        creator_tokens = set()
        if author and author not in {"instagram_creator", "Instagram", "Instagram Reel"}:
            entities.append(author)
            for part in re.split(r"[\s._]+", author.lower()):
                if len(part) >= 2:
                    creator_tokens.add(part)

        if display_name:
            for part in display_name.split("|"):
                part_clean = part.strip()
                if part_clean and part_clean not in entities and part_clean.lower() not in ContextExtractor.ALL_STOPWORDS:
                    entities.append(part_clean)
                    for tok in re.split(r"[\s._]+", part_clean.lower()):
                        if len(tok) >= 2:
                            creator_tokens.add(tok)

        # Detect capitalized entities / acronyms (UPI, EMI, FD, BMW, Supra, Tokyo, etc.)
        acronyms = set(re.findall(r"\b[A-Z]{2,6}\b", combined))
        for acr in acronyms:
            if acr.lower() not in ContextExtractor.ALL_STOPWORDS:
                entities.append(acr)

        # Proper noun detection (Capitalized words excluding all stopwords and creator name pieces)
        capitalized = re.findall(r"\b[A-Z][a-z]{2,}\b", combined)
        for cap in capitalized:
            cap_low = cap.lower()
            if cap_low not in ContextExtractor.ALL_STOPWORDS and cap not in entities and cap_low not in creator_tokens:
                entities.append(cap)

        # 2. Topic deduction from hashtags and keywords
        topic_domain_map = {
            "finance": ["finance", "money", "investing", "investment", "rules", "upi", "emi", "fd", "loan", "bank", "rates", "inflation", "stock", "crypto", "tax"],
            "automotive": ["car", "cars", "drift", "drifting", "supra", "toyota", "turbo", "jdm", "motorsport", "engine", "exhaust", "speed", "racing"],
            "food": ["pizza", "recipe", "cooking", "dough", "sourdough", "food", "chef", "delicious", "kitchen", "bake", "baking", "cheese", "taste"],
            "sports": ["climb", "climbing", "bouldering", "dyno", "gym", "fitness", "workout", "athlete", "training"],
            "travel": ["travel", "tokyo", "japan", "street", "city", "shibuya", "night", "explore", "vacation", "photography"],
            "technology": ["tech", "ai", "electronics", "gadget", "software", "code", "appliances", "phone"],
        }
        topics = list(set(hashtags[:8]))
        combined_lower = combined.lower()
        for domain, keywords in topic_domain_map.items():
            if any(k in combined_lower for k in keywords):
                if domain not in topics:
                    topics.append(domain)

        # Fallback topic for conversational/opinion reels with no hashtags
        if not topics:
            if any(q in combined_lower for q in ["what do you think", "what think", "thoughts", "opinion", "comment below"]):
                topics.extend(["social commentary", "discussion"])
            elif author or display_name:
                topics.append("creator content")

        # 3. Action deduction (common verbs/ing forms, excluding stopwords)
        actions = []
        for w in words:
            wl = w.lower()
            if wl.endswith("ing") and len(wl) > 4 and wl not in ContextExtractor.ALL_STOPWORDS:
                if wl not in actions:
                    actions.append(wl)
            if len(actions) >= 10:
                break

        # 4. Objects (concrete terms excluding all stopwords AND creator tokens)
        objects = []
        for w in words:
            wl = w.lower()
            if len(wl) >= 3 and wl not in ContextExtractor.ALL_STOPWORDS and not wl.endswith("ing") and wl not in creator_tokens:
                if w not in objects and wl not in [o.lower() for o in objects]:
                    objects.append(w)
            if len(objects) >= 15:
                break

        # 5. Environments
        environments = []
        env_keywords = [
            "mountain", "road", "city", "studio", "indoor", "outdoor", "sunset", "night",
            "street", "beach", "kitchen", "restaurant", "gym", "office", "urban", "forest"
        ]
        for ek in env_keywords:
            if ek in combined_lower and ek not in environments:
                environments.append(ek)

        # 6. Summary: Clean first meaningful sentence or headline
        summary = ""
        clean_lines = [l.strip() for l in combined.split("\n") if l.strip()]
        if clean_lines:
            seen_parts = []
            for line in clean_lines:
                if line not in seen_parts:
                    seen_parts.append(line)
            summary = " — ".join(seen_parts[:2])
        else:
            summary = title or caption or f"Instagram Reel {shortcode}"

        # Clean emoji or artifacts if needed, truncate
        summary = summary.strip()[:350]

        # 7. Keywords
        raw_keywords = set()
        for h in hashtags:
            raw_keywords.add(h)
        for e in entities:
            raw_keywords.add(e.lower())
        for o in objects[:8]:
            raw_keywords.add(o.lower())

        raw_context = {
            "summary": summary,
            "objects": objects[:15],
            "actions": actions[:10],
            "entities": entities[:10],
            "topics": topics[:10],
            "environments": environments[:8],
            "visual_style": ["cinematic", "vertical video"] if "video" in combined_lower or not environments else ["documentary", "social video"],
            "keywords": list(raw_keywords)[:25]
        }
        return ContextExtractor.normalize_and_validate(raw_context)

    @staticmethod
    def _extract_with_gemini(canonical_url: str, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not settings.GEMINI_API_KEY:
            return None
        import json
        key = settings.GEMINI_API_KEY
        candidate_models = [
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
            "gemini-3.8-flash",
            "gemini-pro-latest"
        ]
        author = meta.get("author_display_name") or meta.get("author_name") or "Instagram Creator"
        prompt = f"""
You are an expert video indexing AI for an Instagram Reel search engine.
Analyze the following Instagram Reel metadata and infer rich, high-quality, structured search context.

Instagram URL: {canonical_url}
Metadata: {json.dumps(meta, ensure_ascii=False)}

Guidelines:
1. "summary": A descriptive, informative 1-2 sentence overview of what the creator ({author}) is discussing, demonstrating, or presenting.
2. "objects": Specific tangible objects, tools, vehicles, clothing, or visual props mentioned or implied (NEVER include pronouns, verbs, or creator names).
3. "actions": Verbs in present participle describing what is happening or being explained (e.g., explaining, discussing, presenting, reacting, drifting, cooking).
4. "entities": Recognized people, creators, organizations, brands, or public figures (e.g. {author}).
5. "topics": Broad thematic categories (e.g., finance, technology, automotive, social commentary, education).
6. "environments": Physical setting/context (e.g., indoor room, studio, outdoor, street, stage).
7. "visual_style": Aesthetic tags (e.g., "cinematic", "vertical video", "talking head").
8. "keywords": High-intent search phrases users might type to find this video.

Return ONLY valid JSON matching this schema:
{{
    "summary": "string",
    "objects": ["string"],
    "actions": ["string"],
    "entities": ["string"],
    "topics": ["string"],
    "environments": ["string"],
    "visual_style": ["string"],
    "keywords": ["string"]
}}
"""
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=12.0)
                if resp.status_code == 200:
                    data = resp.json()
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
                    text = parts[0].get("text", "")
                    clean_json = re.search(r"\{.*\}", text, re.DOTALL)
                    if clean_json:
                        parsed = json.loads(clean_json.group(0))
                        logger.info(f"Gemini model {model} successfully extracted context for {canonical_url}")
                        return parsed
                elif resp.status_code in (404, 503):
                    logger.debug(f"Gemini model {model} returned status {resp.status_code}, trying next model...")
                    continue
                else:
                    logger.warning(f"Gemini API returned status {resp.status_code}: {resp.text[:150]}")
            except Exception as e:
                logger.warning(f"Error calling Gemini model {model}: {e}")
        return None

    @staticmethod
    def _extract_with_openai(canonical_url: str, meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        import json
        prompt = f"Analyze Instagram Reel {canonical_url}, metadata: {meta} and output JSON with summary, objects, actions, entities, topics, environments, visual_style, keywords."
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a video indexing AI that outputs JSON conforming to the requested schema."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        resp = httpx.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=15.0)
        if resp.status_code == 200:
            res = resp.json()
            return json.loads(res["choices"][0]["message"]["content"])
        return None

    @staticmethod
    def normalize_and_validate(raw: Dict[str, Any]) -> StructuredContext:
        """
        Normalizes unicode, trims strings, bounds array lengths as per Section 15 & 16.
        """
        def clean_str(s: Any) -> str:
            if not isinstance(s, str):
                s = str(s or "")
            s = unicodedata.normalize("NFKC", s).strip()
            # remove control chars
            return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", s)

        def clean_list(items: Any, max_len: int) -> List[str]:
            if not isinstance(items, list):
                return []
            cleaned = []
            seen = set()
            for item in items:
                cs = clean_str(item)
                low = cs.lower()
                if cs and low not in seen and len(cs) <= 100:
                    seen.add(low)
                    cleaned.append(cs)
                if len(cleaned) >= max_len:
                    break
            return cleaned

        summary = clean_str(raw.get("summary", "Instagram Reel"))[:500]
        if not summary:
            summary = "Instagram Reel"

        return StructuredContext(
            summary=summary,
            objects=clean_list(raw.get("objects", []), 30),
            actions=clean_list(raw.get("actions", []), 20),
            entities=clean_list(raw.get("entities", []), 30),
            topics=clean_list(raw.get("topics", []), 30),
            environments=clean_list(raw.get("environments", []), 20),
            visual_style=clean_list(raw.get("visual_style", []), 20),
            keywords=clean_list(raw.get("keywords", []), 50)
        )

    @staticmethod
    def build_searchable_text(ctx: StructuredContext) -> str:
        """
        Builds flattened searchable text as per Section 11:
        searchable_text = summary + entities + topics + objects + actions + environments + visual_style + keywords
        """
        parts = [
            ctx.summary,
            " ".join(ctx.entities),
            " ".join(ctx.topics),
            " ".join(ctx.objects),
            " ".join(ctx.actions),
            " ".join(ctx.environments),
            " ".join(ctx.visual_style),
            " ".join(ctx.keywords),
        ]
        return " ".join([p for p in parts if p]).strip()
