import os
import sys
import json
from decimal import Decimal
from dotenv import load_dotenv

# Ensure root and backend directory are in path
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("backend"))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.database import Base, engine, SessionLocal
from backend.seed import seed_db
from backend.app.agents.ai_gateway import get_ai_gateway

# 1. Setup and seed DB
Base.metadata.create_all(bind=engine)
db = SessionLocal()
seed_db(db)
db.close()

client = TestClient(app)

print("=" * 80)
print("1. QUERYING /api/agent/provider-status")
print("=" * 80)
resp = client.get("/api/agent/provider-status")
print(f"HTTP {resp.status_code}")
status_data = resp.json()
print(f"Gateway Status:     {status_data.get('gateway_status')}")
print(f"Active Provider:    {status_data.get('active_provider_name')} (Model: {status_data.get('active_model_name')})")
print(f"Buyer Chain:        {status_data.get('buyer', {}).get('chain')}")
print(f"Merchant Chain:     {status_data.get('merchant', {}).get('chain')}")
print(f"Circuit States:     {json.dumps(status_data.get('circuit_states'), indent=2)}")

print("\n" + "=" * 80)
print("2. EXECUTING REAL PRODUCTION E2E NEGOTIATION")
print("Prompt: 'I need wireless earbuds under ₹2,000.'")
print("=" * 80)

payload = {
    "buyer_id": "buyer_prod_real_001",
    "intent": "I need wireless earbuds under ₹2,000.",
    "budget": "2000.00"
}

resp = client.post("/api/demo/commerce", json=payload)
print(f"HTTP {resp.status_code}")
res_json = resp.json()

print(f"\n[NEGOTIATION RESULT]")
print(f"  * Decision:              {res_json.get('decision')}")
print(f"  * Reasons:               {res_json.get('reasons')}")
print(f"  * Selected Product ID:   {res_json.get('selected_product_id')}")
print(f"  * Original Amount:       INR {res_json.get('original_amount')}")
print(f"  * Final Amount:          INR {res_json.get('final_amount')}")
print(f"  * Discount:              {res_json.get('discount_percent')}%")
print(f"  * Margin:                {res_json.get('margin_percent')}%")
print(f"  * Execution Mode:        {res_json.get('execution_mode')}")
print(f"  * Provider:              {res_json.get('provider')}")
print(f"  * Model:                 {res_json.get('model')}")

prov_sum = res_json.get("provider_summary", {})
print(f"\n[PROVIDER EXECUTION SUMMARY]")
print(f"  * Real LLM Calls Made:   {prov_sum.get('real_llm_calls_made', 0)}")
print(f"  * Mock Fallback Count:   {prov_sum.get('mock_calls_made', 0)}")
print(f"  * Avoided Operations:    {prov_sum.get('avoided_deterministic_operations', 0)}")

print("\n" + "-" * 80)
print("CONVERSATION TURNS & PROVIDER METADATA TRACE")
print("-" * 80)

events = res_json.get("conversation_events", [])
real_llm_turns = 0

for evt in events:
    role = str(evt.get("speaker", "")).upper()
    seq = evt.get("sequence_number", 0)
    provider = str(evt.get("provider_used", "unknown"))
    p_type = str(evt.get("provider_type", "unknown"))
    model = str(evt.get("model_name", "unknown"))
    fb_depth = evt.get("fallback_depth", 0)
    msg = str(evt.get("message", ""))
    
    if p_type == "real_llm":
        real_llm_turns += 1

    print(f"[{role:12}] Seq {str(seq):2} | Provider: {provider:10} ({p_type:22}) | Model: {model} | Depth: {fb_depth}")
    print(f"               Message: {msg[:110]}...")

print("-" * 80)
print(f"Total Real LLM Turns: {real_llm_turns}")
if real_llm_turns > 0:
    print(">>> VERIFICATION SUCCESS: Real LLM Provider Successfully Used in Autonomous Negotiation! <<<")
else:
    print(">>> WARNING: Zero Real LLM Turns Recorded <<<")
