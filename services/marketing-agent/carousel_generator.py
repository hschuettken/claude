"""Carousel Generator — Convert blog posts into structured carousel slides with visual prompts.

Implements Task #188: Carousel generator
- Blog→Carousel conversion
- Layout prompts with visual design specifications
- Brand consistency via style presets
"""

import logging
import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class BrandTone(str, Enum):
    """Voice tone presets."""
    professional_insightful = "professional_insightful"
    technical_deep = "technical_deep"
    approachable_friendly = "approachable_friendly"
    innovative_forward_thinking = "innovative_forward_thinking"


class LayoutType(str, Enum):
    """Carousel slide layout types."""
    slide_title = "slide_title"  # Title slide with logo/branding
    slide_content = "slide_content"  # Content with text + visual
    slide_quote = "slide_quote"  # Quote/callout slide
    slide_list = "slide_list"  # Bullet list slide
    slide_cta = "slide_cta"  # Call-to-action final slide


@dataclass
class ColorPalette:
    """Brand color palette."""
    primary: str = "#1e3a8a"
    secondary: str = "#0891b2"
    accent: str = "#f59e0b"
    text_dark: str = "#1f2937"
    text_light: str = "#f3f4f6"
    background: str = "#ffffff"


@dataclass
class BrandStyle:
    """Brand style configuration for carousels."""
    name: str = "default"
    tone: BrandTone = BrandTone.professional_insightful
    colors: ColorPalette = None
    fonts: Dict[str, str] = None
    max_words_per_slide: int = 45
    include_cta: bool = True
    style_notes: str = ""
    
    def __post_init__(self):
        if self.colors is None:
            self.colors = ColorPalette()
        if self.fonts is None:
            self.fonts = {
                "heading": "Montserrat",
                "body": "Open Sans",
                "mono": "JetBrains Mono"
            }


