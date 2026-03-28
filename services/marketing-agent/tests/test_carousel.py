"""Unit tests for carousel generator (Task #188)."""

import pytest
import asyncio
import sys
from pathlib import Path
import importlib.util

# Import carousel_generator from parent directory
carousel_path = Path(__file__).parent.parent / "carousel_generator.py"
spec = importlib.util.spec_from_file_location("carousel_generator", carousel_path)
carousel_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(carousel_module)

CarouselGenerator = carousel_module.CarouselGenerator
BrandStyle = carousel_module.BrandStyle
BrandTone = carousel_module.BrandTone
LayoutType = carousel_module.LayoutType
ColorPalette = carousel_module.ColorPalette


@pytest.fixture
def brand_style():
    """Create a default brand style for testing."""
    return BrandStyle(
        name="test",
        tone=BrandTone.professional_insightful,
        colors=ColorPalette(
            primary="#1e3a8a",
            secondary="#0891b2",
            accent="#f59e0b",
        ),
        max_words_per_slide=45,
    )


@pytest.fixture
def generator(brand_style):
    """Create carousel generator instance."""
    return CarouselGenerator(brand_style=brand_style)


@pytest.fixture
def sample_blog_post():
    """Sample blog post for testing."""
    return {
        "title": "Getting Started with Carousel Slides",
        "content": """
        Carousel slides are a powerful way to share information visually.
        They allow you to break down complex topics into digestible pieces.
        Each slide should have a clear message and supporting visual.
        When designing carousels, consider your audience and tone.
        Professional presentations require clean, minimalist design.
        Technical content needs clear diagrams and code examples.
        Always include a strong call-to-action at the end.
        Brand consistency ensures recognition across all materials.
        Use consistent colors, fonts, and styling throughout.
        Visual hierarchy guides the viewer's attention.
        """,
        "summary": "A comprehensive guide to creating professional carousels.",
    }


