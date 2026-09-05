import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from backend.app.agents.provider import (
    LLMProvider,
    ProviderExecutionMetadata,
    MockProvider,
    BuyerDecision,
    MerchantDecision,
    BasketItemSchema
)
from backend.app.agents.orchestrator import NegotiationOrchestrator
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Product, MerchantPolicy, PurchaseRequest

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

class FakeRealProvider(LLMProvider):
    """Simulates a real LLM provider (e.g. Gemini / Groq) returning structured decisions."""
    def __init__(self, provider_name: str, model_name: str):
        super().__init__()
        self._provider_name = provider_name
        self._model_name = model_name
        self.last_execution_metadata = None
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def agent_mode(self) -> str:
        return "LIVE"

    def generate_response(self, prompt: str, system_instruction: str = None, tools: list = None):
        return {"text": "Fake response"}

    def get_last_execution_metadata(self):
        return self.last_execution_metadata

    def generate_structured_response(self, prompt: str, system_instruction: str, response_model):
        self.call_count += 1
        self.last_execution_metadata = ProviderExecutionMetadata(
            provider_used=self.provider_name,
            provider_type="real_llm",
            model_name=self.model_name,
            agent_role="agent",
            fallback_used=False,
            fallback_depth=0,
            fallback_reason=None,
            response_latency_ms=120.0,
            provider_attempts=[{"provider": self.provider_name, "model": self.model_name, "success": True, "latency_ms": 120.0}]
        )
        if response_model == BuyerDecision:
            return BuyerDecision(
                action="COUNTER",
                product_id=1,
                unit_price=Decimal("1480.00"),
                quantity=1,
                total_amount=Decimal("1480.00"),
                rationale="Buyer opening proposal within budget.",
                message="I'd like to offer ₹1,480 for the Wireless Earbuds.",
                constraints_checked=["budget_fit", "catalog_price_bound"],
                basket_items=[
                    BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1480.00"), is_primary=True)
                ]
            )
        elif response_model == MerchantDecision:
            return MerchantDecision(
                action="COUNTER",
                product_id=1,
                unit_price=Decimal("1500.00"),
                quantity=1,
                total_amount=Decimal("1500.00"),
                margin_check="Margin check: PASSED",
                rationale="Merchant counter defending minimum margin.",
                message="I can offer ₹1,500 for the standalone product.",
                basket_items=[
                    BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("1500.00"), is_primary=True)
                ]
            )
        return response_model()

def test_negotiation_uses_at_most_3_real_llm_calls(db_session):
    """Test 1: Normal negotiation uses <= 3 real LLM calls."""
    buyer_p = FakeRealProvider("gemini", "gemini-3.5-flash-lite")
    merchant_p = FakeRealProvider("groq", "openai/gpt-oss-20b")
    
    buyer = BuyerAgent(provider=buyer_p)
    merchant = MerchantAgent(provider=merchant_p)
    orchestrator = NegotiationOrchestrator(db=db_session, buyer=buyer, merchant=merchant)

    result = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_1",
        intent="I need Wireless Earbuds under 2000",
        budget=Decimal("2000.00"),
        max_llm_calls=3
    )

    summary = result["provider_summary"]
    assert summary["real_llm_calls"] <= 3
    assert summary["total_llm_calls"] <= 3
    assert summary["real_llm_calls"] == buyer_p.call_count + merchant_p.call_count
    assert result["decision"] in ("APPROVED", "REQUIRES_APPROVAL")

def test_early_agreement_uses_only_2_llm_calls(db_session):
    """Test 2: Negotiation where merchant accepts buyer's opening offer uses exactly 2 LLM calls."""
    class AcceptingMerchantProvider(FakeRealProvider):
        def generate_structured_response(self, prompt: str, system_instruction: str, response_model):
            self.call_count += 1
            self.last_execution_metadata = ProviderExecutionMetadata(
                provider_used=self.provider_name,
                provider_type="real_llm",
                model_name=self.model_name,
                agent_role="MERCHANT_AGENT",
                fallback_used=False,
                fallback_depth=0,
                response_latency_ms=100.0,
                provider_attempts=[{"provider": self.provider_name, "model": self.model_name, "success": True, "latency_ms": 100.0}]
            )
            return MerchantDecision(
                action="ACCEPT",
                product_id=1,
                unit_price=Decimal("1480.00"),
                quantity=1,
                total_amount=Decimal("1480.00"),
                margin_check="Margin check: PASSED",
                rationale="Accepted buyer opening price above floor.",
                message="Deal agreed! I'll accept ₹1,480."
            )

    buyer_p = FakeRealProvider("gemini", "gemini-3.5-flash-lite")
    merchant_p = AcceptingMerchantProvider("groq", "openai/gpt-oss-20b")

    buyer = BuyerAgent(provider=buyer_p)
    merchant = MerchantAgent(provider=merchant_p)
    orchestrator = NegotiationOrchestrator(db=db_session, buyer=buyer, merchant=merchant)

    result = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_early",
        intent="I need Wireless Earbuds under 2000",
        budget=Decimal("2000.00"),
        max_llm_calls=3
    )

    summary = result["provider_summary"]
    assert summary["real_llm_calls"] == 2
    assert summary["buyer_llm_calls"] == 1
    assert summary["merchant_llm_calls"] == 1
    assert summary["mock_calls"] == 0
    assert result["decision"] == "APPROVED"

