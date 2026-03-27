# Metaphor Engine — Content from Lived Systems

**Task #177** — Auto-detect metaphors connecting Henning's lived technical systems with professional SAP/enterprise domain knowledge.

## Overview

The Metaphor Engine detects and surfaces content ideas by identifying metaphorical connections between:

1. **Lived System Domains**:
   - **HEMS** (Home Energy Management): Solar PV, battery storage, grid optimization
   - **Homelab**: Kubernetes, monitoring, resilience, backup
   - **Renovation**: Sequencing, dependencies, phasing

2. **Professional Domains**:
   - **SAP Control**: Resource allocation, supply chain, process migration
   - **SAP Analytics**: Business intelligence, real-time dashboards
   - **Platform Ops**: HA/DR, observability, automation

## Architecture

```
Metaphor Engine (app/metaphor_engine.py)
├── MetaphorMapping Registry (6 metaphor types)
├── LivedSystemNode Registry (13 nodes across 3 domains)
├── Content Idea Generator
└── FastAPI Endpoints (/api/v1/metaphor/*)
    ├── POST /generate-ideas → List[ContentIdea]
    ├── GET /registry → metaphor mappings
    ├── GET /nodes → lived system nodes
    └── GET /health → service health
```

## Metaphor Types (6)

### 1. **ENERGY_CONTROL**: HEMS ↔ Enterprise Resource Control

**Pattern**: Both optimize production and consumption patterns.

- HEMS: Solar production fluctuates; consumption patterns vary; batteries buffer mismatch
- Enterprise: Supply availability fluctuates; demand varies; inventory buffers mismatch

**Example Content**:
- "Why energy grids need supply chain thinking: lessons from home PV systems"
- "Real-time optimization: patterns from home energy systems apply to enterprise procurement"

### 2. **RESILIENCE_OPS**: Homelab ↔ Platform Operations

**Pattern**: Both implement redundancy, failover, and self-healing at different scales.

- Homelab: K3S orchestration, multi-node failover, automated recovery
- Enterprise: Platform HA/DR, orchestrated failover, automated remediation

**Example Content**:
- "Building reliability on a budget: homelab patterns for enterprise architects"
- "Container orchestration at home and at scale: lessons from Kubernetes and K3S"

### 3. **SEQUENCING_TRANSFORM**: Renovation ↔ Digital Transformation

**Pattern**: Both involve sequencing interdependent changes to complex systems.

- Renovation: Fix foundation → walls → systems → finishes (parallel tracks, dependencies)
- Transformation: Migrate data → update processes → train staff → go-live (critical path)

**Example Content**:
- "Renovation as metaphor: why digital transformation projects fail without sequencing"
- "Dependencies matter: lessons from building maintenance to ERP implementation"

### 4. **MONITORING_VISIBILITY**: HEMS ↔ SAP Analytics

**Pattern**: Both provide real-time insights into system state and KPIs.

- HEMS: Real-time energy dashboard, production/consumption KPIs
- Enterprise: Real-time business dashboard, revenue/cost KPIs

**Example Content**:
- "Building real-time dashboards: what energy analytics teaches about business BI"
- "SAP Datasphere for real-time: patterns from home energy visibility"

### 5. **FEEDBACK_LOOP**: Homelab ↔ Platform Operations

**Pattern**: Both implement closed-loop automation with feedback and remediation.

- Homelab: Home automation rules trigger actions (lights on at sunset → adjust if occupied)
- Enterprise: Automated workflows trigger remediation (CPU high → scale out → monitor)

**Example Content**:
- "Closed-loop operations: from home automation to enterprise workflows"
- "When to automate, when to alert: threshold management across scales"

### 6. **SCALING**: Homelab ↔ Platform Scaling

**Pattern**: Both experience similar architectural constraints as they grow.

- Homelab: 1→5→50 devices; early decisions shape architecture
- Enterprise: Single-app→multi-tenant→global; early decisions shape platform

**Example Content**:
- "Scaling from home to enterprise: architectural lessons learned"
- "Cost per unit: from home device costs to enterprise cost of ownership"

---

## Lived System Nodes (13)

### HEMS Domain (4 nodes)

| Node ID | Concept | Description |
|---------|---------|-------------|
| `hems_pv_production` | Solar PV optimization | Fronius SnapINVERT 10kW system; production variability |
| `hems_consumption_profile` | Home consumption | 40+ devices tracked at 15-min granularity |
| `hems_battery_buffer` | Battery storage | Tesla Powerwall 13.5kWh; temporal arbitrage |
| `hems_grid_interaction` | Grid optimization | Prosumer role; grid balancing flexibility |

