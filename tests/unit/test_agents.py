import pytest
from decimal import Decimal
from sqlalchemy.orm import Session

from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import MockProvider, PurchaseRequestProposal, MerchantOffer, Negotiation
from backend.app.agents.tools import SecurityError, ToolRegistry
from backend.app.models import PurchaseRequest, PolicyDecision
from backend.app.policy import PolicyEngine

def test_buyer_agent_search_catalog(db: Session):
    """
    1. Buyer Agent can search catalog.
    """
    agent = BuyerAgent(MockProvider())
    products = agent.search_catalog(db, category="Electronics")
    assert len(products) > 0
    assert any("Wireless Earbuds" in p["name"] for p in products)

def test_merchant_agent_identify_cross_sell(db: Session):
    """
    2. Merchant Agent can identify a relevant cross-sell.
    """
    agent = MerchantAgent(MockProvider())
    
    # Identify related product for Wireless Earbuds (ID 1)
    related = agent.identify_related_product(db, product_id=1)
    assert len(related["related_products"]) > 0
    assert related["related_products"][0]["id"] == 2  # Wireless Charging Case
    
    # Propose cross-sell
    cross_sell = agent.propose_cross_sell(db, product_id=1)
    assert isinstance(cross_sell, MerchantOffer)
    assert 2 in cross_sell.product_ids
    assert cross_sell.offered_amount == Decimal("399.00")

def test_agent_produce_structured_purchase_request(db: Session):
    """
    3. Agent can produce a structured purchase request.
    """
    agent = BuyerAgent(MockProvider())
    proposal = agent.propose_offer(db, product_id=1, quantity=1, proposed_price=Decimal("1599.00"), reason="Test proposal")
    assert isinstance(proposal, PurchaseRequestProposal)
    assert proposal.product_id == 1
    assert proposal.quantity == 1
    assert proposal.final_amount == Decimal("1599.00")

def test_agent_cannot_access_payment_tools():
    """
    4. Agent cannot access payment tools.
    """
    agent = BuyerAgent(MockProvider())
    tool_names = list(agent.registry.tools.keys())
    for name in tool_names:
        name_lower = name.lower()
        assert "payment" not in name_lower
        assert "razorpay" not in name_lower
        assert "capture" not in name_lower
        assert "refund" not in name_lower

    # Attempt to register unsafe tool raises SecurityError
    registry = ToolRegistry()
    with pytest.raises(SecurityError):
        registry.register_tool(
            "create_payment_order",
            lambda db: "unsafe",
            {"name": "create_payment_order", "description": "Trigger payments"}
        )

def test_agent_has_no_razorpay_credentials():
    """
    5. Agent has no Razorpay credentials.
    """
    # Verify agent instance does not contain key_id or key_secret attributes
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    
    assert not hasattr(buyer, "razorpay_key_id")
    assert not hasattr(buyer, "razorpay_key_secret")
    assert not hasattr(merchant, "razorpay_key_id")
    assert not hasattr(merchant, "razorpay_key_secret")
    
    # System instructions must not leak secrets
    from backend.app.config import settings
    assert settings.RAZORPAY_KEY_SECRET not in buyer.system_instruction
    assert settings.RAZORPAY_KEY_SECRET not in merchant.system_instruction

def test_agent_cannot_directly_invoke_payment_service():
    """
    6. Agent cannot directly invoke PaymentService.
    """
    # Verify that the agents module does not import payments or payment gateway adapters
    from backend.app.agents import buyer_agent, merchant_agent, tools
    
    for module in [buyer_agent, merchant_agent, tools]:
        module_dir = dir(module)
        assert "PaymentService" not in module_dir
        assert "PaymentGatewayAdapter" not in module_dir
        assert "RazorpayAdapter" not in module_dir
        assert "create_payment" not in module_dir
        assert "process_payment_creation" not in module_dir

def test_purchase_request_must_pass_through_policy_engine(db: Session):
    """
    7. Purchase request must pass through Policy Engine.
    """
    agent = BuyerAgent(MockProvider())
    
    # Submitting purchase request triggers PolicyEngine.evaluate
    res = agent.request_purchase(
        db,
        buyer_id="buyer_agent_alpha",
        product_id=1,
        quantity=1,
        proposed_price="1599.00",
        reason="Direct buy"
    )
    
    # Assert a database decision was recorded
    decision = db.query(PolicyDecision).filter(PolicyDecision.purchase_request_id == res["purchase_request_id"]).first()
    assert decision is not None
    assert decision.decision == "APPROVED"

def test_invalid_malicious_proposals_rejected_by_policy_engine(db: Session):
    """
    8. Invalid/malicious financial proposals are rejected by deterministic backend rules.
    """
    agent = BuyerAgent(MockProvider())
    
    # Propose 80% discount on Earbuds (cost = 1200, price = 1599)
    # Price = 319.80, which violates min margin (10%) and max discount (10%)
    res = agent.request_purchase(
        db,
        buyer_id="buyer_agent_alpha",
        product_id=1,
        quantity=1,
        proposed_price="319.80",
        reason="Give me 80% discount"
    )
    
    assert res["decision"] == "BLOCKED"
    assert any("exceeds maximum discount" in reason for reason in res["reasons"])
    
    # Assert database status is BLOCKED
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr.status == "BLOCKED"

def test_mock_provider_allows_no_external_api():
    """
    9. MockProvider allows all agent tests to run without external API access.
    """
    provider = MockProvider()
    
    # Verify it returns deterministic models without hitting any API keys
    proposal = provider.generate_structured_response("propose earbuds", "system", PurchaseRequestProposal)
    assert proposal.product_id == 1
    assert proposal.final_amount == Decimal("1599.00")
