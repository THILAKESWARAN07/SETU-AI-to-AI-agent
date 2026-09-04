import time
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from pydantic import BaseModel

from backend.app.agents.ai_gateway import (
    AIGateway,
    BaseLLMProvider,
    CircuitBreaker,
    IntentCache,
    NegotiationContext,
    UserIntent,
    BuyerDecision,
    MerchantDecision,
    ProviderExecutionMetadata,
    MockProvider,
    parse_deterministic_intent
)
from backend.app.policy import PolicyEngine
from backend.app.agents.tools import search_catalog_tool, view_product_tool, get_policy_constraints_tool, get_inventory_tool
from backend.app.database import get_db
from backend.seed import seed_db


# ==============================================================================
# TEST 1: BUYER REAL LLM CALL
# ==============================================================================
def test_buyer_real_llm_call_increments_metric():
    """Verify healthy provider yields real_llm_calls increment and provider metadata."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["groq", "mock"]

    mock_groq = MagicMock(spec=BaseLLMProvider)
    mock_groq.is_available = True
    mock_groq.provider_name = "groq"
    mock_decision = BuyerDecision(
        action="OFFER",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1400.00"),
        total_amount=Decimal("1400.00"),
        rationale="Realistic buyer offer."
    )
    mock_meta = ProviderExecutionMetadata(
        provider_used="groq",
        provider_type="real_llm",
        model_name="groq/compound-mini",
        fallback_used=False
    )
    mock_groq.generate_structured.return_value = (mock_decision, mock_meta)
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

    initial_calls = gw._session_metrics["real_llm_calls"]
    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision)

    assert meta.provider_used == "groq"
    assert meta.provider_type == "real_llm"
    assert gw._session_metrics["real_llm_calls"] == initial_calls + 1
    assert decision.action == "OFFER"


# ==============================================================================
# TEST 2: MERCHANT REAL LLM CALL
# ==============================================================================
def test_merchant_real_llm_call_increments_metric():
    """Verify healthy merchant provider yields real_llm_calls increment."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["cerebras", "mock"]

    mock_cerebras = MagicMock(spec=BaseLLMProvider)
    mock_cerebras.is_available = True
    mock_cerebras.provider_name = "cerebras"
    mock_decision = MerchantDecision(
        action="COUNTER",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1499.00"),
        total_amount=Decimal("1499.00"),
        rationale="Profitable merchant counter."
    )
    mock_meta = ProviderExecutionMetadata(
        provider_used="cerebras",
        provider_type="real_llm",
        model_name="llama3.1-70b",
        fallback_used=False
    )
    mock_cerebras.generate_structured.return_value = (mock_decision, mock_meta)
    gw._providers_registry["cerebras"] = mock_cerebras

    ctx = NegotiationContext(
        agent_role="MERCHANT_AGENT",
        current_round=2,
        buyer_max_budget=Decimal("2000.00"),
        current_product={"id": 1, "name": "Wireless Earbuds", "price": 1599, "cost": 1000, "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1300.00"),
        current_proposal={"product_id": 1, "unit_price": "1400.00", "total_amount": "1400.00"},
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=2
    )

    initial_calls = gw._session_metrics["real_llm_calls"]
    decision, meta = gw.generate_negotiation_turn(ctx, "MERCHANT_AGENT", MerchantDecision)

    assert meta.provider_used == "cerebras"
    assert meta.provider_type == "real_llm"
    assert gw._session_metrics["real_llm_calls"] == initial_calls + 1
    assert decision.action == "COUNTER"


# ==============================================================================
# TEST 3: NO UNNECESSARY LLM OPERATIONS
# ==============================================================================
def test_no_unnecessary_llm_operations():
    """Verify catalog search, inventory, price calculation, policy check use 0 LLM calls."""
    db = next(get_db())
    seed_db(db)
    gw = AIGateway()
    init_real_calls = gw._session_metrics["real_llm_calls"]

    # 1. Search catalog (SQL)
    res = search_catalog_tool(db, query="earbuds")
    assert len(res) > 0

    # 2. View product & inventory (SQL)
    prod = view_product_tool(db, 1)
    inv = get_inventory_tool(db, 1)
    assert prod is not None
    assert inv["inventory"] >= 0

    # 3. Policy evaluation (Python math)
    policy = get_policy_constraints_tool(db)
    assert "max_discount_percent" in policy

    # Verify zero external LLM calls were made
    assert gw._session_metrics["real_llm_calls"] == init_real_calls


