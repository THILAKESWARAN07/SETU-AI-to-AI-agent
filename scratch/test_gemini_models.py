import os
import sys
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import time
from backend.app.config import settings
from backend.app.agents.provider import GeminiProvider, BuyerDecision

api_key = os.getenv("GEMINI_API_KEY", settings.GEMINI_API_KEY)

for model_name in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]:
    print(f"\nTesting model: {model_name}")
    try:
        provider = GeminiProvider(api_key=api_key, model_name=model_name)
        start = time.perf_counter()
        resp = provider.generate_structured_response(
            "I want to purchase a Samsung Galaxy A15 with budget 12000 INR.",
            "You are a buyer agent.",
            BuyerDecision
        )
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        print(f"SUCCESS in {elapsed}ms! Response: {resp.action} {resp.total_amount} - {resp.message}")
        print(f"Recorded metadata: {provider.get_last_execution_metadata()}")
    except Exception as e:
        print(f"FAILED for {model_name}: {type(e).__name__}: {e}")
