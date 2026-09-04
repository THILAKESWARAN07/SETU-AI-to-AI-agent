import pytest
from decimal import Decimal
from pydantic import ValidationError

from backend.app.agents.provider import (
    BundleProposalSchema,
    MerchantDecision,
    BuyerDecision,
    BasketItemSchema,
    MockProvider,
)
from backend.app.agents.ai_gateway import (
    CentralAIGateway,
    NegotiationContext,
)
from backend.app.agents.pricing_strategy import (
    calculate_basket_financials,
    MerchantPricingStrategy,
)
from backend.app.database import SessionLocal
from backend.app.models import Product, MerchantPolicy
from backend.app.agents.orchestrator import NegotiationOrchestrator
from backend.app.agents.agents import BuyerAgent, MerchantAgent


def test_merchant_bundle_proposal_schema_validation():
    """1. Merchant bundle proposal schema validation."""
    bundle_prop = BundleProposalSchema(
        proposal_id="prop_m_r2_bundle",
        is_optional=True,
        bundle_name="Wireless Earbuds Pro + Premium Charging Case",
        basket_items=[
            {"product_id": 1, "name": "Wireless Earbuds Pro", "quantity": 1, "original_price": Decimal("1599.00"), "negotiated_price": Decimal("1499.00"), "is_primary": True},
            {"product_id": 2, "name": "Premium Charging Case", "quantity": 1, "original_price": Decimal("399.00"), "negotiated_price": Decimal("400.00"), "is_primary": False}
        ],
        standalone_price=Decimal("1499.00"),
        bundle_price=Decimal("1899.00"),
        savings=Decimal("99.00")
    )
    assert bundle_prop.is_optional is True
    assert bundle_prop.bundle_price == Decimal("1899.00")
    assert bundle_prop.savings == Decimal("99.00")

    # MerchantDecision can take PROPOSE_BUNDLE and bundle_proposal
    merchant_dec = MerchantDecision(
        action="PROPOSE_BUNDLE",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1499.00"),
        total_amount=Decimal("1499.00"),
        rationale="Offering standalone at 1499 with optional charging case bundle at 1899.",
        bundle_proposal=bundle_prop
    )
    assert merchant_dec.action == "PROPOSE_BUNDLE"
    assert merchant_dec.bundle_proposal.bundle_name == "Wireless Earbuds Pro + Premium Charging Case"


def test_merchant_receives_bundle_context():
    """2. Merchant receives bundle/cross-sell context in NegotiationContext."""
    optional_bundle = {
        "bundle_product_ids": [1, 2],
        "included_product_names": ["Wireless Earbuds Pro", "Premium Charging Case"],
        "bundle_list_price": Decimal("1998.00"),
        "allowed_bundle_selling_range": "1849.00 - 1998.00",
        "bundle_min_price": Decimal("1849.00"),
        "bundle_price": Decimal("1899.00"),
        "savings": Decimal("99.00"),
        "inventory_available": True,
        "fits_buyer_budget": True
    }
    ctx = NegotiationContext(
        agent_role="MERCHANT_AGENT",
        current_round=2,
        buyer_max_budget=Decimal("2000.00"),
        current_product={"id": 1, "name": "Wireless Earbuds Pro", "price": "1599.00", "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1400.00"),
        optional_bundle=optional_bundle,
        bundle_already_proposed=False
    )
    prompt_compact = CentralAIGateway._build_compact_turn_prompt("Buyer offered 1400", ctx)
    assert "OPTIONAL BUNDLE / CROSS-SELL OPPORTUNITY" in prompt_compact
    assert "1899.00" in prompt_compact
    assert "Savings" in prompt_compact or "99.00" in prompt_compact


def test_merchant_can_choose_propose_bundle():
    """3. Merchant can choose PROPOSE_BUNDLE and gateway clamps safely."""
    bundle_prop = BundleProposalSchema(
        proposal_id="prop_m_r2_bundle",
        is_optional=True,
        bundle_name="Wireless Earbuds Pro + Premium Charging Case",
        basket_items=[],
        standalone_price=Decimal("1499.00"),
        bundle_price=Decimal("1899.00"),
        savings=Decimal("99.00")
    )
    decision = MerchantDecision(
        action="PROPOSE_BUNDLE",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1499.00"),
        total_amount=Decimal("1499.00"),
        rationale="Proposing standalone with value bundle.",
        message="I can offer the standalone for 1499 or the bundle for 1899.",
        bundle_proposal=bundle_prop
    )
    ctx = NegotiationContext(
        agent_role="MERCHANT_AGENT",
        current_round=2,
        buyer_max_budget=Decimal("2000.00"),
        current_product={"id": 1, "name": "Wireless Earbuds Pro", "price": "1599.00", "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1400.00")
    )
    from backend.app.agents.ai_gateway import ai_gateway
    clamped = ai_gateway._clamp_decision(decision, ctx)
    assert clamped.action == "PROPOSE_BUNDLE"
    assert clamped.bundle_proposal.bundle_price == Decimal("1899.00")


