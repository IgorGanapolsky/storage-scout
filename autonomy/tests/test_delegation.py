import pytest

from autonomy.delegation import (
    AgentBid,
    DelegationMarket,
    TrustManager,
    VerifiableContract,
)


def test_trust_manager() -> None:
    tm = TrustManager({"agent_a": 0.8})
    assert tm.get_trust("agent_a") == 0.8
    assert tm.get_trust("agent_b") == 0.5  # default

    tm.update_trust("agent_a", success=True, weight=0.1)
    assert pytest.approx(tm.get_trust("agent_a")) == 0.9

    tm.update_trust("agent_a", success=True, weight=0.5)
    assert tm.get_trust("agent_a") == 1.0  # capped

    tm.update_trust("agent_b", success=False, weight=0.6)
    assert tm.get_trust("agent_b") == 0.0  # floored


def test_delegation_market() -> None:
    tm = TrustManager({"agent_good": 0.9, "agent_bad": 0.1})
    market = DelegationMarket(tm)

    # Invalid bid
    bad_contract = VerifiableContract(
        agent_id="agent_invalid", is_valid=False, reason="No permissions"
    )
    market.receive_bid(AgentBid("agent_invalid", 1.0, 0.0, bad_contract))
    assert len(market.bids) == 0

    # Valid bids
    c1 = VerifiableContract("agent_good", True, "OK")
    # effective score: 0.8 * 0.9 = 0.72
    market.receive_bid(AgentBid("agent_good", 0.8, 1.0, c1))

    c2 = VerifiableContract("agent_bad", True, "OK")
    # effective score: 0.9 * 0.1 = 0.09
    market.receive_bid(AgentBid("agent_bad", 0.9, 1.0, c2))

    best = market.select_best_agent(min_confidence=0.5)
    assert best is not None
    assert best.agent_id == "agent_good"
    assert pytest.approx(best.confidence_score) == 0.72

    # Test no valid bids over threshold
    best_high = market.select_best_agent(min_confidence=0.99)
    assert best_high is None

    # Test empty market
    empty_market = DelegationMarket(tm)
    assert empty_market.select_best_agent() is None
