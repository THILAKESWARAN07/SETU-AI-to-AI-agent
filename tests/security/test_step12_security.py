import pytest
from decimal import Decimal
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import MockProvider, BuyerDecision, MerchantDecision
from backend.app.agents.tools import SecurityError
from backend.app.models import PurchaseRequest, PolicyDecision, Transaction
from backend.app.policy import PolicyEngine
from backend.app.config import settings

def test_buyer_merchant_tool_isolation():
    """
    4. Buyer Agent cannot access merchant-only tools, and vice-versa.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    
    # Merchant-only tools must NOT be present in buyer's registry
    merchant_only = ["get_inventory", "get_product_price", "get_merchant_constraints", "evaluate_margin"]
    for tool in merchant_only:
        assert tool not in buyer.registry.tools
        with pytest.raises(ValueError):
            buyer.registry.execute_tool(tool, None)

    # Buyer-only tools must NOT be present in merchant's registry
    buyer_only = ["search_catalog", "get_product_details", "get_policy_constraints", "evaluate_budget", "request_purchase"]
    for tool in buyer_only:
        assert tool not in merchant.registry.tools
        with pytest.raises(ValueError):
            merchant.registry.execute_tool(tool, None)


def test_neither_agent_has_payment_or_secret_access():
    """
    4. Gating verification: Neither agent has access to payment tools or API keys.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())

    unsafe_payment_keywords = ["razorpay", "capture_payment", "refund", "credit_card", "bank"]
    
    # Check tool lists
    for agent in [buyer, merchant]:
        for name in agent.registry.tools:
            for kw in unsafe_payment_keywords:
                assert kw not in name.lower()
        
        # Verify no direct API key attributes are stored on agents
        assert not hasattr(agent, "api_key")
        assert not hasattr(agent, "RAZORPAY_KEY_SECRET")
        assert not hasattr(agent, "RAZORPAY_KEY_ID")


def test_policy_engine_margin_and_budget_checks(db: Session):
    """
    4. PolicyEngine remains authoritative: Output cannot bypass budget or margin checks.
    """
    from backend.app.models import Product, MerchantPolicy
    product = db.query(Product).filter(Product.id == 1).first()
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()

    # 1. Budget violation check (budget is 1000, price is 1599)
    res_budget = PolicyEngine.evaluate(product, policy, quantity=1, final_amount=Decimal("1599.00"), buyer_budget=Decimal("1000.00"))
    assert res_budget["decision"] == "BLOCKED"
    assert any("budget" in r.lower() for r in res_budget["reasons"])

    # 2. Margin violation check (min margin is 30%, cost is 1050, final_amount is 1100 -> margin = (1100-1050)/1100 = 4.5% < 30%)
    res_margin = PolicyEngine.evaluate(product, policy, quantity=1, final_amount=Decimal("1100.00"))
    assert res_margin["decision"] == "BLOCKED"
    assert any("margin" in r.lower() for r in res_margin["reasons"])


def test_negotiation_round_limit_enforced(db: Session):
    """
    4. Negotiation cannot exceed configured maximum rounds.
    """
    from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError

    # Loop provider to force counters infinitely
    class CounterInfiniteProvider(MockProvider):
        def generate_structured_response(self, prompt, system, schema):
            if schema == BuyerDecision:
                return BuyerDecision(
                    action="COUNTER",
                    product_id=1,
                    quantity=1,
                    unit_price=Decimal("1400.00"),
                    total_amount=Decimal("1400.00"),
                    rationale="Buyer Counter",
                    constraints_checked=[]
                )
            elif schema == MerchantDecision:
                return MerchantDecision(
                    action="COUNTER",
                    product_id=1,
                    quantity=1,
                    unit_price=Decimal("1900.00"),
                    total_amount=Decimal("1900.00"),
                    rationale="Merchant Counter",
                    margin_check="passed"
                )
            return super().generate_structured_response(prompt, system, schema)

    buyer = BuyerAgent(CounterInfiniteProvider())
    merchant = MerchantAgent(CounterInfiniteProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    with pytest.raises(NegotiationError) as exc_info:
        orchestrator.run_negotiation_loop(
            buyer_id="buyer_loop_limit",
            intent="earbuds",
            budget=Decimal("1500.00"),
            max_rounds=3
        )
    assert "could not reach" in str(exc_info.value)
