import os
import sys
import time
from dotenv import load_dotenv

# Ensure both root and backend directory are in path
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("backend"))

load_dotenv()

from backend.app.database import Base, engine, SessionLocal
from backend.seed import seed_db

Base.metadata.create_all(bind=engine)
db = SessionLocal()
seed_db(db)
db.close()

from backend.app.agents.runtime import NegotiationRuntime
from backend.app.agents.ai_gateway import get_ai_gateway

print("=" * 80)
print("SETU REAL PRODUCTION E2E NEGOTIATION VERIFICATION")
print("User Request: 'I need wireless earbuds under ₹2,000.'")
print("=" * 80)

gateway = get_ai_gateway()
health_status = gateway.get_health_status()
print("\n[AI GATEWAY STATUS]")
for p, s in health_status.get("provider_health", {}).items():
    print(f"  * {p:12}: status={s.get('status')} | model={s.get('model')} | circuit={s.get('circuit_breaker')}")

print("\nExecuting autonomous multi-round negotiation...")
start_time = time.time()

runtime = NegotiationRuntime()
db = SessionLocal()

try:
    result = runtime.run_negotiation(
        buyer_prompt="I need wireless earbuds under ₹2,000.",
        buyer_max_budget=2000.0,
        buyer_target_price=1700.0,
        db=db,
        session_id="prod_live_verification_001"
    )
    elapsed = time.time() - start_time

    print(f"\n[NEGOTIATION COMPLETED in {elapsed:.2f}s]")
    print(f"  * Status:           {result.get('status')}")
    print(f"  * Product:          {result.get('product_name')} (ID: {result.get('product_id')})")
    print(f"  * Agreed Price:     INR {result.get('agreed_price', 0):.2f}")
    print(f"  * Total Amount:     INR {result.get('total_amount', 0):.2f}")
    print(f"  * Real LLM Calls:   {result.get('real_llm_calls_made', 0)}")
    print(f"  * Deterministic:    {result.get('deterministic_fallback_used', False)}")

    print("\n" + "-" * 80)
    print("DETAILED CONVERSATION & PROVIDER TRACE")
    print("-" * 80)

    turns = result.get("conversation_turns", [])
    real_llm_turns = 0

    for turn in turns:
        role = turn.get("role", "").upper()
        seq = turn.get("sequence_number")
        provider = turn.get("provider_used", "unknown")
        model = turn.get("model_name", "unknown")
        p_type = turn.get("provider_type", "unknown")
        msg = turn.get("message", "")
        fb_depth = turn.get("fallback_depth", 0)

        if p_type == "real_llm":
            real_llm_turns += 1

        print(f"[{role:8}] Seq {seq:2} | Provider: {provider:8} ({p_type}) | Model: {model} | FB Depth: {fb_depth}")
        print(f"           Message: {msg[:100]}...")

    print("-" * 80)
    print(f"Verification Check: Real LLM Turns Executed = {real_llm_turns}")
    if real_llm_turns > 0:
        print(">>> SUCCESS: Real LLM Provider Successfully Executed Live Commerce Negotiation Turns! <<<")
    else:
        print(">>> WARNING: Zero Real LLM Turns Executed <<<")

finally:
    db.close()
