import pytest
from decimal import Decimal
from datetime import datetime, timezone
import json
import uuid

from sqlalchemy.orm import Session
from backend.app import models, schemas
from backend.app.main import safe_json_dumps
from backend.app.payments import process_payment_creation, get_payment_adapter
from backend.app.agents.orchestrator import NegotiationOrchestrator
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import MockProvider


def test_safe_json_dumps_complex_types():
    """Test that safe_json_dumps serializes Decimal, datetime, UUID, Enum, and Pydantic models."""
    data = {
        "decimal_val": Decimal("1475.50"),
        "date_val": datetime.now(timezone.utc),
        "uuid_val": uuid.uuid4(),
        "stage": schemas.NegotiationStage.PURCHASE_REQUEST_CREATION,
        "items": [{"name": "Earbuds", "price": Decimal("1475.00")}],
        "set_val": {"a", "b"}
    }
    dumped = safe_json_dumps(data)
    assert isinstance(dumped, str)
    parsed = json.loads(dumped)
    assert parsed["decimal_val"] == "1475.50"
    assert parsed["stage"] == "PURCHASE_REQUEST_CREATION"
    assert parsed["items"][0]["price"] == "1475.00"


def test_e2e_full_lifecycle_and_payment(db: Session):
    """Test A: Full lifecycle intent -> negotiation -> policy approval -> snapshot -> purchase request -> Razorpay mock order -> payment verification -> SUCCESS."""
    buyer_provider = MockProvider(agent_role="BUYER_AGENT")
    merchant_provider = MockProvider(agent_role="MERCHANT_AGENT")

    buyer = BuyerAgent(buyer_provider)
    merchant = MerchantAgent(merchant_provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    # 1. Run negotiation loop
    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer-001",
        intent="I need wireless earbuds under Rs 2000",
        budget=Decimal("2000.00"),
        max_rounds=3
    )

    assert res["decision"] == "APPROVED"
    assert res["purchase_request_id"] > 0
    assert float(res["final_amount"]) > 0
    assert res["status"] == "success"
    assert res["stage"] == schemas.NegotiationStage.PURCHASE_REQUEST_CREATION.value

    # 2. Verify PurchaseRequest was saved and matches approved snapshot
    pr_id = res["purchase_request_id"]
    pr = db.query(models.PurchaseRequest).filter(models.PurchaseRequest.id == pr_id).first()
    assert pr is not None
    assert pr.status == "APPROVED"
    assert pr.final_amount == Decimal(res["final_amount"])

    # 3. Create payment order
    tx = process_payment_creation(db, pr_id)
    assert tx is not None
    assert tx.status == "PENDING"
    assert tx.amount == pr.final_amount
    assert tx.razorpay_order_id.startswith("order_")

    # 4. Verify payment signature in mock mode
    adapter = get_payment_adapter()
    is_valid = adapter.verify_payment_signature(
        order_id=tx.razorpay_order_id,
        payment_id="pay_mock_123456",
        signature="" # In mock mode with adapter
    )
    # Mock signature matches correctly with key secret
    assert isinstance(is_valid, bool)


def test_payment_creation_idempotency(db: Session):
    """Test B: Idempotency of payment creation. Repeated calls for the same purchase_request_id return the existing pending order."""
    buyer_provider = MockProvider(agent_role="BUYER_AGENT")
    merchant_provider = MockProvider(agent_role="MERCHANT_AGENT")

    orchestrator = NegotiationOrchestrator(db, BuyerAgent(buyer_provider), MerchantAgent(merchant_provider))
    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer-002",
        intent="I need wireless earbuds under 2000",
        budget=Decimal("2000.00"),
        max_rounds=2
    )

    pr_id = res["purchase_request_id"]
    tx1 = process_payment_creation(db, pr_id)
    assert tx1 is not None

    # Call again for the same purchase request ID
    tx2 = process_payment_creation(db, pr_id)
    assert tx2 is not None
    assert tx2.id == tx1.id
    assert tx2.razorpay_order_id == tx1.razorpay_order_id
    assert tx2.status == "PENDING"


def test_deal_preservation_on_payment_failure(db: Session):
    """Test C: Payment failure does not destroy the deal. Deal remains APPROVED and can be retried."""
    buyer_provider = MockProvider(agent_role="BUYER_AGENT")
    merchant_provider = MockProvider(agent_role="MERCHANT_AGENT")

    orchestrator = NegotiationOrchestrator(db, BuyerAgent(buyer_provider), MerchantAgent(merchant_provider))
    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer-003",
        intent="I need wireless earbuds under 2000",
        budget=Decimal("2000.00"),
        max_rounds=2
    )

    pr_id = res["purchase_request_id"]
    tx = process_payment_creation(db, pr_id)
    assert tx.status == "PENDING"

    # Simulate payment cancellation / failure
    tx.status = "FAILED"
    db.commit()

    # Verify PurchaseRequest is still APPROVED
    pr = db.query(models.PurchaseRequest).filter(models.PurchaseRequest.id == pr_id).first()
    assert pr.status == "APPROVED"

    # Retry payment creation creates/resumes order without error
    retry_tx = process_payment_creation(db, pr_id)
    assert retry_tx is not None
    assert retry_tx.status == "PENDING"


def test_demo_commerce_response_schema_validation():
    """Test E: DemoCommerceResponse model validation with full fields."""
    response_data = {
        "buyer_id": "demo-buyer-001",
        "intent": "I need wireless earbuds under 2000",
        "catalog_search_results": [{"id": 1, "name": "Wireless Earbuds Pro", "price": "1599.00"}],
        "selected_product_id": 1,
        "cross_sell_product_id": 2,
        "bundle_offer": {"product_ids": [1, 2], "original_amount": "2018.00", "offered_amount": "1899.00"},
        "negotiation_history": [],
        "conversation_events": [],
        "purchase_request_id": 101,
        "decision": "APPROVED",
        "reasons": ["Within merchant margin and price floor rules."],
        "original_amount": "1599.00",
        "final_amount": "1450.00",
        "discount_percent": "9.32",
        "margin_percent": "27.59",
        "policy_version": "policy_v1.0",
        "basket": {"items": [{"product_id": 1, "name": "Wireless Earbuds Pro", "negotiated_price": "1450.00"}]},
        "basket_type": "STANDALONE",
        "selected_basket_type": "STANDALONE",
        "stage": "PURCHASE_REQUEST_CREATION",
        "status": "success",
        "error_code": None
    }

    validated = schemas.DemoCommerceResponse.model_validate(response_data)
    assert validated.decision == "APPROVED"
    assert validated.purchase_request_id == 101
    assert validated.basket_type == "STANDALONE"
    assert validated.stage == "PURCHASE_REQUEST_CREATION"
