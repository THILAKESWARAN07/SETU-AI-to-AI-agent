import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from backend.app.agents.provider import (
    ProviderExecutionMetadata,
    MockProvider,
    GeminiProvider,
    FallbackProvider,
    BuyerDecision,
    MerchantDecision,
    get_provider
)
from backend.app.agents.orchestrator import NegotiationOrchestrator
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Product, MerchantPolicy

@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    # Ensure sample products exist
    p1 = db.query(Product).filter(Product.id == 1).first()
    if not p1:
        p1 = Product(id=1, name="Wireless Earbuds Pro", category="Audio", price=Decimal("1599.00"), cost=Decimal("1050.00"), min_selling_price=Decimal("1440.00"), inventory=50, active=True, related_product_ids=[2])
        db.add(p1)
    p2 = db.query(Product).filter(Product.id == 2).first()
    if not p2:
        p2 = Product(id=2, name="Premium Charging Case", category="Accessories", price=Decimal("399.00"), cost=Decimal("200.00"), min_selling_price=Decimal("300.00"), inventory=100, active=True, related_product_ids=[])
        db.add(p2)
    p41 = db.query(Product).filter(Product.id == 41).first()
    if not p41:
        p41 = Product(id=41, name="Samsung Galaxy A15", category="Mobile Phones", price=Decimal("12999.00"), cost=Decimal("9500.00"), min_selling_price=Decimal("11499.00"), inventory=25, active=True, related_product_ids=[44, 45, 46])
        db.add(p41)

    policy = db.query(MerchantPolicy).filter(MerchantPolicy.active == True).first()
    if not policy:
        policy = MerchantPolicy(max_discount_percent=Decimal("15.00"), min_margin_percent=Decimal("15.00"), max_auto_order_amount=Decimal("50000.00"), require_approval_above=Decimal("50000.00"), policy_version="v1.0", active=True)
        db.add(policy)

    db.commit()
    yield db
    db.close()


def test_mock_provider_records_metadata():
    provider = MockProvider()
    res = provider.generate_structured_response("I need earbuds", "You are a buyer", BuyerDecision)
    meta = provider.get_last_execution_metadata()
    
    assert meta is not None
    assert meta.provider_used == "mock"
    assert meta.model_name == "mock-model-v2"
    assert meta.fallback_used is False
    assert meta.fallback_reason is None
    assert meta.response_latency_ms >= 0.0


def test_fallback_provider_primary_success():
    primary_mock = MagicMock(spec=MockProvider)
    primary_mock.provider_name = "Gemini"
    primary_mock.model_name = "gemini-2.5-flash"
    primary_mock.agent_mode = "LIVE LLM"
    
    dummy_decision = BuyerDecision(
        action="OFFER",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1450.00"),
        total_amount=Decimal("1450.00"),
        rationale="Primary Gemini offer",
        constraints_checked=[]
    )
    
    primary_meta = ProviderExecutionMetadata(
        provider_used="gemini",
        model_name="gemini-2.5-flash",
        fallback_used=False,
        fallback_reason=None,
        response_latency_ms=120.5
    )
    primary_mock.last_execution_metadata = primary_meta
    primary_mock.generate_structured_response.return_value = dummy_decision
    
    fallback = FallbackProvider(primary=primary_mock, fallback=MockProvider(), timeout_seconds=5.0)
    result = fallback.generate_structured_response("prompt", "sys", BuyerDecision)
    
    meta = fallback.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "gemini"
    assert meta.model_name == "gemini-2.5-flash"
    assert meta.fallback_used is False
    assert meta.fallback_reason is None


def test_fallback_provider_handles_timeout_and_records_reason():
    primary_mock = MagicMock(spec=MockProvider)
    primary_mock.provider_name = "Gemini"
    primary_mock.model_name = "gemini-2.5-flash"
    primary_mock.agent_mode = "LIVE LLM"
    
    import time
    def slow_call(*args, **kwargs):
        time.sleep(1.0)
        return BuyerDecision(action="OFFER", product_id=1, quantity=1, unit_price=Decimal("1000.00"), total_amount=Decimal("1000.00"), rationale="too slow")
    
    primary_mock.generate_structured_response.side_effect = slow_call
    
    fallback = FallbackProvider(primary=primary_mock, fallback=MockProvider(), timeout_seconds=0.1)
    result = fallback.generate_structured_response("prompt", "sys", BuyerDecision)
    
    assert fallback.fallback_active is True
    meta = fallback.get_last_execution_metadata()
    assert meta is not None
    assert meta.provider_used == "mock"
    assert meta.fallback_used is True
    assert "TimeoutError" in meta.fallback_reason
    assert meta.response_latency_ms >= 100.0


def test_orchestrator_negotiation_events_have_provider_metadata(db_session):
    provider = MockProvider()
    buyer = BuyerAgent(provider=provider)
    merchant = MerchantAgent(provider=provider)
    orchestrator = NegotiationOrchestrator(db_session, buyer=buyer, merchant=merchant)
    
    streamed_events = []
    result = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_obs",
        intent="I need Wireless Earbuds under 2000",
        budget=Decimal("2000.00"),
        on_event=lambda evt: streamed_events.append(evt)
    )
    
    # Verify events emitted
    agent_events = [e for e in streamed_events if e.get("actor") in ("buyer", "merchant")]
    assert len(agent_events) >= 2
    for evt in agent_events:
        assert "provider_used" in evt
        assert evt["provider_used"] in ("gemini", "mock", "openai")
        assert "fallback_used" in evt
        assert "response_latency_ms" in evt
    
    # Verify final result summary
    assert "provider_summary" in result
    summary = result["provider_summary"]
    assert "gemini_calls" in summary
    assert "mock_calls" in summary
    assert "fallback_count" in summary
    assert "all_agent_turns_used_gemini" in summary
    assert summary["mock_calls"] >= 2
    assert summary["all_agent_turns_used_gemini"] is False
