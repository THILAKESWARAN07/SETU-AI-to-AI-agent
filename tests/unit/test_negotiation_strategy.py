import pytest
from decimal import Decimal
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from backend.app.models import Product, MerchantPolicy, PurchaseRequest, Transaction
from backend.app.agents.pricing_strategy import MerchantPricingStrategy
from backend.app.agents.orchestrator import NegotiationOrchestrator, parse_budget_intent
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.provider import MockProvider

# 1. Buyer offer is profitable but merchant correctly COUNTERS instead of immediately accepting
def test_merchant_counters_profitable_subtarget_offer(db: Session):
    primary_prod = {
        "id": 1,
        "name": "Wireless Earbuds",
        "price": "1599.00",
        "cost": "1050.00",
        "min_selling_price": "1349.00",
        "inventory": 25
    }
    # Offer 1400 is above floor 1349, but below target ~1500
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=[],
        buyer_offer_price=Decimal("1400.00"),
        buyer_max_budget=Decimal("2000.00"),
        standalone_preferred=True,
        round_idx=1
    )
    assert sales_eval["strategy"] == "COUNTER_PRICE"
    assert sales_eval["recommended_standalone_price"] >= Decimal("1400.00")
    assert sales_eval["recommended_standalone_price"] >= Decimal("1349.00")

# 2. Merchant proposes a compatible profitable bundle
def test_merchant_proposes_compatible_profitable_bundle(db: Session):
    primary_prod = {
        "id": 1,
        "name": "Wireless Earbuds",
        "price": "1599.00",
        "cost": "1050.00",
        "min_selling_price": "1349.00",
        "inventory": 25
    }
    related_prods = [
        {
            "id": 2,
            "name": "Earbuds Charging Case",
            "price": "399.00",
            "cost": "250.00",
            "min_selling_price": "299.00",
            "inventory": 20,
            "active": True
        }
    ]
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=related_prods,
        buyer_offer_price=Decimal("1400.00"),
        buyer_max_budget=Decimal("2000.00"),
        standalone_preferred=False,
        round_idx=1
    )
    assert sales_eval["strategy"] == "BUNDLE"
    assert sales_eval["bundle_info"] is not None
    assert sales_eval["bundle_info"]["bundle_profit"] > sales_eval["bundle_info"]["standalone_profit"]

# 3. Buyer explicitly requests standalone only and bundle is not forced
def test_standalone_only_request_prevents_bundle(db: Session):
    primary_prod = {
        "id": 1,
        "name": "Wireless Earbuds",
        "price": "1599.00",
        "cost": "1050.00",
        "min_selling_price": "1349.00",
        "inventory": 25
    }
    related_prods = [
        {
            "id": 2,
            "name": "Earbuds Charging Case",
            "price": "399.00",
            "cost": "250.00",
            "min_selling_price": "299.00",
            "inventory": 20,
            "active": True
        }
    ]
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=related_prods,
        buyer_offer_price=Decimal("1400.00"),
        buyer_max_budget=Decimal("2000.00"),
        standalone_preferred=True,  # User explicitly wants standalone only
        round_idx=1
    )
    assert sales_eval["strategy"] == "COUNTER_PRICE"
    assert sales_eval["bundle_info"] is None

# 4. Strict budget prevents acceptance of an over-budget bundle
def test_strict_budget_prevents_overbudget_bundle_proposal(db: Session):
    # Galaxy A15 listed at 12,999; buyer max budget 12,000
    primary_prod = {
        "id": 41,
        "name": "Samsung Galaxy A15",
        "price": "12999.00",
        "cost": "10000.00",
        "min_selling_price": "11764.71",
        "inventory": 15
    }
    related_prods = [
        {"id": 44, "name": "25W Fast Charger", "price": "1299.00", "cost": "800.00", "min_selling_price": "941.18", "inventory": 10, "active": True},
        {"id": 45, "name": "Mobile Protective Case", "price": "499.00", "cost": "300.00", "min_selling_price": "352.94", "inventory": 15, "active": True},
        {"id": 46, "name": "Tempered Glass", "price": "299.00", "cost": "150.00", "min_selling_price": "176.47", "inventory": 20, "active": True}
    ]
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=related_prods,
        buyer_offer_price=Decimal("12000.00"),
        buyer_max_budget=Decimal("12000.00"),  # Strict budget
        standalone_preferred=False,
        round_idx=1
    )
    # Since bundle (~13,596) exceeds 12,000 max budget, bundle_info is None
    assert sales_eval["bundle_info"] is None

