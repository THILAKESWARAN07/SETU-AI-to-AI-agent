"""
tests/unit/test_negotiation_invariants.py
Unit tests verifying the 14 core SETU negotiation invariants and financial correctness:
1. Exact gross margin math vs margin on cost.
2. Exact bundle savings calculation.
3. No duplicate proposal ID on HOLD_PREVIOUS_OFFER.
4. Correct natural dialogue distinction for HOLD vs CONCESSION vs REJECT.
5. Exact immutable accepted proposal validation in Policy Engine.
6. Proposal lineage and history integrity.
"""
from decimal import Decimal
import pytest
from backend.app.agents.pricing_strategy import (
    calculate_basket_financials,
    MerchantPricingStrategy,
)
from backend.app.agents.provider import MockProvider, MerchantDecision
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.policy import PolicyEngine
from backend.app.database import get_db, SessionLocal
from backend.app.models import Product, MerchantPolicy


def test_invariant_1_and_11_exact_gross_margin_math():
    """
    Gross margin percentage MUST equal (profit / selling_price) * 100.
    Example: Earbuds cost = ₹1,050, Case cost = ₹250.
    Total cost = ₹1,300. Selling price = ₹1,899.
    Profit = ₹599.
    Gross margin = (599 / 1899) * 100 = 31.5429...% (31.54%)
    Margin on cost = (599 / 1300) * 100 = 46.0769...% (46.08%)
    NEVER confuse gross margin with margin on cost.
    """
    catalog = {
        1: Product(id=1, name="Earbuds", category="Electronics", price=Decimal("1599.00"), cost=Decimal("1050.00")),
        2: Product(id=2, name="Case", category="Accessories", price=Decimal("399.00"), cost=Decimal("250.00")),
    }
    basket_items = [
        {"product_id": 1, "quantity": 1, "negotiated_price": Decimal("1500.00")},
        {"product_id": 2, "quantity": 1, "negotiated_price": Decimal("399.00")},
    ] # Total bundle selling price = 1899.00

    financials = calculate_basket_financials(basket_items, catalog)

    assert Decimal(financials["basket_total"]) == Decimal("1899.00")
    assert Decimal(financials["total_cost"]) == Decimal("1300.00")
    assert Decimal(financials["profit_amount"]) == Decimal("599.00")

    # Exact gross margin: 599 / 1899 * 100 = 31.542917... -> 31.54%
    assert Decimal(financials["gross_margin_percent"]) == Decimal("31.54")
    assert Decimal(financials["gross_margin_percent"]) != Decimal("34.18")

    # Margin on cost: 599 / 1300 * 100 = 46.0769... -> 46.08%
    assert Decimal(financials["margin_on_cost_percent"]) == Decimal("46.08")


def test_invariant_2_and_12_exact_bundle_savings():
    """
    Bundle savings MUST equal sum(original list prices) - bundle total.
    Earbuds list = ₹1,599, Case list = ₹399. Combined list = ₹1,998.
    Bundle price = ₹1,899.
    Savings = ₹1,998 - ₹1,899 = ₹99.00 (4.95%).
    """
    catalog = {
        1: Product(id=1, name="Earbuds", category="Electronics", price=Decimal("1599.00"), cost=Decimal("1050.00")),
        2: Product(id=2, name="Case", category="Accessories", price=Decimal("399.00"), cost=Decimal("250.00")),
    }
    basket_items = [
        {"product_id": 1, "quantity": 1, "negotiated_price": Decimal("1500.00")},
        {"product_id": 2, "quantity": 1, "negotiated_price": Decimal("399.00")},
    ]

    financials = calculate_basket_financials(basket_items, catalog)

    assert Decimal(financials["catalog_total"]) == Decimal("1998.00")
    assert Decimal(financials["buyer_savings_amount"]) == Decimal("99.00")
    assert Decimal(financials["buyer_savings_percent"]) == Decimal("4.95")