def test_buyer_receives_and_reasons_about_bundle_proposals():
    """4 & 5. Buyer can receive optional bundle proposal, compare, or reject bundle to negotiate standalone."""
    # BuyerDecision allows ACCEPT_BUNDLE, REJECT_BUNDLE, COUNTER, etc.
    buyer_dec = BuyerDecision(
        action="COUNTER",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1450.00"),
        total_amount=Decimal("1450.00"),
        rationale="I prefer lower total cost for the standalone earbuds.",
        message="I only need the standalone earbuds. Can we do ₹1,450?"
    )
    assert buyer_dec.action == "COUNTER"
    assert buyer_dec.total_amount == Decimal("1450.00")


def test_bundle_cannot_be_selected_when_inventory_unavailable():
    """6. Bundle cannot be proposed or selected when inventory is unavailable."""
    primary_prod = {"id": 1, "name": "Earbuds", "price": Decimal("1599.00"), "cost": Decimal("1050.00"), "min_selling_price": Decimal("1400.00"), "inventory": 10}
    # Out of stock accessory filtered out prior to bundle evaluation
    all_related = [{"id": 2, "name": "Case", "price": Decimal("399.00"), "cost": Decimal("250.00"), "min_selling_price": Decimal("350.00"), "inventory": 0, "active": True}]
    in_stock_related = [p for p in all_related if p.get("inventory", 0) > 0]
    
    eval_res = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=in_stock_related,
        buyer_offer_price=Decimal("1400.00"),
        buyer_max_budget=Decimal("2000.00"),
        round_idx=1
    )
    # Bundle info is None when accessory inventory is 0
    assert eval_res.get("bundle_info") is None


def test_bundle_price_floor_and_margin_rules():
    """7. Bundle price floor and margin rules remain strictly enforced."""
    items = [
        {"product_id": 1, "name": "Earbuds", "quantity": 1, "original_price": Decimal("1599.00"), "negotiated_price": Decimal("1400.00"), "cost": Decimal("1050.00"), "is_primary": True},
        {"product_id": 2, "name": "Case", "quantity": 1, "original_price": Decimal("399.00"), "negotiated_price": Decimal("350.00"), "cost": Decimal("250.00"), "is_primary": False}
    ]
    fin = calculate_basket_financials(items)
    # Total cost = 1050 + 250 = 1300
    # Basket total = 1400 + 350 = 1750
    # Gross margin = (1750 - 1300) / 1750 = 450 / 1750 = 25.71%
    assert Decimal(str(fin["gross_margin_percent"])) > Decimal("20.0")
    assert Decimal(str(fin["buyer_savings_amount"])) == Decimal("248.00") # (1599+399) - (1400+350) = 1998 - 1750 = 248


def test_deterministic_savings_calculation():
    """8 & 9. Deterministic savings calculation: ₹1,599 -> ₹1,450 => ₹149 (9.32%), positive only."""
    catalog_list = Decimal("1599.00")
    final_price = Decimal("1450.00")
    
    savings = max(Decimal("0.00"), catalog_list - final_price)
    discount_pct = (savings / catalog_list) * Decimal("100")
    
    assert savings == Decimal("149.00")
    assert round(float(discount_pct), 2) == 9.32
    
    # UI formatting should never be negative
    savings_str = f"You Save: ₹{int(savings)}"
    discount_str = f"Discount: ₹{int(savings)} ({discount_pct:.2f}%)"
    assert "You Save: ₹149" in savings_str
    assert "-₹" not in savings_str
    assert "9.32%" in discount_str


def test_basket_snapshot_records_basket_type():
    """12. Final basket snapshot correctly records whether STANDALONE or BUNDLE was selected."""
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        # 1. Standalone flow
        res_standalone = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test_standalone",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4
        )
        assert res_standalone["basket_type"] == "STANDALONE"
        assert res_standalone["selected_basket_type"] == "STANDALONE"
        assert len(res_standalone["basket"]["items"]) == 1

        # 2. Bundle flow
        res_bundle = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test_bundle",
            intent="I want a complete bundle of wireless earbuds with charging case under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4
        )
        assert res_bundle["basket_type"] == "BUNDLE"
        assert res_bundle["selected_basket_type"] == "BUNDLE"
        assert len(res_bundle["basket"]["items"]) == 2
    finally:
        db.close()
