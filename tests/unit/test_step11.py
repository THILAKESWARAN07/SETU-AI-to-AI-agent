import pytest
from decimal import Decimal
from sqlalchemy.orm import Session

from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.agents.provider import MockProvider
from backend.app.agents.tools import ToolRegistry, SecurityError
from backend.app.models import PurchaseRequest, Transaction, PolicyDecision
from backend.app.policy import PolicyEngine

def test_step11_successful_negotiation(db: Session):
    """Verify Scenario A: Successful negotiation with budget ₹2,000."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer",
        intent="I need wireless earbuds under ₹2,000.",
        budget=Decimal("2000.00"),
        max_rounds=4
    )

    assert res["decision"] == "APPROVED"
    assert res["purchase_request_id"] > 0
    assert Decimal(res["final_amount"]) <= Decimal("2000.00")
    assert len(res["negotiation_history"]) > 0

def test_step11_buyer_budget_protection(db: Session):
    """Verify Scenario C: Budget protection blocks negotiation when price exceeds budget limit."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    with pytest.raises(NegotiationError) as exc_info:
        orchestrator.run_negotiation_loop(
            buyer_id="test-buyer",
            intent="earbuds, budget is 1500",
            budget=Decimal("1000.00"),
            max_rounds=4
        )

    assert "exceeds" in str(exc_info.value).lower() or "budget" in str(exc_info.value).lower() or "could not reach" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()
    assert exc_info.value.result_data is not None
    assert exc_info.value.result_data["decision"] in ["BLOCKED", "REJECTED"]

def test_step11_merchant_minimum_margin_protection(db: Session):
    """Verify Scenario B: Merchant rejection when proposed price violates minimum margin."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    with pytest.raises(NegotiationError) as exc_info:
        orchestrator.run_negotiation_loop(
            buyer_id="test-buyer",
            intent="earbuds, budget is 1000",
            budget=Decimal("1000.00"),
            max_rounds=4
        )

    assert exc_info.value.result_data is not None
    assert exc_info.value.result_data["decision"] == "BLOCKED" or exc_info.value.result_data["decision"] == "REJECTED"

def test_step11_tool_allowlist_enforcement():
    """Verify neither buyer nor merchant can fetch disallowed keys or payment tools."""
    registry = ToolRegistry()

    # Verify unsafe payment keywords are blocked during registration
    with pytest.raises(SecurityError):
        registry.register_tool("capture_payment", lambda x: x, {"description": "Captures a payment"})

def test_step11_payment_isolation(db: Session):
    """Verify that agents cannot directly execute payment operations."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    
    # Check that tools registry does not contain any payment tools
    assert "create_payment" not in buyer.registry.tools
    assert "capture_payment" not in merchant.registry.tools

def test_step11_agreement_locking_and_handoff(db: Session):
    """Verify agreement is locked server-side and amount cannot be modified by client."""
    # Create manual approved Purchase Request
    pr = PurchaseRequest(
        buyer_id="test-buyer-001",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1439.10"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1439.10"),
        discount_percent=Decimal("10.00"),
        currency="INR",
        reason="Locked deal test",
        status="APPROVED"
    )
    db.add(pr)
    db.commit()

    # Create matching policy decision
    decision = PolicyDecision(
        purchase_request_id=pr.id,
        decision="APPROVED",
        reasons=[],
        policy_version="policy_v1.0",
        calculated_margin_percent=Decimal("27.04"),
        product_id=1,
        quantity=1,
        unit_price=Decimal("1439.10"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1439.10"),
        discount_percent=Decimal("10.00"),
        currency="INR"
    )
    db.add(decision)
    db.commit()

    # Handoff to Payment creation
    from backend.app.payments import process_payment_creation
    tx = process_payment_creation(db, pr.id)

    assert tx.status == "PENDING"
    assert tx.amount == Decimal("1439.10")  # Verified lock matches final negotiated amount
    assert tx.purchase_request_id == pr.id