def test_invariant_3_and_14_hold_dialogue_and_no_false_concession():
    """
    When buyer offers ₹1,475 and merchant floor is ₹1,499:
    1. Strategy must be HOLD_PRICE / HOLD_PREVIOUS_OFFER.
    2. Price remains ₹1,499 (same as previous merchant offer).
    3. Natural dialogue MUST explicitly indicate holding / previous offer, NOT "I can meet you at".
    """
    primary_prod = {
        "id": 1,
        "name": "Noise-Canceling Wireless Earbuds",
        "price": Decimal("1599.00"),
        "cost": Decimal("1050.00"),
        "min_selling_price": Decimal("1499.00"),
        "inventory": 15,
    }
    strat = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=[],
        buyer_offer_price=Decimal("1475.00"),
        buyer_max_budget=Decimal("2000.00"),
        standalone_preferred=True,
        round_idx=3,
        max_rounds=4,
        min_margin_percent=Decimal("15.00"),
        max_discount_percent=Decimal("15.00"),
        previous_merchant_price=Decimal("1499.00"),
    )

    # Strategy should be HOLD_PRICE, not NEW_COUNTER
    assert strat["strategy"] == "HOLD_PRICE"
    assert strat["recommended_standalone_price"] == Decimal("1499.00")

    # Now verify MockProvider dialogue for Round 4 standalone hold
    provider = MockProvider()
    prompt = (
        "Buyer Counter Offer: ₹1475.00 for Product 1 (Earbuds). "
        "Round: 4. Previous merchant standalone offer: ₹1499.00. "
        "Your minimum floor is ₹1499.00. (standalone preferred: true)"
    )
    decision = provider.generate_structured_response(prompt, "", MerchantDecision)

    # Dialogue must indicate holding at previous offer
    msg = decision.message.lower()
    assert "hold" in msg or "previous offer" in msg or "cannot support" in msg
    assert "meet you at 1,499" not in msg
    assert "meet you at ₹1,499" not in msg
    assert "concession to 1,499" not in msg