# 5. Flexible budget allows an appropriate bundle
def test_flexible_budget_allows_appropriate_bundle(db: Session):
    primary_prod = {
        "id": 41,
        "name": "Samsung Galaxy A15",
        "price": "12999.00",
        "cost": "10000.00",
        "min_selling_price": "11764.71",
        "inventory": 15
    }
    related_prods = [
        {"id": 44, "name": "25W Fast Charger", "price": "1299.00", "cost": "800.00", "min_selling_price": "941.18", "inventory": 10, "active": True},
        {"id": 45, "name": "Mobile Protective Case", "price": "499.00", "cost": "300.00", "min_selling_price": "352.94", "inventory": 15, "active": True}
    ]
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=related_prods,
        buyer_offer_price=Decimal("12000.00"),
        buyer_max_budget=Decimal("15000.00"),  # Flexible budget up to 15k
        standalone_preferred=False,
        round_idx=1
    )
    assert sales_eval["strategy"] == "BUNDLE"
    assert sales_eval["bundle_info"] is not None
    assert sales_eval["bundle_info"]["prescription"]["bundle_total"] <= Decimal("15000.00")

# 6. Bundle arithmetic equals exact item total
def test_bundle_arithmetic_exact_item_sum(db: Session):
    primary_prod = {"id": 1, "name": "Earbuds", "price": "1599.00", "cost": "1050.00", "min_selling_price": "1349.00", "inventory": 20}
    related_prods = [
        {"id": 2, "name": "Case", "price": "399.00", "cost": "250.00", "min_selling_price": "299.00", "inventory": 15, "active": True}
    ]
    pres = MerchantPricingStrategy.generate_bundle_prescription(primary_prod, related_prods)
    assert pres is not None
    item_sum = sum(item["negotiated_price"] for item in pres["bundle_items"])
    assert pres["bundle_total"] == item_sum

# 7. Every item in bundle respects its individual effective price floor
def test_every_item_in_bundle_respects_floor(db: Session):
    primary_prod = {"id": 1, "name": "Earbuds", "price": "1599.00", "cost": "1050.00", "min_selling_price": "1349.00", "inventory": 20}
    related_prods = [
        {"id": 2, "name": "Case", "price": "399.00", "cost": "250.00", "min_selling_price": "299.00", "inventory": 15, "active": True}
    ]
    pres = MerchantPricingStrategy.generate_bundle_prescription(primary_prod, related_prods, min_margin_percent=Decimal("15.00"))
    assert pres is not None
    for item in pres["bundle_items"]:
        assert item["negotiated_price"] >= item["effective_floor"]

# 8. Monotonic merchant concessions for the exact same basket
def test_monotonic_merchant_concessions():
    bounds_r1 = MerchantPricingStrategy.calculate_pricing_bounds(cost=Decimal("1000"), base_price=Decimal("1500"), min_selling_price=Decimal("1200"), inventory=25, round_idx=1)
    bounds_r2 = MerchantPricingStrategy.calculate_pricing_bounds(cost=Decimal("1000"), base_price=Decimal("1500"), min_selling_price=Decimal("1200"), inventory=25, round_idx=2)
    bounds_r3 = MerchantPricingStrategy.calculate_pricing_bounds(cost=Decimal("1000"), base_price=Decimal("1500"), min_selling_price=Decimal("1200"), inventory=25, round_idx=3)
    
    # Target prices must monotonically decrease (or stay equal at floor)
    assert bounds_r1["target_offer_price"] >= bounds_r2["target_offer_price"] >= bounds_r3["target_offer_price"]
    assert bounds_r3["target_offer_price"] >= bounds_r3["absolute_floor"]

# 9. Full orchestration produces structured conversation_events in correct chronological order
def test_orchestration_produces_structured_conversation_events(db: Session):
    provider = MockProvider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_alpha",
        intent="I want wireless earbuds under ₹2,000.",
        budget=Decimal("2000.00"),
        max_rounds=4
    )

    assert "conversation_events" in res
    events = res["conversation_events"]
    assert len(events) >= 5

    # Check first event is buyer message
    assert events[0]["actor"] == "buyer"
    assert events[0]["event_type"] == "message"

    # Check second event is SETU trust check
    assert events[1]["actor"] == "setu"
    assert events[1]["event_type"] == "trust_check"

    # Check merchant response follows
    assert any(e["actor"] == "merchant" for e in events)

    # Check final event is SETU approval/verdict
    assert events[-1]["actor"] == "setu"
    assert events[-1]["is_final"] is True

