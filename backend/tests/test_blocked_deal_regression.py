import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from backend.app.models import Product, MerchantPolicy, PurchaseRequest, PolicyDecision
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import (
    MockProvider,
    BuyerDecision,
    MerchantDecision,
    BasketItemSchema,
    ProviderExecutionMetadata
)
from backend.app.payments import process_payment_creation, MockRazorpayAdapter, RazorpayAdapter
from backend.app.policy import PolicyEngine


class CustomBuyerProvider(MockProvider):
    def __init__(self, action="OFFER", total_amount=Decimal("500.00"), product_id=1, basket_items=None):
        super().__init__(agent_role="buyer")
        self.call_count = 0
        self.custom_action = action
        self.custom_total = Decimal(str(total_amount))
        self.custom_product_id = product_id
        self.custom_basket_items = basket_items or [
            BasketItemSchema(
                product_id=product_id,
                name="Wireless Earbuds Pro",
                quantity=1,
                original_price=Decimal("1599.00"),
                negotiated_price=self.custom_total,
                is_primary=True
            )
        ]

    def generate_structured_response(self, prompt: str, system_instruction: str, schema_class):
        self.call_count += 1
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used="custom_mock",
            provider_type="mock",
            model_name="mock-model",
            agent_role="BUYER_AGENT",
            fallback_used=False,
            fallback_depth=0,
            response_latency_ms=10.0
        )
        return BuyerDecision(
            action=self.custom_action,
            product_id=self.custom_product_id,
            unit_price=self.custom_total,
            quantity=1,
            total_amount=self.custom_total,
            rationale="Custom buyer test offer.",
            message=f"I offer ₹{self.custom_total}.",
            basket_items=self.custom_basket_items
        )


def test_blocked_negotiation_does_not_produce_zero_final_price(db):
    """Test 1 & 2: Blocked negotiation serializes final_amount as None/null, not '0.00' or ₹0."""
    # Buyer lowballs below merchant floor and budget limit rejection occurs
    buyer_p = CustomBuyerProvider(action="OFFER", total_amount=Decimal("50.00"))
    merchant_p = MockProvider(agent_role="merchant")

    buyer = BuyerAgent(provider=buyer_p)
    merchant = MerchantAgent(provider=merchant_p)
    orchestrator = NegotiationOrchestrator(db=db, buyer=buyer, merchant=merchant)

    # Force rejection
    try:
        res = orchestrator.run_negotiation_loop(
            buyer_id="buyer_blocked_test",
            intent="I want earbuds for 50 rs",
            budget=Decimal("100.00"),
            max_rounds=1
        )
    except NegotiationError as e:
        res = e.result_data

    assert res is not None
    assert res["decision"] in ["BLOCKED", "REJECTED"]
    assert res["final_amount"] is None
    assert res["discount_percent"] is None
    assert res["margin_percent"] is None
    assert len(res["reasons"]) > 0


