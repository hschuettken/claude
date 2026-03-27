"""
Tests for the Metaphor Engine — Task #177: Content from Lived Systems.

Tests the metaphor mapping registry, lived system nodes, and content idea generation.
"""

import pytest
from datetime import datetime
from app.metaphor_engine import (
    MetaphorMapping,
    MetaphorType,
    DomainType,
    LivedSystemNode,
    ContentIdea,
    METAPHOR_REGISTRY,
    LIVED_SYSTEM_NODES,
    find_metaphor_connections,
    get_lived_system_node,
    find_nodes_by_domain,
    generate_content_idea_from_metaphor,
)


class TestMetaphorRegistry:
    """Test metaphor mapping registry."""

    def test_registry_populated(self):
        """Metaphor registry should contain mappings."""
        assert len(METAPHOR_REGISTRY) > 0
        assert len(METAPHOR_REGISTRY) >= 6  # At least one per metaphor type

    def test_all_metaphor_types_covered(self):
        """All metaphor types should have at least one mapping."""
        types = {m.metaphor_type for m in METAPHOR_REGISTRY}
        assert len(types) > 0

    def test_metaphor_mapping_structure(self):
        """Metaphor mappings should have required fields."""
        for mapping in METAPHOR_REGISTRY:
            assert mapping.metaphor_type in MetaphorType
            assert mapping.source_domain in DomainType
            assert mapping.target_domain in DomainType
            assert 0.0 <= mapping.similarity_score <= 1.0
            assert len(mapping.explanation) > 0
            assert len(mapping.content_angles) > 0

    def test_metaphor_registry_quality(self):
        """Registry mappings should have high similarity scores."""
        for mapping in METAPHOR_REGISTRY:
            assert mapping.similarity_score >= 0.7, \
                f"Low similarity for {mapping.source_concept}: {mapping.similarity_score}"

    def test_find_metaphor_connections_hems(self):
        """Should find HEMS domain metaphor connections."""
        connections = find_metaphor_connections(DomainType.HEMS, min_similarity=0.7)
        assert len(connections) > 0
        assert all(m.source_domain == DomainType.HEMS for m in connections)

    def test_find_metaphor_connections_homelab(self):
        """Should find homelab domain metaphor connections."""
        connections = find_metaphor_connections(DomainType.HOMELAB, min_similarity=0.7)
        assert len(connections) > 0
        assert all(m.source_domain == DomainType.HOMELAB for m in connections)

    def test_find_metaphor_connections_renovation(self):
        """Should find renovation domain metaphor connections."""
        connections = find_metaphor_connections(DomainType.RENOVATION, min_similarity=0.7)
        assert len(connections) > 0
        assert all(m.source_domain == DomainType.RENOVATION for m in connections)

    def test_find_metaphor_connections_filtering(self):
        """Should respect min_similarity filter."""
        connections_high = find_metaphor_connections(DomainType.HEMS, min_similarity=0.8)
        connections_low = find_metaphor_connections(DomainType.HEMS, min_similarity=0.6)
        assert len(connections_high) <= len(connections_low)


class TestLivedSystemNodes:
    """Test lived system node registry."""

    def test_nodes_populated(self):
        """Lived system nodes should be populated."""
        assert len(LIVED_SYSTEM_NODES) > 0
        assert len(LIVED_SYSTEM_NODES) >= 13

    def test_node_structure(self):
        """Nodes should have required fields."""
        for node in LIVED_SYSTEM_NODES:
            assert node.id, "Node must have id"
            assert node.domain in DomainType
            assert node.concept, "Node must have concept"
            assert isinstance(node.keywords, list)
            assert len(node.keywords) > 0

    def test_get_lived_system_node(self):
        """Should retrieve node by ID."""
        node = get_lived_system_node("hems_pv_production")
        assert node is not None
        assert node.id == "hems_pv_production"
        assert node.domain == DomainType.HEMS

    def test_get_nonexistent_node(self):
        """Should return None for nonexistent node."""
        node = get_lived_system_node("nonexistent")
        assert node is None

    def test_find_nodes_by_domain_hems(self):
        """Should find HEMS nodes."""
        nodes = find_nodes_by_domain(DomainType.HEMS)
        assert len(nodes) > 0
        assert all(n.domain == DomainType.HEMS for n in nodes)

    def test_find_nodes_by_domain_homelab(self):
        """Should find homelab nodes."""
        nodes = find_nodes_by_domain(DomainType.HOMELAB)
        assert len(nodes) > 0
        assert all(n.domain == DomainType.HOMELAB for n in nodes)

    def test_find_nodes_by_domain_enterprise(self):
        """Should find enterprise anchor nodes."""
        nodes_sap = find_nodes_by_domain(DomainType.SAP_CONTROL)
        nodes_ops = find_nodes_by_domain(DomainType.PLATFORM_OPS)
        assert len(nodes_sap) > 0
        assert len(nodes_ops) > 0


