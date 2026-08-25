import pytest
from decimal import Decimal
from backend.app.policy import PolicyEngine
from backend.app.models import Product, MerchantPolicy

def test_valid_purchase_approved():
    # Setup test models
    product = Product(
        name="Test Earbuds",
        price=Decimal("1599.00"),
        cost=Decimal("1200.00"),
        inventory=10,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("10.00"),
        min_margin_percent=Decimal("10.00"),
        max_auto_order_amount=Decimal("2000.00"),
        require_approval_above=Decimal("2000.00"),
        policy_version="v1.0",
        active=True
    )
    
    # Proposing price 1599.00 for quantity 1 (0% discount, 24.95% margin)
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("1599.00"), buyer_budget=Decimal("2000.00"))
    assert result["decision"] == "APPROVED"
    assert len(result["reasons"]) == 0
    assert result["discount_percent"] == Decimal("0")
    assert result["calculated_margin_percent"] > Decimal("10.00")


def test_excessive_discount_blocked():
    product = Product(
        name="Test Earbuds",
        price=Decimal("1599.00"),
        cost=Decimal("1000.00"),  # Cost is low, margin passes, but discount fails
        inventory=10,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("10.00"),
        min_margin_percent=Decimal("10.00"),
        max_auto_order_amount=Decimal("2000.00"),
        require_approval_above=Decimal("2000.00"),
        policy_version="v1.0",
        active=True
    )
    
    # Proposing total 1400.00 for quantity 1 (approx 12.44% discount > 10%)
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("1400.00"))
    assert result["decision"] == "BLOCKED"
    assert any("discount" in r.lower() for r in result["reasons"])


def test_insufficient_margin_blocked():
    product = Product(
        name="Test Earbuds",
        price=Decimal("1599.00"),
        cost=Decimal("1500.00"),  # Cost is high
        inventory=10,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("20.00"),
        min_margin_percent=Decimal("10.00"),
        max_auto_order_amount=Decimal("2000.00"),
        require_approval_above=Decimal("2000.00"),
        policy_version="v1.0",
        active=True
    )
    
    # Proposing total 1550.00 for quantity 1 (margin ~ 3.22% < 10%)
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("1550.00"))
    assert result["decision"] == "BLOCKED"
    assert any("margin" in r.lower() for r in result["reasons"])


def test_budget_exceeded_blocked():
    product = Product(
        name="Test Earbuds",
        price=Decimal("1599.00"),
        cost=Decimal("1200.00"),
        inventory=10,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("10.00"),
        min_margin_percent=Decimal("10.00"),
        max_auto_order_amount=Decimal("2000.00"),
        require_approval_above=Decimal("2000.00"),
        policy_version="v1.0",
        active=True
    )
    
    # Proposed amount 1599.00 exceeds buyer budget of 1500.00
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("1599.00"), buyer_budget=Decimal("1500.00"))
    assert result["decision"] == "BLOCKED"
    assert any("budget" in r.lower() for r in result["reasons"])


def test_transaction_above_auto_limit_requires_approval():
    product = Product(
        name="Premium Soundbar",
        price=Decimal("5000.00"),
        cost=Decimal("3500.00"),
        inventory=10,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("10.00"),
        min_margin_percent=Decimal("10.00"),
        max_auto_order_amount=Decimal("2000.00"),  # max ₹2000 auto limit
        require_approval_above=Decimal("2000.00"),
        policy_version="v1.0",
        active=True
    )
    
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("4500.00"))
    assert result["decision"] == "REQUIRES_APPROVAL"
    assert any("auto transaction limit" in r.lower() for r in result["reasons"])


def test_out_of_stock_blocked():
    product = Product(
        name="Out of Stock Charger",
        price=Decimal("499.00"),
        cost=Decimal("350.00"),
        inventory=0,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("10.00"),
        min_margin_percent=Decimal("10.00"),
        max_auto_order_amount=Decimal("2000.00"),
        require_approval_above=Decimal("2000.00"),
        policy_version="v1.0",
        active=True
    )
    
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("499.00"))
    assert result["decision"] == "BLOCKED"
    assert any("inventory" in r.lower() for r in result["reasons"])


def test_bundle_purchase_approved():
    # Setup test models matching the exact bundle scenario
    # Component 1: Earbuds (Price: 1599, Cost: 1050)
    # Component 2: Charging Case (Price: 399, Cost: 200)
    # Bundle Product: Price: 1998 (1599 + 399), Cost: 1250 (1050 + 200)
    product = Product(
        name="Earbuds & Charging Case Bundle",
        price=Decimal("1998.00"),
        cost=Decimal("1250.00"),
        inventory=20,
        active=True
    )
    policy = MerchantPolicy(
        max_discount_percent=Decimal("10.00"),
        min_margin_percent=Decimal("20.00"),
        max_auto_order_amount=Decimal("2000.00"),
        require_approval_above=Decimal("2000.00"),
        policy_version="policy_v1.0",
        active=True
    )
    
    # Proposing price 1899.00 for quantity 1
    # 1. Original amount = 1998
    # 2. Final amount = 1899
    # 3. Discount percentage = ((1998 - 1899) / 1998) * 100 = 4.95495%
    # 4. Total cost = 1250
    # 5. Margin percentage = ((1899 - 1250) / 1899) * 100 = 34.175882...%
    result = PolicyEngine.evaluate(product, policy, 1, Decimal("1899.00"), buyer_budget=Decimal("2000.00"))
    
    assert result["decision"] == "APPROVED"
    assert len(result["reasons"]) == 0
    assert float(result["discount_percent"]) == pytest.approx(4.95495, abs=1e-3)
    assert float(result["calculated_margin_percent"]) == pytest.approx(34.176, abs=1e-3)

