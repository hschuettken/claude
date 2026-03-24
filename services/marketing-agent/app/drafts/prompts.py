"""LLM prompts for draft generation."""

BLOG_SYSTEM_PROMPT = """You are writing a technical blog post for Henning Schüttken, published on Layer 8 (layer8.schuettken.net).

## Voice & Style
- Direct, opinionated, and pragmatic
- Technical depth over fluff
- Focus on real-world implementation challenges
- SAP Datasphere and enterprise software specialist
- Trading systems and EV/PV orchestration expertise
- Avoid generic "AI is transforming everything" statements
- Write in first-person when sharing insights or experience
- Lead with a concrete problem, not background history

## Guidelines
- Never invent SAP features or roadmap dates
- Do not use confidential client examples (e.g., Lindt, Horváth)
- Word count: 1000-1800 words max
- Use markdown H2 headers for sections (no H1 in body)
- Each section: 200-400 words
- Include at least one implementation-near technical detail per section
- Label claims: [OFFICIAL], [COMMUNITY-REPORTED], or [SPECULATION]
- End with concrete takeaway reader can apply

## Structure
- Title: compelling, technical-forward
- Subtitle: 1 sentence, "why this matters"
- Hook: 2-3 sentences max, problem statement or provocative insight
- [2-4 H2 sections, 200-400 words each]
- Key Takeaways: 3-5 bullet points
- CTA: soft, e.g. "If you're working on X, I'd like to hear..."

## Never do
- Use markdown H1 headers (#) in body content
- Make unverified claims about performance
- Reference client work or internal projects
- Use buzzwords without substance
- Create listicles or numbered top-10 lists
- Use ALL CAPS for emphasis (use **bold** instead)

## Always do
- Lead with a concrete problem or insight, not background
- Include at least one technical implementation detail per section
- Label any roadmap claims with confidence level
- Reference official SAP documentation for claims
- End with actionable takeaway
- Write in Henning's direct, slightly opinionated voice
"""

BLOG_OUTLINE_PROMPT = """Given the following topic and signals, create a blog post outline.

Topic: {title}
Summary: {summary}

Source signals:
{signals}

Create a markdown outline with:
1. **Title** (H1 style, compelling and technical)
2. **Subtitle** (1 line, why this matters)
3. **Hook** (2-3 sentences, problem statement)
4. **Section list** with H2 headers and brief descriptions (3-5 sections)
5. **Key Takeaways** section outline
6. **CTA** section outline

Format as valid JSON with keys: title, subtitle, hook, sections (array with h2 and description), takeaways (array), cta.

Only return valid JSON, no markdown.
"""

BLOG_CONTENT_PROMPT = """Write a technical blog post based on this outline.

{outline}

Topic: {title}
Signals/sources:
{signals}

Requirements:
- 1000-1800 words total
- Use the outline structure
- Include technical details (code snippets, API examples, config)
- Label unverified claims with [SPECULATION] or [COMMUNITY-REPORTED]
- Reference sources where available
- Write in markdown format
- End with Key Takeaways (bullets) and soft CTA

Output ONLY the blog content in markdown. No frontmatter, no JSON.
"""

BLOG_CONFIDENCE_PROMPT = """Review this blog content and label confidence levels for each claim.

Content:
{content}

For each paragraph or section, assign a confidence label:
- official: verified via official documentation (SAP, docs, etc.)
- confirmed: verified via community/implementation
- reasonable: logical but not explicitly confirmed
- speculation: educated guess, needs verification
- warning: potentially inaccurate, needs review

Return JSON dict mapping section_number to confidence level. Example:
{
  "1": "official",
  "2": "confirmed",
  "3": "speculation",
  "4": "reasonable"
}

Only return valid JSON.
"""

LINKEDIN_TEASER_PROMPT = """Convert this blog post into a LinkedIn teaser post.

Blog title: {title}
Blog content (first 500 words):
{content_preview}

Requirements:
- 150-300 words
- Strong opening hook (first line is critical on LinkedIn)
- 3-5 insight paragraphs (short, scannable)
- Link to full article at end: [Read full article →](URL)
- 2-3 relevant hashtags (no more)
- Conversational, engaging tone
- Format as markdown

Output ONLY the LinkedIn post content.
"""

LINKEDIN_NATIVE_PROMPT = """Create a standalone LinkedIn native post (no external links).

Blog title: {title}
Key concepts:
{key_concepts}

Requirements:
- 200-400 words
- Storytelling voice, more personal than blog
- NO external links
- One concrete takeaway
- Question or CTA at end
- 2-3 hashtags
- Format as markdown

Output ONLY the LinkedIn post content.
"""

SEO_META_PROMPT = """Generate SEO metadata for this blog post.

Title: {title}
Content summary: {summary}

Return JSON with keys:
- meta_title (60 chars max)
- meta_description (160 chars max)
- keywords (array of 5-8 keywords)
- slug (url-friendly slug)

Only return valid JSON.
"""

VISUAL_PROMPT_PROMPT = """Create an image generation prompt for the hero image of this blog post.

Title: {title}
Summary: {summary}
Key concepts: {concepts}

The prompt should:
- Be descriptive and visual
- Evoke the technical theme
- Avoid people/faces
- Be suitable for mid-journey or DALL-E
- 1-2 sentences

Return JSON with key "visual_prompt" containing the prompt string. Example:
{{"visual_prompt": "A detailed technical diagram of..."}}

Only return valid JSON.
"""

KG_CONTEXT_BLOCK = """## Knowledge Graph Context

This post builds on existing content and active work in the Layer 8 ecosystem:

{content}

Use this context to:
- Avoid redundant content (link to existing posts instead of repeating)
- Build on previous insights and implementation patterns
- Align with active projects and initiatives
- Provide fresh perspective on related topics
"""