### Homelab Domain (5 nodes)

| Node ID | Concept | Description |
|---------|---------|-------------|
| `homelab_k3s_orchestration` | Container orchestration | ~20 services across 6 nodes |
| `homelab_monitoring_observability` | Prometheus + Grafana | 2000+ metrics; 365-day retention |
| `homelab_networking` | Network segmentation | 8 VLANs, 50 devices, OPNsense firewall |
| `homelab_storage` | Distributed storage | ZFS pools, 100TB, 3 backup copies |
| `homelab_resilience` | Self-healing | 5-min RTO, 1-hour RPO |

### Renovation Domain (3 nodes)

| Node ID | Concept | Description |
|---------|---------|-------------|
| `renovation_sequencing` | Phase ordering | 5 phases, 18 months, 3 parallel tracks |
| `renovation_dependencies` | Critical path | 12 critical tasks; 8 decision points |
| `renovation_stakeholder_mgmt` | Coordination | Architect, contractors, family; weekly decisions |

### Enterprise Domain (6 nodes — metaphor anchors)

| Node ID | Concept | Description |
|---------|---------|-------------|
| `sap_supply_optimization` | Supply chain planning | S2P process optimization |
| `sap_resource_allocation` | Resource management | Capacity planning; multi-tenant |
| `sap_process_migration` | Digital transformation | 12-month migration; high complexity |
| `sap_datasphere_analytics` | Real-time analytics | 20 data sources; 500 users |
| `platform_ha_dr` | HA/DR strategies | 60-min RTO, 4-hour RPO |
| `platform_observability` | Platform monitoring | 99.9% SLO; comprehensive alerting |

---

## API Endpoints

### 1. Generate Content Ideas

```http
POST /api/v1/metaphor/generate-ideas
Content-Type: application/json

{
  "domains": ["hems", "homelab"],
  "min_confidence": 0.6,
  "limit": 5
}
```

**Response**:
```json
{
  "status": "ok",
  "total_ideas": 3,
  "execution_time_ms": 45,
  "ideas": [
    {
      "title": "Solar production optimization → Supply chain optimization: ...",
      "summary": "Connect HEMS patterns to SAP practices...",
      "metaphor_types": ["energy_control"],
      "source_domain": "hems",
      "source_concepts": ["Solar PV production optimization"],
      "enterprise_angle": "Supply chain optimization",
      "suggested_pillar_ids": [1, 3],
      "confidence_score": 0.85,
      "content_outlines": [
        "Why energy grids need supply chain thinking...",
        "Real-time optimization: patterns from home energy systems...",
        ...
      ],
      "generated_at": "2026-03-26T10:30:00Z"
    },
    ...
  ],
  "metadata": {
    "domains_analyzed": ["hems", "homelab"],
    "min_confidence": 0.6,
    "registry_size": 9
  }
}
```

### 2. View Metaphor Registry

```http
GET /api/v1/metaphor/registry?source_domain=hems&min_similarity=0.6
```

**Response**:
```json
{
  "status": "ok",
  "total": 3,
  "mappings": [
    {
      "type": "energy_control",
      "source": "hems: Solar production optimization",
      "target": "sap_control: Supply chain optimization",
      "similarity": 0.85,
      "explanation": "Both optimize production/consumption patterns...",
      "angles": [
        "Why energy grids need supply chain thinking...",
        ...
      ]
    },
    ...
  ]
}
```

### 3. List Lived System Nodes

```http
GET /api/v1/metaphor/nodes?domain=hems
```

**Response**:
```json
{
  "status": "ok",
  "total": 4,
  "nodes": [
    {
      "id": "hems_pv_production",
      "domain": "hems",
      "concept": "Solar PV production optimization",
      "description": "Fronius SnapINVERT 10kW system...",
      "keywords": ["solar", "production", "optimization", ...]
    },
    ...
  ]
}
```

### 4. Health Check

```http
GET /api/v1/metaphor/health
```

**Response**:
```json
{
  "status": "ok",
  "service": "metaphor-engine",
  "metaphor_count": 9,
  "node_count": 13,
  "domains_supported": [
    "hems", "homelab", "renovation",
    "sap_control", "sap_analytics", "platform_ops"
  ]
}
```

