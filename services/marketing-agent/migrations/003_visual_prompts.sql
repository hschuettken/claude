-- Migration 003: Visual Prompts & Brand Presets
-- Adds tables for visual prompt generation: brand_presets, visual_prompt_templates, visual_prompts
-- Date: 2026-03-27

-- 1. Brand Presets — predefined brand styles for image generation
CREATE TABLE IF NOT EXISTS marketing.brand_presets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    
    -- Visual branding
    primary_color VARCHAR(7) DEFAULT '#1e3a8a',  -- Hex color
    secondary_color VARCHAR(7) DEFAULT '#0891b2',
    accent_color VARCHAR(7) DEFAULT '#f59e0b',
    text_dark_color VARCHAR(7) DEFAULT '#1f2937',
    text_light_color VARCHAR(7) DEFAULT '#f3f4f6',
    background_color VARCHAR(7) DEFAULT '#ffffff',
    
    -- Typography
    heading_font VARCHAR(255) DEFAULT 'Montserrat',
    body_font VARCHAR(255) DEFAULT 'Open Sans',
    mono_font VARCHAR(255) DEFAULT 'JetBrains Mono',
    
    -- Tone/style descriptors
    tone VARCHAR(255) DEFAULT 'professional_insightful',  -- professional_insightful, technical_deep, approachable_friendly
    style_keywords TEXT[] DEFAULT ARRAY[]::TEXT[],  -- e.g., ["minimalist", "technical", "modern"]
    
    -- Image generation specifics
    aspect_ratio VARCHAR(20) DEFAULT '16:9',  -- Common: 16:9, 1:1, 4:3
    style_notes TEXT DEFAULT 'Enterprise technical audience, focus on business value',
    
    -- Metadata
    is_default BOOLEAN DEFAULT false,
    created_by VARCHAR(255),
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_brand_presets_name ON marketing.brand_presets(name);
CREATE INDEX idx_brand_presets_is_default ON marketing.brand_presets(is_default);
CREATE INDEX idx_brand_presets_created_at ON marketing.brand_presets(created_at DESC);

-- 2. Visual Prompt Templates — reusable prompt patterns
CREATE TABLE IF NOT EXISTS marketing.visual_prompt_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(100) NOT NULL,  -- architecture_diagram, signal_map, isometric_scene, hero_image, carousel_slide, infographic
    description TEXT,
    
    -- Prompt template with placeholders
    template TEXT NOT NULL,  -- Template with {variable} placeholders
    
    -- Metadata
    parameters TEXT[] DEFAULT ARRAY[]::TEXT[],  -- List of available {variable} names
    example_output TEXT,  -- Example filled-in prompt
    
    -- Usage tracking
    usage_count INTEGER DEFAULT 0,
    popularity_score FLOAT DEFAULT 0.0,  -- 0-1 based on usage/quality
    
    -- Status
    status VARCHAR(50) DEFAULT 'active',  -- active, archived, experimental
    
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_visual_templates_category ON marketing.visual_prompt_templates(category);
CREATE INDEX idx_visual_templates_status ON marketing.visual_prompt_templates(status);
CREATE INDEX idx_visual_templates_created_at ON marketing.visual_prompt_templates(created_at DESC);