class CarouselGenerator:
    """Generate carousels from blog posts with visual layout prompts and brand consistency."""
    
    def __init__(self, brand_style: Optional[BrandStyle] = None):
        """Initialize carousel generator with optional brand style."""
        self.brand_style = brand_style or BrandStyle()
        self.llm_client = None  # To be initialized with actual LLM integration
    
    async def generate_slides(
        self,
        title: str,
        content: str,
        summary: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Generate carousel slides from blog post content.
        
        Produces 5-7 slides with:
        - Structured slide text (max 45 words per slide)
        - Layout type (title, content, quote, list, cta)
        - Visual prompt for design/image generation
        - Layout description with positioning and typography
        - Brand-consistent styling
        
        Args:
            title: Blog post title
            content: Full blog post content (markdown or HTML)
            summary: Optional summary/excerpt
        
        Returns:
            List of carousel slides with full structure
        """
        logger.info(f"Generating carousel: {title}")
        
        # Clean and normalize content
        content = self._clean_content(content)
        
        # Extract key points and structure from content
        key_points = self._extract_key_points(title, content, summary)
        
        # Generate slide structure (5-7 slides)
        slide_count = self._determine_slide_count(len(key_points))
        
        # Generate slides
        slides = []
        
        # Slide 1: Title slide
        slides.append(self._generate_title_slide(title))
        
        # Slides 2-N: Content slides (distribute key points)
        content_slides = self._distribute_content_into_slides(
            key_points,
            slide_count - 2,  # Reserve first and last slide
            self.brand_style.max_words_per_slide
        )
        for i, slide_data in enumerate(content_slides, start=2):
            slides.append(self._generate_content_slide(slide_data, slide_number=i))
        
        # Final slide: CTA slide
        if self.brand_style.include_cta:
            slides.append(self._generate_cta_slide(slide_number=len(slides) + 1))
        
        logger.info(f"Generated {len(slides)} carousel slides")
        return slides
    
    def _clean_content(self, content: str) -> str:
        """Clean HTML/markdown content to plain text."""
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)
        
        # Remove markdown formatting
        content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)  # Bold
        content = re.sub(r'\*(.+?)\*', r'\1', content)  # Italic
        content = re.sub(r'#{1,6}\s(.+)', r'\1', content)  # Headers
        content = re.sub(r'- (.+)', r'\1', content)  # List items
        
        # Clean up extra whitespace
        content = ' '.join(content.split())
        
        return content
    
    def _extract_key_points(self, title: str, content: str, summary: str) -> List[str]:
        """Extract key points and main themes from content."""
        points = []
        
        # Add summary as first point if available
        if summary:
            points.append(summary)
        
        # Split content into sentences and extract substantive ones
        sentences = re.split(r'[.!?]+', content)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 20 and len(sentence) < 300:  # Reasonable sentence length
                # Check if it's substantive (not just filler)
                word_count = len(sentence.split())
                if word_count >= 4:
                    points.append(sentence)
        
        # Keep top 10-12 key points (will be distributed across slides)
        return points[:12]
    
    def _determine_slide_count(self, point_count: int) -> int:
        """Determine optimal slide count based on content."""
        # Rule: 2-3 points per content slide
        content_slides = max(2, min(5, (point_count + 2) // 2))
        
        # Add title and CTA slides
        total = 1 + content_slides + (1 if self.brand_style.include_cta else 0)
        
        # Clamp to 5-7 slides
        return max(5, min(7, total))
    
    def _distribute_content_into_slides(
        self,
        points: List[str],
        slide_count: int,
        max_words: int,
    ) -> List[Dict[str, Any]]:
        """Distribute key points across content slides."""
        distributed = []
        
        if slide_count <= 0:
            return distributed
        
        points_per_slide = max(1, len(points) // slide_count)
        
        for i in range(slide_count):
            start = i * points_per_slide
            end = start + points_per_slide if i < slide_count - 1 else len(points)
            
            slide_points = points[start:end]
            
            # Combine points for this slide, respecting word limit
            combined_text = " ".join(slide_points)
            
            # Truncate if needed
            words = combined_text.split()
            if len(words) > max_words:
                words = words[:max_words]
            combined_text = " ".join(words)
            
            distributed.append({
                "text": combined_text,
                "layout_type": self._select_layout_type(combined_text),
                "source_points": slide_points,
            })
        
        return distributed
    
    def _select_layout_type(self, text: str) -> str:
        """Determine best layout type for text content."""
        # Simple heuristic: check for bullet-list patterns or quote-like structure
        if text.startswith('"') or text.startswith("'"):
            return LayoutType.slide_quote.value
        
        if len(text.split()) <= 20:
            return LayoutType.slide_list.value
        
        return LayoutType.slide_content.value
    
    def _generate_title_slide(self, title: str) -> Dict[str, Any]:
        """Generate title slide."""
        return {
            "slide_number": 1,
            "text": title,
            "word_count": len(title.split()),
            "layout_type": LayoutType.slide_title.value,
            "visual_prompt": self._generate_visual_prompt_title(title),
            "layout_description": self._generate_layout_description_title(),
            "theme_elements": {
                "heading_color": self.brand_style.colors.primary,
                "background_color": self.brand_style.colors.background,
                "accent_color": self.brand_style.colors.accent,
                "font_family": self.brand_style.fonts["heading"],
            },
        }
    
    def _generate_content_slide(
        self,
        slide_data: Dict[str, Any],
        slide_number: int,
    ) -> Dict[str, Any]:
        """Generate content slide with visual prompt and layout."""
        text = slide_data["text"]
        layout_type = slide_data["layout_type"]
        
        return {
            "slide_number": slide_number,
            "text": text,
            "word_count": len(text.split()),
            "layout_type": layout_type,
            "visual_prompt": self._generate_visual_prompt(text, layout_type),
            "layout_description": self._generate_layout_description(text, layout_type),
            "theme_elements": {
                "text_color": self.brand_style.colors.text_dark,
                "background_color": self.brand_style.colors.background,
                "accent_color": self.brand_style.colors.secondary,
                "font_family": self.brand_style.fonts["body"],
                "accent_font": self.brand_style.fonts["heading"],
            },
        }
    
    def _generate_cta_slide(self, slide_number: int) -> Dict[str, Any]:
        """Generate call-to-action final slide."""
        cta_text = "Ready to explore further? Let's connect."
        
        return {
            "slide_number": slide_number,
            "text": cta_text,
            "word_count": len(cta_text.split()),
            "layout_type": LayoutType.slide_cta.value,
            "visual_prompt": self._generate_visual_prompt_cta(),
            "layout_description": self._generate_layout_description_cta(),
            "theme_elements": {
                "heading_color": self.brand_style.colors.primary,
                "button_color": self.brand_style.colors.accent,
                "background_color": self.brand_style.colors.secondary,
                "text_color": self.brand_style.colors.text_light,
                "font_family": self.brand_style.fonts["heading"],
            },
        }
    
    def _generate_visual_prompt_title(self, title: str) -> str:
        """Generate visual prompt for title slide."""
        tone_hint = self._get_tone_hint()
        
        prompt = (
            f"Professional {tone_hint} carousel title slide. "
            f"Typography-focused design with title: '{title}'. "
            f"Use brand colors {self.brand_style.colors.primary}, {self.brand_style.colors.accent}. "
            f"Subtle gradient background, modern minimalist style. "
            f"Include abstract tech/business visual element in background. "
            f"4K quality, clean and professional."
        )
        return prompt
    
    def _generate_visual_prompt(self, text: str, layout_type: str) -> str:
        """Generate visual prompt for content slide."""
        tone_hint = self._get_tone_hint()
        
        # Extract key concept from text
        concept = self._extract_concept(text)
        
        base_prompt = (
            f"Professional {tone_hint} carousel content slide. "
            f"Concept: {concept}. "
            f"Design with plenty of whitespace, {self.brand_style.fonts['body']} typography. "
            f"Use brand colors: primary {self.brand_style.colors.primary}, "
            f"secondary {self.brand_style.colors.secondary}. "
        )
        
        if layout_type == LayoutType.slide_list.value:
            base_prompt += "Layout: bullet points or list format on left, visual element on right. "
        elif layout_type == LayoutType.slide_quote.value:
            base_prompt += "Layout: large quote in center, subtle background pattern. "
        else:
            base_prompt += "Layout: text on left or top, complementary visual/diagram on right. "
        
        base_prompt += "4K quality, modern clean aesthetic."
        return base_prompt
    
    def _generate_visual_prompt_cta(self) -> str:
        """Generate visual prompt for CTA slide."""
        tone_hint = self._get_tone_hint()
        
        prompt = (
            f"Professional {tone_hint} carousel CTA (call-to-action) slide. "
            f"Bold design with primary color {self.brand_style.colors.primary} "
            f"and accent {self.brand_style.colors.accent}. "
            f"Feature a prominent call-to-action button or next steps. "
            f"Include subtle business/tech visual elements. "
            f"Motivational and forward-looking aesthetic. 4K quality."
        )
        return prompt
    
    def _generate_layout_description_title(self) -> str:
        """Generate layout description for title slide."""
        return (
            "Title slide layout: "
            f"Large heading ({self.brand_style.fonts['heading']}) centered or left-aligned at 54-72pt. "
            f"Subtle background gradient from {self.brand_style.colors.primary} to white. "
            "Logo/brand element in corner. "
            "Ample whitespace. Full-width 16:9 aspect ratio."
        )
    
    def _generate_layout_description(self, text: str, layout_type: str) -> str:
        """Generate layout description for content slide."""
        base = (
            f"Content slide layout ({layout_type}): "
            f"Body font: {self.brand_style.fonts['body']} at 24-32pt. "
            f"Heading/accent font: {self.brand_style.fonts['heading']}. "
            f"Text color: {self.brand_style.colors.text_dark}. "
            f"Background: white or {self.brand_style.colors.background}. "
        )
        
        if layout_type == LayoutType.slide_list.value:
            base += "Bullet layout: 4-6 bullets, left-aligned column (60% width), visual on right (40%). "
        elif layout_type == LayoutType.slide_quote.value:
            base += "Quote layout: large centered quote in 32-48pt, attribution below, "
            base += f"accent line in {self.brand_style.colors.secondary}. "
        else:
            base += "Mixed layout: text on left (60%), visual/diagram on right (40%) or above. "
        
        base += "16:9 aspect ratio, ~16px padding."
        return base
    
    def _generate_layout_description_cta(self) -> str:
        """Generate layout description for CTA slide."""
        return (
            f"CTA slide layout: "
            f"Large heading ({self.brand_style.fonts['heading']} 48-64pt) in white or {self.brand_style.colors.text_light}. "
            f"Subheading/supporting text at 24-28pt. "
            f"Prominent button or 'next steps' call-out in {self.brand_style.colors.accent}. "
            f"Background gradient: {self.brand_style.colors.primary} to {self.brand_style.colors.secondary}. "
            "Center-aligned layout, high contrast text. 16:9 aspect ratio."
        )
    
    def _get_tone_hint(self) -> str:
        """Get tone description for visual prompts."""
        tone_map = {
            BrandTone.professional_insightful: "professional and insightful",
            BrandTone.technical_deep: "technical and detailed",
            BrandTone.approachable_friendly: "approachable and friendly",
            BrandTone.innovative_forward_thinking: "innovative and forward-thinking",
        }
        return tone_map.get(self.brand_style.tone, "professional")
    
    def _extract_concept(self, text: str) -> str:
        """Extract main concept from slide text."""
        # Simple: first few words or key term
        words = text.split()
        if len(words) <= 5:
            return text
        return " ".join(words[:3]) + "..."
