import os
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv()
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["LLM_MODEL"] = "gemini-3.5-flash"
os.environ["LLM_FALLBACK_TO_MOCK"] = "false"

from backend.app.agents.provider import get_provider, GeminiProvider, BuyerDecision

provider = get_provider()
print(f"Provider class: {type(provider).__name__}")
print(f"Provider name: {provider.provider_name}, Model: {provider.model_name}")

test_prompt = """
Product ID: 52
Product: Samsung Galaxy A15
Catalog Price: 12999
Buyer Budget: 12000
History: Initial round

Choose your opening bid and message.
"""

decision = provider.generate_structured_response(
    prompt=test_prompt,
    system_instruction="You are a smart buyer agent negotiating on SETU platform. Output structured JSON matching the BuyerDecision schema.",
    schema_class=BuyerDecision
)

print("\n--- Direct Gemini Response ---")
print("Action:", decision.action)
print("Product ID:", decision.product_id)
print("Unit Price:", decision.unit_price)
print("Total Amount:", decision.total_amount)
print("Rationale:", decision.rationale)
print("Message:", decision.message)

meta = provider.get_last_execution_metadata()
print("\n--- Provider Execution Metadata ---")
if meta:
    print(meta.model_dump_json(indent=2))
else:
    print("None")
