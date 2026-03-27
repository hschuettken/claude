"""
Metaphor Engine — Content from Lived Systems.

Task #177: Auto-detect metaphors connecting Henning's lived technical systems
(HEMS, homelab, renovation) with professional SAP/enterprise domain knowledge.

Metaphor Mappings:
- HEMS energy management ↔ enterprise resource control
- homelab resilience ↔ platform ops
- renovation sequencing ↔ digital transformation

This module:
1. Maintains a metaphor mapping registry
2. Detects KG nodes from infra/home domains
3. Cross-references with SAP/enterprise nodes
4. Generates content ideas based on metaphorical connections
5. Exposes endpoints for suggestion API and Neo4j enrichment
"""

import logging
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metaphor", tags=["metaphor-engine"])


class DomainType(str, Enum):
    """Domain classification for metaphor mapping."""
    HEMS = "hems"               # Home energy management
    HOMELAB = "homelab"         # Home infrastructure/lab
    RENOVATION = "renovation"   # Renovation/construction
    SAP_CONTROL = "sap_control" # Enterprise resource control (SAP)
    SAP_ANALYTICS = "sap_analytics"  # Analytics/insights (SAP Datasphere)
    PLATFORM_OPS = "platform_ops"    # Platform operations (enterprise)


class MetaphorType(str, Enum):
    """Type of metaphorical connection."""
    ENERGY_CONTROL = "energy_control"      # HEMS ↔ enterprise control
    RESILIENCE_OPS = "resilience_ops"      # homelab ↔ platform ops
    SEQUENCING_TRANSFORM = "sequencing_transform"  # renovation ↔ digital transformation
    MONITORING_VISIBILITY = "monitoring_visibility"  # system monitoring ↔ business visibility
    FEEDBACK_LOOP = "feedback_loop"        # feedback mechanisms ↔ business loops
    SCALING = "scaling"                    # scaling/growth patterns


@dataclass
class MetaphorMapping:
    """Mapping between two concepts in different domains."""
    metaphor_type: MetaphorType
    source_domain: DomainType
    source_concept: str
    target_domain: DomainType
    target_concept: str
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    explanation: str = ""
    content_angles: List[str] = field(default_factory=list)


class LivedSystemNode(BaseModel):
    """A knowledge graph node from a lived system domain."""
    id: str
    domain: DomainType
    concept: str
    description: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ContentIdea(BaseModel):
    """Generated content idea from metaphorical connection."""
    title: str
    summary: str
    metaphor_types: List[MetaphorType]
    source_domain: DomainType
    source_concepts: List[str]
    enterprise_angle: str
    suggested_pillar_ids: List[int] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    content_outlines: List[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now())


class MetaphorEngineRequest(BaseModel):
    """Request to generate content ideas from lived systems."""
    domains: List[DomainType] = Field(
        default=[DomainType.HEMS, DomainType.HOMELAB],
        description="Lived system domains to analyze"
    )
    min_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence score for ideas"
    )
    limit: int = Field(default=5, ge=1, le=20, description="Max ideas to return")


class MetaphorEngineResponse(BaseModel):
    """Response with generated content ideas."""
    status: str
    total_ideas: int
    ideas: List[ContentIdea]
    execution_time_ms: float
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# METAPHOR REGISTRY
# ============================================================================