def test_razorpay_order_creation_impossible_for_blocked_deal(db):
    """Test 3: Razorpay order creation is impossible when decision != APPROVED."""
    # Create PurchaseRequest in BLOCKED status
    pr = PurchaseRequest(
        buyer_id="blocked_buyer",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1499.00"),
        discount_percent=Decimal("6.25"),
        currency="INR",
        reason="Blocked deal test",
        status="BLOCKED"
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    dec = PolicyDecision(
        purchase_request_id=pr.id,
        decision="BLOCKED",
        reasons=["Merchant margin constraint violated"],
        policy_version="policy_v1.0",
        calculated_margin_percent=Decimal("5.00"),
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1499.00"),
        discount_percent=Decimal("6.25"),
        currency="INR"
    )
    db.add(dec)
    db.commit()

    with pytest.raises(PermissionError) as exc_info:
        process_payment_creation(db=db, purchase_request_id=pr.id)
    assert "APPROVED" in str(exc_info.value)


def test_razorpay_order_creation_rejects_amount_lte_zero(db):
    """Test 4: Razorpay order creation strictly rejects amount <= 0."""
    pr = PurchaseRequest(
        buyer_id="zero_buyer",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("0.00"),
        discount_percent=Decimal("100.00"),
        currency="INR",
        reason="Zero amount deal test",
        status="APPROVED"
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    dec = PolicyDecision(
        purchase_request_id=pr.id,
        decision="APPROVED",
        reasons=["Test override"],
        policy_version="policy_v1.0",
        calculated_margin_percent=Decimal("30.00"),
        product_id=1,
        quantity=1,
        unit_price=Decimal("1599.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("0.00"),
        discount_percent=Decimal("100.00"),
        currency="INR"
    )
    db.add(dec)
    db.commit()

    with pytest.raises(ValueError) as exc_info:
        process_payment_creation(db=db, purchase_request_id=pr.id)
    assert "positive" in str(exc_info.value) or "zero" in str(exc_info.value)

    # Also test adapter direct call
    mock_adapter = MockRazorpayAdapter("secret", "webhook")
    with pytest.raises(ValueError):
        mock_adapter.create_order(Decimal("0.00"), "rcpt_1")

    with pytest.raises(ValueError):
        mock_adapter.create_order(Decimal("-10.00"), "rcpt_2")


def test_valid_approved_negotiation_has_real_positive_price(db):
    """Test 5: APPROVED negotiation retains real positive final price."""
    buyer = BuyerAgent(provider=MockProvider(agent_role="buyer"))
    merchant = MerchantAgent(provider=MockProvider(agent_role="merchant"))
    orchestrator = NegotiationOrchestrator(db=db, buyer=buyer, merchant=merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="buyer_valid_appr",
        intent="I want Wireless Earbuds Pro for 1499",
        budget=Decimal("2000.00"),
        max_rounds=3
    )

    assert res["decision"] == "APPROVED"
    assert Decimal(str(res["final_amount"])) > Decimal("0.00")
    assert Decimal(str(res["final_amount"])) >= Decimal("1440.00")  # Floor respected


def test_invalid_bundle_does_not_produce_zero_as_valid_transaction(db):
    """Test 7: An invalid bundle (e.g. non-existent items or negative margin) terminates with BLOCKED and None amount."""
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    
    # Evaluate a broken basket where items have 0 cost or impossible margin
    broken_basket = {
        "items": [
            {
                "product_id": 99999,  # Non-existent
                "name": "Ghost Item",
                "quantity": 1,
                "original_price": "100.00",
                "negotiated_price": "10.00",
                "is_primary": True
            }
        ],
        "original_total": "100.00",
        "final_total": "10.00",
        "discount_amount": "90.00"
    }

    eval_res = PolicyEngine.evaluate_basket(broken_basket, policy, Decimal("1000.00"), 1, db)
    assert eval_res["decision"] == "BLOCKED"
    assert len(eval_res["reasons"]) > 0


def test_bundle_inventory_failure_produces_deterministic_block(db):
    """Test 8: Bundle accessory out-of-stock produces deterministic policy block reason."""
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    
    # Temporarily set case inventory to 0
    case_prod = db.query(Product).filter(Product.id == 2).first()
    orig_inv = case_prod.inventory
    try:
        case_prod.inventory = 0
        db.commit()

        bundle_basket = {
            "items": [
                {
                    "product_id": 1,
                    "name": "Wireless Earbuds Pro",
                    "quantity": 1,
                    "original_price": "1599.00",
                    "negotiated_price": "1500.00",
                    "is_primary": True
                },
                {
                    "product_id": 2,
                    "name": "Charging Case",
                    "quantity": 1,
                    "original_price": "399.00",
                    "negotiated_price": "399.00",
                    "is_primary": False
                }
            ],
            "original_total": "1998.00",
            "final_total": "1899.00",
            "discount_amount": "99.00"
        }

        eval_res = PolicyEngine.evaluate_basket(bundle_basket, policy, Decimal("2000.00"), 1, db)
        assert eval_res["decision"] == "BLOCKED"
        assert any("inventory" in r.lower() or "out of stock" in r.lower() or "available" in r.lower() for r in eval_res["reasons"])
    finally:
        case_prod.inventory = orig_inv
        db.commit()


def test_bundle_margin_failure_produces_deterministic_block(db):
    """Test 9: Extreme bundle discount violating margin threshold produces deterministic block."""
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    
    # Propose ₹1,000 for earbuds + case (total cost is 1050 + 200 = 1250)
    bundle_basket = {
        "items": [
            {
                "product_id": 1,
                "name": "Wireless Earbuds Pro",
                "quantity": 1,
                "original_price": "1599.00",
                "negotiated_price": "800.00",
                "is_primary": True
            },
            {
                "product_id": 2,
                "name": "Charging Case",
                "quantity": 1,
                "original_price": "399.00",
                "negotiated_price": "200.00",
                "is_primary": False
            }
        ],
        "original_total": "1998.00",
        "final_total": "1000.00",
        "discount_amount": "998.00"
    }

    eval_res = PolicyEngine.evaluate_basket(bundle_basket, policy, Decimal("2000.00"), 1, db)
    assert eval_res["decision"] == "BLOCKED"
    assert any("margin" in r.lower() or "floor" in r.lower() for r in eval_res["reasons"])
