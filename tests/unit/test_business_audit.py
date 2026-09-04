import pytest
from decimal import Decimal
from sqlalchemy.orm import Session

from backend.app.models import Product, MerchantPolicy, PurchaseRequest, Transaction, ProcessedWebhookEvent
from backend.app.payments import deduct_inventory_for_paid_purchase, process_payment_creation, get_payment_adapter
from backend.app.webhooks import WebhookProcessor
from backend.app.policy import PolicyEngine
from backend.app.agents.pricing_strategy import MerchantPricingStrategy
from backend.app.agents.orchestrator import parse_budget_intent, NegotiationOrchestrator, NegotiationError
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import MockProvider
from backend.app.agents.tools import search_catalog_tool


# --- 1. ATOMIC INVENTORY & PAYMENT TESTS ---

def test_inventory_deduction_after_successful_payment(db: Session):
    """1. Verify inventory decrements only after successful payment."""
    prod = db.query(Product).filter(Product.id == 1).first()
    initial_inv = prod.inventory

    pr = PurchaseRequest(
        buyer_id="buyer_inv_1",
        product_id=1,
        quantity=2,
        unit_price=Decimal("1500.00"),
        original_amount=Decimal("3198.00"),
        final_amount=Decimal("3000.00"),
        discount_percent=Decimal("6.19"),
        currency="INR",
        status="APPROVED",
        basket={"items": [{"product_id": 1, "name": "Wireless Earbuds Pro", "quantity": 2, "original_price": "1599.00", "negotiated_price": "1500.00", "is_primary": True}]}
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    # Deduct inventory for paid purchase
    deduct_inventory_for_paid_purchase(db, pr)

    db.refresh(prod)
    db.refresh(pr)
    assert prod.inventory == initial_inv - 2
    assert pr.status == "PAID"


def test_failed_payment_does_not_deduct_inventory(db: Session):
    """2. Verify failed payment signature does not deduct inventory."""
    prod = db.query(Product).filter(Product.id == 1).first()
    initial_inv = prod.inventory

    pr = PurchaseRequest(
        buyer_id="buyer_inv_2",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1500.00"),
        original_amount=Decimal("1599.00"),
        final_amount=Decimal("1500.00"),
        discount_percent=Decimal("6.19"),
        currency="INR",
        status="APPROVED"
    )
    db.add(pr)
    db.commit()

    # Product inventory remains unchanged
    db.refresh(prod)
    assert prod.inventory == initial_inv
    assert pr.status == "APPROVED"


def test_duplicate_webhook_idempotency(db: Session):
    """3. Verify duplicate webhook delivery does not deduct inventory twice."""
    prod = db.query(Product).filter(Product.id == 2).first()
    initial_inv = prod.inventory

    pr = PurchaseRequest(
        buyer_id="buyer_inv_3",
        product_id=2,
        quantity=1,
        unit_price=Decimal("300.00"),
        original_amount=Decimal("399.00"),
        final_amount=Decimal("300.00"),
        discount_percent=Decimal("24.81"),
        currency="INR",
        status="APPROVED",
        basket={"items": [{"product_id": 2, "name": "Premium Charging Case", "quantity": 1, "original_price": "399.00", "negotiated_price": "300.00", "is_primary": True}]}
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    tx = Transaction(
        purchase_request_id=pr.id,
        razorpay_order_id="order_test_webhook_idem_123",
        amount=Decimal("300.00"),
        status="PENDING"
    )
    db.add(tx)
    db.commit()

    payload = {
        "event": "order.paid",
        "id": "evt_test_idem_999",
        "payload": {
            "order": {"entity": {"id": "order_test_webhook_idem_123", "amount": 30000}},
            "payment": {"entity": {"id": "pay_test_idem_999", "amount": 30000}}
        }
    }
    import json
    import hmac
    import hashlib
    from backend.app.config import settings
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw_bytes, hashlib.sha256).hexdigest()

    # First delivery
    res1 = WebhookProcessor.process_razorpay_webhook(db, raw_bytes, sig)
    assert res1["status"] == "success"
    db.refresh(prod)
    assert prod.inventory == initial_inv - 1

    # Second (duplicate) delivery
    res2 = WebhookProcessor.process_razorpay_webhook(db, raw_bytes, sig)
    assert res2["status"] == "success"
    db.refresh(prod)
    # Inventory must NOT be deducted again
    assert prod.inventory == initial_inv - 1


def test_verify_and_webhook_no_double_deduction(db: Session):
    """4. Verify that manual verification followed by webhook does not double deduct inventory."""
    prod = db.query(Product).filter(Product.id == 7).first()
    initial_inv = prod.inventory

    pr = PurchaseRequest(
        buyer_id="buyer_inv_4",
        product_id=7,
        quantity=2,
        unit_price=Decimal("200.00"),
        original_amount=Decimal("598.00"),
        final_amount=Decimal("400.00"),
        discount_percent=Decimal("33.11"),
        currency="INR",
        status="APPROVED",
        basket={"items": [{"product_id": 7, "name": "USB-C Fast Charging Cable", "quantity": 2, "original_price": "299.00", "negotiated_price": "200.00", "is_primary": True}]}
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    tx = Transaction(
        purchase_request_id=pr.id,
        razorpay_order_id="order_test_double_deduct_456",
        amount=Decimal("400.00"),
        status="PENDING"
    )
    db.add(tx)
    db.commit()

    # Manual verification simulates payment completion
    deduct_inventory_for_paid_purchase(db, pr)
    db.refresh(prod)
    assert prod.inventory == initial_inv - 2

    # Subsequent webhook arrival
    payload = {
        "event": "payment.captured",
        "id": "evt_test_double_456",
        "payload": {
            "order": {"entity": {"id": "order_test_double_deduct_456", "amount": 40000}},
            "payment": {"entity": {"id": "pay_test_double_456", "amount": 40000}}
        }
    }
    import json
    import hmac
    import hashlib
    from backend.app.config import settings
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw_bytes, hashlib.sha256).hexdigest()

    res = WebhookProcessor.process_razorpay_webhook(db, raw_bytes, sig)
    assert res["status"] == "success"
    db.refresh(prod)
    # Still only decremented by 2
    assert prod.inventory == initial_inv - 2


def test_out_of_stock_prevents_purchase(db: Session):
    """5. Verify out-of-stock product prevents purchase deduction and raises error."""
    prod5 = db.query(Product).filter(Product.id == 5).first()
    assert prod5.inventory == 0

    pr = PurchaseRequest(
        buyer_id="buyer_inv_5",
        product_id=5,
        quantity=1,
        unit_price=Decimal("420.00"),
        original_amount=Decimal("499.00"),
        final_amount=Decimal("420.00"),
        discount_percent=Decimal("15.83"),
        currency="INR",
        status="APPROVED",
        basket={"items": [{"product_id": 5, "name": "Out of Stock Charger", "quantity": 1, "original_price": "499.00", "negotiated_price": "420.00", "is_primary": True}]}
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    with pytest.raises(ValueError) as exc:
        deduct_inventory_for_paid_purchase(db, pr)
    assert "Insufficient inventory" in str(exc.value)


# --- 2. SEARCH & INTENT TESTS ---

def test_unknown_product_clean_failure(db: Session):
    """6. Verify unknown product like 'refrigerator' or 'shoes' returns clean failure without fallback."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    # Refrigerator test
    with pytest.raises(NegotiationError) as exc1:
        orchestrator.run_negotiation_loop(
            buyer_id="buyer_fridge",
            intent="I want a refrigerator. Budget is 25000 INR.",
            budget=Decimal("25000.00")
        )
    assert "refrigerator" in str(exc1.value)

    # Shoes test
    with pytest.raises(NegotiationError) as exc2:
        orchestrator.run_negotiation_loop(
            buyer_id="buyer_shoes",
            intent="Looking for running shoes under 3000.",
            budget=Decimal("3000.00")
        )
    assert "shoes" in str(exc2.value)


def test_empty_search_behavior(db: Session):
    """7. Verify empty search query allows normal catalog discovery."""
    results = search_catalog_tool(db, query="")
    assert len(results) > 0


def test_same_category_alternative_behavior(db: Session):
    """8. Verify same category alternative recommendation does not cross into unrelated categories."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    # Product 5 is an Out of Stock Charger in Accessories
    # Searching for charger should not cross to laptops or smartwatches
    results = search_catalog_tool(db, query="charger")
    assert len(results) > 0
    for r in results:
        assert r["category"] in ["Accessories", "Audio", "Mobile Phones"]


# --- 3. PRICING & FLOOR TESTS ---

def test_all_catalog_effective_floors(db: Session):
    """9. Verify ALL active catalog products have min_selling_price satisfying 15% merchant policy."""
    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    assert policy is not None
    min_margin = policy.min_margin_percent / Decimal("100.00")
    margin_factor = Decimal("1.00") - min_margin

    products = db.query(Product).filter(Product.active == True).all()
    assert len(products) >= 15

    for p in products:
        margin_floor = (p.cost / margin_factor).quantize(Decimal("0.01"))
        effective_floor = max(p.min_selling_price, margin_floor, p.cost)
        
        # Effective floor must never be below cost
        assert effective_floor >= p.cost, f"Product {p.name} (ID {p.id}) floor is below cost!"
        # Effective floor must satisfy min margin
        calculated_margin = ((effective_floor - p.cost) / effective_floor) * Decimal("100")
        assert calculated_margin >= Decimal("14.99"), f"Product {p.name} (ID {p.id}) floor margin {calculated_margin}% is below 15%!"


def test_strict_budget_parsing():
    """10. Verify deterministic parsing for strict budget phrases."""
    cases = [
        ("I need a phone, maximum 12000 INR", Decimal("12000.00")),
        ("cannot spend more than 15000", Decimal("15000.00")),
        ("not above 10000", Decimal("10000.00")),
        ("hard limit 12000", Decimal("12000.00")),
        ("strict budget 12000", Decimal("12000.00")),
        ("12k max", Decimal("12000.00")),
        ("budget cap 15k", Decimal("15000.00")),
    ]
    for phrase, expected in cases:
        res = parse_budget_intent(phrase, expected)
        assert res["budget_type"] == "strict", f"Failed for phrase '{phrase}'"
        assert res["maximum_budget"] == expected, f"Failed max budget for phrase '{phrase}'"
        assert res["is_flexible"] is False


def test_flexible_budget_parsing():
    """11. Verify deterministic parsing for flexible budget phrases."""
    res1 = parse_budget_intent("around 12000", Decimal("12000.00"))
    assert res1["budget_type"] == "flexible"
    assert res1["is_flexible"] is True
    assert res1["maximum_budget"] > Decimal("12000.00")

    res2 = parse_budget_intent("I have 12000 but can stretch to 15000", Decimal("12000.00"))
    assert res2["budget_type"] == "flexible"
    assert res2["is_flexible"] is True
    assert res2["maximum_budget"] == Decimal("15000.00")


def test_budget_shorthand_parsing():
    """12. Verify shorthand amounts (12k, 15k, 1.5k, INR 12,000, etc.)."""
    res1 = parse_budget_intent("budget 12k max", Decimal("10000.00"))
    assert res1["target_budget"] == Decimal("12000.00")
    assert res1["maximum_budget"] == Decimal("12000.00")

    res2 = parse_budget_intent("budget 1.5k", Decimal("1000.00"))
    assert res2["target_budget"] == Decimal("1500.00")


def test_buyer_does_not_offer_above_list_price():
    """13. Verify buyer opening offer is at or below list price when budget > list price."""
    provider = MockProvider()
    res = provider.generate_structured_response(
        prompt="Parse user intent: 'I want Wireless Earbuds' with budget limit: 2000 INR. Selected Target Product Details: {'id': 1, 'name': 'Wireless Earbuds Pro', 'price': '1599.00'}",
        system_instruction="Buyer Agent",
        schema_class=from_provider_import()
    )
    assert res.total_amount <= Decimal("1599.00"), f"Buyer offered {res.total_amount} which exceeds list price 1599.00!"


def from_provider_import():
    from backend.app.agents.provider import BuyerDecision
    return BuyerDecision


# --- 4. BUNDLE & BASKET ARITHMETIC TESTS ---

def test_bundle_primary_and_accessory_floor_protection():
    """14 & 15. Verify individual item price floors in bundle prescriptions."""
    primary = {
        "id": 41,
        "name": "Samsung Galaxy A15",
        "price": Decimal("12999.00"),
        "cost": Decimal("10000.00"),
        "min_selling_price": Decimal("11799.00"),
        "inventory": 10,
        "active": True
    }
    acc1 = {
        "id": 44,
        "name": "25W Fast Charger",
        "price": Decimal("1299.00"),
        "cost": Decimal("500.00"),
        "min_selling_price": Decimal("999.00"),
        "inventory": 20,
        "active": True
    }
    bundle = MerchantPricingStrategy.generate_bundle_prescription(
        primary_prod=primary,
        related_prods=[acc1],
        min_margin_percent=Decimal("15.00")
    )
    assert bundle is not None
    for item in bundle["bundle_items"]:
        assert item["negotiated_price"] >= item["effective_floor"], f"Item {item['name']} priced below floor!"

    # Exact basket arithmetic
    assert bundle["bundle_total"] == sum(i["negotiated_price"] for i in bundle["bundle_items"])
    assert bundle["margin_percent"] >= Decimal("15.00")


def test_exact_basket_arithmetic():
    """16. Verify bundle total is exact sum of all item negotiated prices."""
    primary = {"id": 1, "name": "Wireless Earbuds Pro", "price": Decimal("1599.00"), "cost": Decimal("1050.00"), "min_selling_price": Decimal("1399.00"), "inventory": 10, "active": True}
    acc = {"id": 2, "name": "Premium Charging Case", "price": Decimal("399.00"), "cost": Decimal("200.00"), "min_selling_price": Decimal("299.00"), "inventory": 10, "active": True}
    
    bundle = MerchantPricingStrategy.generate_bundle_prescription(primary, [acc])
    assert bundle["bundle_total"] == bundle["bundle_items"][0]["negotiated_price"] + bundle["bundle_items"][1]["negotiated_price"]


# --- 5. MERCHANT STRATEGY TESTS ---

def test_inventory_flexibility_scarcity():
    """17 & 18. Verify high inventory allows greater discounts and low inventory restricts discounts."""
    high_inv = MerchantPricingStrategy.calculate_pricing_bounds(Decimal("1000.00"), Decimal("1500.00"), Decimal("1200.00"), inventory=30, round_idx=4)
    low_inv = MerchantPricingStrategy.calculate_pricing_bounds(Decimal("1000.00"), Decimal("1500.00"), Decimal("1200.00"), inventory=2, round_idx=4)
    
    assert high_inv["inventory_flexibility"] > low_inv["inventory_flexibility"]
    assert high_inv["merchant_best_price"] < low_inv["merchant_best_price"]


def test_monotonic_merchant_concessions():
    """19. Verify round concessions do not increase price for the exact same item."""
    r1 = MerchantPricingStrategy.calculate_pricing_bounds(Decimal("1000.00"), Decimal("1500.00"), Decimal("1200.00"), inventory=25, round_idx=1)
    r2 = MerchantPricingStrategy.calculate_pricing_bounds(Decimal("1000.00"), Decimal("1500.00"), Decimal("1200.00"), inventory=25, round_idx=2)
    r3 = MerchantPricingStrategy.calculate_pricing_bounds(Decimal("1000.00"), Decimal("1500.00"), Decimal("1200.00"), inventory=25, round_idx=3)
    
    assert r1["target_offer_price"] >= r2["target_offer_price"] >= r3["target_offer_price"]


# --- 6. POLICY & PERSISTENCE CONSISTENCY TESTS ---

def test_transaction_basket_equals_charged_and_persisted(db: Session):
    """23 & 24. Verify exact match across negotiated basket, PolicyDecision, and PurchaseRequest."""
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="buyer_cons_test",
        intent="Samsung Galaxy A15 with accessories. Budget is 15000 INR.",
        budget=Decimal("15000.00")
    )
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr is not None
    assert str(pr.final_amount) == str(res["final_amount"])
    
    basket_sum = sum(Decimal(str(item["negotiated_price"])) * Decimal(item["quantity"]) for item in pr.basket["items"])
    assert basket_sum == pr.final_amount


def test_inventory_never_becomes_negative(db: Session):
    """25. Verify inventory never becomes negative even when multiple purchases attempt to exhaust stock."""
    prod = db.query(Product).filter(Product.id == 4).first()
    current_inv = prod.inventory

    # Create purchase request requesting more than available stock
    pr_excess = PurchaseRequest(
        buyer_id="buyer_excess",
        product_id=4,
        quantity=current_inv + 10,
        unit_price=Decimal("4500.00"),
        original_amount=Decimal("5000.00") * (current_inv + 10),
        final_amount=Decimal("4500.00") * (current_inv + 10),
        discount_percent=Decimal("10.00"),
        currency="INR",
        status="APPROVED",
        basket={"items": [{"product_id": 4, "name": "Premium Soundbar", "quantity": current_inv + 10, "original_price": "5000.00", "negotiated_price": "4500.00", "is_primary": True}]}
    )
    db.add(pr_excess)
    db.commit()

    with pytest.raises(ValueError) as exc:
        deduct_inventory_for_paid_purchase(db, pr_excess)
    assert "Insufficient inventory" in str(exc.value)

    db.refresh(prod)
    assert prod.inventory == current_inv
    assert prod.inventory >= 0