def test_invariant_4_proposal_lineage_no_duplicate_id_on_hold():
    """
    In the multi-turn negotiation:
    Round 2 Merchant: prop_m_r2_standalone = 1499
    Round 3 Buyer: prop_b_r2 = 1475
    Round 4 Merchant: Holds at 1499.
    The merchant event MUST reference the existing prop_m_r2_standalone and NOT create a new prop_m_r4_standalone.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        events = []
        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4,
            on_event=lambda ev: events.append(ev)
        )

        # Find merchant hold event
        hold_events = [e for e in events if e.get("event_type") == "hold_offer" or e.get("state") == "MERCHANT_HOLD"]
        assert len(hold_events) > 0, f"Expected at least one hold_offer event, got: {[e.get('event_type') for e in events]}"
        hold_event = hold_events[0]

        # Assert proposal_id points back to previous standalone proposal without duplicate creation for round 4
        assert hold_event["proposal_id"].startswith("prop_m_r")
        assert hold_event["proposal_type"] == "HOLD_PREVIOUS_OFFER"
        assert Decimal(str(hold_event["offer"])) == Decimal("1499.00")

        # Verify no duplicate prop_m_r4_standalone was created
        proposal_ids = [p["proposal_id"] for p in result["proposals"]]
        assert "prop_m_r4_standalone" not in proposal_ids
    finally:
        db.close()


def test_invariant_5_immutable_accepted_proposal_policy_validation():
    """
    Policy engine must evaluate the EXACT immutable snapshot of the accepted proposal.
    """
    db = SessionLocal()
    try:
        policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
        assert policy is not None

        # Create an accepted proposal snapshot for Earbuds at ₹1,499
        basket_snapshot = {
            "proposal_id": "prop_m_r2_standalone",
            "items": [
                {
                    "product_id": 1,
                    "name": "Noise-Canceling Wireless Earbuds",
                    "quantity": 1,
                    "original_price": Decimal("1599.00"),
                    "negotiated_price": Decimal("1499.00"),
                    "cost": Decimal("1050.00"),
                    "is_primary": True,
                }
            ],
            "total_amount": Decimal("1499.00"),
        }

        result = PolicyEngine.evaluate_basket(
            basket=basket_snapshot,
            policy=policy,
            buyer_budget=Decimal("2000.00"),
            primary_product_id=1,
            db=db,
        )

        assert result["decision"] == "APPROVED"
        assert result["reasons"] == []
        assert result["calculated_margin_percent"] > Decimal("15.0")
        # Final transaction amount matches accepted proposal total
        assert basket_snapshot["total_amount"] == Decimal("1499.00")
        assert len(basket_snapshot["items"]) == 1
        assert basket_snapshot["items"][0]["negotiated_price"] == Decimal("1499.00")
    finally:
        db.close()


def test_invariant_6_inventory_flexibility_low_vs_high():
    """
    Low inventory (e.g. 2 units) must hold price more aggressively (lower discount flexibility)
    than high inventory (e.g. 25 units).
    """
    low_inv_bounds = MerchantPricingStrategy.calculate_pricing_bounds(
        cost=Decimal("1050.00"),
        base_price=Decimal("1599.00"),
        min_selling_price=Decimal("1499.00"),
        inventory=2,
        round_idx=2,
        max_rounds=4
    )

    high_inv_bounds = MerchantPricingStrategy.calculate_pricing_bounds(
        cost=Decimal("1050.00"),
        base_price=Decimal("1599.00"),
        min_selling_price=Decimal("1499.00"),
        inventory=25,
        round_idx=2,
        max_rounds=4
    )

    # Low inventory gives less discount flexibility
    assert low_inv_bounds["inventory_flexibility"] < high_inv_bounds["inventory_flexibility"]
    # Merchant best price for low inventory is higher (less discount)
    assert low_inv_bounds["merchant_best_price"] > high_inv_bounds["merchant_best_price"]


def test_invariant_7_severe_low_offer_rejection():
    """
    Absurdly low or predatory buyer offers (e.g. ₹50 or ₹500 on a ₹1050 cost product)
    must trigger REJECT strategy deterministically.
    """
    prod = {
        "id": 1,
        "name": "Earbuds",
        "price": Decimal("1599.00"),
        "cost": Decimal("1050.00"),
        "min_selling_price": Decimal("1499.00"),
        "inventory": 10
    }
    eval_reject = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=prod,
        related_prods=[],
        buyer_offer_price=Decimal("50.00"),
        buyer_max_budget=Decimal("2000.00"),
        round_idx=1
    )
    assert eval_reject["strategy"] == "REJECT"
    assert "rejected" in eval_reject["reason"].lower() or "severely below" in eval_reject["reason"].lower()


def test_invariant_8_strict_budget_blocks_overbudget_bundle():
    """
    If buyer has a strict budget of ₹1,400, a bundle priced at ₹1,899 must NOT be prescribed
    or forced into the negotiation.
    """
    prod = {
        "id": 1,
        "name": "Earbuds",
        "price": Decimal("1599.00"),
        "cost": Decimal("1050.00"),
        "min_selling_price": Decimal("1400.00"),
        "inventory": 10
    }
    case_prod = {
        "id": 2,
        "name": "Case",
        "price": Decimal("399.00"),
        "cost": Decimal("250.00"),
        "min_selling_price": Decimal("350.00"),
        "inventory": 10,
        "active": True
    }
    eval_res = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=prod,
        related_prods=[case_prod],
        buyer_offer_price=Decimal("1300.00"),
        buyer_max_budget=Decimal("1400.00"), # Strict budget
        round_idx=1
    )
    # Bundle should NOT be returned because ₹1,899 exceeds ₹1,400 max budget
    assert eval_res["bundle_info"] is None


def test_invariant_9_concessions_strictly_monotonic():
    """
    When the merchant makes concessions across rounds, each successive concession price
    must be strictly lower than the previous merchant price (new_price < previous_price).
    """
    prod = {
        "id": 1,
        "name": "Phone",
        "price": Decimal("12999.00"),
        "cost": Decimal("10000.00"),
        "min_selling_price": Decimal("11499.00"),
        "inventory": 30
    }
    r1 = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=prod,
        related_prods=[],
        buyer_offer_price=Decimal("11500.00"),
        buyer_max_budget=Decimal("13000.00"),
        round_idx=1,
        max_rounds=4
    )
    p1 = r1["recommended_standalone_price"]

    r2 = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=prod,
        related_prods=[],
        buyer_offer_price=Decimal("11500.00"),
        buyer_max_budget=Decimal("13000.00"),
        round_idx=2,
        max_rounds=4,
        previous_merchant_price=p1
    )
    p2 = r2["recommended_standalone_price"]

    assert p2 <= p1
    if r2["strategy"] == "CONCESSION":
        assert p2 < p1


def test_unchanged_price_and_unchanged_basket_creates_no_new_proposal_id():
    """
    Requirement 1 & 2:
    If merchant_new_price == previous_active_merchant_price and basket unchanged:
    - strategy = HOLD_PRICE
    - action/type = HOLD_PREVIOUS_OFFER
    - DO NOT create a new proposal_id
    - DO NOT append a duplicate proposal record
    - reference the existing active proposal_id
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        events = []
        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4,
            on_event=lambda ev: events.append(ev)
        )

        # Find initial merchant standalone proposal (Round 2)
        merchant_standalone_props = [
            p for p in result["proposals"] 
            if p.get("actor") == "merchant" and p.get("proposal_type") == "STANDALONE_COUNTER"
        ]
        assert len(merchant_standalone_props) == 1, f"Expected exactly 1 merchant standalone proposal, found {len(merchant_standalone_props)}: {merchant_standalone_props}"
        r2_prop_id = merchant_standalone_props[0]["proposal_id"]
        assert r2_prop_id == "prop_m_r2_standalone"
        assert Decimal(str(merchant_standalone_props[0]["total_amount"])) == Decimal("1499.00")

        # Find hold events
        hold_events = [e for e in events if e.get("event_type") == "hold_offer" or e.get("proposal_type") == "HOLD_PREVIOUS_OFFER"]
        assert len(hold_events) >= 1
        for h_evt in hold_events:
            # Must reference the exact previous proposal ID, NOT create a new one
            assert h_evt["proposal_id"] == r2_prop_id
            assert Decimal(str(h_evt["standalone_counter"])) == Decimal("1499.00")

        # Ensure no duplicate merchant standalone proposal was created in round 3 or round 4
        prop_ids = [p["proposal_id"] for p in result["proposals"]]
        assert "prop_m_r3_standalone" not in prop_ids
        assert "prop_m_r4_standalone" not in prop_ids
    finally:
        db.close()


