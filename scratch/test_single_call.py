import os
import sys
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import time
from backend.app.config import settings
from backend.app.agents.provider import GeminiProvider, BuyerDecision

api_key = os.getenv("GEMINI_API_KEY", settings.GEMINI_API_KEY)

for model in ["gemini-2.5-flash", "gemini-3.6-flash"]:
    print(f"\n--- Testing {model} ---")
    provider = GeminiProvider(api_key=api_key, model_name=model)
    try:
        t0 = time.perf_counter()
        res = provider.generate_structured_response(
            "I want to purchase a Samsung Galaxy A15 with budget 12000 INR.",
            "You are a helpful buyer agent.",
            BuyerDecision
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        print(f"SUCCESS in {elapsed} ms: {res}")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
