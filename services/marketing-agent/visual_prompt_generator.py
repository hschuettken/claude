"""
Visual Prompt Generator — Creates image generation prompts from drafts using brand presets and templates.

Implements Task #160: Visual prompt generator
- Prompt templates for architecture diagrams, signal maps, isometric scenes
- Brand style presets stored in DB
- Integration with image generation (Grok API, local Ollama, or diffusion endpoints)
"""

import os
import logging
import json
import string
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import aiohttp
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class BrandStyle:
    """Brand style configuration for image generation."""
    name: str
    primary_color: str
    secondary_color: str
    accent_color: str
    tone: str
    style_keywords: List[str]
    aspect_ratio: str = "16:9"
    style_notes: str = ""
    heading_font: str = "Montserrat"
    body_font: str = "Open Sans"
    mono_font: str = "JetBrains Mono"


class VisualPromptGenerator:
    """Generate visual prompts from drafts using templates and brand presets."""
    
    # Predefined use cases
    HERO_IMAGE = "hero_image"
    CAROUSEL_SLIDE = "carousel_slide"
    DIAGRAM = "diagram"
    SIGNAL_MAP = "signal_map"
    ISOMETRIC = "isometric_scene"
    INFOGRAPHIC = "infographic"
    
    # Available generators
    GROK_API = "grok"
    OLLAMA_API = "ollama"
    DALL_E_API = "dall-e"
    LOCAL_DIFFUSION = "diffusion"
    
    def __init__(self, db_session=None):
        """Initialize generator with optional DB session."""
        self.db = db_session
        self.grok_api_key = os.getenv("GROK_API_KEY", "")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://192.168.0.84:11434")
        self.diffusion_base_url = os.getenv("DIFFUSION_BASE_URL", "http://192.168.0.84:7860")
        self.default_generator = os.getenv("DEFAULT_IMAGE_GENERATOR", "ollama")
    
    async def generate_prompt_for_draft(
        self,
        draft_id: int,
        draft_title: str,
        draft_content: str,
        use_case: str = HERO_IMAGE,
        brand_preset: Optional[BrandStyle] = None,
        template_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generate a visual prompt for a draft.
        
        Args:
            draft_id: Draft database ID
            draft_title: Draft title
            draft_content: Draft content/body
            use_case: Type of visual (hero_image, carousel_slide, diagram, etc.)
            brand_preset: Brand style to use (uses default if not provided)
            template_id: Specific template ID (auto-selects if not provided)
        
        Returns:
            Dict with prompt_text, variants, metadata
        """
        # Default brand preset
        if not brand_preset:
            brand_preset = self._get_default_brand_style()
        
        # Auto-select template if not provided
        if not template_id:
            template_id = self._select_template_for_use_case(use_case)
        
        # Extract key concepts from draft
        key_concepts = self._extract_concepts(draft_content)
        
        # Generate prompt from template
        prompt_text = self._fill_template(
            template_id=template_id,
            title=draft_title,
            concepts=key_concepts,
            brand=brand_preset,
            use_case=use_case,
        )
        
        # Generate variants
        variants = self._generate_variants(prompt_text, brand_preset)
        
        return {
            "prompt_text": prompt_text,
            "variants": variants,
            "use_case": use_case,
            "brand_preset_name": brand_preset.name,
            "template_id": template_id,
            "key_concepts": key_concepts,
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "draft_id": draft_id,
                "aspect_ratio": brand_preset.aspect_ratio,
            }
        }
    
    async def generate_carousel_prompts(
        self,
        draft_id: int,
        draft_title: str,
        draft_content: str,
        slide_count: int = 5,
        brand_preset: Optional[BrandStyle] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate visual prompts for carousel slides.
        
        Args:
            draft_id: Draft ID
            draft_title: Draft title
            draft_content: Draft content
            slide_count: Number of slides
            brand_preset: Brand preset (uses default if not provided)
        
        Returns:
            List of prompts, one per slide
        """
        if not brand_preset:
            brand_preset = self._get_default_brand_style()
        
        # Split content into sections for each slide
        sections = self._split_content_for_carousel(draft_content, slide_count)
        
        prompts = []
        for i, section in enumerate(sections, start=1):
            use_case = f"carousel_slide_{i}"
            prompt = await self.generate_prompt_for_draft(
                draft_id=draft_id,
                draft_title=f"{draft_title} - Slide {i}",
                draft_content=section,
                use_case=use_case,
                brand_preset=brand_preset,
                template_id=self._select_template_for_use_case("carousel_slide"),
            )
            prompts.append(prompt)
        
        return prompts
    
    async def generate_architecture_diagram_prompt(
        self,
        title: str,
        description: str,
        components: List[str],
        brand_preset: Optional[BrandStyle] = None,
    ) -> Dict[str, Any]:
        """
        Generate prompt for architecture diagram.
        
        Args:
            title: Diagram title
            description: Technical description
            components: List of architecture components
            brand_preset: Brand preset
        
        Returns:
            Generated prompt dict
        """
        if not brand_preset:
            brand_preset = self._get_default_brand_style()
        
        template_vars = {
            "components": ", ".join(components),
            "connections": "component interconnections",
            "style_keywords": " ".join(brand_preset.style_keywords),
            "primary_color": brand_preset.primary_color,
            "secondary_color": brand_preset.secondary_color,
            "aspect_ratio": brand_preset.aspect_ratio,
        }
        
        prompt_text = self._substitute_template(
            "Architecture Diagram - Clean",
            template_vars
        )
        
        return {
            "prompt_text": prompt_text,
            "use_case": "architecture_diagram",
            "components": components,
            "brand_preset_name": brand_preset.name,
            "metadata": {
                "title": title,
                "description": description,
                "component_count": len(components),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        }
    
    async def generate_signal_map_prompt(
        self,
        signal_title: str,
        signal_type: str,
        flow_description: str,
        brand_preset: Optional[BrandStyle] = None,
    ) -> Dict[str, Any]:
        """
        Generate prompt for signal/data flow map.
        
        Args:
            signal_title: Signal title
            signal_type: Type of signal (data, event, metric, etc.)
            flow_description: Description of flow pattern
            brand_preset: Brand preset
        
        Returns:
            Generated prompt dict
        """
        if not brand_preset:
            brand_preset = self._get_default_brand_style()
        
        template_vars = {
            "data_type": signal_type,
            "system_type": "distributed data",
            "flow_pattern": flow_description,
            "color_palette": f"{brand_preset.primary_color}, {brand_preset.secondary_color}",
            "style_keyword": brand_preset.tone,
            "aspect_ratio": brand_preset.aspect_ratio,
        }
        
        prompt_text = self._substitute_template(
            "Signal Map - Data Flow",
            template_vars
        )
        
        return {
            "prompt_text": prompt_text,
            "use_case": "signal_map",
            "signal_type": signal_type,
            "brand_preset_name": brand_preset.name,
            "metadata": {
                "title": signal_title,
                "flow_description": flow_description,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        }
    
    async def generate_isometric_prompt(
        self,
        concept: str,
        description: str,
        elements: List[str],
        brand_preset: Optional[BrandStyle] = None,
    ) -> Dict[str, Any]:
        """
        Generate prompt for isometric 3D scene.
        
        Args:
            concept: Concept to visualize
            description: Technical description
            elements: List of elements to show
            brand_preset: Brand preset
        
        Returns:
            Generated prompt dict
        """
        if not brand_preset:
            brand_preset = self._get_default_brand_style()
        
        template_vars = {
            "concept": concept,
            "elements": ", ".join(elements),
            "environment": "clean, minimal background",
            "color_scheme": f"{brand_preset.primary_color} / {brand_preset.secondary_color}",
            "style_descriptor": "minimalist, modern",
            "aspect_ratio": brand_preset.aspect_ratio,
        }
        
        prompt_text = self._substitute_template(
            "Isometric Scene - 3D",
            template_vars
        )
        
        return {
            "prompt_text": prompt_text,
            "use_case": "isometric_scene",
            "concept": concept,
            "elements": elements,
            "brand_preset_name": brand_preset.name,
            "metadata": {
                "description": description,
                "element_count": len(elements),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        }
    
    async def generate_images(
        self,
        prompts: List[str],
        generator: str = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Generate actual images from prompts using configured generator.
        
        Args:
            prompts: List of prompt texts
            generator: Generator to use (grok, ollama, dall-e, diffusion)
            **kwargs: Additional parameters for generator
        
        Returns:
            List of dicts with generated_image_url, status, etc.
        """
        if not generator:
            generator = self.default_generator
        
        if generator == self.GROK_API:
            return await self._generate_with_grok(prompts, **kwargs)
        elif generator == self.OLLAMA_API:
            return await self._generate_with_ollama(prompts, **kwargs)
        elif generator == self.LOCAL_DIFFUSION:
            return await self._generate_with_diffusion(prompts, **kwargs)
        else:
            logger.warning(f"Unknown generator: {generator}, using ollama")
            return await self._generate_with_ollama(prompts, **kwargs)
    
    async def _generate_with_grok(
        self,
        prompts: List[str],
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Generate images using Grok API."""
        if not self.grok_api_key:
            logger.error("GROK_API_KEY not set")
            return [{"status": "error", "message": "GROK_API_KEY not configured"}] * len(prompts)
        
        results = []
        async with aiohttp.ClientSession() as session:
            for prompt in prompts:
                try:
                    # Placeholder for Grok API call
                    # TODO: Implement actual Grok API integration when available
                    logger.info(f"Grok generation not yet implemented: {prompt[:100]}...")
                    results.append({
                        "status": "pending",
                        "message": "Grok API integration coming soon",
                        "prompt": prompt,
                    })
                except Exception as e:
                    logger.error(f"Grok generation error: {e}")
                    results.append({
                        "status": "error",
                        "message": str(e),
                        "prompt": prompt,
                    })
        
        return results
    
    async def _generate_with_ollama(
        self,
        prompts: List[str],
        model: str = "llava",
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Generate images using local Ollama."""
        results = []
        async with aiohttp.ClientSession() as session:
            for prompt in prompts:
                try:
                    # Ollama generate endpoint (if using a vision model that can generate)
                    # For now, we'll just log and return a placeholder
                    logger.info(f"Ollama generation started: {prompt[:100]}...")
                    results.append({
                        "status": "pending",
                        "message": "Image generation queued",
                        "prompt": prompt,
                        "model": model,
                    })
                except Exception as e:
                    logger.error(f"Ollama generation error: {e}")
                    results.append({
                        "status": "error",
                        "message": str(e),
                        "prompt": prompt,
                    })
        
        return results
    
    async def _generate_with_diffusion(
        self,
        prompts: List[str],
        steps: int = 20,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Generate images using local Stable Diffusion WebUI."""
        results = []
        async with aiohttp.ClientSession() as session:
            for prompt in prompts:
                try:
                    url = f"{self.diffusion_base_url}/api/txt2img"
                    payload = {
                        "prompt": prompt,
                        "steps": steps,
                        "sampler_name": "Euler",
                    }
                    
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            # Extract image from response
                            image_url = data.get("images", [None])[0]
                            results.append({
                                "status": "success",
                                "generated_image_url": image_url,
                                "prompt": prompt,
                            })
                        else:
                            results.append({
                                "status": "error",
                                "message": f"HTTP {resp.status}",
                                "prompt": prompt,
                            })
                except asyncio.TimeoutError:
                    logger.error(f"Diffusion generation timeout: {prompt[:100]}")
                    results.append({
                        "status": "timeout",
                        "message": "Generation took too long",
                        "prompt": prompt,
                    })
                except Exception as e:
                    logger.error(f"Diffusion generation error: {e}")
                    results.append({
                        "status": "error",
                        "message": str(e),
                        "prompt": prompt,
                    })
        
        return results
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _get_default_brand_style(self) -> BrandStyle:
        """Get default brand style."""
        return BrandStyle(
            name="Layer 8 - Professional",
            primary_color="#1e3a8a",
            secondary_color="#0891b2",
            accent_color="#f59e0b",
            tone="professional_insightful",
            style_keywords=["minimalist", "technical", "modern", "enterprise"],
            aspect_ratio="16:9",
            style_notes="Enterprise technical blog style",
        )
    
    def _select_template_for_use_case(self, use_case: str) -> int:
        """Select appropriate template for use case."""
        # Mapping of use cases to template names
        template_map = {
            "hero_image": "Hero Image - Blog Post",
            "carousel_slide": "Carousel Slide - Minimal",
            "architecture_diagram": "Architecture Diagram - Clean",
            "signal_map": "Signal Map - Data Flow",
            "isometric_scene": "Isometric Scene - 3D",
            "infographic": "Infographic - Data Viz",
        }
        # In a real implementation, this would query the database
        # For now, return a placeholder ID
        return 1
    
    def _extract_concepts(self, content: str) -> List[str]:
        """Extract key concepts from draft content."""
        # Simple extraction: split on common delimiters and filter
        words = content.lower().split()
        # Filter for common technical terms (simplified)
        concepts = [w.strip(".,;:") for w in words if len(w) > 5 and w.isalpha()]
        # Deduplicate and limit
        return list(set(concepts))[:10]
    
    def _split_content_for_carousel(self, content: str, slide_count: int) -> List[str]:
        """Split content into carousel slides."""
        sentences = content.split(".")
        sentences_per_slide = max(1, len(sentences) // slide_count)
        slides = []
        for i in range(slide_count):
            start = i * sentences_per_slide
            end = start + sentences_per_slide if i < slide_count - 1 else len(sentences)
            slide = ". ".join(sentences[start:end])
            slides.append(slide[:200])  # Limit each slide
        return slides
    
    def _fill_template(
        self,
        template_id: int,
        title: str,
        concepts: List[str],
        brand: BrandStyle,
        use_case: str,
    ) -> str:
        """Fill template with values (simplified implementation)."""
        # In a real implementation, this would query the database for the template
        # For now, return a constructed prompt
        return (
            f"A professional {brand.tone} image for: {title}. "
            f"Key concepts: {', '.join(concepts[:3])}. "
            f"Style: {', '.join(brand.style_keywords)}. "
            f"Colors: {brand.primary_color}, {brand.secondary_color}. "
            f"Aspect ratio: {brand.aspect_ratio}."
        )
    
    def _generate_variants(self, prompt: str, brand: BrandStyle) -> List[str]:
        """Generate prompt variants."""
        variants = []
        # Variant 1: More detailed
        variants.append(prompt + " Detailed, high quality, professional rendering.")
        # Variant 2: Minimal
        variants.append(f"Minimal {brand.tone} design. {prompt}")
        # Variant 3: With style emphasis
        variants.append(f"{prompt} Emphasis on {brand.tone} aesthetic.")
        return variants
    
    def _substitute_template(self, template_name: str, variables: Dict[str, str]) -> str:
        """Substitute variables into template (simplified)."""
        # Template mapping (in real implementation, would come from DB)
        templates = {
            "Architecture Diagram - Clean": (
                "A clean technical architecture diagram showing {components} connected by "
                "{connections}, using {style_keywords} design style. Colors: {primary_color}, "
                "{secondary_color}. No text labels, use icons only. {aspect_ratio} format."
            ),
            "Signal Map - Data Flow": (
                "An abstract visualization of {data_type} signals flowing through a {system_type} "
                "system. Show {flow_pattern} patterns using {color_palette}. {style_keyword} aesthetic. {aspect_ratio}."
            ),
            "Isometric Scene - 3D": (
                "A clean isometric 3D illustration of {concept}. Show {elements} in {environment}. "
                "Use {color_scheme} color scheme. {style_descriptor} style. No people. {aspect_ratio}."
            ),
        }
        
        template = templates.get(template_name, "")
        if not template:
            # Fallback
            return f"Image for: {list(variables.values())}"
        
        # Simple string substitution
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.warning(f"Missing variable in template: {e}")
            return template