# ==============================================================================
# TEST 4: PROVIDER FALLBACK (Cerebras 429 -> Groq called next)
# ==============================================================================
def test_provider_fallback_cerebras_to_groq():
    """Verify when Cerebras hits 429, Groq is immediately called without falling back to Mock."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["cerebras", "groq", "mock"]

    mock_cerebras = MagicMock(spec=BaseLLMProvider)
    mock_cerebras.is_available = True
    mock_cerebras.generate_structured.side_effect = RuntimeError("429 ResourceExhausted: rate limit reached")
    gw._providers_registry["cerebras"] = mock_cerebras

    mock_groq = MagicMock(spec=BaseLLMProvider)
    mock_groq.is_available = True
    mock_groq.provider_name = "groq"
    mock_groq.generate_structured.return_value = (
        BuyerDecision(action="OFFER", product_id=1, quantity=1, unit_price=Decimal("1420.00"), total_amount=Decimal("1420.00"), rationale="Groq fallback offer"),
        ProviderExecutionMetadata(provider_used="groq", provider_type="real_llm", model_name="groq/compound-mini", fallback_used=True, fallback_depth=1)
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

    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision)
    assert meta.provider_used == "groq"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_depth == 1
    assert decision.total_amount == Decimal("1420.00")


# ==============================================================================
# TEST 5: ALL PROVIDERS FAIL -> MOCK FALLBACK
# ==============================================================================
def test_all_providers_fail_to_mock():
    """Verify priority chain falls through to MockProvider gracefully when all real providers fail."""
    gw = AIGateway()
    for p_name in ["cerebras", "groq", "gemini", "nvidia_nim", "openrouter", "ollama"]:
        mock_fail = MagicMock(spec=BaseLLMProvider)
        mock_fail.is_available = True
        mock_fail.generate_structured.side_effect = RuntimeError(f"{p_name} 429 RateLimitExceeded")
        gw._providers_registry[p_name] = mock_fail

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
# TEST 6: CIRCUIT BREAKER BYPASSES PROVIDER DURING COOLDOWN
# ==============================================================================
def test_circuit_breaker_bypasses_provider_during_cooldown():
    """Verify CircuitBreaker trips to OPEN on 429 and subsequent turn bypasses with 0 network calls."""
    cb = CircuitBreaker(cooldown_seconds=60.0)
    assert cb.is_available("gemini") is True

    # Record 429
    cb.record_failure("gemini", RuntimeError("429 ResourceExhausted"), status_code=429)
    assert cb.is_available("gemini") is False

    # Next check during cooldown is instant False without executing network call
    t0 = time.perf_counter()
    avail = cb.is_available("gemini")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert avail is False
    assert elapsed_ms < 1.0  # < 1ms fast check


# ==============================================================================
# TEST 7: INVALID LLM OUTPUT CLAMPED / VALIDATED
# ==============================================================================
def test_invalid_llm_output_clamped_by_policy():
    """Verify LLM proposing over-budget price is deterministically clamped."""
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["cerebras", "mock"]

    ctx = NegotiationContext(
        agent_role="BUYER_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("1500.00"),
        current_product={"id": 1, "name": "Wireless Earbuds", "price": 1599, "cost": 1000, "inventory": 10},
        catalog_price=Decimal("1599.00"),
        merchant_min_price=Decimal("1300.00"),
        previous_offers=[],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    mock_bad_p = MagicMock(spec=BaseLLMProvider)
    mock_bad_p.is_available = True
    bad_decision = BuyerDecision(
        action="OFFER",
        product_id=1,
        quantity=1,
        unit_price=Decimal("1900.00"),
        total_amount=Decimal("1900.00"),
        rationale="Over budget proposal"
    )
    meta_p = ProviderExecutionMetadata(provider_used="cerebras", provider_type="real_llm", model_name="llama3.1-70b")
    mock_bad_p.generate_structured.return_value = (bad_decision, meta_p)
    gw._providers_registry["cerebras"] = mock_bad_p

    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision, max_retries=0)
    assert decision.total_amount <= Decimal("1500.00")


# ==============================================================================
# TEST 8: DETERMINISTIC INTENT PARSING (0 TOKENS)
# ==============================================================================
def test_deterministic_intent_parsing_and_cache():
    """Verify structured procurement queries are parsed deterministically with 0 LLM calls."""
    gw = AIGateway()
    init_real_calls = gw._session_metrics["real_llm_calls"]

    intent = gw.parse_user_intent("I want Samsung Galaxy A15 with budget ₹14,000.", budget=Decimal("14000.00"))
    assert intent.product == "Samsung Galaxy A15"
    assert intent.max_budget == 14000.0
    assert intent.intent_parse_mode == "deterministic"
    assert intent.intent_llm_used is False
    assert gw._session_metrics["real_llm_calls"] == init_real_calls

    # Cache check
    cached = gw.parse_user_intent("i want samsung galaxy a15 with budget 14000 inr")
    assert cached.product == "Samsung Galaxy A15"
    assert gw._session_metrics["real_llm_calls"] == init_real_calls
