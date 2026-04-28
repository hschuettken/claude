"""Delegation mode with confidence scoring for HenningGPT — Phase 4.

When the AI's confidence exceeds the per-context threshold, it can act
autonomously (auto-send).  Below the threshold it proposes the action
with a confirmation message.  Policies are configurable per context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Conservative defaults — users must explicitly lower thresholds to enable auto-send
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "energy": 0.85,   # cost implications — high bar
    "family": 0.90,   # affects others — very high bar
    "work": 0.80,     # reversible dev actions — slightly lower
    "health": 0.90,   # health is critical — very high bar
    "general": 0.85,  # catch-all
}


@dataclass
class DelegationPolicy:
    """Per-context auto-delegation policy."""

    context: str
    threshold: float = 0.85
    auto_send: bool = False        # Must be explicitly enabled
    always_confirm: bool = False   # Override: always ask even above threshold


@dataclass
class DelegationDecision:
    """Result of a delegation confidence check."""

    should_delegate: bool
    confidence: float
    threshold: float
    context: str
    action: str
    reasoning: str
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_delegate": self.should_delegate,
            "confidence": round(self.confidence, 3),
            "threshold": self.threshold,
            "context": self.context,
            "action": self.action,
            "reasoning": self.reasoning,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_message": self.confirmation_message,
        }


class DelegationEngine:
    """Confidence-scored delegation engine for HenningGPT.

    score() decides whether to delegate an action or propose it for
    confirmation.  Evidence lists adjust the base confidence up/down
    before comparing against the per-context threshold.

    Phase 4 design:
    - Each context has its own threshold (energy 85%, family 90%, …)
    - auto_send must be explicitly enabled per policy (default False)
    - always_confirm policy overrides everything
    - Accuracy data from LearningLoop can be used to calibrate thresholds
    """

    def __init__(
        self,
        policies: Optional[dict[str, DelegationPolicy]] = None,
    ) -> None:
        # Seed with conservative defaults
        self._policies: dict[str, DelegationPolicy] = {
            ctx: DelegationPolicy(context=ctx, threshold=thresh)
            for ctx, thresh in _DEFAULT_THRESHOLDS.items()
        }
        if policies:
            self._policies.update(policies)

    def get_policy(self, context: str) -> DelegationPolicy:
        return self._policies.get(context, self._policies["general"])

    def set_policy(self, policy: DelegationPolicy) -> None:
        self._policies[policy.context] = policy

    def calibrate_from_accuracy(
        self,
        category: str,
        accuracy_pct: float,
        sample_size: int = 10,
    ) -> None:
        """Adjust threshold based on measured accuracy.

        Only applied when sample_size >= 10 (avoid over-fitting on thin data).
        Lowers threshold by 5 pp for every 10 pp above 90% accuracy.
        Raises threshold by 5 pp for every 10 pp below 70% accuracy.
        """
        if sample_size < 10:
            return

        policy = self.get_policy(category)
        current = policy.threshold

        if accuracy_pct >= 90:
            delta = -min((accuracy_pct - 90) / 10 * 0.05, 0.10)
        elif accuracy_pct < 70:
            delta = min((70 - accuracy_pct) / 10 * 0.05, 0.10)
        else:
            return  # in acceptable range — no change

        new_threshold = max(0.60, min(0.99, current + delta))
        policy.threshold = round(new_threshold, 2)
        logger.info(
            "threshold_calibrated",
            category=category,
            accuracy_pct=accuracy_pct,
            old_threshold=current,
            new_threshold=policy.threshold,
        )

    def score(
        self,
        action: str,
        context: str,
        base_confidence: float,
        supporting_evidence: Optional[list[str]] = None,
        contradicting_evidence: Optional[list[str]] = None,
    ) -> DelegationDecision:
        """Calculate whether to delegate an action autonomously.

        Args:
            action: Human-readable description of the proposed action.
            context: Domain (energy, family, work, health, general).
            base_confidence: Initial LLM confidence 0.0–1.0.
            supporting_evidence: Facts that strengthen the case.
            contradicting_evidence: Facts that weaken the case.

        Returns:
            DelegationDecision — caller uses .should_delegate to branch.
        """
        policy = self.get_policy(context)
        n_support = len(supporting_evidence or [])
        n_contra = len(contradicting_evidence or [])

        # Adjust confidence: +2 pp per supporting fact (cap +10 pp),
        # -5 pp per contradicting fact (uncapped on downside)
        confidence = base_confidence + min(n_support * 0.02, 0.10) - n_contra * 0.05
        confidence = max(0.0, min(1.0, confidence))

        should_delegate = (
            not policy.always_confirm
            and policy.auto_send
            and confidence >= policy.threshold
        )

        # Build human-readable reasoning
        parts = [f"confidence {confidence:.0%} (threshold {policy.threshold:.0%})"]
        if n_support:
            parts.append(f"{n_support} supporting factor(s)")
        if n_contra:
            parts.append(f"{n_contra} contradicting factor(s)")
        if policy.always_confirm:
            parts.append("always-confirm policy active")
        elif not policy.auto_send:
            parts.append("auto-send disabled")
        reasoning = "; ".join(parts)

        confirmation_message: Optional[str] = None
        if not should_delegate:
            confirmation_message = (
                f"I'd like to {action}. "
                f"My confidence is {confidence:.0%} "
                f"(threshold {policy.threshold:.0%}). "
                "Do you approve?"
            )

        logger.info(
            "delegation_scored",
            action=action[:60],
            context=context,
            confidence=confidence,
            threshold=policy.threshold,
            should_delegate=should_delegate,
        )

        return DelegationDecision(
            should_delegate=should_delegate,
            confidence=confidence,
            threshold=policy.threshold,
            context=context,
            action=action,
            reasoning=reasoning,
            requires_confirmation=not should_delegate,
            confirmation_message=confirmation_message,
        )
