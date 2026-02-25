from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

@dataclass
class VerifiableContract:
    """A cryptographic or deterministic proof that an agent is allowed to act."""
    agent_id: str
    is_valid: bool
    reason: str
    compliance_checks_passed: List[str] = field(default_factory=list)

@dataclass
class AgentBid:
    """An agent's bid to take on a task based on its trust score and capability."""
    agent_id: str
    confidence_score: float  # 0.0 to 1.0
    estimated_cost: float
    contract: VerifiableContract

class TrustManager:
    """Manages formal trust models for agents."""
    def __init__(self, initial_trust: Dict[str, float] | None = None) -> None:
        self._trust_scores = initial_trust or {}

    def get_trust(self, agent_id: str) -> float:
        return self._trust_scores.get(agent_id, 0.5)  # Default neutral trust

    def update_trust(self, agent_id: str, success: bool, weight: float = 0.1) -> None:
        current = self.get_trust(agent_id)
        if success:
            new_trust = min(1.0, current + weight)
        else:
            new_trust = max(0.0, current - weight)
        self._trust_scores[agent_id] = new_trust

class DelegationMarket:
    """A market where agents bid on tasks and the best verifiable bid wins."""
    def __init__(self, trust_manager: TrustManager) -> None:
        self.trust_manager = trust_manager
        self.bids: List[AgentBid] = []

    def receive_bid(self, bid: AgentBid) -> None:
        if not bid.contract.is_valid:
            log.warning(f"Market rejected invalid bid from {bid.agent_id}: {bid.contract.reason}")
            return

        # Adjust confidence by formal trust score
        trust = self.trust_manager.get_trust(bid.agent_id)
        adjusted_score = bid.confidence_score * trust

        bid.confidence_score = adjusted_score
        self.bids.append(bid)

    def select_best_agent(self, min_confidence: float = 0.2) -> Optional[AgentBid]:
        if not self.bids:
            return None

        # Sort by confidence score descending
        valid_bids = [b for b in self.bids if b.confidence_score >= min_confidence]
        if not valid_bids:
            return None

        valid_bids.sort(key=lambda b: b.confidence_score, reverse=True)
        return valid_bids[0]
