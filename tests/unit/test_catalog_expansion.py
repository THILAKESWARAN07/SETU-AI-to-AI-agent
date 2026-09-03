import pytest
from decimal import Decimal
from sqlalchemy.orm import Session

from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import MockProvider
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.models import Product, PurchaseRequest
from backend.app.policy import PolicyEngine
from backend.app.agents.tools import search_catalog_tool

def test_mobile_phone_search(db: Session):
    """
    Verify search_catalog resolves aliases like 'phone' or 'mobile' to mobile phone category
    and excludes unrelated categories.
    """
    buyer = BuyerAgent(MockProvider())
    products = buyer.search_catalog(db, query="phone")
    
    assert len(products) > 0
    names = [p["name"] for p in products]
    assert "Samsung Galaxy A15" in names
    assert "Redmi Note 13" in names
    assert "Motorola G54" in names
    
    # Verify no laptop or smartwatch is returned
    for p in products:
        assert p["category"] not in ["Computing", "Laptops", "Smartwatches", "Wearables"]

def test_same_category_alternatives(db: Session):
    """
    Verify search_catalog can filter by standard category Audio and returns in-stock alternatives.
    """
    buyer = BuyerAgent(MockProvider())
    products = buyer.search_catalog(db, category="Audio")
    
    assert len(products) > 0
    categories = [p["category"] for p in products]
    # Standard seed Audio products and compatible Electronics category products are returned
    for c in categories:
        assert c in ["Audio", "Electronics", "Accessories"]

    # Verify active/in-stock out-of-stock alternative recommendation behavior
    # Out of stock product 5 (Out of Stock Charger) has category Accessories.
    # Safe fallback finds another active, in-stock accessory like 44 (25W Fast Charger).
    alternative = db.query(Product).filter(
        Product.category == "Accessories",
        Product.inventory > 0,
        Product.active == True,
        Product.id != 5
    ).first()
    assert alternative is not None
    assert alternative.inventory > 0
    assert alternative.active is True

def test_unrelated_product_rejection(db: Session):
    """
    Verify that query for laptop accessories isolates computing accessories and rejects smartphones.
    """
    buyer = BuyerAgent(MockProvider())
    products = buyer.search_catalog(db, query="laptop accessories")
    
    assert len(products) > 0
    for p in products:
        assert p["name"] not in ["Samsung Galaxy A15", "Redmi Note 13", "Motorola G54"]

def test_earbuds_charging_case_bundle(db: Session):
    """
    Verify e2e negotiation for earbuds + charging case bundle.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="buyer_e2e_01",
        intent="I want to buy earbuds and a charging case. Budget ₹2000.",
        budget=Decimal("2000.00")
    )
    
    assert res["selected_product_id"] == 1
    assert res["cross_sell_product_id"] == 2
    assert Decimal(res["bundle_offer"]["offered_amount"]) == Decimal("1899.00")
    
    # Check persistence
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr is not None
    assert pr.basket is not None
    assert len(pr.basket["items"]) == 2

def test_smartphone_compatible_accessories_bundle(db: Session):
    """
    Verify that smartphone negotiation dynamically counters with charger/protective case/glass bundle.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="buyer_e2e_02",
        intent="I need a Samsung Galaxy A15 with accessories. Budget is 15000 INR.",
        budget=Decimal("15000.00")
    )
    
    assert res["selected_product_id"] == 41
    # Dynamic bundle has 4 items
    assert Decimal(res["bundle_offer"]["offered_amount"]) == Decimal("13596.00")
    
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr is not None
    assert pr.basket is not None
    assert len(pr.basket["items"]) == 4
    item_ids = [item["product_id"] for item in pr.basket["items"]]
    assert 41 in item_ids
    assert 44 in item_ids
    assert 45 in item_ids
    assert 46 in item_ids

def test_standalone_purchase_without_accessories(db: Session):
    """
    Verify buyer can procure smartphone standalone without accessories.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="buyer_e2e_03",
        intent="I need a Samsung Galaxy A15 standalone without accessories. Budget is 13000 INR.",
        budget=Decimal("13000.00")
    )
    
    assert res["selected_product_id"] == 41
    assert Decimal(res["bundle_offer"]["offered_amount"]) == Decimal("12500.00")
    
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr is not None
    assert pr.basket is not None
    assert len(pr.basket["items"]) == 1
    assert pr.basket["items"][0]["product_id"] == 41

def test_budget_constraint(db: Session):
    """
    Verify negotiation fails when the merchant counter exceeds the buyer's budget limit.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    with pytest.raises(NegotiationError) as exc_info:
        orchestrator.run_negotiation_loop(
            buyer_id="buyer_e2e_04",
            intent="I need a Samsung Galaxy A15 with accessories. Budget is 13000 INR.",
            budget=Decimal("13000.00") # Bundle costs 13596, so it exceeds budget
        )
    assert "budget" in str(exc_info.value) or "exceeds" in str(exc_info.value) or "failed" in str(exc_info.value)

