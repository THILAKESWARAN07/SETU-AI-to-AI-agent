import os
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()
from backend.app.agents.provider import GeminiProvider, BuyerDecision

p = GeminiProvider(api_key=os.getenv("GEMINI_API_KEY"), model_name="gemini-3.1-flash-lite")
print(f"Provider: {p.provider_name}, Model: {p.model_name}", flush=True)

res = p.generate_structured_response(
    "Product ID 41: Samsung Galaxy A15, Budget 12000. Give opening offer.",
    "You are Buyer Agent",
    BuyerDecision
)
print("SUCCESS:", res.action, res.total_amount, res.message, flush=True)
meta = p.get_last_execution_metadata()
print("META:", meta.model_dump_json(indent=2), flush=True)
