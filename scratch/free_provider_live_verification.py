import os
import sys
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.config import settings
from backend.app.agents.provider import (
    LLMProvider,
    GeminiProvider,
    GroqProvider,
    OpenRouterProvider,
    MockProvider,
    MultiFallbackProvider,
    get_provider_for_agent,
    BuyerDecision,
    MerchantDecision,
    ProviderExecutionMetadata
)

class FailingProvider(LLMProvider):
    def __init__(self, name: str = "Gemini", agent_role: str = "buyer"):
        super().__init__(agent_role=agent_role)
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return f"{self._name.lower()}-test-model"

    def generate_response(self, prompt, system_instruction, tools):
        raise Exception(f"{self._name} 429 ResourceExhausted: rate limit exceeded")

    def generate_structured_response(self, prompt, system_instruction, schema_class):
        raise Exception(f"{self._name} 429 ResourceExhausted: rate limit exceeded")


def run_live_verification():
    print("=" * 60)
    print("SETU FREE MULTI-PROVIDER ARCHITECTURE LIVE VERIFICATION")
    print("=" * 60)

    # 1. Inspect Keys Configured (Masked)
    gemini_key = os.getenv("GEMINI_API_KEY") or settings.GEMINI_API_KEY
    groq_key = os.getenv("GROQ_API_KEY") or settings.GROQ_API_KEY
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or settings.OPENROUTER_API_KEY

    print(f"\n1. Configured Free-Tier Keys:")
    print(f"   - GEMINI_API_KEY:     {'[PRESENT]' if gemini_key else '[NOT CONFIGURED]'}")
    print(f"   - GROQ_API_KEY:       {'[PRESENT]' if groq_key else '[NOT CONFIGURED]'}")
    print(f"   - OPENROUTER_API_KEY: {'[PRESENT]' if openrouter_key else '[NOT CONFIGURED]'}")

    # 2. Live Gemini Call (Buyer Primary)
    print(f"\n2. Testing GeminiProvider (Buyer Primary)...")
    if gemini_key:
        try:
            gemini = GeminiProvider(api_key=gemini_key, model_name=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"))
            resp = gemini.generate_response("Hello, confirm you are Gemini for SETU Buyer agent.", "You are a commerce agent.", [])
            meta = gemini.get_last_execution_metadata()
            print(f"   [SUCCESS] Gemini Live Response: '{resp['text'][:60]}...'")
            print(f"   Metadata: provider_used={meta.provider_used}, model={meta.model_name}, latency={meta.response_latency_ms}ms, fallback_used={meta.fallback_used}")
        except Exception as e:
            print(f"   [GEMINI ERROR/QUOTA]: {type(e).__name__}({str(e)[:100]})")
    else:
        print("   [SKIPPED] GEMINI_API_KEY not set.")

    # 3. Live Groq Call (Merchant Primary)
    print(f"\n3. Testing GroqProvider (Merchant Primary)...")
    if groq_key:
        try:
            groq = GroqProvider(api_key=groq_key, model_name=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
            resp = groq.generate_response("Hello, confirm you are Groq LLaMA-3.3 for SETU Merchant agent.", "You are a commerce agent.", [])
            meta = groq.get_last_execution_metadata()
            print(f"   [SUCCESS] Groq Live Response: '{resp['text'][:60]}...'")
            print(f"   Metadata: provider_used={meta.provider_used}, model={meta.model_name}, latency={meta.response_latency_ms}ms, fallback_used={meta.fallback_used}")
        except Exception as e:
            print(f"   [GROQ ERROR]: {type(e).__name__}({str(e)[:100]})")
    else:
        print("   [SKIPPED] GROQ_API_KEY not set (User can provide free key in .env).")

    # 4. Live OpenRouter Call (Fallback 1)
    print(f"\n4. Testing OpenRouterProvider (Fallback 1)...")
    if openrouter_key:
        try:
            openrouter = OpenRouterProvider(api_key=openrouter_key, model_name=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"))
            resp = openrouter.generate_response("Hello, confirm you are OpenRouter for SETU agent.", "You are a commerce agent.", [])
            meta = openrouter.get_last_execution_metadata()
            print(f"   [SUCCESS] OpenRouter Live Response: '{resp['text'][:60]}...'")
            print(f"   Metadata: provider_used={meta.provider_used}, model={meta.model_name}, latency={meta.response_latency_ms}ms, fallback_used={meta.fallback_used}")
        except Exception as e:
            print(f"   [OPENROUTER ERROR]: {type(e).__name__}({str(e)[:100]})")
    else:
        print("   [SKIPPED] OPENROUTER_API_KEY not set (User can provide free key in .env).")

    # 5. Buyer Chain and Merchant Chain Independence
    print(f"\n5. Testing Buyer & Merchant Provider Chains via Router...")
    buyer_provider = get_provider_for_agent("buyer")
    merchant_provider = get_provider_for_agent("merchant")

    print(f"   Buyer Provider Chain:    {buyer_provider.provider_name} (Role: {getattr(buyer_provider, 'agent_role', 'N/A')})")
    print(f"   Merchant Provider Chain: {merchant_provider.provider_name} (Role: {getattr(merchant_provider, 'agent_role', 'N/A')})")

    # 6. Simulated Buyer Failure & Isolation Test
    print(f"\n6. Testing Simulated Buyer Provider Failure Isolation...")
    failing_buyer_gemini = FailingProvider(name="Gemini", agent_role="buyer")

    buyer_chain = MultiFallbackProvider(
        providers=[failing_buyer_gemini, MockProvider(agent_role="buyer")],
        agent_role="buyer"
    )

    healthy_merchant_chain = MultiFallbackProvider(
        providers=[MockProvider(agent_role="merchant")],
        agent_role="merchant"
    )

    buyer_resp = buyer_chain.generate_structured_response("propose earbuds", "sys", BuyerDecision)
    buyer_meta = buyer_chain.get_last_execution_metadata()
    print(f"   Buyer Fallback Result: provider_used={buyer_meta.provider_used}, fallback_used={buyer_meta.fallback_used}, depth={buyer_meta.fallback_depth}, reason='{buyer_meta.fallback_reason}'")

    merchant_resp = healthy_merchant_chain.generate_structured_response("counter earbuds", "sys", MerchantDecision)
    merchant_meta = healthy_merchant_chain.get_last_execution_metadata()
    print(f"   Merchant Result (Should be unaffected): provider_used={merchant_meta.provider_used}, fallback_used={merchant_meta.fallback_used}, depth={merchant_meta.fallback_depth}")

    assert buyer_meta.fallback_used is True
    assert merchant_meta.fallback_used is False
    print("   [VERIFIED] Buyer failure did NOT affect Merchant provider selection!")

    print("\n" + "=" * 60)
    print("ALL LIVE ARCHITECTURAL VERIFICATION CHECKS COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    run_live_verification()