-- 3. Visual Prompts — generated prompts for image generation
CREATE TABLE IF NOT EXISTS marketing.visual_prompts (
    id SERIAL PRIMARY KEY,
    
    -- Relationships
    draft_id INTEGER REFERENCES marketing.drafts(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES marketing.visual_prompt_templates(id) ON DELETE SET NULL,
    brand_preset_id INTEGER REFERENCES marketing.brand_presets(id) ON DELETE SET NULL,
    
    -- Generated content
    prompt_text TEXT NOT NULL,  -- The actual prompt for image generator
    prompt_variants TEXT[] DEFAULT ARRAY[]::TEXT[],  -- Alternative variations
    
    -- Image generation metadata
    use_case VARCHAR(100) NOT NULL,  -- hero_image, carousel_slide_1, diagram, thumbnail
    image_style VARCHAR(255),  -- e.g., "minimalist", "detailed technical diagram"
    aspect_ratio VARCHAR(20),  -- e.g., "16:9", "1:1"
    
    -- Generation tracking
    generator_name VARCHAR(100),  -- grok, ollama, dall-e, midjourney
    generation_attempted BOOLEAN DEFAULT false,
    generation_timestamp TIMESTAMPTZ,
    generated_image_url VARCHAR(1024),  -- URL to generated image if available
    
    -- Quality assessment
    quality_score INTEGER DEFAULT 0,  -- 1-5 rating or internal score
    feedback TEXT,  -- User feedback on generated image
    approved BOOLEAN DEFAULT false,
    
    -- Metadata
    metadata JSONB DEFAULT '{}',  -- Any additional params passed to generator
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_visual_prompts_draft_id ON marketing.visual_prompts(draft_id);
CREATE INDEX idx_visual_prompts_template_id ON marketing.visual_prompts(template_id);
CREATE INDEX idx_visual_prompts_brand_preset_id ON marketing.visual_prompts(brand_preset_id);
CREATE INDEX idx_visual_prompts_use_case ON marketing.visual_prompts(use_case);
CREATE INDEX idx_visual_prompts_generator ON marketing.visual_prompts(generator_name);
CREATE INDEX idx_visual_prompts_approved ON marketing.visual_prompts(approved);
CREATE INDEX idx_visual_prompts_created_at ON marketing.visual_prompts(created_at DESC);

-- ============================================================================
-- Seed Default Brand Presets
-- ============================================================================

INSERT INTO marketing.brand_presets (
    name, description, tone, style_keywords, is_default, created_by
) VALUES
    (
        'Layer 8 - Professional',
        'Enterprise technical blog style - minimalist, modern, technical focus',
        'professional_insightful',
        ARRAY['minimalist', 'technical', 'modern', 'enterprise'],
        true,
        'system'
    ),
    (
        'Layer 8 - Technical Deep',
        'Deep technical focus - detailed diagrams, code-forward',
        'technical_deep',
        ARRAY['detailed', 'code-centric', 'developer-focused', 'dark'],
        false,
        'system'
    ),
    (
        'Layer 8 - Approachable',
        'Friendly, accessible technical content',
        'approachable_friendly',
        ARRAY['friendly', 'accessible', 'bright', 'illustrative'],
        false,
        'system'
    )
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- Seed Visual Prompt Templates
-- ============================================================================

INSERT INTO marketing.visual_prompt_templates (
    name, category, description, template, parameters, status
) VALUES
    (
        'Architecture Diagram - Clean',
        'architecture_diagram',
        'Clean technical architecture diagram with components and flows',
        'A clean technical architecture diagram showing {components} connected by {connections}, using {style_keywords} design style. Colors: {primary_color}, {secondary_color}. No text labels, use icons only. {aspect_ratio} format.',
        ARRAY['components', 'connections', 'style_keywords', 'primary_color', 'secondary_color', 'aspect_ratio'],
        'active'
    ),
    (
        'Signal Map - Data Flow',
        'signal_map',
        'Abstract signal/data flow visualization',
        'An abstract visualization of {data_type} signals flowing through a {system_type} system. Show {flow_pattern} patterns using {color_palette}. {style_keyword} aesthetic. {aspect_ratio}.',
        ARRAY['data_type', 'system_type', 'flow_pattern', 'color_palette', 'style_keyword', 'aspect_ratio'],
        'active'
    ),
    (
        'Isometric Scene - 3D',
        'isometric_scene',
        '3D isometric illustration of technical concept',
        'A clean isometric 3D illustration of {concept}. Show {elements} in {environment}. Use {color_scheme} color scheme. {style_descriptor} style. No people. {aspect_ratio}.',
        ARRAY['concept', 'elements', 'environment', 'color_scheme', 'style_descriptor', 'aspect_ratio'],
        'active'
    ),
    (
        'Hero Image - Blog Post',
        'hero_image',
        'Hero image for blog post header',
        'A compelling hero image for a technical blog post about {topic}. Key theme: {theme}. Style: {style}. Colors: primarily {primary_color} and {secondary_color}. Professional, modern, {aspect_ratio}.',
        ARRAY['topic', 'theme', 'style', 'primary_color', 'secondary_color', 'aspect_ratio'],
        'active'
    ),
    (
        'Carousel Slide - Minimal',
        'carousel_slide',
        'Minimal carousel slide with typography focus',
        'A minimal carousel slide with {color} background. Design: {design_type}. Show {content_type} with {layout_style} layout. {aspect_ratio}. No text overlay, pure design.',
        ARRAY['color', 'design_type', 'content_type', 'layout_style', 'aspect_ratio'],
        'active'
    ),
    (
        'Infographic - Data Viz',
        'infographic',
        'Data visualization infographic',
        'An infographic visualizing {data_topic}. Show {data_points} key insights. Style: {visual_style}. Colors: {color_scheme}. Layout: {layout_style}. {aspect_ratio}.',
        ARRAY['data_topic', 'data_points', 'visual_style', 'color_scheme', 'layout_style', 'aspect_ratio'],
        'active'
    )
ON CONFLICT (name) DO NOTHING;

-- Grant permissions
GRANT ALL PRIVILEGES ON marketing.brand_presets TO homelab;
GRANT ALL PRIVILEGES ON marketing.visual_prompt_templates TO homelab;
GRANT ALL PRIVILEGES ON marketing.visual_prompts TO homelab;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA marketing TO homelab;

COMMIT;