# 10. Immediate acceptance occurs ONLY when offer meets strategic acceptance threshold
def test_immediate_acceptance_on_target_offer(db: Session):
    primary_prod = {
        "id": 1,
        "name": "Wireless Earbuds",
        "price": "1599.00",
        "cost": "1050.00",
        "min_selling_price": "1349.00",
        "inventory": 25
    }
    # Full list price offer meets/exceeds target
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=[],
        buyer_offer_price=Decimal("1599.00"),
        buyer_max_budget=Decimal("2000.00"),
        round_idx=1
    )
    assert sales_eval["strategy"] == "ACCEPT"

# 11. Low budget below floor triggers HOLD_PRICE or rejection
def test_below_floor_offer_holds_or_counters_floor(db: Session):
    primary_prod = {
        "id": 1,
        "name": "Wireless Earbuds",
        "price": "1599.00",
        "cost": "1050.00",
        "min_selling_price": "1349.00",
        "inventory": 25
    }
    # Offer 900 is far below floor 1349
    sales_eval = MerchantPricingStrategy.evaluate_sales_strategy(
        primary_prod=primary_prod,
        related_prods=[],
        buyer_offer_price=Decimal("900.00"),
        buyer_max_budget=Decimal("1000.00"),
        round_idx=1
    )
    assert sales_eval["strategy"] == "HOLD_PRICE"
    assert sales_eval["recommended_standalone_price"] == Decimal("1599.00")

# 12. E2E Commerce endpoint returns conversation_events
def test_demo_commerce_api_returns_conversation_events(client: TestClient, db: Session):
    req_data = {
        "buyer_id": "test_buyer",
        "intent": "I want wireless earbuds around 1500 INR.",
        "budget": 2000.00
    }
    response = client.post("/api/demo/commerce", json=req_data)
    assert response.status_code == 200
    data = response.json()
    assert "conversation_events" in data
    assert len(data["conversation_events"]) > 0
    assert data["decision"] in ["APPROVED", "REQUIRES_APPROVAL"]

# 13. FallbackProvider automatically catches primary provider errors and completes multi-turn negotiation
def test_fallback_provider_handles_primary_failure(db: Session):
    from backend.app.agents.provider import FallbackProvider, LLMProvider
    
    class FailingProvider(LLMProvider):
        @property
        def agent_mode(self) -> str:
            return "FAILING_PROVIDER"
        @property
        def provider_name(self) -> str:
            return "FailingProvider"
        @property
        def model_name(self) -> str:
            return "fail-v1"
        def generate_response(self, prompt, system_instruction, tools):
            raise RuntimeError("429 Resource has been exhausted (quota limit reached)")
        def generate_structured_response(self, prompt, system_instruction, schema_class):
            raise RuntimeError("429 Resource has been exhausted (quota limit reached)")

    failing = FailingProvider()
    fallback_provider = FallbackProvider(primary=failing, fallback=MockProvider(), timeout_seconds=1.0)

    buyer = BuyerAgent(fallback_provider)
    merchant = MerchantAgent(fallback_provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="fallback_buyer",
        intent="I want wireless earbuds under ₹2,000.",
        budget=Decimal("2000.00"),
        max_rounds=4
    )

    assert fallback_provider.fallback_active is True
    assert "Resource has been exhausted" in fallback_provider.fallback_error
    assert res["decision"] == "APPROVED"
    assert len(res["conversation_events"]) >= 5
    assert Decimal(res["final_amount"]) > Decimal("0")

# 14. SSE Stream endpoint yields structured events progressively and terminates cleanly
def test_sse_stream_yields_events_and_terminates(client: TestClient, db: Session):
    import json
    req_data = {
        "buyer_id": "stream_buyer",
        "intent": "I want wireless earbuds under ₹2,000.",
        "budget": 2000.00
    }
    with client.stream("POST", "/api/demo/commerce/stream", json=req_data) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                events.append(payload)

    assert len(events) >= 5
    # The last event must be COMPLETE
    complete_event = next((e for e in events if e.get("type") == "complete" or e.get("event_type") == "COMPLETE"), None)
    assert complete_event is not None
    assert complete_event["result"]["decision"] == "APPROVED"