METAPHOR_REGISTRY: List[MetaphorMapping] = [
    # ENERGY CONTROL: HEMS ↔ Enterprise Resource Control
    MetaphorMapping(
        metaphor_type=MetaphorType.ENERGY_CONTROL,
        source_domain=DomainType.HEMS,
        source_concept="Solar production optimization",
        target_domain=DomainType.SAP_CONTROL,
        target_concept="Supply chain optimization",
        similarity_score=0.85,
        explanation=(
            "Both systems optimize production and consumption patterns. "
            "PV production fluctuates like supply availability; consumption patterns like demand variability. "
            "Batteries = strategic inventory buffers."
        ),
        content_angles=[
            "Why energy grids need supply chain thinking: lessons from home PV systems",
            "Real-time optimization: patterns from home energy systems apply to enterprise procurement",
            "Buffering strategies: comparing home battery logic to strategic inventory management",
            "Predictive demand: how homes forecast usage like enterprises forecast demand",
        ]
    ),
    MetaphorMapping(
        metaphor_type=MetaphorType.ENERGY_CONTROL,
        source_domain=DomainType.HEMS,
        source_concept="Load balancing and peak management",
        target_domain=DomainType.SAP_CONTROL,
        target_concept="Resource allocation and bottleneck management",
        similarity_score=0.80,
        explanation=(
            "Both manage peak periods and distribute load. "
            "Home systems shift loads to off-peak; enterprises shift workloads to available capacity."
        ),
        content_angles=[
            "Load shifting as a business strategy: insights from home energy management",
            "Peak vs off-peak: pricing and incentives in home and enterprise systems",
            "Bottleneck detection: from home electrical panels to ERP system performance",
        ]
    ),

    # RESILIENCE OPS: homelab ↔ Platform Operations
    MetaphorMapping(
        metaphor_type=MetaphorType.RESILIENCE_OPS,
        source_domain=DomainType.HOMELAB,
        source_concept="Redundancy and failover architecture",
        target_domain=DomainType.PLATFORM_OPS,
        target_concept="High availability and disaster recovery",
        similarity_score=0.90,
        explanation=(
            "Homelab resilience patterns (backup power, network redundancy, containerization) "
            "mirror enterprise HA/DR strategies at different scale."
        ),
        content_angles=[
            "Building reliability on a budget: homelab patterns for enterprise architects",
            "Container orchestration at home and at scale: lessons from Kubernetes and K3S",
            "Self-healing systems: from Proxmox HA to enterprise recovery automation",
            "The cost of downtime: why homelab backup practices matter in enterprise",
        ]
    ),
    MetaphorMapping(
        metaphor_type=MetaphorType.RESILIENCE_OPS,
        source_domain=DomainType.HOMELAB,
        source_concept="Monitoring and observability",
        target_domain=DomainType.PLATFORM_OPS,
        target_concept="Platform observability and SLO management",
        similarity_score=0.85,
        explanation=(
            "Home monitoring (Prometheus, Home Assistant) provides same insights as enterprise observability stacks. "
            "Scale differs; principles align."
        ),
        content_angles=[
            "From home dashboards to enterprise dashboards: observability patterns",
            "Alerting effectiveness: why your home alerts beat your enterprise ones",
            "Metrics that matter: what a 50-device homelab teaches about enterprise telemetry",
        ]
    ),

    # SEQUENCING & TRANSFORMATION: Renovation ↔ Digital Transformation
    MetaphorMapping(
        metaphor_type=MetaphorType.SEQUENCING_TRANSFORM,
        source_domain=DomainType.RENOVATION,
        source_concept="Renovation sequencing and dependencies",
        target_domain=DomainType.SAP_CONTROL,
        target_concept="Digital transformation and process migration",
        similarity_score=0.78,
        explanation=(
            "Both involve sequencing interdependent changes. "
            "Renovation: fix foundation before raising walls. Transformation: migrate data before process change."
        ),
        content_angles=[
            "Renovation as metaphor: why digital transformation projects fail without sequencing",
            "Dependencies matter: lessons from building maintenance to ERP implementation",
            "Reversibility and go/no-go decisions: how renovation mirrors transformation go-live risk",
            "Stakeholder management: keeping the house livable during renovation vs running operations during transformation",
        ]
    ),

    # MONITORING & VISIBILITY
    MetaphorMapping(
        metaphor_type=MetaphorType.MONITORING_VISIBILITY,
        source_domain=DomainType.HEMS,
        source_concept="Real-time visibility into energy flows",
        target_domain=DomainType.SAP_ANALYTICS,
        target_concept="Real-time business intelligence and analytics",
        similarity_score=0.82,
        explanation=(
            "Both provide real-time insights into system state. "
            "Energy dashboard ≈ business dashboard; KPIs similar in design."
        ),
        content_angles=[
            "Building real-time dashboards: what energy analytics teaches about business BI",
            "From kilowatts to metrics: designing dashboards that matter",
            "SAP Datasphere for real-time: patterns from home energy visibility",
        ]
    ),

    # FEEDBACK LOOPS
    MetaphorMapping(
        metaphor_type=MetaphorType.FEEDBACK_LOOP,
        source_domain=DomainType.HOMELAB,
        source_concept="Automated remediation and self-healing",
        target_domain=DomainType.PLATFORM_OPS,
        target_concept="Closed-loop operations and automation",
        similarity_score=0.87,
        explanation=(
            "Both implement feedback loops that detect and fix issues automatically. "
            "Home automation rules ≈ enterprise automation workflows."
        ),
        content_angles=[
            "Closed-loop operations: from home automation to enterprise workflows",
            "When to automate, when to alert: threshold management across scales",
            "Feedback latency: response time trade-offs in home and enterprise systems",
        ]
    ),

    # SCALING
    MetaphorMapping(
        metaphor_type=MetaphorType.SCALING,
        source_domain=DomainType.HOMELAB,
        source_concept="Scaling infrastructure incrementally",
        target_domain=DomainType.PLATFORM_OPS,
        target_concept="Enterprise platform scaling and capacity planning",
        similarity_score=0.75,
        explanation=(
            "Homelab growth (1→5→50 devices) experiences similar constraints as enterprise scaling. "
            "Early decisions shape architecture."
        ),
        content_angles=[
            "Scaling from home to enterprise: architectural lessons learned",
            "Cost per unit: from home device costs to enterprise cost of ownership",
            "When to refactor: recognizing technical debt in growing systems",
        ]
    ),
]


