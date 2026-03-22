"""Risk flag scanner — governance and compliance checks."""

import re
from typing import List
from pydantic import BaseModel


class RiskFlag(BaseModel):
    """A detected risk flag in content."""

    type: str
    match: str
    line_number: int
    action: str = "review"  # review, block


# Risk patterns and their flag types
RISK_PATTERNS = [
    # Unverified metrics (claims without proof)
    (r"\b(\d+%|\$\d+[BM]|billion|million|thousand)\s+(?:increase|decrease|growth|improvement)", "unverified_metric"),
    
    # Client references (confidentiality)
    (r"\b(Lindt|Horváth|client|customer|account)\b", "client_reference"),
    
    # Roadmap claims (avoid future predictions)
    (r"\b(will|is planning to|is scheduled to|will release|upcoming)\s+(release|launch|announce|introduce)", "roadmap_claim"),
    
    # Confidential information
    (r"\b(confidential|internal|under NDA|proprietary|secret)\b", "confidentiality_risk"),
    
    # Unverified feature claims
    (r"\b(SAP is|SAP will|Datasphere can|Datasphere will)\b.*\b(feature|capability|support)", "unverified_feature"),
    
    # Comparative claims without evidence
    (r"\b(better than|faster than|superior to|best|worst)\b.*\b(competitor|tool|solution)\b", "unsubstantiated_claim"),
    
    # All-caps for emphasis (style issue)
    (r"\b[A-Z]{3,}\b", "style_allcaps"),
]


async def scan_risk_flags(content: str) -> List[RiskFlag]:
    """
    Scan content for governance risks.
    
    Returns list of RiskFlag objects with type, match, and line number.
    """
    flags: List[RiskFlag] = []
    lines = content.split("\n")
    
    for line_num, line in enumerate(lines, 1):
        for pattern, flag_type in RISK_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                # Skip markdown syntax (headers, links)
                if line.strip().startswith("#") or line.strip().startswith("["):
                    continue
                
                flags.append(
                    RiskFlag(
                        type=flag_type,
                        match=match.group(0),
                        line_number=line_num,
                        action="review" if flag_type != "confidentiality_risk" else "block",
                    )
                )
    
    return flags


async def should_block_draft(flags: List[RiskFlag]) -> bool:
    """Check if any critical flags should block publishing."""
    blocking_types = {"confidentiality_risk"}
    return any(f.type in blocking_types for f in flags)


def format_risk_report(flags: List[RiskFlag]) -> str:
    """Format risk flags as human-readable report."""
    if not flags:
        return "✓ No risks detected"
    
    report_lines = [f"Found {len(flags)} risk flag(s):"]
    
    for flag in flags:
        action = "🚫 BLOCK" if flag.action == "block" else "⚠️  REVIEW"
        report_lines.append(f"{action}: [{flag.type}] Line {flag.line_number}: \"{flag.match}\"")
    
    return "\n".join(report_lines)
