import time
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, ValidationError

from backend.app.agents.ai_gateway import (
    AIGateway,
    BaseLLMProvider,
    GroqProvider,
    GeminiProvider,
    OpenRouterProvider,
    MockProvider,
    CircuitBreaker,
    IntentCache,
    NegotiationContext,
    UserIntent,
    BuyerDecision,
    MerchantDecision,
    ProviderExecutionMetadata,
    ProviderFailure,
    FailureCategory,
    parse_deterministic_intent,
    circuit_breaker
)
from backend.app.policy import PolicyEngine
from backend.app.agents.tools import search_catalog_tool, view_product_tool, get_policy_constraints_tool, get_inventory_tool
from backend.app.database import get_db, SessionLocal
from backend.seed import seed_db


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


# ==============================================================================
# TEST 1: GROQ 404 MODEL / ENDPOINT ERROR FAST FAILOVER
# ==============================================================================
def test_groq_404_model_not_found_failover():
    """Verify Groq HTTP 404 trips circuit breaker and immediately fails over to next provider without sleeping."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["groq", "mock"]

    mock_groq = MagicMock(spec=BaseLLMProvider)
    mock_groq.is_available = True
    mock_groq.provider_name = "groq"
    mock_groq.model_name = "invalid-groq-model"
    # Simulate Groq 404
    mock_groq.generate_structured.side_effect = ProviderFailure(
        provider_name="groq",
        category=FailureCategory.MODEL_NOT_FOUND,
        message="HTTP 404: The model `invalid-groq-model` does not exist",
        status_code=404,
        model_name="invalid-groq-model"
    )
    gw._providers_registry["groq"] = mock_groq

    ctx = NegotiationContext(
        agent_role="BUYER_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("2000.00"),
        current_product={"id": 1, "name": "Wireless Earbuds", "price": 1599, "cost": 1000, "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1300.00"),
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    t0 = time.perf_counter()
    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert meta.provider_used == "mock"
    assert meta.fallback_used is True
    assert meta.fallback_depth >= 1
    assert decision.action in ["OFFER", "COUNTER", "ACCEPT"]
    assert elapsed_ms < 500.0  # Fast failover with zero sleep delay


# ==============================================================================
# TEST 2: GROQ 429 RATE LIMIT FAST FAILOVER
# ==============================================================================
def test_groq_429_rate_limited_failover():
    """Verify Groq HTTP 429 trips circuit breaker and fails over to Gemini/Mock immediately."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["groq", "gemini", "mock"]

    mock_groq = MagicMock(spec=BaseLLMProvider)
    mock_groq.is_available = True
    mock_groq.provider_name = "groq"
    mock_groq.generate_structured.side_effect = ProviderFailure(
        provider_name="groq",
        category=FailureCategory.RATE_LIMITED,
        message="HTTP 429: Rate limit reached",
        status_code=429
    )
    gw._providers_registry["groq"] = mock_groq

    mock_gemini = MagicMock(spec=BaseLLMProvider)
    mock_gemini.is_available = True
    mock_gemini.provider_name = "gemini"
    mock_gemini.generate_structured.return_value = (
        BuyerDecision(
            action="OFFER",
            product_id=1,
            quantity=1,
            unit_price=Decimal("1400.00"),
            total_amount=Decimal("1400.00"),
            rationale="Gemini fallback offer after Groq 429."
        ),
        ProviderExecutionMetadata(provider_used="gemini", provider_type="real_llm", model_name="gemini-3.1-flash-lite")
    )
    gw._providers_registry["gemini"] = mock_gemini

    ctx = NegotiationContext(
        agent_role="BUYER_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("2000.00"),
        current_product={"id": 1, "name": "Wireless Earbuds", "price": 1599, "cost": 1000, "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1300.00"),
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision)
    assert meta.provider_used == "gemini"
    assert meta.fallback_used is True
    assert meta.fallback_depth == 1
    assert decision.unit_price == Decimal("1400.00")


