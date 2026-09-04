import os
import sys
import json
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, ".")

from backend.app.agents.provider import GeminiProvider, MockProvider, FallbackProvider, BuyerDecision

print("=" * 80, flush=True)
print("TESTING FALLBACK PROVIDER RESILIENCE", flush=True)
print("=" * 80, flush=True)

# Test 1: FallbackProvider with working Gemini
print("\n--- Test 1: FallbackProvider with Working Gemini ---", flush=True)
working_gemini = GeminiProvider(api_key=os.getenv("GEMINI_API_KEY"), model_name="gemini-3.1-flash-lite")
resilient_provider = FallbackProvider(primary=working_gemini, fallback=MockProvider(), timeout_seconds=25.0)

res1 = resilient_provider.generate_structured_response(
    "Product ID 41: Samsung Galaxy A15, Budget 12000. Give opening offer.",
    "You are Buyer Agent",
    BuyerDecision
)
meta1 = resilient_provider.get_last_execution_metadata()
print(f"Result action: {res1.action}, Amount: INR {res1.total_amount}", flush=True)
print("Metadata 1:", meta1.model_dump_json(indent=2), flush=True)
assert meta1.provider_used == "gemini", f"Expected gemini, got {meta1.provider_used}"
assert meta1.fallback_used is False, f"Expected fallback_used=False, got {meta1.fallback_used}"
assert meta1.fallback_reason is None

# Test 2: FallbackProvider with failing Gemini (invalid key)
print("\n--- Test 2: FallbackProvider with Failing Gemini (Invalid Key) ---", flush=True)
broken_gemini = GeminiProvider(api_key="INVALID_KEY_FOR_TESTING_FALLBACK_12345", model_name="gemini-3.1-flash-lite")
resilient_broken_provider = FallbackProvider(primary=broken_gemini, fallback=MockProvider(), timeout_seconds=10.0)

res2 = resilient_broken_provider.generate_structured_response(
    "Product ID 41: Samsung Galaxy A15, Budget 12000. Give opening offer.",
    "You are Buyer Agent",
    BuyerDecision
)
meta2 = resilient_broken_provider.get_last_execution_metadata()
print(f"Result action: {res2.action}, Amount: INR {res2.total_amount}", flush=True)
print("Metadata 2:", meta2.model_dump_json(indent=2), flush=True)
assert meta2.provider_used == "mock", f"Expected mock, got {meta2.provider_used}"
assert meta2.fallback_used is True, f"Expected fallback_used=True, got {meta2.fallback_used}"
assert meta2.fallback_reason is not None, "Expected fallback_reason to be populated"
print(f"Recorded fallback reason: {meta2.fallback_reason[:100]}...", flush=True)

print("\n" + "=" * 80, flush=True)
print("FALLBACK PROVIDER RESILIENCE TESTS PASSED 100%!", flush=True)
print("=" * 80, flush=True)
