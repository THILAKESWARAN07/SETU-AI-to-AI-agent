from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from backend.app.models import Product, MerchantPolicy
from backend.app.agents.pricing_strategy import calculate_basket_financials
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError
from backend.app.agents.provider import MockLLMProvider
from backend.app.schemas import DemoCommerceResponse


def test_merchant_financials_deterministic_calculation():
    """Verify exact deterministic formula matching the spec:
    Original: 1599, Cost: 1050, Final: 1425
    Customer Savings = 174, Customer Discount = 10.88%
    Merchant Profit = 375, Merchant Margin = 26.32%
    """
    basket_items = [
        {
            "product_id": 1,
            "original_price": "1599.00",
            "negotiated_price": "1425.00",
            "quantity": 1,
            "cost": "1050.00"
        }
    ]
    fin = calculate_basket_financials(basket_items)
    
    assert Decimal(fin["catalog_total"]) == Decimal("1599.00")
    assert Decimal(fin["total_cost"]) == Decimal("1050.00")
    assert Decimal(fin["basket_total"]) == Decimal("1425.00")
    assert Decimal(fin["profit_amount"]) == Decimal("375.00")
    assert Decimal(fin["gross_margin_percent"]) == Decimal("26.32")
    assert Decimal(fin["buyer_savings_amount"]) == Decimal("174.00")
    assert Decimal(fin["buyer_savings_percent"]) == Decimal("10.88")


def test_approved_negotiation_includes_authoritative_merchant_financials(db: Session):
    """Verify that an APPROVED negotiation populates merchant_financials deterministically."""
    mock_provider = MockLLMProvider()
    buyer = BuyerAgent(mock_provider)
    merchant = MerchantAgent(mock_provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer-merchant-fin",
        intent="I want wireless earbuds pro for 1450",
        budget=Decimal("2000.00"),
        max_rounds=3
    )

    assert res["decision"] == "APPROVED"
    assert "merchant_financials" in res
    mf = res["merchant_financials"]
    assert mf is not None

    # Verify merchant financial fields exist and are authoritative
    assert mf["original_price"] is not None
    assert mf["merchant_cost"] is not None
    assert mf["final_price"] is not None
    assert mf["merchant_profit"] is not None
    assert mf["merchant_margin_percent"] is not None
    assert mf["customer_savings"] is not None
    assert mf["customer_discount_percent"] is not None
    assert mf["is_within_margin_policy"] is True

    # Check math consistency
    orig = Decimal(mf["original_price"])
    cost = Decimal(mf["merchant_cost"])
    final = Decimal(mf["final_price"])
    profit = Decimal(mf["merchant_profit"])
    margin = Decimal(mf["merchant_margin_percent"])
    savings = Decimal(mf["customer_savings"])

    assert profit == (final - cost).quantize(Decimal("0.01"))
    expected_margin = (((final - cost) / final) * Decimal("100")).quantize(Decimal("0.01"))
    assert margin == expected_margin
    assert savings == (orig - final).quantize(Decimal("0.01"))


def test_blocked_negotiation_does_not_show_fake_zero_profit(db: Session):
    """Verify that a BLOCKED deal returns None for final_price, merchant_profit, merchant_margin_percent (N/A in UI)."""
    mock_provider = MockLLMProvider()
    buyer = BuyerAgent(mock_provider)
    merchant = MerchantAgent(mock_provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    # 500 budget will be BLOCKED because product 1 min_selling_price is 1399 and cost is 1050
    try:
        res = orchestrator.run_negotiation_loop(
            buyer_id="test-buyer-blocked",
            intent="I want earbuds for 500",
            budget=Decimal("500.00"),
            max_rounds=2
        )
    except NegotiationError as e:
        res = e.result_data

    assert res["decision"] in ["BLOCKED", "REJECTED"]
    assert res["final_amount"] is None

    mf = res.get("merchant_financials")
    assert mf is not None
    assert mf["final_price"] is None
    assert mf["merchant_profit"] is None
    assert mf["merchant_margin_percent"] is None
    assert mf["customer_savings"] is None
    assert mf["customer_discount_percent"] is None
    assert mf["is_within_margin_policy"] is False
    assert mf["block_reason"] is not None


def test_buyer_privacy_guarantee_no_merchant_cost_in_events(db: Session):
    """Verify that buyer conversation events and buyer opening offers NEVER contain merchant_cost or profit."""
    mock_provider = MockLLMProvider()
    buyer = BuyerAgent(mock_provider)
    merchant = MerchantAgent(mock_provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer-privacy",
        intent="I want wireless earbuds pro for 1450",
        budget=Decimal("2000.00"),
        max_rounds=3
    )

    # Inspect all conversation events
    for evt in res.get("conversation_events", []):
        assert "merchant_cost" not in evt
        assert "merchant_profit" not in evt
        assert "merchant_margin" not in evt
        assert "cost" not in evt

    # Inspect buyer opening offer record
    if res.get("buyer_opening_offer"):
        bo = res["buyer_opening_offer"]
        assert "merchant_cost" not in bo
        assert "merchant_profit" not in bo
        assert "cost" not in bo


def test_demo_commerce_response_schema_validation(db: Session):
    """Verify Pydantic validation passes with merchant_financials."""
    mock_provider = MockLLMProvider()
    buyer = BuyerAgent(mock_provider)
    merchant = MerchantAgent(mock_provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test-buyer-schema",
        intent="I want wireless earbuds",
        budget=Decimal("2000.00"),
        max_rounds=2
    )

    validated = DemoCommerceResponse.model_validate(res)
    assert validated.merchant_financials is not None
    assert "merchant_cost" in validated.merchant_financials