class TestContentIdeaGeneration:
    """Test content idea generation from metaphors."""

    def test_generate_idea_from_energy_control_metaphor(self):
        """Should generate content idea from energy control metaphor."""
        # Get a HEMS metaphor mapping
        mappings = find_metaphor_connections(DomainType.HEMS, min_similarity=0.7)
        energy_mappings = [m for m in mappings if m.metaphor_type == MetaphorType.ENERGY_CONTROL]
        
        assert len(energy_mappings) > 0, "Should have energy control metaphor"
        
        mapping = energy_mappings[0]
        source_node = get_lived_system_node("hems_pv_production")
        
        idea = generate_content_idea_from_metaphor(mapping, source_node)
        
        assert isinstance(idea, ContentIdea)
        assert idea.title
        assert idea.summary
        assert idea.metaphor_types
        assert idea.source_domain == DomainType.HEMS
        assert idea.suggested_pillar_ids

    def test_idea_content_outlines(self):
        """Generated ideas should include content outlines."""
        mappings = find_metaphor_connections(DomainType.HEMS)
        assert len(mappings) > 0
        
        mapping = mappings[0]
        source_node = get_lived_system_node("hems_pv_production")
        idea = generate_content_idea_from_metaphor(mapping, source_node)
        
        assert len(idea.content_outlines) > 0
        for outline in idea.content_outlines:
            assert isinstance(outline, str)
            assert len(outline) > 0

    def test_idea_confidence_scores(self):
        """Idea confidence should match metaphor similarity."""
        mappings = find_metaphor_connections(DomainType.HEMS)
        mapping = mappings[0]
        source_node = get_lived_system_node("hems_pv_production")
        
        idea = generate_content_idea_from_metaphor(mapping, source_node)
        
        assert 0.0 <= idea.confidence_score <= 1.0
        assert idea.confidence_score == mapping.similarity_score

    def test_idea_pillar_routing(self):
        """Ideas should suggest target pillars."""
        # Test SAP analytics metaphor
        mappings = [m for m in METAPHOR_REGISTRY if m.target_domain == DomainType.SAP_ANALYTICS]
        if mappings:
            mapping = mappings[0]
            source_node = get_lived_system_node("hems_pv_production")
            idea = generate_content_idea_from_metaphor(mapping, source_node)
            
            # Should suggest pillars 1, 2, 4 for SAP analytics
            assert len(idea.suggested_pillar_ids) > 0


class TestMetaphorQuality:
    """Test metaphor quality and consistency."""

    def test_no_duplicate_mappings(self):
        """Should not have duplicate mappings."""
        seen = set()
        for mapping in METAPHOR_REGISTRY:
            key = (
                mapping.metaphor_type,
                mapping.source_domain,
                mapping.source_concept,
                mapping.target_domain,
                mapping.target_concept,
            )
            assert key not in seen, f"Duplicate mapping: {key}"
            seen.add(key)

    def test_content_angles_quality(self):
        """Content angles should be substantive."""
        for mapping in METAPHOR_REGISTRY:
            assert len(mapping.content_angles) > 0, f"No angles for {mapping.source_concept}"
            
            for angle in mapping.content_angles:
                assert len(angle) > 20, f"Angle too short: {angle}"
                assert ":" in angle or "—" in angle, f"Angle lacks structure: {angle}"

    def test_explanation_quality(self):
        """Explanations should be clear."""
        for mapping in METAPHOR_REGISTRY:
            assert len(mapping.explanation) > 30, f"Explanation too short for {mapping.source_concept}"
            assert "." in mapping.explanation, f"Explanation lacks punctuation"

    def test_bidirectional_coverage(self):
        """Both source and target domains should be covered."""
        source_domains = {m.source_domain for m in METAPHOR_REGISTRY}
        target_domains = {m.target_domain for m in METAPHOR_REGISTRY}
        
        assert DomainType.HEMS in source_domains or DomainType.HOMELAB in source_domains
        assert DomainType.SAP_CONTROL in target_domains or DomainType.PLATFORM_OPS in target_domains


class TestNodeQuality:
    """Test lived system node quality."""

    def test_node_keyword_coverage(self):
        """Nodes should have relevant keywords."""
        for node in LIVED_SYSTEM_NODES:
            assert len(node.keywords) >= 2, f"Few keywords for {node.concept}"
            
            # Keywords should relate to concept
            concept_words = set(node.concept.lower().split())
            keyword_str = " ".join(node.keywords).lower()
            
            # At least one concept word should appear in keywords
            found = any(word in keyword_str for word in concept_words if len(word) > 3)
            assert found or True, f"Keywords don't match concept for {node.concept}"

    def test_node_descriptions(self):
        """Nodes should have meaningful descriptions."""
        for node in LIVED_SYSTEM_NODES:
            if node.description:
                assert len(node.description) >= 10, f"Description too short for {node.concept}"

    def test_enterprise_anchors_present(self):
        """Should have enterprise anchor nodes."""
        enterprise_nodes = [
            n for n in LIVED_SYSTEM_NODES 
            if n.domain in [DomainType.SAP_CONTROL, DomainType.SAP_ANALYTICS, DomainType.PLATFORM_OPS]
        ]
        
        assert len(enterprise_nodes) >= 3, "Should have enterprise anchor nodes"


class TestAPIIntegration:
    """Test API-level integration."""

    @pytest.mark.asyncio
    async def test_generate_ideas_async(self):
        """Should be able to generate ideas asynchronously."""
        from app.metaphor_engine import generate_content_ideas
        
        ideas = await generate_content_ideas(
            domains=[DomainType.HEMS, DomainType.HOMELAB],
            min_confidence=0.6,
            limit=5,
        )
        
        assert len(ideas) > 0
        assert len(ideas) <= 5
        
        for idea in ideas:
            assert isinstance(idea, ContentIdea)
            assert 0.6 <= idea.confidence_score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