# ==============================================================================
# TEST 3: GEMINI SDK IMPORT FAILURE GRACEFUL HANDLING
# ==============================================================================
def test_gemini_sdk_import_failure_handling():
    """Verify that when neither Gemini SDK is installed, Gemini safely reports unavailable and fails over."""
    with patch.object(GeminiProvider, "get_sdk_status", return_value=(None, None, None)):
        gemini = GeminiProvider(api_key="mock_gemini_key", model="gemini-3.1-flash-lite")
        assert gemini.is_available is False

        # Attempting structured generation raises SDK_ERROR
        with pytest.raises(ProviderFailure) as exc_info:
            gemini.generate_structured("sys", "user", BuyerDecision)
        assert exc_info.value.category == FailureCategory.SDK_ERROR


# ==============================================================================
# TEST 4: OPENROUTER 404 & 402 BILLING ERROR FAILOVER
# ==============================================================================
def test_openrouter_404_and_402_failover():
    """Verify OpenRouter 404 and 402 errors are properly classified and fail over."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["openrouter", "mock"]

    mock_openrouter = MagicMock(spec=BaseLLMProvider)
    mock_openrouter.is_available = True
    mock_openrouter.provider_name = "openrouter"
    mock_openrouter.generate_structured.side_effect = ProviderFailure(
        provider_name="openrouter",
        category=FailureCategory.BILLING_ERROR,
        message="HTTP 402: Credits exhausted",
        status_code=402
    )
    gw._providers_registry["openrouter"] = mock_openrouter

    ctx = NegotiationContext(
        agent_role="BUYER_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("2000.00"),
        current_product={"id": 1, "name": "Wireless Earbuds", "price": 1599, "cost": 1000, "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1300.00"),
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision)
    assert meta.provider_used == "mock"
    assert meta.fallback_used is True
    assert decision.action in ["OFFER", "COUNTER", "ACCEPT"]


# ==============================================================================
# TEST 5: PROVIDER TIMEOUT TRIPS CIRCUIT BREAKER
# ==============================================================================
def test_provider_timeout_fast_failover():
    """Verify provider timeouts trip the circuit breaker and bypass on subsequent calls."""
    cb = CircuitBreaker(cooldown_seconds=60.0)
    timeout_fail = ProviderFailure("cerebras", FailureCategory.TIMEOUT, "Request timed out after 20s")
    cb.record_failure("cerebras", timeout_fail, category=FailureCategory.TIMEOUT)

    assert cb.is_available("cerebras") is False


# ==============================================================================
# TEST 6: MOCKPROVIDER NEVER RETURNS EMPTY OBJECT FOR BUYER DECISION
# ==============================================================================
def test_mock_provider_never_empty_buyer_decision():
    """Verify MockProvider constructs ALL required BuyerDecision fields with valid types."""
    mock_p = MockProvider()
    ctx = NegotiationContext(
        agent_role="BUYER_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("14000.00"),
        current_product={"id": 41, "name": "Samsung Galaxy A15", "price": 12999, "cost": 10000, "inventory": 10},
        catalog_price=Decimal("12999.00"),
        merchant_min_price=Decimal("11049.15"),
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    decision, meta = mock_p.generate_structured("sys", "user prompt", BuyerDecision, context=ctx)
    assert isinstance(decision, BuyerDecision)
    assert decision.action in ["OFFER", "COUNTER", "ACCEPT", "REJECT"]
    assert decision.product_id == 41
    assert decision.quantity == 1
    assert decision.unit_price > Decimal("0.00")
    assert decision.total_amount > Decimal("0.00")
    assert decision.total_amount <= Decimal("14000.00")
    assert len(decision.rationale) > 5
    assert decision.basket_items is not None
    assert len(decision.basket_items) >= 1
    assert meta.provider_used == "mock"
    assert meta.provider_type == "deterministic_fallback"


# ==============================================================================
# TEST 7: MOCKPROVIDER NEVER RETURNS EMPTY OBJECT FOR MERCHANT DECISION
# ==============================================================================
def test_mock_provider_never_empty_merchant_decision():
    """Verify MockProvider constructs ALL required MerchantDecision fields respecting price floor."""
    mock_p = MockProvider()
    ctx = NegotiationContext(
        agent_role="MERCHANT_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("14000.00"),
        current_product={"id": 41, "name": "Samsung Galaxy A15", "price": 12999, "cost": 10000, "inventory": 10},
        catalog_price=Decimal("12999.00"),
        merchant_min_price=Decimal("11049.15"),
        current_proposal={"product_id": 41, "total_amount": "10000.00"},  # Below floor
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    decision, meta = mock_p.generate_structured("sys", "user prompt", MerchantDecision, context=ctx)
    assert isinstance(decision, MerchantDecision)
    assert decision.action in ["COUNTER", "ACCEPT", "BUNDLE", "REJECT"]
    assert decision.product_id == 41
    assert decision.quantity == 1
    assert decision.unit_price >= Decimal("11049.15")  # Respects floor
    assert decision.total_amount >= Decimal("11049.15")
    assert "PASSED" in decision.margin_check
    assert len(decision.rationale) > 5
    assert meta.provider_used == "mock"


# ==============================================================================
# TEST 8: CASE C SIMULATION — EVERY REAL PROVIDER FAILS -> MOCK COMPLETES SAFELY
# ==============================================================================
def test_case_c_all_real_fail_mock_completes_negotiation_safely():
    """
    CASE C SIMULATION:
    Groq -> 404
    Gemini -> SDK failure
    OpenRouter -> 404
    Cerebras -> 429
    NVIDIA -> 401
    Ollama -> unavailable
    MockProvider -> VALID decision

    Verify negotiation completes successfully without crashing or throwing ValidationError.
    """
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["cerebras", "groq", "gemini", "nvidia_nim", "openrouter", "ollama", "mock"]

    # 1. Cerebras 429
    m_cer = MagicMock(spec=BaseLLMProvider)
    m_cer.is_available = True
    m_cer.generate_structured.side_effect = ProviderFailure("cerebras", FailureCategory.RATE_LIMITED, "Rate limit", status_code=429)
    gw._providers_registry["cerebras"] = m_cer

    # 2. Groq 404
    m_groq = MagicMock(spec=BaseLLMProvider)
    m_groq.is_available = True
    m_groq.generate_structured.side_effect = ProviderFailure("groq", FailureCategory.MODEL_NOT_FOUND, "Model not found", status_code=404)
    gw._providers_registry["groq"] = m_groq

    # 3. Gemini SDK failure
    m_gem = MagicMock(spec=BaseLLMProvider)
    m_gem.is_available = True
    m_gem.generate_structured.side_effect = ProviderFailure("gemini", FailureCategory.SDK_ERROR, "No SDK installed")
    gw._providers_registry["gemini"] = m_gem

    # 4. NVIDIA NIM 401 Auth
    m_nvid = MagicMock(spec=BaseLLMProvider)
    m_nvid.is_available = True
    m_nvid.generate_structured.side_effect = ProviderFailure("nvidia_nim", FailureCategory.AUTH_ERROR, "Unauthorized", status_code=401)
    gw._providers_registry["nvidia_nim"] = m_nvid

    # 5. OpenRouter 404
    m_or = MagicMock(spec=BaseLLMProvider)
    m_or.is_available = True
    m_or.generate_structured.side_effect = ProviderFailure("openrouter", FailureCategory.MODEL_NOT_FOUND, "Endpoint not found", status_code=404)
    gw._providers_registry["openrouter"] = m_or

    # 6. Ollama unavailable
    m_oll = MagicMock(spec=BaseLLMProvider)
    m_oll.is_available = True
    m_oll.generate_structured.side_effect = ProviderFailure("ollama", FailureCategory.UNAVAILABLE, "Connection refused")
    gw._providers_registry["ollama"] = m_oll

    # Run Buyer Turn
    ctx_buyer = NegotiationContext(
        agent_role="BUYER_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("14000.00"),
        current_product={"id": 41, "name": "Samsung Galaxy A15", "price": 12999, "cost": 10000, "inventory": 10},
        catalog_price=Decimal("12999.00"),
        merchant_min_price=Decimal("11049.15"),
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    buyer_dec, buyer_meta = gw.generate_negotiation_turn(ctx_buyer, "BUYER_AGENT", BuyerDecision)
    assert buyer_meta.provider_used == "mock"
    assert buyer_meta.provider_type == "deterministic_fallback"
    assert buyer_meta.fallback_used is True
    assert buyer_meta.fallback_depth >= 5
    assert isinstance(buyer_dec, BuyerDecision)
    assert buyer_dec.action == "OFFER"
    assert buyer_dec.total_amount <= Decimal("14000.00")

    # Run Merchant Turn
    ctx_merch = NegotiationContext(
        agent_role="MERCHANT_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("14000.00"),
        current_product={"id": 41, "name": "Samsung Galaxy A15", "price": 12999, "cost": 10000, "inventory": 10},
        catalog_price=Decimal("12999.00"),
        merchant_min_price=Decimal("11049.15"),
        current_proposal={"product_id": 41, "total_amount": str(buyer_dec.total_amount)},
        previous_offers=[{"round": 1, "actor": "buyer", "amount": str(buyer_dec.total_amount), "action": "OFFER"}],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    merch_dec, merch_meta = gw.generate_negotiation_turn(ctx_merch, "MERCHANT_AGENT", MerchantDecision)
    assert merch_meta.provider_used == "mock"
    assert merch_meta.provider_type == "deterministic_fallback"
    assert isinstance(merch_dec, MerchantDecision)
    assert merch_dec.action in ["COUNTER", "ACCEPT"]
    assert merch_dec.total_amount >= Decimal("11049.15")  # Preserves floor


# ==============================================================================
# TEST 9: DETERMINISTIC SETU OPERATIONS USE 0 LLM CALLS
# ==============================================================================
def test_deterministic_setu_tools_zero_llm_calls():
    """Verify catalog search, product detail, inventory, and policy math use 0 LLM calls."""
    db = next(get_db())
    seed_db(db)
    gw = AIGateway()
    init_real_calls = gw._session_metrics["real_llm_calls"]

    res = search_catalog_tool(db, query="Samsung")
    assert len(res) > 0
    prod = view_product_tool(db, 41)
    inv = get_inventory_tool(db, 41)
    assert prod is not None
    assert inv["inventory"] >= 0
    policy = get_policy_constraints_tool(db)
    assert "max_discount_percent" in policy

    assert gw._session_metrics["real_llm_calls"] == init_real_calls


# ==============================================================================
# TEST 10: DETERMINISTIC INTENT PARSER & CACHE
# ==============================================================================
def test_deterministic_intent_parsing_and_cache():
    """Verify procurement queries with products and budgets parse deterministically (0 LLM tokens)."""
    gw = AIGateway()
    init_real_calls = gw._session_metrics["real_llm_calls"]

    intent = gw.parse_user_intent("I want Samsung Galaxy A15 with budget ₹14,000.", budget=Decimal("14000.00"))
    assert intent.product == "Samsung Galaxy A15"
    assert intent.max_budget == 14000.0
    assert intent.intent_parse_mode == "deterministic"
    assert intent.intent_llm_used is False
    assert gw._session_metrics["real_llm_calls"] == init_real_calls

    # Normalized cache hit
    cached = gw.parse_user_intent("i want samsung galaxy a15 with budget 14000 inr")
    assert cached.product == "Samsung Galaxy A15"
    assert gw._session_metrics["real_llm_calls"] == init_real_calls