# ============================================================================
# LIVED SYSTEM NODE REGISTRY
# ============================================================================

LIVED_SYSTEM_NODES: List[LivedSystemNode] = [
    # HEMS Domain
    LivedSystemNode(
        id="hems_pv_production",
        domain=DomainType.HEMS,
        concept="Solar PV production optimization",
        description="Home rooftop PV system with daily production variability",
        keywords=["solar", "production", "optimization", "prediction", "variability"],
        metadata={"system": "Fronius SnapINVERT", "capacity_kw": 10, "active": True}
    ),
    LivedSystemNode(
        id="hems_consumption_profile",
        domain=DomainType.HEMS,
        concept="Home consumption patterns",
        description="Predictable and variable consumption across devices",
        keywords=["consumption", "demand", "load", "prediction", "pattern"],
        metadata={"devices_tracked": 40, "granularity": "15min"}
    ),
    LivedSystemNode(
        id="hems_battery_buffer",
        domain=DomainType.HEMS,
        concept="Battery storage and strategic buffering",
        description="Tesla Powerwall providing temporal arbitrage and resilience",
        keywords=["battery", "buffer", "storage", "resilience", "arbitrage"],
        metadata={"capacity_kwh": 13.5, "soc_optimization": "dynamic"}
    ),
    LivedSystemNode(
        id="hems_grid_interaction",
        domain=DomainType.HEMS,
        concept="Grid import/export optimization",
        description="Negotiating with grid provider for grid balancing",
        keywords=["grid", "export", "import", "balancing", "pricing"],
        metadata={"grid_role": "prosumer", "flexibility_provided": True}
    ),

    # HOMELAB Domain
    LivedSystemNode(
        id="homelab_k3s_orchestration",
        domain=DomainType.HOMELAB,
        concept="Kubernetes containerized workloads",
        description="K3S cluster running ~20 services across multiple nodes",
        keywords=["kubernetes", "orchestration", "containerization", "scaling", "automation"],
        metadata={"nodes": 6, "services": 20, "redundancy": "multi-node"}
    ),
    LivedSystemNode(
        id="homelab_monitoring_observability",
        domain=DomainType.HOMELAB,
        concept="Prometheus + Grafana observability stack",
        description="Real-time monitoring of 50+ physical devices",
        keywords=["monitoring", "observability", "metrics", "alerting", "dashboard"],
        metadata={"metrics_collected": 2000, "retention_days": 365}
    ),
    LivedSystemNode(
        id="homelab_networking",
        domain=DomainType.HOMELAB,
        concept="Multi-segment network architecture",
        description="VLAN-based network segmentation with firewalling",
        keywords=["networking", "segmentation", "vlan", "security", "resilience"],
        metadata={"vlans": 8, "devices": 50, "firewall": "OPNsense"}
    ),
    LivedSystemNode(
        id="homelab_storage",
        domain=DomainType.HOMELAB,
        concept="Distributed storage and backup",
        description="ZFS-based storage with automated backups and redundancy",
        keywords=["storage", "backup", "redundancy", "disaster_recovery", "availability"],
        metadata={"storage_pool_tb": 100, "backup_copies": 3}
    ),
    LivedSystemNode(
        id="homelab_resilience",
        domain=DomainType.HOMELAB,
        concept="System resilience and self-healing",
        description="Automated recovery from component failures",
        keywords=["resilience", "failover", "self_healing", "availability", "automation"],
        metadata={"rto_minutes": 5, "rpo_hours": 1}
    ),

    # RENOVATION Domain
    LivedSystemNode(
        id="renovation_sequencing",
        domain=DomainType.RENOVATION,
        concept="Renovation project sequencing",
        description="Multi-phase home renovation with coordinated contractor scheduling",
        keywords=["sequencing", "dependencies", "project_management", "phasing", "coordination"],
        metadata={"phases": 5, "duration_months": 18, "parallel_tracks": 3}
    ),
    LivedSystemNode(
        id="renovation_dependencies",
        domain=DomainType.RENOVATION,
        concept="Structural dependencies and constraints",
        description="Critical path: foundation → structure → systems → finishes",
        keywords=["dependencies", "critical_path", "constraints", "ordering", "precedence"],
        metadata={"critical_tasks": 12, "decision_points": 8}
    ),
    LivedSystemNode(
        id="renovation_stakeholder_mgmt",
        domain=DomainType.RENOVATION,
        concept="Stakeholder coordination and communication",
        description="Managing architect, contractors, family needs during renovation",
        keywords=["stakeholders", "communication", "coordination", "expectations", "changes"],
        metadata={"stakeholder_groups": 4, "decision_freq": "weekly"}
    ),

    # SAP / Enterprise Domain (target metaphor anchors)
    LivedSystemNode(
        id="sap_supply_optimization",
        domain=DomainType.SAP_CONTROL,
        concept="Supply chain and procurement optimization",
        description="Enterprise supply chain planning and optimization",
        keywords=["supply_chain", "procurement", "optimization", "planning", "forecasting"],
        metadata={"use_case": "S2P process"}
    ),
    LivedSystemNode(
        id="sap_resource_allocation",
        domain=DomainType.SAP_CONTROL,
        concept="Enterprise resource allocation and capacity planning",
        description="Optimizing resource usage across business units",
        keywords=["resource", "allocation", "capacity", "planning", "optimization"],
        metadata={"scope": "multi_tenant"}
    ),
    LivedSystemNode(
        id="sap_process_migration",
        domain=DomainType.SAP_CONTROL,
        concept="Digital transformation and process migration",
        description="Sequenced migration of processes to new platforms",
        keywords=["transformation", "migration", "change_management", "sequencing", "rollout"],
        metadata={"complexity": "high", "duration_months": 12}
    ),
    LivedSystemNode(
        id="sap_datasphere_analytics",
        domain=DomainType.SAP_ANALYTICS,
        concept="Real-time business analytics and insights",
        description="SAP Datasphere providing real-time BI and analytics",
        keywords=["analytics", "business_intelligence", "real_time", "insights", "dashboard"],
        metadata={"data_sources": 20, "users": 500}
    ),
    LivedSystemNode(
        id="platform_ha_dr",
        domain=DomainType.PLATFORM_OPS,
        concept="High availability and disaster recovery",
        description="Enterprise platform HA/DR strategies",
        keywords=["availability", "disaster_recovery", "resilience", "failover", "automation"],
        metadata={"rto_minutes": 60, "rpo_hours": 4}
    ),
    LivedSystemNode(
        id="platform_observability",
        domain=DomainType.PLATFORM_OPS,
        concept="Platform observability and monitoring",
        description="Comprehensive platform monitoring and alerting",
        keywords=["observability", "monitoring", "alerting", "metrics", "slo"],
        metadata={"slo_availability": 0.999}
    ),
]


