"""
Memora Meeting Intelligence Service — Auto-extraction of meeting insights.

Extracts from transcripts:
  - Action items (tasks)
  - Decisions
  - Open questions
  - Risks

Stores results as linked artifacts.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Data Models
class ActionItem(BaseModel):
    """Extracted action item from transcript."""
    id: str
    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "medium"  # low, medium, high
    mentioned_at_segment: Optional[int] = None


class Decision(BaseModel):
    """Extracted decision from transcript."""
    id: str
    description: str
    rationale: Optional[str] = None
    agreed_by: list[str] = []
    mentioned_at_segment: Optional[int] = None


class OpenQuestion(BaseModel):
    """Extracted open question from transcript."""
    id: str
    question: str
    asked_by: Optional[str] = None
    related_to: Optional[str] = None
    mentioned_at_segment: Optional[int] = None


class Risk(BaseModel):
    """Extracted risk from transcript."""
    id: str
    description: str
    severity: str = "medium"  # low, medium, high, critical
    mitigation: Optional[str] = None
    owner: Optional[str] = None
    mentioned_at_segment: Optional[int] = None


class MeetingIntelligenceResult(BaseModel):
    """Complete meeting intelligence extraction result."""
    meeting_id: str
    timestamp: str
    transcript: str
    language: str = "en"
    duration_seconds: Optional[float] = None
    
    action_items: list[ActionItem] = []
    decisions: list[Decision] = []
    open_questions: list[OpenQuestion] = []
    risks: list[Risk] = []
    
    summary: Optional[str] = None
    key_topics: list[str] = []


class MeetingIntelligenceService:
    """Service for extracting intelligence from meeting transcripts."""

    def __init__(self):
        """Initialize meeting intelligence service."""
        self.logger = logging.getLogger(__name__)

    def extract_all(
        self,
        transcript: str,
        meeting_id: str = "default",
        language: str = "en",
        duration_seconds: Optional[float] = None,
    ) -> MeetingIntelligenceResult:
        """
        Extract all intelligence from meeting transcript.

        Args:
            transcript: Full meeting transcript text
            meeting_id: Unique meeting identifier
            language: Language of transcript (default: en)
            duration_seconds: Meeting duration in seconds

        Returns:
            MeetingIntelligenceResult with all extracted insights
        """
        self.logger.info(f"Extracting intelligence from meeting {meeting_id}")

        result = MeetingIntelligenceResult(
            meeting_id=meeting_id,
            timestamp=datetime.utcnow().isoformat(),
            transcript=transcript,
            language=language,
            duration_seconds=duration_seconds,
        )

        # Extract all types
        result.action_items = self.extract_action_items(transcript)
        result.decisions = self.extract_decisions(transcript)
        result.open_questions = self.extract_open_questions(transcript)
        result.risks = self.extract_risks(transcript)
        result.key_topics = self.extract_key_topics(transcript)
        result.summary = self.generate_summary(transcript, result)

        self.logger.info(
            f"Extraction complete: {len(result.action_items)} items, "
            f"{len(result.decisions)} decisions, "
            f"{len(result.open_questions)} questions, "
            f"{len(result.risks)} risks"
        )

        return result

    def extract_action_items(self, transcript: str) -> list[ActionItem]:
        """
        Extract action items from transcript.

        Looks for patterns like:
        - "I will...", "I'll...", "We need to...", "Action item:"
        - "Owner:", "Due:", "Deadline:"
        """
        items = []
        action_patterns = [
            r"(?:I|we|you)\s+(?:will|need to|have to|must)\s+([^.\n]+)",
            r"action\s+item[:\s]+([^.\n]+)",
            r"(?:todo|to-do)[:\s]+([^.\n]+)",
            r"owner[:\s]+(\w+)[^.\n]*(?:(?:due|deadline)[:\s]+(\d{4}-\d{2}-\d{2}|[^.\n]+))?",
        ]

        for idx, pattern in enumerate(action_patterns):
            matches = re.finditer(pattern, transcript, re.IGNORECASE)
            for match_idx, match in enumerate(matches):
                description = match.group(1).strip()
                if len(description) > 5:  # Filter short matches
                    item = ActionItem(
                        id=f"action_{idx}_{match_idx}",
                        description=description,
                        priority="medium",
                    )
                    # Try to extract owner and due date
                    context = transcript[max(0, match.start() - 100) : match.end() + 100]
                    owner_match = re.search(r"owner[:\s]+(\w+)", context, re.IGNORECASE)
                    if owner_match:
                        item.owner = owner_match.group(1)

                    due_match = re.search(r"(?:due|deadline)[:\s]+([^,.\n]+)", context, re.IGNORECASE)
                    if due_match:
                        item.due_date = due_match.group(1).strip()

                    if item not in items:  # Avoid duplicates
                        items.append(item)

        return items[:10]  # Return top 10

    def extract_decisions(self, transcript: str) -> list[Decision]:
        """
        Extract decisions from transcript.

        Looks for patterns like:
        - "We decided...", "We've agreed...", "Decision:", "Decided to..."
        """
        decisions = []
        decision_patterns = [
            r"(?:we\s+)?decided\s+(?:to\s+)?([^.\n]+)",
            r"(?:we\s+)?agreed\s+(?:to\s+)?([^.\n]+)",
            r"decision[:\s]+([^.\n]+)",
            r"(?:we|you)\s+(?:will|must|should)\s+([^.\n]+)(?:\s+because|reason)",
        ]

        for idx, pattern in enumerate(decision_patterns):
            matches = re.finditer(pattern, transcript, re.IGNORECASE)
            for match_idx, match in enumerate(matches):
                description = match.group(1).strip()
                if len(description) > 5:
                    decision = Decision(
                        id=f"decision_{idx}_{match_idx}",
                        description=description,
                    )
                    # Try to extract rationale from context
                    context = transcript[max(0, match.start() - 150) : match.end() + 150]
                    rationale_match = re.search(
                        r"because\s+([^.\n]+)|reason[:\s]+([^.\n]+)",
                        context,
                        re.IGNORECASE,
                    )
                    if rationale_match:
                        decision.rationale = (
                            rationale_match.group(1) or rationale_match.group(2)
                        ).strip()

                    if decision not in decisions:
                        decisions.append(decision)

        return decisions[:8]  # Return top 8

    def extract_open_questions(self, transcript: str) -> list[OpenQuestion]:
        """
        Extract open questions from transcript.

        Looks for patterns like:
        - "What...", "How...", "Why...", "Who..."
        - "Question:", "Open item:"
        - "We need to clarify..."
        """
        questions = []
        question_patterns = [
            r"(?:what|how|why|who|when|where|which)\s+[^?]*\?",
            r"question[:\s]+([^?\n]+\?)",
            r"open\s+(?:item|question)[:\s]+([^.\n]+)",
            r"(?:we\s+)?need\s+to\s+clarify\s+([^.\n]+)",
        ]

        for idx, pattern in enumerate(question_patterns):
            matches = re.finditer(pattern, transcript, re.IGNORECASE)
            for match_idx, match in enumerate(matches):
                text = match.group(0) if match.lastindex is None else match.group(1)
                question_text = text.strip().rstrip("?") + ("?" if not text.endswith("?") else "")

                if len(question_text) > 5:
                    question = OpenQuestion(
                        id=f"question_{idx}_{match_idx}",
                        question=question_text,
                    )

                    if question not in questions:
                        questions.append(question)

        return questions[:10]  # Return top 10

    def extract_risks(self, transcript: str) -> list[Risk]:
        """
        Extract risks from transcript.

        Looks for patterns like:
        - "Risk:", "Concern:", "Problem:", "Issue:"
        - "Could fail", "Might not work", "Dependency on..."
        """
        risks = []
        risk_patterns = [
            r"risk[:\s]+([^.\n]+)",
            r"concern[:\s]+([^.\n]+)",
            r"problem[:\s]+([^.\n]+)",
            r"issue[:\s]+([^.\n]+)",
            r"(?:could|might|may)\s+(?:fail|break|not work|go wrong)\s+([^.\n]+)",
            r"dependency\s+on\s+([^.\n]+)",
            r"blockers?\s+(?:include|are)[:\s]+([^.\n]+)",
        ]

        for idx, pattern in enumerate(risk_patterns):
            matches = re.finditer(pattern, transcript, re.IGNORECASE)
            for match_idx, match in enumerate(matches):
                description = match.group(1).strip()
                if len(description) > 5:
                    risk = Risk(
                        id=f"risk_{idx}_{match_idx}",
                        description=description,
                        severity="medium",
                    )

                    # Heuristic severity assessment
                    severity_keywords = {
                        "critical": ["critical", "blocker", "breaking", "urgent"],
                        "high": ["major", "significant", "important", "immediately"],
                        "medium": ["concern", "potential", "could"],
                        "low": ["might", "possibly", "minor"],
                    }

                    for severity, keywords in severity_keywords.items():
                        if any(kw in description.lower() for kw in keywords):
                            risk.severity = severity
                            break

                    if risk not in risks:
                        risks.append(risk)

        return risks[:8]  # Return top 8

    def extract_key_topics(self, transcript: str) -> list[str]:
        """
        Extract key topics mentioned in transcript.

        Simple heuristic: extract capitalized phrases and common meeting topics.
        """
        topics = []

        # Look for capitalized phrases (likely proper nouns or topics)
        capitalized = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", transcript)
        # Filter common words
        stop_words = {"The", "I", "We", "You", "He", "She", "It", "And", "Or", "But"}
        topics = [t for t in set(capitalized) if t not in stop_words][:5]

        # Also look for common meeting topics
        topic_keywords = {
            "Timeline": ["timeline", "deadline", "schedule", "when"],
            "Budget": ["budget", "cost", "expense", "funding"],
            "Resources": ["resource", "team", "staff", "capacity"],
            "Quality": ["quality", "testing", "qa", "bug"],
            "Performance": ["performance", "speed", "optimization"],
            "Security": ["security", "privacy", "encryption"],
            "Integration": ["integration", "api", "system", "connect"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in transcript.lower() for kw in keywords):
                topics.append(topic)

        return list(set(topics))[:7]

    def generate_summary(
        self,
        transcript: str,
        result: MeetingIntelligenceResult,
    ) -> str:
        """
        Generate brief summary of meeting.

        Combines extracted insights.
        """
        summary_parts = []

        if result.key_topics:
            summary_parts.append(f"Topics: {', '.join(result.key_topics)}")

        if result.decisions:
            summary_parts.append(
                f"Decisions: {len(result.decisions)} key decision(s) made"
            )

        if result.action_items:
            summary_parts.append(
                f"Action items: {len(result.action_items)} item(s) assigned"
            )

        if result.risks:
            high_risk_count = sum(1 for r in result.risks if r.severity == "critical")
            summary_parts.append(f"Risks: {len(result.risks)} identified")
            if high_risk_count:
                summary_parts.append(f"({high_risk_count} critical)")

        if result.open_questions:
            summary_parts.append(
                f"Open questions: {len(result.open_questions)} to be addressed"
            )

        return " | ".join(summary_parts) if summary_parts else "Meeting intelligence extraction complete"