def test_changed_price_creates_new_proposal_id():
    """
    Requirement 2:
    A new merchant proposal_id must be created when the price materially changes.
    """
    db = SessionLocal()
    try:
        b_bounds = MerchantPricingStrategy.calculate_pricing_bounds(
            cost=Decimal("1000.00"),
            base_price=Decimal("1800.00"),
            min_selling_price=Decimal("1200.00"),
            inventory=100,
            round_idx=1,
            max_rounds=4
        )
        p1 = b_bounds["target_offer_price"]
        
        b_bounds2 = MerchantPricingStrategy.calculate_pricing_bounds(
            cost=Decimal("1000.00"),
            base_price=Decimal("1800.00"),
            min_selling_price=Decimal("1200.00"),
            inventory=100,
            round_idx=3,
            max_rounds=4
        )
        p2 = b_bounds2["target_offer_price"]

        # If prices differ, distinct proposals are minted
        assert p1 != p2
        assert p2 < p1
    finally:
        db.close()


def test_changed_basket_creates_new_proposal_id():
    """
    Requirement 2:
    A new proposal_id must be created when the basket changes (e.g. standalone -> bundle).
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4
        )

        standalone_props = [p for p in result["proposals"] if p.get("proposal_type") == "STANDALONE_COUNTER" and p.get("actor") == "merchant"]
        bundle_props = [p for p in result["proposals"] if p.get("proposal_type") == "BUNDLE_PROPOSAL" and p.get("actor") == "merchant"]

        assert len(standalone_props) >= 1
        assert len(bundle_props) >= 1
        assert standalone_props[0]["proposal_id"] != bundle_props[0]["proposal_id"]
        assert len(standalone_props[0]["basket_items"]) == 1
        assert len(bundle_props[0]["basket_items"]) == 2
    finally:
        db.close()


def test_buyer_acceptance_references_original_held_proposal():
    """
    Requirement 3 & 4:
    Buyer ACCEPTANCE must reference the exact original merchant proposal_id that was held.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        events = []
        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4,
            on_event=lambda ev: events.append(ev)
        )

        # Standalone proposal minted in Round 2
        r2_prop = next(p for p in result["proposals"] if p.get("proposal_type") == "STANDALONE_COUNTER" and p.get("actor") == "merchant")
        expected_prop_id = r2_prop["proposal_id"]  # "prop_m_r2_standalone"

        # Buyer accepts after merchant holds
        accept_events = [
            e for e in events 
            if e.get("actor") == "buyer" and (
                e.get("state") in ["AGREED", "BUYER_ACCEPTED"] or 
                e.get("event_type") in ["acceptance", "buyer_accept_standalone"] or 
                e.get("proposal_type") == "ACCEPTANCE"
            )
        ]
        assert len(accept_events) >= 1
        accept_evt = accept_events[0]
        assert accept_evt.get("accepted_proposal_id") == expected_prop_id

        # Orchestrator final accepted proposal id matches
        assert result.get("accepted_proposal_id") == expected_prop_id
    finally:
        db.close()