---

## Integration Points

### 1. Marketing Agent Content Suggestion Pipeline

The metaphor engine can be called during:
- **Signal ingestion**: Auto-suggest content angles based on signal domain
- **Draft creation**: Suggest metaphor-based angles during outline generation
- **Topic clustering**: Group signals by metaphor type

### 2. Knowledge Graph Enrichment

Future: Metaphor nodes can be stored in Neo4j:

```cypher
MATCH (cp:ContentPillar)
CREATE (m:MetaphorMapping {
  id: "...",
  type: "energy_control",
  source_domain: "hems",
  target_domain: "sap_control",
  similarity: 0.85
})
CREATE (cp)-[:INFORMED_BY]->(m)
```

### 3. Content Routing

Metaphor-generated ideas can be routed to specific pillars:

```python
idea = generate_content_idea(mapping, source_node)
routed = route_to_pillars(idea)  # Uses suggested_pillar_ids
```

### 4. NATS Event Publishing

Metaphor ideas can trigger content drafting workflows:

```
metaphor.idea.generated → signal.auto_draft → draft.pending_review
```

---

## Configuration & Extensibility

### Adding New Metaphor Mappings

Edit `METAPHOR_REGISTRY` in `app/metaphor_engine.py`:

```python
METAPHOR_REGISTRY.append(
    MetaphorMapping(
        metaphor_type=MetaphorType.ENERGY_CONTROL,
        source_domain=DomainType.HEMS,
        source_concept="...",
        target_domain=DomainType.SAP_CONTROL,
        target_concept="...",
        similarity_score=0.8,
        explanation="...",
        content_angles=[...]
    )
)
```

### Adding New Lived System Nodes

Edit `LIVED_SYSTEM_NODES` in `app/metaphor_engine.py`:

```python
LIVED_SYSTEM_NODES.append(
    LivedSystemNode(
        id="hems_new_system",
        domain=DomainType.HEMS,
        concept="...",
        description="...",
        keywords=[...],
        metadata={...}
    )
)
```

### Dynamic Similarity Scoring

Current: Static similarity scores. Future enhancements:

1. **Vector similarity**: Use embeddings to compute dynamic similarity
2. **KG traversal**: Query Neo4j for related nodes
3. **Feedback loop**: Learn from published content performance

---

## Testing

### Unit Tests

```bash
cd /path/to/marketing-agent
pytest tests/test_metaphor_engine.py -v
```

### API Testing

```bash
# Generate ideas
curl -X POST http://localhost:8210/api/v1/metaphor/generate-ideas \
  -H "Content-Type: application/json" \
  -d '{
    "domains": ["hems", "homelab"],
    "min_confidence": 0.6,
    "limit": 5
  }'

# View registry
curl http://localhost:8210/api/v1/metaphor/registry?source_domain=hems

# List nodes
curl http://localhost:8210/api/v1/metaphor/nodes?domain=hems

# Health check
curl http://localhost:8210/api/v1/metaphor/health
```

---

## Future Enhancements

### Phase 2: KG Integration

- [ ] Store metaphor mappings in Neo4j
- [ ] Query KG for related posts/topics
- [ ] Compute similarity dynamically via embeddings

### Phase 3: Automated Drafting

- [ ] Metaphor-triggered auto-draft creation
- [ ] Content outline generation from metaphor angles
- [ ] Persona-aligned voice rules

### Phase 4: Performance Feedback

- [ ] Track which metaphor-based ideas convert to published posts
- [ ] Learn which angles resonate with audience
- [ ] Adjust similarity scores based on engagement

### Phase 5: Cross-Domain Knowledge Transfer

- [ ] Extract insights from high-performing metaphor content
- [ ] Suggest reverse metaphors (enterprise → lived systems)
- [ ] Identify emergent domains (e.g., EV charging, PV forecasting)

---

## References

- **Task**: #177 — Content from lived systems
- **Spec**: `/home/hesch/.openclaw/workspace/projects/orbit/specs/ORBIT_SPEC.md`
- **NB9OS**: `/home/hesch/.openclaw/workspace/services/nb9os/`
- **Marketing Agent**: `/home/hesch/.openclaw/workspace/claude/services/marketing-agent/`

---

**Status**: ✅ Phase 1 complete (metaphor registry, node registry, API endpoints)  
**Created**: 2026-03-26  
**Last Updated**: 2026-03-26