# ============================================================================
# METAPHOR ENGINE FUNCTIONS
# ============================================================================

def find_metaphor_connections(
    source_domain: DomainType,
    target_domains: Optional[List[DomainType]] = None,
    min_similarity: float = 0.6,
) -> List[MetaphorMapping]:
    """Find metaphor mappings for a source domain."""
    if target_domains is None:
        target_domains = [
            DomainType.SAP_CONTROL,
            DomainType.SAP_ANALYTICS,
            DomainType.PLATFORM_OPS,
        ]

    matches = [
        m for m in METAPHOR_REGISTRY
        if m.source_domain == source_domain
        and m.target_domain in target_domains
        and m.similarity_score >= min_similarity
    ]
    return sorted(matches, key=lambda m: m.similarity_score, reverse=True)


def get_lived_system_node(node_id: str) -> Optional[LivedSystemNode]:
    """Retrieve a lived system node by ID."""
    for node in LIVED_SYSTEM_NODES:
        if node.id == node_id:
            return node
    return None


def find_nodes_by_domain(domain: DomainType) -> List[LivedSystemNode]:
    """Find all nodes in a specific domain."""
    return [n for n in LIVED_SYSTEM_NODES if n.domain == domain]


def generate_content_idea_from_metaphor(
    mapping: MetaphorMapping,
    source_node: LivedSystemNode,
    target_node: Optional[LivedSystemNode] = None,
) -> ContentIdea:
    """Generate a content idea from a metaphor mapping and nodes."""
    
    # Build title from metaphor
    title = (
        f"{source_node.concept} → {target_node.concept if target_node else mapping.target_concept}: "
        f"What enterprises can learn from lived systems"
    )

    # Build summary
    summary = (
        f"Connect {mapping.source_domain.value} patterns to {mapping.target_domain.value} practices. "
        f"{mapping.explanation}"
    )

    # Determine suggested pillars based on target domain
    suggested_pillars = []
    if mapping.target_domain == DomainType.SAP_ANALYTICS:
        suggested_pillars = [1, 2, 4]  # SAP deep technical, roadmap, AI
    elif mapping.target_domain == DomainType.SAP_CONTROL:
        suggested_pillars = [1, 3]  # SAP deep technical, Architecture
    elif mapping.target_domain == DomainType.PLATFORM_OPS:
        suggested_pillars = [3, 5]  # Architecture, Builder/lab

    return ContentIdea(
        title=title,
        summary=summary,
        metaphor_types=[mapping.metaphor_type],
        source_domain=mapping.source_domain,
        source_concepts=[mapping.source_concept],
        enterprise_angle=mapping.target_concept,
        suggested_pillar_ids=suggested_pillars,
        confidence_score=mapping.similarity_score,
        content_outlines=mapping.content_angles,
    )