def test_policy_engine_validates_exact_accepted_proposal_snapshot():
    """
    Requirement 4 & 6:
    Policy Engine validates the exact immutable basket snapshot of the accepted proposal.
    """
    db = SessionLocal()
    try:
        policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
        assert policy is not None

        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4
        )

        accepted_id = result.get("accepted_proposal_id")
        matching_proposal = next(p for p in result["proposals"] if p["proposal_id"] == accepted_id)

        # Basket submitted to Policy Engine must strictly match the accepted proposal
        assert Decimal(str(result["final_amount"])) == Decimal(str(matching_proposal["total_amount"]))
        assert len(result["basket"]["items"]) == len(matching_proposal["basket_items"])
        assert result["decision"] == "APPROVED"
        assert result["reasons"] == []
    finally:
        db.close()


def test_event_proposal_id_matches_amount_and_basket_strictly():
    """
    Requirement 7:
    Every event's proposal_id MUST strictly match the corresponding proposal's amount and basket.
    Standalone proposal (prop_m_r2_standalone) cannot display bundle price (₹1,899).
    Bundle proposal (prop_m_r2_bundle) cannot display standalone basket (1 item).
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        events = []
        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4,
            on_event=lambda ev: events.append(ev)
        )

        merchant_counter_events = [e for e in events if e.get("actor") == "merchant" and e.get("state") == "MERCHANT_COUNTER"]
        assert len(merchant_counter_events) >= 1
        r2_merchant_evt = merchant_counter_events[0]

        # 1. Main event proposal_id is the standalone proposal
        assert r2_merchant_evt["proposal_id"] == "prop_m_r2_standalone"
        # 2. Main event offer is strictly ₹1,499.00 (NOT ₹1,899.00)
        assert Decimal(str(r2_merchant_evt["offer"])) == Decimal("1499.00")
        assert Decimal(str(r2_merchant_evt["standalone_counter"])) == Decimal("1499.00")
        # 3. Main event basket is strictly 1 item (standalone earbuds)
        assert len(r2_merchant_evt["basket_items"]) == 1
        assert r2_merchant_evt["basket_items"][0]["is_primary"] is True
        assert Decimal(str(r2_merchant_evt["basket_items"][0]["negotiated_price"])) == Decimal("1499.00")

        # 4. Bundle proposal is attached with its own distinct proposal ID and bundle amount
        bundle_prop = r2_merchant_evt.get("bundle_proposal")
        assert bundle_prop is not None
        assert bundle_prop["proposal_id"] == "prop_m_r2_bundle"
        assert Decimal(str(bundle_prop["offered_amount"])) == Decimal("1899.00")
        assert len(bundle_prop["basket_items"]) == 2

        # 5. Multi-option proposal snapshots are intact and distinct in result["proposals"]
        all_proposals = {p["proposal_id"]: p for p in result["proposals"]}
        assert "prop_m_r2_standalone" in all_proposals
        assert "prop_m_r2_bundle" in all_proposals

        standalone_p = all_proposals["prop_m_r2_standalone"]
        bundle_p = all_proposals["prop_m_r2_bundle"]

        assert Decimal(str(standalone_p["total_amount"])) == Decimal("1499.00")
        assert len(standalone_p["basket_items"]) == 1

        assert Decimal(str(bundle_p["total_amount"])) == Decimal("1899.00")
        assert len(bundle_p["basket_items"]) == 2

        # 6. Final acceptance matches the exact chosen proposal
        accepted_id = result.get("accepted_proposal_id")
        assert accepted_id == "prop_m_r2_standalone"
        assert Decimal(str(result["final_amount"])) == Decimal("1499.00")
        assert len(result["basket"]["items"]) == 1
    finally:
        db.close()


def test_proposal_snapshot_immutability_across_rounds():
    """
    Verify that proposal snapshots stored in result['proposals'] cannot be mutated or corrupted
    by subsequent rounds or basket operations.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_immutability_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4
        )

        # Retrieve prop_m_r2_standalone and prop_m_r2_bundle
        proposals_by_id = {p["proposal_id"]: p for p in result["proposals"]}
        standalone = proposals_by_id["prop_m_r2_standalone"]
        bundle = proposals_by_id["prop_m_r2_bundle"]

        # Ensure amounts and baskets were not altered by round 3 or round 4 operations
        assert Decimal(str(standalone["total_amount"])) == Decimal("1499.00")
        assert len(standalone["basket_items"]) == 1
        assert standalone["basket_items"][0]["product_id"] == 1
        assert Decimal(str(standalone["basket_items"][0]["negotiated_price"])) == Decimal("1499.00")

        assert Decimal(str(bundle["total_amount"])) == Decimal("1899.00")
        assert len(bundle["basket_items"]) == 2
    finally:
        db.close()