# 15. Sequence numbers in conversation_events are strictly 1-indexed and monotonic
def test_conversation_events_sequence_numbers_are_strictly_ordered(db: Session):
    provider = MockProvider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_seq",
        intent="I want Samsung Galaxy A15 with budget 15000.",
        budget=Decimal("15000.00"),
        max_rounds=4
    )

    events = res["conversation_events"]
    assert len(events) > 0
    for idx, evt in enumerate(events):
        assert evt["sequence"] == idx + 1
        assert "event_id" in evt
        assert "actor" in evt
        assert "message" in evt
        assert evt["actor"] in ["buyer", "merchant", "setu"]

# 16. Standalone preference prevents accessory bundling in full negotiation
def test_standalone_preference_in_full_negotiation(db: Session):
    provider = MockProvider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_standalone",
        intent="I only want Samsung Galaxy A15 standalone without accessories. Budget is ₹13,000.",
        budget=Decimal("13000.00"),
        max_rounds=4
    )

    assert res["decision"] in ["APPROVED", "REQUIRES_APPROVAL"]
    assert res["selected_product_id"] == 41
    # Standalone bundle should have exactly 1 item
    assert len(res["basket"]["items"]) == 1
    assert res["basket"]["items"][0]["product_id"] == 41

# 17. No approved transaction can have negotiated total <= 0
def test_approved_transaction_always_has_positive_total(db: Session):
    provider = MockProvider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_pos",
        intent="Wireless earbuds under 2000.",
        budget=Decimal("2000.00"),
        max_rounds=4
    )

    assert res["decision"] == "APPROVED"
    assert Decimal(res["final_amount"]) > Decimal("0")
    assert Decimal(res["original_amount"]) > Decimal("0")
    assert Decimal(res["margin_percent"]) >= Decimal("15.00")

# 18. Policy verification happens only after agreement
def test_policy_validation_happens_only_after_agreed_state(db: Session):
    provider = MockProvider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    res = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_policy_order",
        intent="Wireless earbuds under 2000.",
        budget=Decimal("2000.00"),
        max_rounds=4
    )

    events = res["conversation_events"]
    # Final approval must be at the very end
    policy_eval_idx = next(i for i, e in enumerate(events) if e.get("id") == "evt_final_policy_eval")
    approved_idx = next(i for i, e in enumerate(events) if e.get("id") == "evt_final_approved")

    # Both must occur after all buyer/merchant turns
    assert policy_eval_idx < approved_idx
    assert policy_eval_idx >= 3


# 19. Performance benchmark: multi-turn negotiation completes under 5 seconds
def test_negotiation_runtime_latency_under_5_seconds(db: Session):
    import time
    provider = MockProvider()
    buyer = BuyerAgent(provider)
    merchant = MerchantAgent(provider)
    orchestrator = NegotiationOrchestrator(db, buyer, merchant)

    start_time = time.perf_counter()
    res = orchestrator.run_negotiation_loop(
        buyer_id="test_perf_buyer",
        intent="I want Wireless Earbuds Pro with budget ₹2,000.",
        budget=Decimal("2000.00"),
        max_rounds=4
    )
    elapsed = time.perf_counter() - start_time

    assert res["decision"] == "APPROVED"
    assert len(res["conversation_events"]) >= 5
    assert elapsed < 5.0, f"Negotiation took too long: {elapsed:.2f}s"


# 20. Performance benchmark: SSE streaming emits first event rapidly (< 1.5s) and full stream under 5s
def test_sse_stream_latency_and_first_event_speed(db: Session, client: TestClient):
    import time
    import json
    
    req_data = {
        "buyer_id": "test_perf_sse_buyer",
        "intent": "I need wireless earbuds under 2000 INR",
        "budget": 2000.0
    }
    
    start_time = time.perf_counter()
    first_event_time = None
    events = []
    
    with client.stream("POST", "/api/demo/commerce/stream", json=req_data) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                if first_event_time is None:
                    first_event_time = time.perf_counter() - start_time
                payload = json.loads(line[6:])
                events.append(payload)

    total_time = time.perf_counter() - start_time
    assert first_event_time is not None
    assert first_event_time < 1.5, f"First SSE event was too slow: {first_event_time:.2f}s"
    assert total_time < 5.0, f"Complete SSE stream was too slow: {total_time:.2f}s"
    assert len(events) >= 5

