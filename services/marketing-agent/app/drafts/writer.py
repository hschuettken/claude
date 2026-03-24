"""Draft writer service — async blog and social content generation."""

import asyncio
import json
import logging
from typing import Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.drafts.governance import scan_risk_flags
from app.drafts.prompts import (
    BLOG_SYSTEM_PROMPT,
    BLOG_OUTLINE_PROMPT,
    BLOG_CONTENT_PROMPT,
    BLOG_CONFIDENCE_PROMPT,
    LINKEDIN_TEASER_PROMPT,
    LINKEDIN_NATIVE_PROMPT,
    SEO_META_PROMPT,
    VISUAL_PROMPT_PROMPT,
    KG_CONTEXT_BLOCK,
)
from app.knowledge_graph import Neo4jSingleton, MarketingKGQuery
from config import settings
from models import Topic, Draft, Signal

logger = logging.getLogger(__name__)


class DraftWriter:
    """Service for generating blog and social drafts."""

    def __init__(self, db: Session):
        self.db = db
        self.llm_client = None
        self.kg_query = None
        self._init_llm_client()
        self._init_kg_query()

    def _init_llm_client(self):
        """Initialize LLM client based on config."""
        if settings.llm_provider == "ollama":
            self.llm_client = OllamaClient(settings.ollama_url, settings.llm_model)
        else:
            self.llm_client = OpenAIClient(settings.openai_api_key)

    def _init_kg_query(self):
        """Initialize Knowledge Graph query service."""
        neo4j = Neo4jSingleton()
        self.kg_query = MarketingKGQuery(neo4j) if neo4j.connected else None

    async def generate_blog_draft(self, topic_id: int, timeout: Optional[int] = None) -> Optional[Draft]:
        """
        Generate a complete blog draft from a topic.

        Flow:
        1. Load topic + signals
        2. Generate outline
        3. Generate full article
        4. Label confidence
        5. Scan risk flags
        6. Generate SEO meta
        7. Generate visual prompt
        8. Store in database

        Returns Draft object or None on failure.
        """
        timeout = timeout or settings.draft_generation_timeout

        try:
            # Load topic
            topic = self.db.query(Topic).filter(Topic.id == topic_id).first()
            if not topic:
                logger.error(f"Topic {topic_id} not found")
                return None

            logger.info(f"Generating blog draft for topic {topic.name}")

            # Load signals
            signal_ids = topic.signal_ids or []
            signals = self.db.query(Signal).filter(Signal.id.in_(signal_ids)).all() if signal_ids else []
            signals_text = self._format_signals(signals)

            # Build KG enrichment context
            kg_context = await self._build_kg_context(topic)

            # Generate outline
            logger.info("Generating outline...")
            outline = await asyncio.wait_for(
                self._generate_outline(topic, signals_text, kg_context),
                timeout=timeout,
            )
            if not outline:
                logger.error("Failed to generate outline")
                return None

            # Generate full content
            logger.info("Generating article content...")
            content = await asyncio.wait_for(
                self._generate_content(topic, outline, signals_text, kg_context),
                timeout=timeout,
            )
            if not content:
                logger.error("Failed to generate content")
                return None

            # Validate word count
            word_count = len(content.split())
            if word_count < settings.draft_min_words or word_count > settings.draft_max_words:
                logger.warning(f"Word count {word_count} out of range [{settings.draft_min_words}, {settings.draft_max_words}]")

            # Label confidence
            logger.info("Labeling confidence...")
            confidence_labels = await asyncio.wait_for(
                self._label_confidence(content),
                timeout=30,
            )

            # Scan risk flags
            logger.info("Scanning for risk flags...")
            risk_flags = await scan_risk_flags(content)

            # Generate SEO meta
            logger.info("Generating SEO metadata...")
            seo_meta = await asyncio.wait_for(
                self._generate_seo_meta(topic, content[:500]),
                timeout=30,
            )

            # Generate visual prompt
            logger.info("Generating visual prompt...")
            visual_prompt = await asyncio.wait_for(
                self._generate_visual_prompt(topic, outline),
                timeout=30,
            )

            # Extract sources
            sources = [{"title": s.title, "url": s.url, "source": s.source} for s in signals]

            # Create draft object
            draft = Draft(
                title=outline.get("title", topic.name),
                content=content,
                status="draft",
                topic_id=topic_id,
                platform="blog",
            )

            # Store extended fields if schema supports
            if hasattr(draft, "format"):
                draft.format = "blog"
            if hasattr(draft, "outline"):
                draft.outline = outline
            if hasattr(draft, "sources"):
                draft.sources = sources
            if hasattr(draft, "word_count"):
                draft.word_count = word_count
            if hasattr(draft, "seo_meta"):
                draft.seo_meta = seo_meta
            if hasattr(draft, "visual_prompt"):
                draft.visual_prompt = visual_prompt
            if hasattr(draft, "confidence_labels"):
                draft.confidence_labels = confidence_labels
            if hasattr(draft, "risk_flags"):
                draft.risk_flags = [f.dict() for f in risk_flags]

            self.db.add(draft)
            self.db.commit()
            self.db.refresh(draft)

            logger.info(f"Created draft {draft.id} for topic {topic_id}")
            
            # Publish draft.created event
            try:
                from app.drafts.events import on_draft_created
                await on_draft_created(
                    draft_id=draft.id,
                    title=draft.title,
                    topic_id=topic_id,
                    format=getattr(draft, 'format', 'blog'),
                    word_count=getattr(draft, 'word_count', word_count),
                )
            except Exception as e:
                logger.warning(f"Failed to publish draft.created event: {e}")
            
            return draft

        except asyncio.TimeoutError:
            logger.error(f"Draft generation timeout for topic {topic_id}")
            return None
        except Exception as e:
            logger.error(f"Error generating draft for topic {topic_id}: {e}", exc_info=True)
            return None

    async def generate_linkedin_teaser(self, draft_id: int) -> Optional[Draft]:
        """Generate LinkedIn teaser from blog draft."""
        try:
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if not draft:
                logger.error(f"Draft {draft_id} not found")
                return None

            # Generate teaser
            teaser_content = await self._generate_linkedin_teaser(draft)
            if not teaser_content:
                return None

            # Create new draft
            teaser_draft = Draft(
                title=f"[LinkedIn] {draft.title}",
                content=teaser_content,
                status="draft",
                topic_id=draft.topic_id,
                platform="linkedin",
            )

            if hasattr(teaser_draft, "format"):
                teaser_draft.format = "linkedin_teaser"
            if hasattr(teaser_draft, "word_count"):
                teaser_draft.word_count = len(teaser_content.split())

            self.db.add(teaser_draft)
            self.db.commit()
            self.db.refresh(teaser_draft)

            logger.info(f"Created LinkedIn teaser draft {teaser_draft.id}")
            return teaser_draft

        except Exception as e:
            logger.error(f"Error generating LinkedIn teaser for draft {draft_id}: {e}", exc_info=True)
            return None

    async def generate_linkedin_native(self, draft_id: int) -> Optional[Draft]:
        """Generate LinkedIn native post (standalone)."""
        try:
            draft = self.db.query(Draft).filter(Draft.id == draft_id).first()
            if not draft:
                logger.error(f"Draft {draft_id} not found")
                return None

            # Generate native
            native_content = await self._generate_linkedin_native(draft)
            if not native_content:
                return None

            # Create new draft
            native_draft = Draft(
                title=f"[LinkedIn Native] {draft.title}",
                content=native_content,
                status="draft",
                topic_id=draft.topic_id,
                platform="linkedin",
            )

            if hasattr(native_draft, "format"):
                native_draft.format = "linkedin_native"
            if hasattr(native_draft, "word_count"):
                native_draft.word_count = len(native_content.split())

            self.db.add(native_draft)
            self.db.commit()
            self.db.refresh(native_draft)

            logger.info(f"Created LinkedIn native draft {native_draft.id}")
            return native_draft

        except Exception as e:
            logger.error(f"Error generating LinkedIn native for draft {draft_id}: {e}", exc_info=True)
            return None

    # Private helper methods

    def _format_signals(self, signals: List[Signal]) -> str:
        """Format signals for prompt context."""
        lines = []
        for s in signals:
            lines.append(f"- {s.title} ({s.source})")
        return "\n".join(lines)

    async def _build_kg_context(self, topic: Topic) -> Dict:
        """
        Build Knowledge Graph enrichment context.

        Queries the KG for:
        - Published posts on similar topics
        - Active Orbit tasks related to the topic
        - Content pillar statistics

        Returns empty dict if KG unavailable.
        """
        if not self.kg_query or not self.kg_query.is_available():
            logger.debug("KG unavailable; skipping enrichment context")
            return {}

        try:
            # Extract keywords from topic title and summary
            keywords = topic.name.split()[:5]  # First 5 words as keywords
            if not keywords:
                keywords = ["content"]

            logger.info(f"Querying KG for context with keywords: {keywords}")

            # Get published posts on similar topics
            published_posts = await self.kg_query.get_published_posts_on_topic(keywords)

            # Get active projects
            active_projects = await self.kg_query.get_related_orbit_tasks(keywords)

            # Get pillar statistics
            pillar_stats = {}
            if topic.pillar_id:
                pillar_stats = await self.kg_query.get_pillar_statistics(topic.pillar_id)

            context = {
                "published_posts": published_posts,
                "active_projects": active_projects,
                "pillar_stats": pillar_stats,
            }

            logger.info(
                f"✓ KG context: {len(published_posts)} published posts, "
                f"{len(active_projects)} active projects"
            )
            return context

        except Exception as e:
            logger.error(f"Error building KG context: {e}", exc_info=True)
            return {}

    async def _generate_outline(self, topic: Topic, signals_text: str, kg_context: Optional[Dict] = None) -> Optional[Dict]:
        """Generate blog outline with optional KG context enrichment."""
        # Build KG context block if provided
        kg_context_block = ""
        if kg_context:
            sections = []
            
            if kg_context.get("published_posts"):
                posts_text = "\n".join(
                    [f"  - {p.get('title', 'Unknown')} ({p.get('format', 'blog')})" 
                     for p in kg_context["published_posts"][:3]]
                )
                sections.append(f"## Previously Published Posts\n{posts_text}")
            
            if kg_context.get("active_projects"):
                projects_text = "\n".join(
                    [f"  - {p.get('title', 'Unknown')} ({p.get('status', 'active')})"
                     for p in kg_context["active_projects"][:2]]
                )
                sections.append(f"## Related Active Projects\n{projects_text}")
            
            if kg_context.get("pillar_stats"):
                stats = kg_context["pillar_stats"]
                sections.append(
                    f"## Content Coverage for This Pillar\n"
                    f"  - Total posts: {stats.get('post_count', 0)}\n"
                    f"  - Published: {stats.get('published_count', 0)}\n"
                    f"  - Last published: {stats.get('last_published', 'N/A')}"
                )
            
            if sections:
                kg_context_block = "\n\n" + "## Knowledge Graph Context\n" + "\n\n".join(sections)

        # Build prompt with optional KG context
        prompt = BLOG_OUTLINE_PROMPT.format(
            title=topic.name,
            summary=topic.name,  # TODO: use actual summary
            signals=signals_text,
        )
        
        if kg_context_block:
            prompt += kg_context_block
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        if not response:
            return None

        try:
            outline = json.loads(response)
            return outline
        except json.JSONDecodeError:
            logger.error(f"Failed to parse outline JSON: {response[:200]}")
            # Return default outline
            return {
                "title": topic.name,
                "subtitle": "Technical insights",
                "hook": "Let's explore this topic.",
                "sections": [{"h2": "Introduction", "description": ""}],
                "takeaways": [],
                "cta": "Share your thoughts"
            }

    async def _generate_content(self, topic: Topic, outline: Dict, signals_text: str, kg_context: Optional[Dict] = None) -> Optional[str]:
        """Generate full article content with optional KG context."""
        prompt = BLOG_CONTENT_PROMPT.format(
            outline=json.dumps(outline),
            title=topic.name,
            signals=signals_text,
        )
        
        # Append KG context if available
        if kg_context:
            sections = []
            if kg_context.get("published_posts"):
                posts_text = "\n".join(
                    [f"  - {p.get('title', 'Unknown')}" for p in kg_context["published_posts"][:3]]
                )
                sections.append(f"These posts have been previously written on related topics:\n{posts_text}")
            
            if sections:
                prompt += "\n\nContext from Knowledge Graph:\n" + "\n\n".join(sections)
        
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        return response

    async def _label_confidence(self, content: str) -> Dict[str, str]:
        """Label confidence levels for sections."""
        prompt = BLOG_CONFIDENCE_PROMPT.format(content=content[:1000])
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        if not response:
            return {}

        try:
            labels = json.loads(response)
            return labels
        except json.JSONDecodeError:
            logger.error(f"Failed to parse confidence labels: {response[:200]}")
            return {}

    async def _generate_seo_meta(self, topic: Topic, content_preview: str) -> Optional[Dict]:
        """Generate SEO metadata."""
        prompt = SEO_META_PROMPT.format(
            title=topic.name,
            summary=content_preview,
        )
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        if not response:
            return None

        try:
            meta = json.loads(response)
            return meta
        except json.JSONDecodeError:
            logger.error(f"Failed to parse SEO meta: {response[:200]}")
            return None

    async def _generate_visual_prompt(self, topic: Topic, outline: Dict) -> Optional[str]:
        """Generate image generation prompt."""
        concepts = outline.get("sections", [])
        prompt = VISUAL_PROMPT_PROMPT.format(
            title=topic.name,
            summary=topic.name,
            concepts=", ".join([s.get("h2", "") for s in concepts[:3]]),
        )
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        if not response:
            return None

        try:
            data = json.loads(response)
            return data.get("visual_prompt", "")
        except json.JSONDecodeError:
            logger.error(f"Failed to parse visual prompt: {response[:200]}")
            return None

    async def _generate_linkedin_teaser(self, draft: Draft) -> Optional[str]:
        """Generate LinkedIn teaser from blog draft."""
        prompt = LINKEDIN_TEASER_PROMPT.format(
            title=draft.title,
            content_preview=draft.content[:500],
        )
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        return response

    async def _generate_linkedin_native(self, draft: Draft) -> Optional[str]:
        """Generate LinkedIn native post."""
        # Extract key concepts
        concepts = draft.title
        prompt = LINKEDIN_NATIVE_PROMPT.format(
            title=draft.title,
            key_concepts=concepts,
        )
        response = await self.llm_client.generate(BLOG_SYSTEM_PROMPT, prompt)
        return response


class LLMClient:
    """Base LLM client."""

    async def generate(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Generate response from LLM."""
        raise NotImplementedError


class OllamaClient(LLMClient):
    """Ollama LLM client."""

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model

    async def generate(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Generate response from Ollama."""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "system": system_prompt,
                        "prompt": user_prompt,
                        "stream": False,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", "")
                else:
                    logger.error(f"Ollama error: {response.status_code} {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Ollama client error: {e}")
            return None


class OpenAIClient(LLMClient):
    """OpenAI API client."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def generate(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        """Generate response from OpenAI."""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "gpt-4-turbo",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.7,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"OpenAI error: {response.status_code} {response.text}")
                    return None
        except Exception as e:
            logger.error(f"OpenAI client error: {e}")
            return None