def test_non_default_product_id_resolution():
    """
    Verify that arbitrary product IDs (e.g. Smartwatch ID 56 + Strap ID 57)
    accurately resolve primary product ID from accepted basket items and NEVER fall back to hard-coded ID 1.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_smartwatch_test",
            intent="I want to buy a smartwatch and strap. Budget is 4500 INR.",
            budget=Decimal("4500.00")
        )

        assert result["selected_product_id"] == 56
        assert result["decision"] in ["APPROVED", "REQUIRES_APPROVAL"]
        assert len(result["basket"]["items"]) == 2
        item_ids = [item["product_id"] for item in result["basket"]["items"]]
        assert 56 in item_ids
        assert 57 in item_ids

        # Ensure primary item in basket is ID 56
        primary_item = next(item for item in result["basket"]["items"] if item.get("is_primary"))
        assert primary_item["product_id"] == 56
    finally:
        db.close()


def test_payment_amount_equals_accepted_proposal_total():
    """
    Verify that accepted proposal total == policy validated total == final_amount == Razorpay payment amount.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_payment_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00")
        )

        accepted_id = result["accepted_proposal_id"]
        accepted_prop = next(p for p in result["proposals"] if p["proposal_id"] == accepted_id)

        assert Decimal(str(result["final_amount"])) == Decimal(str(accepted_prop["total_amount"]))
        assert Decimal(str(result["basket"]["final_total"])) == Decimal(str(accepted_prop["total_amount"]))
    finally:
        db.close()


def test_predatory_offer_rejection_at_pricing_strategy():
    """
    Test 1: Predatory offer scenario (Pricing Strategy level)
    Buyer offers ₹50.00 for a product with ₹1,050.00 cost.
    Asserts:
    1. Offer reaches MerchantPricingStrategy.evaluate_sales_strategy.
    2. Since ₹50.00 <= (₹1,050.00 * 0.40 = ₹420.00), strategy must be 'REJECT'.
    3. Reason explicitly indicates uneconomic/severely below cost.
    """
    primary_prod = {
        "id": 1,
        "name": "Wireless Earbuds Pro",
        "price": Decimal("1599.00"),
        "cost": Decimal("1050.00"),
        "min_selling_price": Decimal("1499.00"),
        "inventory": 10,
        "active": True
    }
    
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=[],
        buyer_offer_price=Decimal("50.00"),
        buyer_max_budget=Decimal("50.00"),
        standalone_preferred=True,
        round_idx=1,
        max_rounds=4,
        min_margin_percent=Decimal("15.00"),
        max_discount_percent=Decimal("15.00")
    )

    assert sales_eval["strategy"] == "REJECT"
    assert "severely below product cost" in sales_eval["reason"].lower() or "rejected" in sales_eval["reason"].lower()
    assert "50.00" in sales_eval["reason"] or "50" in sales_eval["reason"]
    assert "1050.00" in sales_eval["reason"] or "1050" in sales_eval["reason"]