async def generate_content_ideas(
    domains: List[DomainType] = None,
    min_confidence: float = 0.6,
    limit: int = 5,
) -> List[ContentIdea]:
    """Generate content ideas from lived system metaphors."""
    
    if domains is None:
        domains = [DomainType.HEMS, DomainType.HOMELAB, DomainType.RENOVATION]

    ideas = []

    for domain in domains:
        # Find metaphor mappings for this domain
        mappings = find_metaphor_connections(domain, min_similarity=min_confidence)

        # For each mapping, create a content idea
        for mapping in mappings:
            # Get source node examples
            source_nodes = find_nodes_by_domain(domain)
            if source_nodes:
                source_node = source_nodes[0]
                idea = generate_content_idea_from_metaphor(
                    mapping, source_node, None
                )
                ideas.append(idea)

    # Sort by confidence and limit
    ideas.sort(key=lambda i: i.confidence_score, reverse=True)
    return ideas[:limit]


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post(
    "/generate-ideas",
    response_model=MetaphorEngineResponse,
    summary="Generate content ideas from lived system metaphors"
)
async def generate_metaphor_ideas(request: MetaphorEngineRequest) -> MetaphorEngineResponse:
    """
    Generate content ideas by detecting metaphorical connections
    between lived systems and enterprise domains.

    **Example**: HEMS energy optimization ↔ SAP supply chain optimization
    """
    import time
    start_time = time.time()

    try:
        ideas = await generate_content_ideas(
            domains=request.domains,
            min_confidence=request.min_confidence,
            limit=request.limit,
        )

        execution_time = (time.time() - start_time) * 1000

        return MetaphorEngineResponse(
            status="ok",
            total_ideas=len(ideas),
            ideas=ideas,
            execution_time_ms=execution_time,
            metadata={
                "domains_analyzed": [d.value for d in request.domains],
                "min_confidence": request.min_confidence,
                "registry_size": len(METAPHOR_REGISTRY),
            }
        )

    except Exception as e:
        logger.error(f"Error generating metaphor ideas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ideas: {str(e)}"
        )


