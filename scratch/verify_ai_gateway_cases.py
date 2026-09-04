import os
import sys
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

# Add workspace to path
sys.path.insert(0, r"c:\Users\HP\OneDrive\Pictures\Desktop\SETU-AI-to-AI-agent")

from backend.app.config import settings
from backend.app.database import SessionLocal
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
    BasketItemSchema,
    ProviderExecutionMetadata,
    ProviderFailure,
    FailureCategory,
    ai_gateway
)
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.orchestrator import NegotiationOrchestrator, NegotiationError

def banner(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def verify_case_a_real_provider_success():
    banner("CASE A: FIRST REAL PROVIDER SUCCEEDS")
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["groq", "gemini", "mock"]

    mock_groq = MagicMock(spec=BaseLLMProvider)
    mock_groq.is_available = True
    mock_groq.provider_name = "groq"
    mock_groq.model_name = "groq/compound-mini"
    
    mock_decision = BuyerDecision(
        action="OFFER",
        product_id=41,
        quantity=1,
        unit_price=Decimal("12000.00"),
        total_amount=Decimal("12000.00"),
        rationale="Buyer proposing realistic discount on Samsung Galaxy A15."
    )
    mock_meta = ProviderExecutionMetadata(
        provider_used="groq",
        provider_type="real_llm",
        model_name="groq/compound-mini",
        fallback_used=False,
        fallback_depth=0,
        response_latency_ms=150.0
    )
    mock_groq.generate_structured.return_value = (mock_decision, mock_meta)
    gw._providers_registry["groq"] = mock_groq

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

    decision, meta = gw.generate_negotiation_turn(ctx, "BUYER_AGENT", BuyerDecision)
    print(f"  [RESULT] Provider Used:   {meta.provider_used.upper()} ({meta.provider_type})")
    print(f"  [RESULT] Model Name:      {meta.model_name}")
    print(f"  [RESULT] Fallback Used:   {meta.fallback_used} (Depth: {meta.fallback_depth})")
    print(f"  [RESULT] Decision:        {decision.action} for INR {decision.total_amount}")
    print(f"  [RESULT] Rationale:       {decision.rationale}")

    assert meta.provider_used == "groq"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_used is False
    assert decision.action == "OFFER"
    print("  -> CASE A PASSED SUCCESSFULLY!")

def verify_case_b_429_failover_to_next_real_provider():
    banner("CASE B: FIRST PROVIDER FAILS WITH 429 -> NEXT REAL PROVIDER SUCCEEDS")
    gw = AIGateway()
    gw.resolve_chain = lambda role: ["cerebras", "gemini", "mock"]

    # 1. Cerebras hits 429
    mock_cerebras = MagicMock(spec=BaseLLMProvider)
    mock_cerebras.is_available = True
    mock_cerebras.generate_structured.side_effect = ProviderFailure(
        provider_name="cerebras",
        category=FailureCategory.RATE_LIMITED,
        message="HTTP 429 RateLimitExceeded: Resource exhausted",
        status_code=429
    )
    gw._providers_registry["cerebras"] = mock_cerebras

    # 2. Gemini succeeds as fallback
    mock_gemini = MagicMock(spec=BaseLLMProvider)
    mock_gemini.is_available = True
    mock_gemini.provider_name = "gemini"
    mock_gemini.model_name = "gemini-3.1-flash-lite"
    
    gemini_decision = MerchantDecision(
        action="COUNTER",
        product_id=41,
        quantity=1,
        unit_price=Decimal("12500.00"),
        total_amount=Decimal("12500.00"),
        rationale="Merchant counter-offer generated via Gemini fallback."
    )
    gemini_meta = ProviderExecutionMetadata(
        provider_used="gemini",
        provider_type="real_llm",
        model_name="gemini-3.1-flash-lite",
        fallback_used=True,
        fallback_depth=1,
        response_latency_ms=220.0
    )
    mock_gemini.generate_structured.return_value = (gemini_decision, gemini_meta)
    gw._providers_registry["gemini"] = mock_gemini

    ctx = NegotiationContext(
        agent_role="MERCHANT_AGENT",
        current_round=1,
        buyer_max_budget=Decimal("14000.00"),
        current_product={"id": 41, "name": "Samsung Galaxy A15", "price": 12999, "cost": 10000, "inventory": 10},
        catalog_price=Decimal("12999.00"),
        merchant_min_price=Decimal("11049.15"),
        current_proposal={"product_id": 41, "total_amount": "12000.00"},
        previous_offers=[{"round": 1, "actor": "buyer", "amount": "12000.00", "action": "OFFER"}],
        max_allowed_discount=Decimal("15.00"),
        inventory_availability=10,
        relevant_policy_constraints={},
        remaining_rounds=3
    )

    decision, meta = gw.generate_negotiation_turn(ctx, "MERCHANT_AGENT", MerchantDecision)
    print(f"  [RESULT] Provider Used:   {meta.provider_used.upper()} ({meta.provider_type})")
    print(f"  [RESULT] Model Name:      {meta.model_name}")
    print(f"  [RESULT] Fallback Used:   {meta.fallback_used} (Depth: {meta.fallback_depth})")
    print(f"  [RESULT] Decision:        {decision.action} for INR {decision.total_amount}")
    print(f"  [RESULT] Rationale:       {decision.rationale}")

    assert meta.provider_used == "gemini"
    assert meta.provider_type == "real_llm"
    assert meta.fallback_used is True
    assert meta.fallback_depth == 1
    assert decision.action == "COUNTER"
    print("  -> CASE B PASSED SUCCESSFULLY!")

def verify_case_c_all_real_fail_mock_completes_full_negotiation():
    banner("CASE C: ALL REAL PROVIDERS FAIL (Groq 404 + Gemini SDK Fail + OpenRouter 404) -> MOCKPROVIDER COMPLETES SAFELY")
    db = SessionLocal()
    try:
        gw = ai_gateway
        gw.resolve_chain = lambda role: ["cerebras", "groq", "gemini", "nvidia_nim", "openrouter", "ollama", "mock"]

        # Simulate failures on all real providers
        saved_providers = dict(gw.providers)
        for p_name, err in [
            ("cerebras", ProviderFailure("cerebras", FailureCategory.RATE_LIMITED, "HTTP 429 Quota Exceeded", status_code=429)),
            ("groq", ProviderFailure("groq", FailureCategory.MODEL_NOT_FOUND, "HTTP 404 Model Not Found", status_code=404)),
            ("gemini", ProviderFailure("gemini", FailureCategory.SDK_ERROR, "ImportError: cannot import name 'genai' from 'google'")),
            ("nvidia_nim", ProviderFailure("nvidia_nim", FailureCategory.AUTH_ERROR, "HTTP 401 Unauthorized", status_code=401)),
            ("openrouter", ProviderFailure("openrouter", FailureCategory.MODEL_NOT_FOUND, "HTTP 404 Not Found", status_code=404)),
            ("ollama", ProviderFailure("ollama", FailureCategory.UNAVAILABLE, "Connection refused")),
        ]:
            m = MagicMock(spec=BaseLLMProvider)
            m.is_available = True
            m.provider_name = p_name
            m.generate_structured.side_effect = err
            gw.providers[p_name] = m
            gw._providers_registry[p_name] = m

        print("Simulated Provider Outage Environment:")
        print("  * Cerebras:    HTTP 429 RateLimitExceeded")
        print("  * Groq:        HTTP 404 Model Not Found")
        print("  * Gemini:      SDK ImportError ('google.genai')")
        print("  * NVIDIA NIM:  HTTP 401 Unauthorized")
        print("  * OpenRouter:  HTTP 404 Model Not Found")
        print("  * Ollama:      Connection Refused (Unavailable)")
        print("  * MockProvider: ONLINE (Deterministic Guardrails Active)")

        # Execute live orchestrator negotiation loop with MockProvider
        buyer = BuyerAgent()
        merchant = MerchantAgent()
        orchestrator = NegotiationOrchestrator(db, buyer, merchant)

        intent = "I want Samsung Galaxy A15 with budget 14000 INR."
        budget = Decimal("14000.00")

        print(f"\nStarting multi-round autonomous negotiation under total real-provider outage...")
        start_t = time.perf_counter()
        try:
            res = orchestrator.run_negotiation_loop(
                buyer_id="case_c_resilience_test_buyer",
                intent=intent,
                budget=budget,
                max_rounds=3
            )
        except NegotiationError as e:
            res = e.result_data or {}
            print(f"[INFO] Negotiation concluded with policy outcome: {e}")

        total_time = time.perf_counter() - start_t
        print(f"\nNegotiation Completed in {total_time:.2f}s | Decision: {res.get('decision')}")
        print(f"Final Amount: INR {res.get('final_amount')} (Original: INR {res.get('original_amount')})")
        print(f"Execution Mode: {res.get('execution_mode')}")

        summary = res.get("provider_summary", {})
        print(f"\nAI Gateway Summary:")
        print(f"  * Real LLM Calls:             {summary.get('real_llm_calls', 0)}")
        print(f"  * Deterministic Fallback:      {summary.get('deterministic_fallback_calls', 0)}")
        print(f"  * MockProvider Used:           {summary.get('mock_calls', 0) > 0 or summary.get('deterministic_fallback_calls', 0) > 0}")

        print("\nConversation Turns Trace:")
        for evt in res.get("conversation_events", []):
            actor_tag = evt['actor'].upper()
            msg = str(evt.get('message', ''))[:80].encode('ascii', 'replace').decode('ascii')
            p_used = evt.get('provider_used', '-')
            p_type = evt.get('provider_type', '-')
            print(f"  [{actor_tag:<8}] Seq {evt['sequence']} | Provider: {p_used:<12} ({p_type}) | {msg}...")

        # Assert no crashes and valid execution
        assert res.get('decision') in ('AGREED', 'REJECTED'), f"Invalid decision: {res.get('decision')}"
        print("\n  -> CASE C PASSED PERFECTLY: SETU NEVER CRASHED AND COMPLETED DETERMINISTICALLY!")
    finally:
        gw.providers.update(saved_providers)
        gw._providers_registry.update(saved_providers)
        db.close()

if __name__ == "__main__":
    verify_case_a_real_provider_success()
    verify_case_b_429_failover_to_next_real_provider()
    verify_case_c_all_real_fail_mock_completes_full_negotiation()
    banner("ALL 3 AI GATEWAY VERIFICATION CASES PASSED FLAWLESSLY!")