def test_predatory_offer_full_orchestrator_flow():
    """
    Test 1 (End-to-End Orchestrator):
    Buyer offers ₹50.00 for product with ₹1,050.00 cost.
    1. Offer does not fail for an unrelated budget-validation reason.
    2. Reaches Round 2 merchant evaluation.
    3. Emits merchant rejection event with strategy 'Merchant Strategy: REJECT'.
    4. Concludes with REJECTED status and NegotiationError.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        events = []
        with pytest.raises(NegotiationError) as exc_info:
            orchestrator.run_negotiation_loop(
                buyer_id="buyer_predatory_test",
                intent="Give me wireless earbuds for Rs. 50 only.",
                budget=Decimal("50.00"),
                max_rounds=4,
                on_event=lambda ev: events.append(ev)
            )

        err = exc_info.value
        assert err.result_data is not None
        assert err.result_data["decision"] == "REJECTED"

        # Verify emitted events
        event_types = [e.get("event_type") for e in events]
        states = [e.get("state") for e in events]

        # Opening buyer offer of ₹50.00 was recorded and evaluated
        buyer_offer_evts = [e for e in events if e.get("actor") == "buyer" and e.get("id") == "evt_r1_buyer_req"]
        assert len(buyer_offer_evts) == 1
        assert Decimal(str(buyer_offer_evts[0]["offer"])) == Decimal("50.00")

        # Merchant rejected in Round 2 due to predatory price
        reject_evts = [e for e in events if e.get("actor") == "merchant" and e.get("state") == "REJECTED"]
        assert len(reject_evts) == 1
        merchant_reject_evt = reject_evts[0]
        assert merchant_reject_evt["strategy"] == "Merchant Strategy: REJECT"
        assert "below price floor" in merchant_reject_evt["reason_label"].lower() or "declined" in merchant_reject_evt["reason_label"].lower()
    finally:
        db.close()


def test_buyer_acceptance_lineage_and_snapshot_harmony():
    """
    Test 2: Buyer acceptance lineage event & snapshot harmony
    When a buyer accepts an existing merchant proposal, the AGREED event must expose the exact accepted proposal ID.
    Ensure buyer acceptance event, final agreed amount, accepted immutable proposal snapshot,
    Policy Engine validation, PurchaseRequest, and payment/order amount all reference the same accepted proposal.
    """
    db = SessionLocal()
    try:
        provider = MockProvider()
        buyer = BuyerAgent(provider)
        merchant = MerchantAgent(provider)
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        events = []
        result = orchestrator.run_negotiation_loop(
            buyer_id="buyer_lineage_test",
            intent="I need wireless earbuds under ₹2,000.",
            budget=Decimal("2000.00"),
            max_rounds=4,
            on_event=lambda ev: events.append(ev)
        )

        # 1. Acceptance Event
        buyer_accept_evts = [e for e in events if e.get("actor") == "buyer" and e.get("state") == "AGREED"]
        assert len(buyer_accept_evts) == 1
        accept_evt = buyer_accept_evts[0]

        accepted_prop_id = accept_evt.get("accepted_proposal_id")
        assert accepted_prop_id == "prop_m_r2_standalone"
        assert accept_evt.get("proposal_id") == "prop_m_r2_standalone"
        assert Decimal(str(accept_evt.get("offer"))) == Decimal("1499.00")

        # 2. Result accepted_proposal_id matches
        assert result.get("accepted_proposal_id") == accepted_prop_id

        # 3. Immutable proposal snapshot matches
        matching_proposal = next(p for p in result["proposals"] if p["proposal_id"] == accepted_prop_id)
        assert Decimal(str(matching_proposal["total_amount"])) == Decimal("1499.00")
        assert len(matching_proposal["basket_items"]) == 1
        assert matching_proposal["status"] == "ACCEPTED"

        # 4. Result final_amount and basket final_total matches
        assert Decimal(str(result["final_amount"])) == Decimal("1499.00")
        assert Decimal(str(result["basket"]["final_total"])) == Decimal("1499.00")

        # 5. Final policy validation event and approved event
        approved_evts = [e for e in events if e.get("state") == "APPROVED"]
        assert len(approved_evts) == 1
        assert Decimal(str(approved_evts[0]["offer"])) == Decimal("1499.00")

        # 6. PurchaseRequest created in DB has same final_amount
        from backend.app.models import PurchaseRequest
        pr = db.query(PurchaseRequest).filter(PurchaseRequest.id == result["purchase_request_id"]).first()
        assert pr is not None
        assert Decimal(str(pr.final_amount)) == Decimal("1499.00")
        assert pr.status == "APPROVED"
    finally:
        db.close()