class TestCarouselGenerator:
    """Test suite for CarouselGenerator."""
    
    def test_initialization(self, generator, brand_style):
        """Test generator initialization."""
        assert generator.brand_style == brand_style
        assert generator.brand_style.max_words_per_slide == 45
    
    def test_clean_content(self, generator):
        """Test content cleaning."""
        html_content = "<p><b>Bold text</b> and <i>italic</i> content.</p>"
        cleaned = generator._clean_content(html_content)
        
        assert "<" not in cleaned
        assert ">" not in cleaned
        assert cleaned.startswith("Bold text")
    
    def test_extract_key_points(self, generator, sample_blog_post):
        """Test key point extraction."""
        points = generator._extract_key_points(
            title=sample_blog_post["title"],
            content=sample_blog_post["content"],
            summary=sample_blog_post["summary"],
        )
        
        assert len(points) > 0
        assert sample_blog_post["summary"] in points
    
    def test_determine_slide_count(self, generator):
        """Test slide count determination."""
        # Few points: 5 slides minimum
        count = generator._determine_slide_count(3)
        assert count >= 5
        
        # Many points: 7 slides maximum
        count = generator._determine_slide_count(20)
        assert count <= 7
    
    def test_distribute_content_into_slides(self, generator):
        """Test content distribution across slides."""
        points = [
            "First key point.",
            "Second key point.",
            "Third key point.",
            "Fourth key point.",
            "Fifth key point.",
        ]
        
        distributed = generator._distribute_content_into_slides(
            points=points,
            slide_count=3,
            max_words=45,
        )
        
        assert len(distributed) == 3
        
        for slide in distributed:
            assert "text" in slide
            assert "layout_type" in slide
            word_count = len(slide["text"].split())
            assert word_count <= 45
    
    def test_select_layout_type(self, generator):
        """Test layout type selection."""
        # Quote-like text
        quote = '"This is a powerful insight"'
        assert generator._select_layout_type(quote) == LayoutType.slide_quote.value
        
        # Short text -> list layout
        short = "Point one. Point two."
        layout = generator._select_layout_type(short)
        assert layout in (LayoutType.slide_list.value, LayoutType.slide_content.value)
    
    def test_generate_title_slide(self, generator):
        """Test title slide generation."""
        title = "Getting Started with Carousels"
        slide = generator._generate_title_slide(title)
        
        assert slide["slide_number"] == 1
        assert slide["text"] == title
        assert slide["layout_type"] == LayoutType.slide_title.value
        assert "visual_prompt" in slide
        assert "layout_description" in slide
        assert "theme_elements" in slide
    
    def test_generate_content_slide(self, generator):
        """Test content slide generation."""
        slide_data = {
            "text": "This is a key point for the carousel slide.",
            "layout_type": LayoutType.slide_content.value,
        }
        
        slide = generator._generate_content_slide(slide_data, slide_number=2)
        
        assert slide["slide_number"] == 2
        assert "text" in slide
        assert "visual_prompt" in slide
        assert "layout_description" in slide
        assert slide["layout_type"] in (
            LayoutType.slide_content.value,
            LayoutType.slide_list.value,
        )
    
    def test_generate_cta_slide(self, generator):
        """Test CTA slide generation."""
        slide = generator._generate_cta_slide(slide_number=7)
        
        assert slide["slide_number"] == 7
        assert slide["layout_type"] == LayoutType.slide_cta.value
        assert "visual_prompt" in slide
        assert "layout_description" in slide
        assert "theme_elements" in slide
    
    def test_generate_visual_prompts(self, generator):
        """Test visual prompt generation."""
        # Title slide prompt
        title_prompt = generator._generate_visual_prompt_title("Amazing Topic")
        assert "Professional" in title_prompt or "professional" in title_prompt
        assert "Amazing Topic" in title_prompt
        
        # Content slide prompt
        content_prompt = generator._generate_visual_prompt(
            "Key content text here",
            LayoutType.slide_content.value,
        )
        assert len(content_prompt) > 50
        
        # CTA slide prompt
        cta_prompt = generator._generate_visual_prompt_cta()
        assert "call-to-action" in cta_prompt or "CTA" in cta_prompt
    
    def test_extract_concept(self, generator):
        """Test concept extraction."""
        text = "This is a comprehensive explanation of a complex topic."
        concept = generator._extract_concept(text)
        
        assert len(concept) > 0
        assert "This" in concept
    
    def test_tone_hint_mapping(self, generator):
        """Test tone hint generation."""
        hint = generator._get_tone_hint()
        
        assert isinstance(hint, str)
        assert len(hint) > 0
    
    @pytest.mark.asyncio
    async def test_generate_slides(self, generator, sample_blog_post):
        """Test full carousel generation."""
        slides = await generator.generate_slides(
            title=sample_blog_post["title"],
            content=sample_blog_post["content"],
            summary=sample_blog_post["summary"],
        )
        
        assert 5 <= len(slides) <= 7
        
        # Check all slides have required fields
        for i, slide in enumerate(slides, start=1):
            assert slide["slide_number"] == i
            assert "text" in slide
            assert "layout_type" in slide
            assert "visual_prompt" in slide
            assert "layout_description" in slide
            assert "theme_elements" in slide
            assert slide["word_count"] >= 0
        
        # First slide should be title
        assert slides[0]["layout_type"] == LayoutType.slide_title.value
        
        # Last slide should be CTA (if enabled)
        if generator.brand_style.include_cta:
            assert slides[-1]["layout_type"] == LayoutType.slide_cta.value


class TestBrandStyle:
    """Test suite for BrandStyle configuration."""
    
    def test_default_brand_style(self):
        """Test default brand style initialization."""
        style = BrandStyle()
        
        assert style.name == "default"
        assert style.tone == BrandTone.professional_insightful
        assert style.max_words_per_slide == 45
        assert style.colors is not None
        assert style.fonts is not None
    
    def test_custom_brand_style(self):
        """Test custom brand style."""
        colors = ColorPalette(primary="#ff0000", secondary="#00ff00")
        style = BrandStyle(
            name="custom",
            tone=BrandTone.technical_deep,
            colors=colors,
            max_words_per_slide=50,
        )
        
        assert style.name == "custom"
        assert style.tone == BrandTone.technical_deep
        assert style.colors.primary == "#ff0000"
        assert style.max_words_per_slide == 50


class TestColorPalette:
    """Test suite for ColorPalette."""
    
    def test_default_palette(self):
        """Test default color palette."""
        palette = ColorPalette()
        
        assert palette.primary == "#1e3a8a"
        assert palette.secondary == "#0891b2"
        assert palette.accent == "#f59e0b"
    
    def test_custom_palette(self):
        """Test custom color palette."""
        palette = ColorPalette(
            primary="#123456",
            secondary="#654321",
        )
        
        assert palette.primary == "#123456"
        assert palette.secondary == "#654321"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