@router.get(
    "/registry",
    response_model=Dict[str, Any],
    summary="View metaphor registry"
)
async def get_metaphor_registry(
    source_domain: Optional[str] = None,
    min_similarity: float = 0.0,
) -> Dict[str, Any]:
    """Retrieve metaphor mappings, optionally filtered by domain and similarity."""
    
    mappings = METAPHOR_REGISTRY
    if source_domain:
        try:
            domain = DomainType(source_domain)
            mappings = find_metaphor_connections(domain, min_similarity=min_similarity)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid domain: {source_domain}"
            )

    return {
        "status": "ok",
        "total": len(mappings),
        "mappings": [
            {
                "type": m.metaphor_type.value,
                "source": f"{m.source_domain.value}: {m.source_concept}",
                "target": f"{m.target_domain.value}: {m.target_concept}",
                "similarity": m.similarity_score,
                "explanation": m.explanation,
                "angles": m.content_angles,
            }
            for m in mappings
        ]
    }


@router.get(
    "/nodes",
    response_model=Dict[str, Any],
    summary="List lived system nodes"
)
async def get_lived_system_nodes(
    domain: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve lived system nodes, optionally filtered by domain."""
    
    nodes = LIVED_SYSTEM_NODES
    if domain:
        try:
            d = DomainType(domain)
            nodes = find_nodes_by_domain(d)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid domain: {domain}"
            )

    return {
        "status": "ok",
        "total": len(nodes),
        "nodes": [
            {
                "id": n.id,
                "domain": n.domain.value,
                "concept": n.concept,
                "description": n.description,
                "keywords": n.keywords,
            }
            for n in nodes
        ]
    }


@router.get(
    "/health",
    response_model=Dict[str, Any],
)
async def metaphor_engine_health() -> Dict[str, Any]:
    """Health check for metaphor engine."""
    return {
        "status": "ok",
        "service": "metaphor-engine",
        "metaphor_count": len(METAPHOR_REGISTRY),
        "node_count": len(LIVED_SYSTEM_NODES),
        "domains_supported": [d.value for d in DomainType],
    }