def test_deterministic_turns_do_not_increment_real_llm_calls(db_session):
    """Test 4: Deterministic turns are tracked separately and do not increment real_llm_calls."""
    buyer_p = FakeRealProvider("gemini", "gemini-3.5-flash-lite")
    merchant_p = FakeRealProvider("groq", "openai/gpt-oss-20b")

    buyer = BuyerAgent(provider=buyer_p)
    merchant = MerchantAgent(provider=merchant_p)
    orchestrator = NegotiationOrchestrator(db=db_session, buyer=buyer, merchant=merchant)

    events = []
    result = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_det",
        intent="I need Wireless Earbuds under 2000",
        budget=Decimal("2000.00"),
        max_llm_calls=2,  # Force LLM budget of 2 so turn 3 is deterministic
        on_event=lambda e: events.append(e)
    )

    summary = result["provider_summary"]
    assert summary["real_llm_calls"] == 2
    assert summary["deterministic_turns"] >= 1
    assert summary["llm_budget"] == 2
    assert summary["llm_budget_remaining"] == 0

    det_events = [e for e in events if e.get("is_deterministic") or e.get("provider_used") == "deterministic_engine"]
    assert len(det_events) >= 1
    for de in det_events:
        assert de["provider_used"] == "deterministic_engine"
        assert de["provider_type"] == "deterministic_turn"

def test_sequential_negotiations_remain_independent(db_session):
    """Test 10: Three consecutive negotiations remain independent and adhere to <= 3 LLM calls each."""
    for run_idx in range(1, 4):
        buyer_p = FakeRealProvider("gemini", "gemini-3.5-flash-lite")
        merchant_p = FakeRealProvider("groq", "openai/gpt-oss-20b")

        buyer = BuyerAgent(provider=buyer_p)
        merchant = MerchantAgent(provider=merchant_p)
        orchestrator = NegotiationOrchestrator(db=db_session, buyer=buyer, merchant=merchant)

        result = orchestrator.run_negotiation_loop(
            buyer_id=f"test_buyer_seq_{run_idx}",
            intent="I need Wireless Earbuds under 2000",
            budget=Decimal("2000.00"),
            max_llm_calls=3
        )

        summary = result["provider_summary"]
        assert summary["real_llm_calls"] <= 3
        assert summary["mock_calls"] == 0
        assert summary["mock_fallback_status"] == "NOT USED"
        assert result["decision"] == "APPROVED"

def test_financial_guardrails_remain_deterministic(db_session):
    """Test 11 & 12: Deterministic engine prevents selling below floor price."""
    class UndersellingBuyerProvider(FakeRealProvider):
        def generate_structured_response(self, prompt: str, system_instruction: str, response_model):
            self.call_count += 1
            self.last_execution_metadata = ProviderExecutionMetadata(
                provider_used=self.provider_name,
                provider_type="real_llm",
                model_name=self.model_name,
                agent_role="BUYER_AGENT",
                fallback_used=False,
                fallback_depth=0,
                response_latency_ms=80.0,
                provider_attempts=[{"provider": self.provider_name, "model": self.model_name, "success": True, "latency_ms": 80.0}]
            )
            # Offer ₹500 for a product with ₹1,050 cost (min selling price ₹1,440)
            return BuyerDecision(
                action="COUNTER",
                product_id=1,
                unit_price=Decimal("500.00"),
                quantity=1,
                total_amount=Decimal("500.00"),
                rationale="Attempting extreme lowball.",
                message="I only want to pay ₹500.",
                constraints_checked=["budget_fit", "catalog_price_bound"],
                basket_items=[
                    BasketItemSchema(product_id=1, name="Wireless Earbuds Pro", quantity=1, original_price=Decimal("1599.00"), negotiated_price=Decimal("500.00"), is_primary=True)
                ]
            )

    buyer_p = UndersellingBuyerProvider("gemini", "gemini-3.5-flash-lite")
    merchant_p = FakeRealProvider("groq", "openai/gpt-oss-20b")

    buyer = BuyerAgent(provider=buyer_p)
    merchant = MerchantAgent(provider=merchant_p)
    orchestrator = NegotiationOrchestrator(db=db_session, buyer=buyer, merchant=merchant)

    result = orchestrator.run_negotiation_loop(
        buyer_id="test_buyer_guardrail",
        intent="I need Wireless Earbuds under 2000",
        budget=Decimal("2000.00"),
        max_llm_calls=3
    )

    # The agreed final price must NEVER be below the merchant floor (₹1,440.00)
    assert Decimal(str(result["final_amount"])) >= Decimal("1440.00")
    assert Decimal(str(result["margin_percent"])) >= Decimal("15.00")
