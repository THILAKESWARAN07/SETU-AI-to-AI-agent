import os
import sys
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import json
from decimal import Decimal
from backend.app.database import Base, engine, SessionLocal
from backend.app.models import Product, MerchantPolicy
from backend.app.agents.provider import get_provider, GeminiProvider
from backend.app.agents.buyer_agent import BuyerAgent
from backend.app.agents.merchant_agent import MerchantAgent
from backend.app.agents.orchestrator import NegotiationOrchestrator

def run_live_scenario(scenario_name: str, intent: str, budget: Decimal):
    print(f"\n=======================================================")
    print(f"RUNNING SCENARIO: {scenario_name}")
    print(f"INTENT: '{intent}' | BUDGET: ₹{budget}")
    print(f"=======================================================")
    
    db = SessionLocal()
    provider = get_provider()
    print(f"Active Provider Name: {provider.provider_name}")
    print(f"Active Model Name: {provider.model_name}")
    print(f"Active Agent Mode: {provider.agent_mode}")
    
    buyer = BuyerAgent(provider=provider)
    merchant = MerchantAgent(provider=provider)
    orchestrator = NegotiationOrchestrator(db, buyer=buyer, merchant=merchant)
    
    streamed_events = []
    try:
        result = orchestrator.run_negotiation_loop(
            buyer_id="live_tester",
            intent=intent,
            budget=budget,
            on_event=lambda evt: streamed_events.append(evt)
        )
        print(f"\nNegotiation Decision: {result['decision']}")
        print(f"Final Agreed Amount: ₹{result['final_amount']}")
        print(f"Accepted Proposal ID: {result.get('accepted_proposal_id')}")
        
        print("\n--- PER-TURN PROVIDER EXECUTION METADATA ---")
        agent_events = [e for e in streamed_events if e.get("actor") in ("buyer", "merchant")]
        for idx, evt in enumerate(agent_events, 1):
            print(f"Turn {idx} [{evt.get('actor', '').upper()}]:")
            print(f"  Event ID: {evt.get('id')}")
            print(f"  Proposal ID: {evt.get('proposal_id')}")
            print(f"  Offer / Bid: ₹{evt.get('offer')}")
            print(f"  Provider Used: {evt.get('provider_used')}")
            print(f"  Model Name: {evt.get('model_name')}")
            print(f"  Fallback Used: {evt.get('fallback_used')}")
            print(f"  Fallback Reason: {evt.get('fallback_reason')}")
            print(f"  Response Latency: {evt.get('response_latency_ms')} ms")
            print(f"  Message Snippet: {evt.get('message', '')[:100]}...")

        print("\n--- PROVIDER SUMMARY ---")
        print(json.dumps(result.get("provider_summary"), indent=2))
        return result
    except Exception as e:
        print(f"Execution Error: {e}")
        return None
    finally:
        db.close()

if __name__ == "__main__":
    # Ensure Gemini is enabled
    os.environ["LLM_PROVIDER"] = "gemini"
    os.environ["LLM_MODEL"] = "gemini-3.6-flash"
    os.environ["LLM_TIMEOUT_SECONDS"] = "30.0"
    
    # Run Scenario 1: Samsung Galaxy A15
    res1 = run_live_scenario(
        "Scenario 1: Samsung Galaxy A15 under ₹12,000",
        "I need a Samsung Galaxy A15 phone under 12000",
        Decimal("12000.00")
    )
    
    # Run Scenario 2: Wireless Earbuds
    res2 = run_live_scenario(
        "Scenario 2: Wireless Earbuds under ₹2,000",
        "I need Wireless Earbuds Pro under 2000",
        Decimal("2000.00")
    )