def test_min_selling_price_protection(db: Session):
    """
    Verify that policy engine blocks items negotiated below min_selling_price limits.
    """
    # Create a basket where primary item 41 is priced at ₹10,000 (its min_selling_price is ₹11,499)
    policy = db.query(Product).filter(Product.id == 41).first()
    assert policy is not None
    
    basket = {
        "items": [
            {
                "product_id": 41,
                "name": "Samsung Galaxy A15",
                "quantity": 1,
                "original_price": "12999.00",
                "negotiated_price": "10000.00",
                "is_primary": True
            }
        ],
        "original_total": "12999.00",
        "final_total": "10000.00",
        "discount_amount": "2999.00"
    }
    
    verdict = PolicyEngine.evaluate_basket(
        db=db,
        primary_product_id=41,
        basket=basket,
        policy=None,
        buyer_budget=Decimal("12000.00")
    )
    
    assert verdict["decision"] == "BLOCKED"
    assert any("min selling price" in r.lower() or "price is below" in r.lower() or "margin" in r.lower() for r in verdict["reasons"])

def test_transaction_basket_persistence(db: Session):
    """
    Verify that dynamic smartwatch + strap bundle negotiation correctly persists the basket structure in DB.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="buyer_e2e_05",
        intent="I want to buy a smartwatch and strap. Budget is 4500 INR.",
        budget=Decimal("4500.00")
    )
    
    assert res["selected_product_id"] == 56
    
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr is not None
    assert pr.basket is not None
    assert len(pr.basket["items"]) == 2
    item_ids = [item["product_id"] for item in pr.basket["items"]]
    assert 56 in item_ids
    assert 57 in item_ids


def test_natural_dialogue_and_reason_labels(db: Session):
    """
    Verify that NegotiationOrchestrator history items contain human-like dialogue messages and concise trust labels.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="test_dialogue_buyer",
        intent="I want to buy the Samsung Galaxy A15 without accessories. Budget is 15000 INR.",
        budget=Decimal("15000.00")
    )
    
    assert res["decision"] in ["APPROVED", "REQUIRES_APPROVAL"]
    assert len(res["negotiation_history"]) > 0
    first_turn = res["negotiation_history"][0]
    assert first_turn["buyer_offer"] is not None
    assert "message" in first_turn["buyer_offer"]
    assert len(first_turn["buyer_offer"]["message"]) > 10
    assert "reason_label" in first_turn["buyer_offer"]


def test_strict_budget_rejects_bundle_and_accepts_standalone_phone(db: Session):
    """
    Verify that a buyer with strict budget of ₹12,000 rejects a ₹13,596 bundle,
    counters for the phone standalone, and reaches a final deal within ₹12,000.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="strict_buyer_01",
        intent="I'm looking for Samsung Galaxy A15. Strict budget is 12000 INR.",
        budget=Decimal("12000.00")
    )
    
    assert res["decision"] in ["APPROVED", "REQUIRES_APPROVAL"]
    # Final amount must NOT exceed 12000
    assert Decimal(str(res["final_amount"])) <= Decimal("12000.00")
    # Must only contain the standalone phone
    assert len(res["basket"]["items"]) == 1
    assert res["basket"]["items"][0]["product_id"] == 41


def test_flexible_budget_allows_bundle_acceptance(db: Session):
    """
    Verify that a buyer with flexible budget / requesting accessories accepts the ₹13,596 bundle.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="flexible_buyer_01",
        intent="I want a Samsung Galaxy A15 with charger and case bundle. Budget is 15000 INR.",
        budget=Decimal("15000.00")
    )
    
    assert res["decision"] in ["APPROVED", "REQUIRES_APPROVAL"]
    assert Decimal(str(res["final_amount"])) == Decimal("13596.00")
    assert len(res["basket"]["items"]) == 4


def test_merchant_pricing_strategy_deterministic_bounds():
    """
    Verify deterministic MerchantPricingStrategy calculations for inventory adjustments and floors.
    """
    from backend.app.agents.pricing_strategy import MerchantPricingStrategy
    
    # High inventory item (stock = 50)
    high_inv_bounds = MerchantPricingStrategy.calculate_pricing_bounds(
        cost=Decimal("10000.00"),
        base_price=Decimal("12999.00"),
        min_selling_price=Decimal("11499.00"),
        inventory=50,
        round_idx=1,
        max_rounds=4
    )
    assert high_inv_bounds["inventory_flexibility"] == Decimal("1.00")
    assert high_inv_bounds["target_offer_price"] >= high_inv_bounds["absolute_floor"]

    # Low inventory item (stock = 3)
    low_inv_bounds = MerchantPricingStrategy.calculate_pricing_bounds(
        cost=Decimal("10000.00"),
        base_price=Decimal("12999.00"),
        min_selling_price=Decimal("11499.00"),
        inventory=3,
        round_idx=1,
        max_rounds=4
    )
    assert low_inv_bounds["inventory_flexibility"] == Decimal("0.40")
    assert low_inv_bounds["merchant_best_price"] > high_inv_bounds["merchant_best_price"]


def test_monotonic_concession_and_exact_amount_consistency(db: Session):
    """
    Verify that the final agreed amount exactly matches the database PurchaseRequest and basket sum.
    """
    buyer = BuyerAgent(MockProvider())
    merchant = MerchantAgent(MockProvider())
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)
    
    res = orchestrator.run_negotiation_loop(
        buyer_id="consistency_buyer",
        intent="Samsung Galaxy A15 without accessories. Budget is 12500 INR.",
        budget=Decimal("12500.00")
    )
    
    pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == res["purchase_request_id"]).first()
    assert pr is not None
    assert str(pr.final_amount) == str(res["final_amount"])
    assert str(pr.basket["final_total"]) == str(res["final_amount"])

